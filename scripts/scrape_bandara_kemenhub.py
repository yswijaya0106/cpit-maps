# -*- coding: utf-8 -*-
"""Scrape daftar lengkap Bandar Udara dari situs resmi Ditjen Perhubungan
Udara Kemenhub (https://hubud.kemenhub.go.id/daftar-bandara, 60 halaman
@ 10 baris) + halaman detail tiap bandara
(https://hubud.kemenhub.go.id/bandara/{id}, 8 tab), simpan ke
bandara_kemenhub + 3 tabel anak (rute, terdekat, fasilitas). Lihat
scripts/schema_bandara_kemenhub.sql. TIDAK terkait usulan_inpres/IJD.

Server-rendered HTML (bukan SPA), semua tab ada dalam satu response
(ditoggle CSS/JS client-side) -- diparsing BeautifulSoup, bukan
Selenium/Playwright. Sopan ke server: 1 request per REQUEST_DELAY detik.

lat/lon diambil dari link "Buka di Google Maps" pada halaman detail
(koordinat desimal bersih) -- bukan parsing teks DMS "Lokasi (ARP)" yang
encoding derajatnya rusak di sumbernya sendiri.

Idempotent: UPSERT bandara_kemenhub per bandara_id; tabel anak (rute,
terdekat, fasilitas) di-DELETE+INSERT ulang per bandara_id tiap run
(list-type child, lebih sederhana drpd diff per baris).

Usage (venv aktif):
    python scripts/scrape_bandara_kemenhub.py                  # semua 60 halaman
    python scripts/scrape_bandara_kemenhub.py --max-page 3      # uji coba
    python scripts/scrape_bandara_kemenhub.py --start-page 10   # lanjutkan dari halaman tertentu
"""
import argparse
import io
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import requests
from bs4 import BeautifulSoup
from psycopg.types.json import Json

from db import db_cursor as pg_cursor  # noqa: E402

LIST_URL = "https://hubud.kemenhub.go.id/daftar-bandara"
DETAIL_URL_FMT = "https://hubud.kemenhub.go.id/bandara/{id}"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; analytic-maps/1.0; data referensi Ditjen Hubud)"}
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_bandara_kemenhub.sql"
REQUEST_DELAY = 0.4
REQUEST_TIMEOUT = 20
DEFAULT_MAX_PAGE = 60

_ID_RE = re.compile(r"/bandara/(\d+)")
_GMAPS_RE = re.compile(r"query=([\-0-9.]+),([\-0-9.]+)")
_TAHUN_RE = re.compile(r"\((\d{4})\)")

# Koordinat tujuan rute TIDAK ada di DOM/li biasa (lihat _parse_rute) --
# cuma ada di blok <script> Highcharts.mapChart('mapRuteDom'/'mapRuteInt', ...)
# sbg data 'mappoint', dgn quote ' atau " campur antar halaman. Diekstrak
# terpisah (bukan BeautifulSoup, ini bukan HTML) lalu dicocokkan berurutan
# dgn hasil _parse_rute (dibuat dari sumber render yg sama, urutan sama).
_MAPPOINT_ENTRY_RE = re.compile(
    r"name:\s*['\"](?P<name>[^'\"]*)['\"],\s*"
    r"geometry:\s*\{\s*type:\s*['\"]Point['\"],\s*"
    r"coordinates:\s*\[\s*(?P<lon>-?[\d.]+)\s*,\s*(?P<lat>-?[\d.]+)\s*\]\s*\},\s*"
    r"data:\s*\{\s*origin:\s*['\"][^'\"]*['\"],\s*"
    r"destination:\s*['\"](?P<destination>[^'\"]*)['\"],\s*"
    r"maskapai:\s*['\"](?P<maskapai>[^'\"]*)['\"]",
)


