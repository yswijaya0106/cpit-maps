# -*- coding: utf-8 -*-
"""Impor titik lokasi PSC 119 (Public Safety Center) ke PostGIS -- layer peta
"PSC 119" di bucket nasional flat "KESELAMATAN" (skema generik map_layers,
pola sama dgn import_blackspot_to_postgis.py).

Sumber: docs/Konektivitas/8. KESELAMATAN/Data Lokasi PSC 119.xlsx (sheet
"Data Lokasi", 207 PSC, versi 27 Sep 2026). Melengkapi tabel psc119_layanan
(survei layanan, TANPA koordinat -- scripts/import_psc119_layanan.py): titik
yang kab/kotanya ada di survei diberi ringkasan layanannya (ambulans,
personel, waktu respons) di popup.

Kolom yang SENGAJA tidak diimpor: NAMA PIC dan NOMOR TELEPON PIC (data
pribadi), VDN / Station / Login ID (konfigurasi sistem call center).

Pemeriksaan koordinat (temuan analisis 3 Okt 2026, ±9% baris bermasalah):
- format angka diperbaiki otomatis: titik ribuan ("3.258.438.213" ->
  3.258438213) dan koma di ujung ("1.518...,");
- titik di luar Indonesia (salah skala/tanda) -> TIDAK digambar;
- kab/kota tempat titik jatuh (poligon BATAS KABUPATEN, atau poligon
  terdekat <= 3 km utk titik di garis pantai) dibandingkan dgn kab/kota dari
  NAMA PSC (wilayah_cocok.PencocokKabupaten). Beda -> TIDAK digambar
  (mis. Badung yg koordinatnya di Banda Aceh). PSC tingkat provinsi (mis.
  "PCC Prov NTB") tidak punya kab/kota di namanya -> cukup provinsinya sama.
Baris yang tidak digambar dicetak di akhir run (untuk dikirim ke pengirim
data); --laporan path.csv menyimpannya ke file.

Idempotent: DELETE + reinsert layer. Restart server setelah rerun
(_map_layer_geojson_cache).

Usage (venv aktif):
    python scripts/import_psc119_lokasi_to_postgis.py [--xlsx path] [--laporan out.csv]
"""
import argparse
import csv
import io
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import openpyxl  # noqa: E402
from psycopg.types.json import Json  # noqa: E402

from db import db_cursor as pg_cursor  # noqa: E402
from wilayah_cocok import PencocokKabupaten, kunci_provinsi  # noqa: E402

XLSX_PATH = REPO_ROOT / "docs" / "Konektivitas" / "8. KESELAMATAN" / "Data Lokasi PSC 119.xlsx"
PROVINSI_BUCKET = "KESELAMATAN"
KABUPATEN_BUCKET = ""
LAYER_NAME = "PSC 119"
LABEL = "Lokasi PSC 119 (Public Safety Center)"
JARAK_PANTAI_M = 3000  # titik di luar semua poligon tapi <= ini dari poligon terdekat dianggap di kab itu

# Penulisan nama di sumber -> nama master (kunci huruf+angka, huruf besar),
# hanya yg tidak ditangani wilayah_cocok.ALIAS_NAMA. Tambah setelah dicek.
ALIAS_PSC = {
    "OKU": "OGANKOMERINGULU",
    "SOLO": "SURAKARTA",
    "MAKASAR": "MAKASSAR",
    "METROLAMPUNG": "METRO",
    "PANGKAJENEKEPULAUAN": "PANGKAJENEDANKEPULAUAN",
}


def _koordinat(v):
    """Teks/angka koordinat -> float, memperbaiki titik ribuan & koma ujung. None bila gagal."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().rstrip(",").strip()
    if s.count(".") > 1:  # "3.258.438.213" -> titik pertama = desimal
        kepala, *ekor = s.split(".")
        s = kepala + "." + "".join(ekor)
    try:
        return float(s)
    except ValueError:
        return None


def _nama_kab(nama_psc):
    """'PSC 119 KAB. ACEH BARAT' -> ('Kab. Aceh Barat', 'Aceh Barat', False);
    'PCC Prov NTB' -> (None, None, True). Elemen ke-2 = nama tanpa awalan Kab/Kota."""
    s = re.sub(r"\(.*?\)", "", str(nama_psc or "")).strip()
    s = re.sub(r"^(PSC|PCC)(\s*119)?\s+", "", s, flags=re.I).strip()
    if re.match(r"^PROV(INSI|\.)?\b", s, re.I):
        return None, None, True
    m = re.match(r"^(KABUPATEN|KAB\.?|KOTA\.?)\s+(.*)$", s, re.I)
    awalan = ("Kota" if m.group(1).upper().startswith("KOTA") else "Kab.") if m else ""
    inti = m.group(2).strip() if m else s
    inti = ALIAS_PSC.get(re.sub(r"[^A-Z0-9]", "", inti.upper()), inti)
    return (f"{awalan} {inti}".strip() if awalan else inti), inti, False


def _kunci_tanpa_awalan(nama):
    s = re.sub(r"^\s*(KABUPATEN|KAB\.?|KOTA\.?)\s+", "", str(nama or ""), flags=re.I)
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def _baca_xlsx(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["Data Lokasi"] if "Data Lokasi" in wb.sheetnames else wb.active
    rows = ws.iter_rows(values_only=True)
    header = [str(h).strip().upper() if h else "" for h in next(rows)]
    ix = {h: i for i, h in enumerate(header)}
    for h in ("NAMA PSC", "ALAMAT LENGKAP", "LATITUDE", "LONGITUDE"):
        if h not in ix:
            sys.exit(f"Kolom '{h}' tidak ada di {path.name}")
    out = []
    for r in rows:
        if not r or r[ix["NAMA PSC"]] in (None, ""):
            continue
        out.append({
            "no": r[ix["NO"]] if "NO" in ix else None,
            "nama": str(r[ix["NAMA PSC"]]).strip(),
            "alamat": (str(r[ix["ALAMAT LENGKAP"]]).strip() if r[ix["ALAMAT LENGKAP"]] else None),
            "lat_mentah": r[ix["LATITUDE"]], "lon_mentah": r[ix["LONGITUDE"]],
            "lat": _koordinat(r[ix["LATITUDE"]]), "lon": _koordinat(r[ix["LONGITUDE"]]),
        })
    return out


def _poligon_kab(cur, rows):
    """no -> (kode_kab, nama kab poligon, provinsi poligon, jarak_m) utk titik dalam rentang Indonesia."""
    pts = [r for r in rows if r["lat"] is not None and r["lon"] is not None
           and -11.5 <= r["lat"] <= 6.5 and 94 <= r["lon"] <= 141.5]
    if not pts:
        return {}
    cur.execute(
        """WITH p(i, lon, lat) AS (SELECT * FROM unnest(%s::int[], %s::float8[], %s::float8[]))
           SELECT p.i, t.kode, t.kab, t.prov, t.jarak FROM p
           CROSS JOIN LATERAL (
               SELECT (m.attrs->>'KODE_KABUPATEN')::int AS kode, m.attrs->>'KABUPATEN_KOTA' AS kab,
                      m.attrs->>'PROVINSI' AS prov,
                      ST_Distance(m.geom::geography, ST_SetSRID(ST_Point(p.lon, p.lat), 4326)::geography) AS jarak
               FROM map_layers m
               WHERE m.provinsi = 'BATAS KABUPATEN'
               ORDER BY m.geom <-> ST_SetSRID(ST_Point(p.lon, p.lat), 4326)
               LIMIT 1) t""",
        ([i for i, r in enumerate(rows) if r in pts], [r["lon"] for r in pts], [r["lat"] for r in pts]),
    )
    return {x["i"]: (x["kode"], x["kab"], x["prov"], float(x["jarak"])) for x in cur.fetchall()}


def _ringkasan_survei(cur, pencocok):
    """kode_kab -> ringkasan baris psc119_layanan (hanya bila kab itu punya tepat 1 baris survei)."""
    cur.execute("SELECT to_regclass('public.psc119_layanan') AS t")
    if cur.fetchone()["t"] is None:
        return {}
    cur.execute("SELECT * FROM psc119_layanan")
    per_kode = {}
    for s in cur.fetchall():
        m = pencocok.cari(s["provinsi"], s["kabupaten_kota"])
        if m:
            per_kode.setdefault(int(m["kode_kabupaten"]), []).append(s)
    out = {}
    for kode, daftar in per_kode.items():
        if len(daftar) != 1:
            continue
        s = daftar[0]
        out[kode] = {
            "Survei: status operasional 2026": s["status_operasional_2026"],
            "Survei: status PSC (UPT/UPTD)": s["status_psc"],
            "Survei: operator call center": s["jumlah_operator_call_center"],
            "Survei: personel lapangan": s["jumlah_personel_lapangan"],
            "Survei: ambulans aktif": s["jumlah_ambulans_aktif"],
            "Survei: GPS tracking": s["kesediaan_gps_tracking"],
            "Survei: integrasi rumah sakit": s["integrasi_rumah_sakit"],
            "Survei: rata-rata waktu respons": s["rata_rata_waktu_respon"],
        }
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--xlsx", type=Path, default=XLSX_PATH)
    ap.add_argument("--laporan", type=Path, help="simpan daftar titik yang tidak digambar ke CSV ini")
    args = ap.parse_args()
    if not args.xlsx.exists():
        sys.exit(f"GAGAL: tidak ditemukan {args.xlsx}")

    rows = _baca_xlsx(args.xlsx)
    print(f"Membaca {args.xlsx.name}: {len(rows)} PSC")

    with pg_cursor() as cur:
        cur.execute("SELECT DISTINCT kode_provinsi, provinsi, kode_kabupaten, kabupaten_kota FROM penduduk_kecamatan")
        master = cur.fetchall()
        pencocok = PencocokKabupaten(master)
        nama_kab_master = {int(m["kode_kabupaten"]): m["kabupaten_kota"] for m in master}
        poligon = _poligon_kab(cur, rows)
        survei = _ringkasan_survei(cur, pencocok)

        valid, ditolak, n_format = [], [], 0
        for i, r in enumerate(rows):
            if r["lat"] is not None and str(r["lat_mentah"]).strip() != str(r["lat"]):
                n_format += isinstance(r["lat_mentah"], str) and (str(r["lat_mentah"]).count(".") > 1
                                                                  or str(r["lat_mentah"]).strip().endswith(","))
            if i not in poligon:
                ditolak.append((r, "koordinat kosong, tak terbaca, atau di luar Indonesia"))
                continue
            kode_p, kab_p, prov_p, jarak = poligon[i]
            if jarak > JARAK_PANTAI_M:
                ditolak.append((r, f"titik {jarak / 1000:.0f} km dari daratan terdekat ({kab_p}); cek tanda/skala koordinat"))
                continue
            nama_kab, inti, tingkat_prov = _nama_kab(r["nama"])
            catatan = None
            if tingkat_prov:
                kode = None
            else:
                m = pencocok.cari(prov_p, nama_kab) or pencocok.cari(None, nama_kab)
                if m is None and inti:
                    # awalan Kab/Kota di sumber salah (mis. "KAB. PRABUMULIH", hanya ada Kota):
                    # terima nama tanpa awalan bila tunggal di master
                    m = pencocok.cari(prov_p, inti) or pencocok.cari(None, inti)
                    if m:
                        catatan = f"Sumber menulis '{nama_kab}'; di master BPS: {m['kabupaten_kota']}"
                if m is None:
                    ditolak.append((r, f"nama kab/kota '{nama_kab}' tidak dikenali; titik jatuh di {kab_p}"))
                    continue
                kode = int(m["kode_kabupaten"])
                if kode_p is not None and kode != kode_p:
                    if _kunci_tanpa_awalan(kab_p) == _kunci_tanpa_awalan(inti):
                        # Kab & Kota bernama sama (Blitar, Madiun): kantor PSC kabupaten berada
                        # di dalam kota -- wajar, titik dipertahankan dgn catatan
                        catatan = f"Lokasi kantor berada di wilayah {kab_p}"
                    else:
                        ditolak.append((r, f"titik jatuh di {kab_p} ({prov_p}), bukan {nama_kab_master.get(kode, nama_kab)}"))
                        continue
            attrs = {
                "Nama PSC": r["nama"],
                "Alamat": r["alamat"],
                "Kab/Kota": (nama_kab_master.get(kode) if kode else None) or kab_p,
                "Provinsi": prov_p,
                "Tingkat": "Provinsi" if tingkat_prov else "Kab/Kota",
                "Kode Kab/Kota (BPS)": kode,
            }
            if catatan:
                attrs["Catatan data"] = catatan
            if kode and kode in survei:
                attrs.update(survei[kode])
            elif kode:
                attrs["Survei layanan 2025"] = "Tidak ada / tidak tunggal di psc119_layanan"
            valid.append((r["lon"], r["lat"], attrs))

        cur.execute("DELETE FROM map_layers WHERE provinsi=%s AND kabupaten=%s AND layer=%s",
                    (PROVINSI_BUCKET, KABUPATEN_BUCKET, LAYER_NAME))
        cur.executemany(
            "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
            "VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))",
            [(PROVINSI_BUCKET, KABUPATEN_BUCKET, LAYER_NAME, Json(a), lon, lat) for lon, lat, a in valid],
        )
        cur.execute(
            """INSERT INTO map_layer_meta (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (provinsi, kabupaten, layer) DO UPDATE SET
                   label=EXCLUDED.label, feature_count=EXCLUDED.feature_count,
                   size_mb=EXCLUDED.size_mb, source_shp=EXCLUDED.source_shp, imported_at=now()""",
            (PROVINSI_BUCKET, KABUPATEN_BUCKET, LAYER_NAME, LABEL, len(valid),
             round(args.xlsx.stat().st_size / 1_048_576, 2), str(args.xlsx.relative_to(REPO_ROOT))),
        )

    n_survei = sum(1 for _, _, a in valid if "Survei: ambulans aktif" in a)
    print(f"Digambar: {len(valid)} titik ({n_survei} tertaut ke survei psc119_layanan); "
          f"format koordinat diperbaiki otomatis: {n_format}")
    print(f"Tidak digambar: {len(ditolak)}")
    for r, alasan in ditolak:
        print(f"  - {r['nama']} [{r['lat_mentah']}, {r['lon_mentah']}]: {alasan}")
    if args.laporan:
        with open(args.laporan, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["No", "Nama PSC", "Latitude (sumber)", "Longitude (sumber)", "Alasan"])
            for r, alasan in ditolak:
                w.writerow([r["no"], r["nama"], r["lat_mentah"], r["lon_mentah"], alasan])
        print(f"Laporan: {args.laporan}")


if __name__ == "__main__":
    main()