def _parse_rute_koordinat(html, chart_var):
    """chart_var: 'mapRuteDom' | 'mapRuteInt'. Return list [(lat, lon), ...]
    seurutan kemunculan pada blok mappoint chart tsb (sama urutan dgn li
    di DOM, krn dibangun dari iterasi sumber data yg sama di server)."""
    marker = f"Highcharts.mapChart('{chart_var}'"
    start = html.find(marker)
    if start < 0:
        return []
    mappoint_idx = html.find("type: 'mappoint'", start)
    if mappoint_idx < 0:
        return []
    # blok mappoint berakhir sebelum "});" penutup mapChart berikutnya
    end = html.find("});", mappoint_idx)
    segmen = html[mappoint_idx: end if end > 0 else mappoint_idx + 20000]
    return [(float(m.group("lat")), float(m.group("lon"))) for m in _MAPPOINT_ENTRY_RE.finditer(segmen)]


def _text(el):
    if el is None:
        return None
    t = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
    return t or None


def _num(v):
    """Angka format Indonesia (titik ribuan, koma desimal) -> int."""
    if v is None:
        return None
    v = str(v).replace(".", "").replace(",", ".").strip()
    if not v or v in ("-", "0"):
        return None if v == "-" else 0
    try:
        return int(float(v))
    except ValueError:
        return None


def _num_en(v):
    """Angka format Inggris (titik desimal, dipakai kolom jarak_km) -> float."""
    if v is None:
        return None
    v = str(v).strip()
    if not v or v == "-":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _fetch(url, params=None):
    resp = requests.get(url, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def _parse_listing(html):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return []
    rows = []
    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 10:
            continue
        a = tr.find("a", href=True)
        detail_url = a["href"] if a else None
        m = _ID_RE.search(detail_url or "")
        if not m:
            continue
        rows.append({
            "bandara_id": int(m.group(1)),
            "icao": _text(tds[0]),
            "iata": _text(tds[1]),
            "nama_bandara": _text(tds[2]),
            "provinsi": _text(tds[3]),
            "kabupaten": _text(tds[4]),
            "penggunaan": _text(tds[5]),
            "kelas": _text(tds[6]),
            "pengelola": _text(tds[7]),
            "tkbn": _text(tds[8]),
            "detail_url": detail_url,
        })
    return rows


def _parse_dl(container):
    """dt/dd generic pairs, dipakai buat tab Data Umum & panel Lalu Lintas Udara."""
    data = {}
    if not container:
        return data
    for dt in container.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if not dd:
            continue
        label = _text(dt)
        if label:
            data[label] = _text(dd)
    return data


def _parse_lalu_lintas(soup):
    h4 = soup.find("h4", string=re.compile(r"Lalu Lintas Udara"))
    if not h4:
        return None, {}
    m = _TAHUN_RE.search(h4.get_text())
    tahun = int(m.group(1)) if m else None
    dl = h4.find_next_sibling("dl")
    return tahun, _parse_dl(dl)


def _parse_gmaps_latlon(soup):
    for a in soup.find_all("a", href=True):
        m = _GMAPS_RE.search(a["href"])
        if m and "google.com/maps" in a["href"]:
            return float(m.group(1)), float(m.group(2))
    return None, None


def _parse_terdekat(soup):
    el = soup.find(id="tab-bandaraTerdekat")
    if not el:
        return []
    out = []
    for li in el.select("ul > li"):
        spans = li.find_all("span")
        if len(spans) < 2:
            continue
        nama = _text(spans[0])
        jarak_text = _text(spans[1])
        jarak = None
        if jarak_text:
            m = re.search(r"([\d.]+)", jarak_text)
            if m:
                jarak = _num_en(m.group(1))
        a = li.find("a", href=True)
        tujuan_id = None
        if a:
            m = _ID_RE.search(a["href"])
            if m:
                tujuan_id = int(m.group(1))
        out.append({"nama_terdekat": nama, "jarak_km": jarak, "bandara_terdekat_id": tujuan_id})
    return out


def _parse_rute(soup, tab_id, tipe):
    el = soup.find(id=tab_id)
    if not el:
        return []
    out = []
    for li in el.select("ul > li"):
        divs = li.find_all("div", recursive=False)
        if not divs:
            continue
        header = divs[0]
        spans = header.find_all("span")
        # urutan span di header: [0]=label "Tujuan", [1]=nilai tujuan,
        # [2]=badge maskapai (class rounded+px-2)
        tujuan = _text(spans[1]) if len(spans) > 1 else None
        maskapai = None
        for sp in spans:
            cls = " ".join(sp.get("class") or [])
            if "rounded" in cls and "px-2" in cls:
                maskapai = _text(sp)
                break
        pesawat = frekuensi = None
        grid = li.find("div", class_=lambda c: c and "grid-cols-2" in c)
        if grid:
            cells = grid.find_all("div")
            for cell in cells:
                spans2 = cell.find_all("span")
                if len(spans2) < 2:
                    continue
                label = _text(spans2[0])
                value = _text(spans2[1])
                if label == "Pesawat":
                    pesawat = value
                elif label == "Frekuensi":
                    frekuensi = value
        out.append({"tipe": tipe, "tujuan": tujuan, "maskapai": maskapai, "pesawat": pesawat, "frekuensi": frekuensi,
                     "tujuan_lat": None, "tujuan_lon": None})
    return out


def _lengkapi_koordinat_rute(rute_list, html, chart_var):
    """Isi tujuan_lat/tujuan_lon in-place dari _parse_rute_koordinat --
    dicocokkan berdasarkan urutan (li dan mappoint dibangun dari iterasi
    sumber data yg sama di server). Kalau jumlahnya tak sama (situs
    berubah/parsial), dilewati drpd salah pasang -- lat/lon tetap None."""
    koordinat = _parse_rute_koordinat(html, chart_var)
    if len(koordinat) != len(rute_list):
        return
    for row, (lat, lon) in zip(rute_list, koordinat):
        row["tujuan_lat"], row["tujuan_lon"] = lat, lon


def _parse_fasilitas(soup, tab_id, kategori):
    el = soup.find(id=tab_id)
    if not el:
        return []
    out = []
    for panel in el.select(f"div.fasilitas-content-{kategori}"):
        h3 = panel.find("h3")
        jenis_fasilitas = _text(h3)
        for card in panel.select("div.grid.gap-6 > div"):
            h4 = card.find("h4")
            nama_item = _text(h4)
            atribut = {}
            for row in card.select("div.grid > div"):
                spans = row.find_all("span", recursive=False)
                if len(spans) < 2:
                    continue
                label = _text(spans[0])
                value = _text(spans[1])
                if label:
                    atribut[label] = value
            out.append({"kategori": kategori, "jenis_fasilitas": jenis_fasilitas, "nama_item": nama_item, "atribut": atribut})
    return out


def _parse_transportasi(soup):
    el = soup.find(id="tab-transportasi")
    if not el:
        return []
    return [
        _text(sp) for sp in el.select("span.font-bold")
        if _text(sp)
    ]


def _parse_galeri(soup):
    el = soup.find(id="tab-gallery")
    if not el:
        return []
    urls = []
    for a in el.select("a[data-src]"):
        src = a.get("data-src")
        if src:
            urls.append(src)
    return urls


def _rute_lengkap(soup, html):
    domestik = _parse_rute(soup, "tab-ruteDomestik", "domestik")
    internasional = _parse_rute(soup, "tab-ruteInternasional", "internasional")
    _lengkapi_koordinat_rute(domestik, html, "mapRuteDom")
    _lengkapi_koordinat_rute(internasional, html, "mapRuteInt")
    return domestik + internasional


def _parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    data_umum_el = soup.find(id="tab-dataUmum")
    dl = data_umum_el.find("dl") if data_umum_el else None
    umum = _parse_dl(dl)
    tahun, lalin = _parse_lalu_lintas(soup)
    lat, lon = _parse_gmaps_latlon(soup)

    return {
        "nama_bandara": umum.get("Nama Bandar Udara"),
        "lokasi_arp_text": umum.get("Lokasi (ARP)"),
        "status_operasi": umum.get("Status Operasi"),
        "critical_aircraft": umum.get("Critical Aircraft"),
        "penggunaan": umum.get("Penggunaan"),
        "pesawat_beroperasi": umum.get("Pesawat Beroperasi"),
        "hierarki": umum.get("Hierarki"),
        "pkp_pk": umum.get("PKP-PK"),
        "klasifikasi": umum.get("Klasifikasi"),
        "dokumen_pendukung": umum.get("Dokumen Pendukung"),
        "pengelola": umum.get("Pengelola"),
        "airnav_info": umum.get("Airnav Indonesia"),
        "provinsi": umum.get("Provinsi"),
        "kabupaten": umum.get("Kabupaten / Kota"),
        "kecamatan": umum.get("Kecamatan"),
        "kelurahan_desa": umum.get("Kelurahan / Desa"),
        "alamat_bandara": umum.get("Alamat Bandar Udara"),
        "status_blu": umum.get("Status BLU"),
        "lat": lat,
        "lon": lon,
        "lalu_lintas_tahun": tahun,
        "lalu_lintas_pesawat": _num(lalin.get("Pesawat")),
        "lalu_lintas_penumpang": _num(lalin.get("Penumpang")),
        "lalu_lintas_kargo_kg": _num(lalin.get("Kargo")),
        "transportasi_darat": _parse_transportasi(soup),
        "galeri_urls": _parse_galeri(soup),
        "rute": _rute_lengkap(soup, html),
        "terdekat": _parse_terdekat(soup),
        "fasilitas": _parse_fasilitas(soup, "tab-fasilitasUdara", "udara") + _parse_fasilitas(soup, "tab-fasilitasDarat", "darat"),
    }


def _simpan(cur, listing_row, detail):
    bandara_id = listing_row["bandara_id"]
    row = {**listing_row, **{k: v for k, v in detail.items() if k not in ("rute", "terdekat", "fasilitas")}}
    row["nama_bandara"] = detail.get("nama_bandara") or listing_row["nama_bandara"]
    row["provinsi"] = detail.get("provinsi") or listing_row["provinsi"]
    row["kabupaten"] = detail.get("kabupaten") or listing_row["kabupaten"]

    cur.execute(
        """INSERT INTO bandara_kemenhub (
               bandara_id, icao, iata, nama_bandara, provinsi, kabupaten, kecamatan,
               kelurahan_desa, penggunaan, kelas, pengelola, tkbn, status_operasi,
               hierarki, pkp_pk, klasifikasi, critical_aircraft, pesawat_beroperasi,
               dokumen_pendukung, airnav_info,
               alamat_bandara, status_blu, lokasi_arp_text, lat, lon,
               lalu_lintas_tahun, lalu_lintas_pesawat, lalu_lintas_penumpang,
               lalu_lintas_kargo_kg, transportasi_darat, galeri_urls, detail_url
           ) VALUES (
               %(bandara_id)s, %(icao)s, %(iata)s, %(nama_bandara)s, %(provinsi)s, %(kabupaten)s, %(kecamatan)s,
               %(kelurahan_desa)s, %(penggunaan)s, %(kelas)s, %(pengelola)s, %(tkbn)s, %(status_operasi)s,
               %(hierarki)s, %(pkp_pk)s, %(klasifikasi)s, %(critical_aircraft)s, %(pesawat_beroperasi)s,
               %(dokumen_pendukung)s, %(airnav_info)s,
               %(alamat_bandara)s, %(status_blu)s, %(lokasi_arp_text)s, %(lat)s, %(lon)s,
               %(lalu_lintas_tahun)s, %(lalu_lintas_pesawat)s, %(lalu_lintas_penumpang)s,
               %(lalu_lintas_kargo_kg)s, %(transportasi_darat)s, %(galeri_urls)s, %(detail_url)s
           )
           ON CONFLICT (bandara_id) DO UPDATE SET
               icao=EXCLUDED.icao, iata=EXCLUDED.iata, nama_bandara=EXCLUDED.nama_bandara,
               provinsi=EXCLUDED.provinsi, kabupaten=EXCLUDED.kabupaten, kecamatan=EXCLUDED.kecamatan,
               kelurahan_desa=EXCLUDED.kelurahan_desa, penggunaan=EXCLUDED.penggunaan, kelas=EXCLUDED.kelas,
               pengelola=EXCLUDED.pengelola, tkbn=EXCLUDED.tkbn, status_operasi=EXCLUDED.status_operasi,
               hierarki=EXCLUDED.hierarki, pkp_pk=EXCLUDED.pkp_pk, klasifikasi=EXCLUDED.klasifikasi,
               critical_aircraft=EXCLUDED.critical_aircraft, pesawat_beroperasi=EXCLUDED.pesawat_beroperasi,
               dokumen_pendukung=EXCLUDED.dokumen_pendukung, airnav_info=EXCLUDED.airnav_info,
               alamat_bandara=EXCLUDED.alamat_bandara, status_blu=EXCLUDED.status_blu,
               lokasi_arp_text=EXCLUDED.lokasi_arp_text, lat=EXCLUDED.lat, lon=EXCLUDED.lon,
               lalu_lintas_tahun=EXCLUDED.lalu_lintas_tahun, lalu_lintas_pesawat=EXCLUDED.lalu_lintas_pesawat,
               lalu_lintas_penumpang=EXCLUDED.lalu_lintas_penumpang, lalu_lintas_kargo_kg=EXCLUDED.lalu_lintas_kargo_kg,
               transportasi_darat=EXCLUDED.transportasi_darat, galeri_urls=EXCLUDED.galeri_urls,
               detail_url=EXCLUDED.detail_url, scraped_at=now()""",
        row,
    )

    cur.execute("DELETE FROM bandara_kemenhub_rute WHERE bandara_id = %s", (bandara_id,))
    for r in detail["rute"]:
        cur.execute(
            """INSERT INTO bandara_kemenhub_rute (bandara_id, tipe, tujuan, maskapai, pesawat, frekuensi, tujuan_lat, tujuan_lon)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (bandara_id, r["tipe"], r["tujuan"], r["maskapai"], r["pesawat"], r["frekuensi"], r["tujuan_lat"], r["tujuan_lon"]),
        )

    cur.execute("DELETE FROM bandara_kemenhub_terdekat WHERE bandara_id = %s", (bandara_id,))
    for t in detail["terdekat"]:
        cur.execute(
            """INSERT INTO bandara_kemenhub_terdekat (bandara_id, nama_terdekat, jarak_km, bandara_terdekat_id)
               VALUES (%s, %s, %s, %s)""",
            (bandara_id, t["nama_terdekat"], t["jarak_km"], t["bandara_terdekat_id"]),
        )

    cur.execute("DELETE FROM bandara_kemenhub_fasilitas WHERE bandara_id = %s", (bandara_id,))
    for f in detail["fasilitas"]:
        cur.execute(
            """INSERT INTO bandara_kemenhub_fasilitas (bandara_id, kategori, jenis_fasilitas, nama_item, atribut)
               VALUES (%s, %s, %s, %s, %s)""",
            (bandara_id, f["kategori"], f["jenis_fasilitas"], f["nama_item"], Json(f["atribut"])),
        )


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-page", type=int, default=DEFAULT_MAX_PAGE)
    ap.add_argument("--start-page", type=int, default=1)
    args = ap.parse_args()

    with pg_cursor() as cur:
        cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

    listing_rows = []
    for page in range(args.start_page, args.max_page + 1):
        print(f"Mengambil daftar halaman {page}/{args.max_page}...", flush=True)
        params = {"page": page} if page > 1 else None
        html = _fetch(LIST_URL, params=params)
        rows = _parse_listing(html)
        if not rows:
            print(f"  (kosong, berhenti di halaman {page})")
            break
        listing_rows.extend(rows)
        time.sleep(REQUEST_DELAY)
    print(f"Total {len(listing_rows)} bandara ditemukan di daftar.\n", flush=True)

    total = len(listing_rows)
    saved = 0
    for i, listing_row in enumerate(listing_rows, start=1):
        bid = listing_row["bandara_id"]
        pct = i / total * 100
        print(f"[{i}/{total}] ({pct:.1f}%) bandara/{bid} {listing_row['nama_bandara']}...", flush=True)
        try:
            html = _fetch(DETAIL_URL_FMT.format(id=bid))
            detail = _parse_detail(html)
        except requests.RequestException as e:
            print(f"  GAGAL ambil detail: {e}")
            continue
        time.sleep(REQUEST_DELAY)

        with pg_cursor() as cur:
            _simpan(cur, listing_row, detail)
        saved += 1

    print(f"\nSelesai: {saved}/{total} bandara di-upsert ke bandara_kemenhub.")


if __name__ == "__main__":
    main()
