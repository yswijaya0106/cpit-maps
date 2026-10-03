# -*- coding: utf-8 -*-
"""Impor inventaris perlintasan KA per BTP (Balai Teknik Perkeretaapian) ke
PostGIS -- layer "Perlintasan KA (Data BTP)" di bucket "PERLINTASAN SEBIDANG KA"
(kategori Kereta Api, berdampingan dgn layer rencana penanganan SS KA).

Sumber: docs/Konektivitas/4. KERETA (KA)/ (versi 27 Sep 2026):
  BTP Bandung (Daop 1-3), BTP Medan (Divre 1), BTP Padang (Divre 2),
  BTP Semarang (Daop 4-6), BTP Surabaya (Daop 7-9), DATA JPL BTP PLM (Palembang).
BTP Jakarta (Daop 1) TIDAK diimpor: file-nya tanpa koordinat (hanya KM/HM).

Format tiap BTP berbeda (header 1-4 baris, status penjagaan berupa teks ATAU
kolom centang resmi/liar x penjaga, koordinat x/y, Latitude/Longitude, teks
"lat, lon", atau derajat-menit-detik). Parser di sini generik: label kolom =
gabungan teks header bertingkat (sel gabungan diisi ke kanan), lalu kolom
dicari lewat kata kunci; konfigurasi per BTP hanya sheet & baris header awal.

Normalisasi (kolom "Kategori", "Legalitas", "Penjagaan"):
  Kategori  Sebidang / Tidak sebidang (flyover, underpass, JPO) / Ditutup
  Legalitas Resmi / Liar (tidak terdaftar)
  Penjagaan Dijaga PT KAI / Dijaga Pemda-Dishub / Dijaga swadaya / Dijaga
            swasta / Dijaga lainnya / Tidak dijaga
Teks status asli tetap disimpan ("Status (sumber)"). Titik diwarnai menurut
status (properti _warna, legenda PERLINTASAN_BTP_LEGEND di maps-overlay.js --
warna HARUS sama dgn WARNA di bawah).

Pengayaan spasial: kab/kota dari poligon BATAS KABUPATEN, dan apakah ada
titik potong jalan-rel (layer TITIK POTONG JALAN-REL KA) <= 100 m.

Idempotent: DELETE + reinsert layer. Restart server setelah rerun.

Usage (venv aktif):
    python scripts/import_perlintasan_btp_to_postgis.py
"""
import io
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import openpyxl  # noqa: E402
from psycopg.types.json import Json  # noqa: E402

from db import db_cursor as pg_cursor  # noqa: E402

SUMBER_DIR = REPO_ROOT / "docs" / "Konektivitas" / "4. KERETA (KA)"
PROVINSI_BUCKET = "PERLINTASAN SEBIDANG KA"
KABUPATEN_BUCKET = ""
LAYER_NAME = "Perlintasan KA (Data BTP)"
LABEL = "Perlintasan KA per BTP (Bandung, Medan, Padang, Semarang, Surabaya, Palembang)"

# (BTP, file, sheet atau None = semua sheet kecuali yg namanya diawali salah satu `lewati`,
#  indeks baris header pertama, awalan nama sheet yg dilewati)
SUMBER = [
    ("BTP Bandung", "BTP Bandung (Daop 1, 2, 3).xlsx", ["MASTER DATA PERLINTASAN BTP "], 0, ()),
    ("BTP Medan", "BTP Medan (Divre 1).xlsx", ["E-PERLINTASAN"], 0, ()),
    ("BTP Padang", "BTP Padang (Divre 2).xlsx", ["PERLINTASAN"], 3, ()),
    ("BTP Semarang", "BTP Semarang (Daop 4, 5, 6).xlsx", None, 1, ("REKAP",)),
    ("BTP Surabaya", "BTP Surabaya (Daop 7, 8, 9).xlsx", None, 0, ("REKAP",)),
    ("BTP Palembang", "DATA JPL BTP PLM.xlsx", ["JPL No Baru Urut"], 1, ()),
]

WARNA = {
    "Dijaga PT KAI": "#1565C0",
    "Dijaga Pemda/Dishub": "#00897B",
    "Dijaga swadaya/swasta/lainnya": "#F9A825",
    "Tidak dijaga (resmi)": "#E53935",
    "Liar": "#6A1B9A",
    "Tidak sebidang": "#9E9E9E",
    "Ditutup": "#424242",
    "Status tidak tercatat": "#BDBDBD",
}

_DMS = re.compile(r"(\d+)\s*°\s*(\d+)\s*['’′]\s*([\d.,]+)\s*[\"”″]?\s*([NS])\s*[,;]?\s*"
                  r"(\d+)\s*°\s*(\d+)\s*['’′]\s*([\d.,]+)\s*[\"”″]?\s*([EW])", re.I)
_DESIMAL = re.compile(r"-?\d{1,3}[.,]\d{3,}")


def _f(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip().replace(",", "."))
    except ValueError:
        return None


def _di_indonesia(lat, lon):
    return lat is not None and lon is not None and -11.5 <= lat <= 6.5 and 94 <= lon <= 141.5 and abs(lat) > 0.01


def _pasangan(a, b):
    """Dua angka -> (lat, lon) bila salah satu urutan masuk akal di Indonesia."""
    if _di_indonesia(a, b):
        return a, b
    if _di_indonesia(b, a):
        return b, a
    return None


def _koordinat_teks(s):
    m = _DMS.search(s)
    if m:
        g = m.groups()
        lat = (float(g[0]) + float(g[1]) / 60 + float(g[2].replace(",", ".")) / 3600) * (-1 if g[3].upper() == "S" else 1)
        lon = (float(g[4]) + float(g[5]) / 60 + float(g[6].replace(",", ".")) / 3600) * (-1 if g[7].upper() == "W" else 1)
        return _pasangan(lat, lon)
    angka = _DESIMAL.findall(s)
    if len(angka) >= 2:
        return _pasangan(_f(angka[0]), _f(angka[1]))
    return None


def _isi(v):
    """Sel centang/teks dianggap terisi?"""
    if v is None or isinstance(v, bool) and not v:
        return False
    s = str(v).strip().upper()
    return s not in ("", "0", "0.0", "-", "FALSE", "TIDAK", "X0")


def _label_kolom(header_rows, n_kol):
    """-> (leaf, full) per kolom. leaf = teks header terbawah yg terisi; full = semua tingkat,
    sel gabungan horizontal diisi ke kanan (hanya di tingkat yg punya nilai di kiri)."""
    tingkat = []
    for r in header_rows:
        baris, terakhir, asal = [], "", None
        for j in range(n_kol):
            v = r[j] if j < len(r) else None
            t = re.sub(r"\s+", " ", str(v)).strip() if v not in (None, "") else ""
            if re.fullmatch(r"\d+(\.0)?", t):  # baris penomoran kolom (1, 2, 3, ...): putus isian ke kanan
                terakhir, asal = "", None
                baris.append(("", False))
                continue
            if t:
                terakhir, asal = t, j
                baris.append((t, True))
            elif asal is not None and all(atas[j][0] == atas[asal][0] for atas in tingkat):
                # sel gabungan: isi ke kanan HANYA selama masih di grup header atas yg sama
                # (Padang: "Tidak Dijaga" tidak boleh merembet ke kolom "Nama Jalan/Desa")
                baris.append((terakhir, False))
            else:
                terakhir, asal = "", None
                baris.append(("", False))
        tingkat.append(baris)
    leaf, full = [], []
    for j in range(n_kol):
        asli = [b[j][0] for b in tingkat if b[j][1]]
        leaf.append(asli[-1] if asli else "")
        full.append(" | ".join(t for t in (b[j][0] for b in tingkat) if t))
    return leaf, full


def _cari(leaf, pola, kecuali=()):
    for j, t in enumerate(leaf):
        if t and re.search(pola, t, re.I) and j not in kecuali:
            return j
    return None


def _peta_kolom(leaf, full):
    k = {
        "km": _cari(leaf, r"^(KM\s*/\s*HM|KM\s*\+\s*HM|KM-HM|KM|LOKASI KM)$"),
        "jpl": (_cari(leaf, r"NO\.?\s*JPL\s*BARU") or _cari(leaf, r"^NOMOR JPL|^NO\.?\s*JPL$")
                or _cari(leaf, r"KODE PERLINTASAN") or _cari(leaf, r"NO\.?\s*JPL\s*LAMA")),
        "petak": _cari(leaf, r"PETAK|^ANTARA|STASIUN ANTARA|ANTARA STASIUN"),
        "lintas": _cari(leaf, r"^LINTAS"),
        "jalan": _cari(leaf, r"NAMA JALAN|^JALAN$"),
        "desa": _cari(leaf, r"^DESA$"),
        "kecamatan": _cari(leaf, r"^KECAMATAN$"),
        "kab": _cari(leaf, r"^KABUPATEN(/KOTA)?$|^DESA/KOTA$"),
        "kelas": _cari(leaf, r"KLASIFIKASI JALAN|STATUS JALAN|KEWENANGAN|KELAS JALAN"),
        "status": _cari(leaf, r"^STATUS PERLINTASAN$|^PENJAGAAN$|^STATUS PENJAGAAN$"),
        "kategori": _cari(leaf, r"^KATEGORI PERLINTASAN$"),
        "lebar": _cari(leaf, r"^LEBAR( JALAN)?"),
        "lat": _cari(leaf, r"^(LATITUDE|LINTANG)$"),
        "lon": _cari(leaf, r"^(LONGITUDE|BUJUR)$"),
        "x": _cari(leaf, r"^x$"),
        "y": _cari(leaf, r"^y$"),
        "koord_teks": _cari(leaf, r"TITIK KOORDINAT"),
    }
    # Padang: kolom "Jalan" di bawah "Status" = status jalan
    j = next((i for i, f in enumerate(full) if re.search(r"^STATUS \| JALAN$", f, re.I)), None)
    if k["kelas"] is None and j is not None:
        k["kelas"] = j
    # kolom centang status: label penuh memuat DIJAGA / FLYOVER / UNDERPASS / TUTUP / TERDAFTAR
    k["centang"] = [i for i, f in enumerate(full)
                    if re.search(r"DIJAGA|FLYOVER|UNDERPASS|\bTUTUP\b|TERDAFTAR", f, re.I)
                    and not re.search(r"RAMBU|KONDISI|TOTAL", f, re.I)]
    # klasifikasi jalan berupa centang (Palembang: Desa / Kab/Kota / Provinsi / Nasional)
    k["kelas_centang"] = [i for i, f in enumerate(full)
                          if re.search(r"^KLASIFIKASI JALAN \| ", f, re.I)
                          and re.search(r"DESA|KAB|KOTA|PROVINSI|NASIONAL", leaf[i], re.I)]
    return k


def _nilai(r, j):
    if j is None or j >= len(r):
        return None
    v = r[j]
    if v in (None, ""):
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    if re.fullmatch(r"-?\d+\.0", s):
        s = s[:-2]
    return None if s in ("-", "None") else s


def _normalisasi(teks):
    u = (teks or "").upper()
    if re.search(r"TIDAK SEBIDANG|FLY ?OVER|UNDERPASS|\bJPO\b|SKYBRIDGE|JEMBATAN PENYEBERANGAN", u):
        return "Tidak sebidang", None, None
    if re.search(r"\bTUTUP\b|DITUTUP|PENUTUPAN", u):
        return "Ditutup", None, None
    legal = ("Liar" if re.search(r"LIAR|TIDAK TERDAFTAR|TIDAK TEREGISTER|TIDAK RESMI|TAK TERDAFTAR", u)
             else "Resmi" if re.search(r"RESMI|TERDAFTAR|TEREGISTER", u) else None)
    if re.search(r"TIDAK DIJAGA|TAK TERJAGA|TIDAK TERJAGA|TANPA PENJAGA", u):
        jaga = "Tidak dijaga"
    elif re.search(r"PT\.?\s*KAI|\bKAI\b", u):
        jaga = "Dijaga PT KAI"
    elif re.search(r"PEMDA|DISHUB|DINAS PERHUBUNGAN", u):
        jaga = "Dijaga Pemda/Dishub"
    elif re.search(r"SWADAYA|MASYARAKAT", u):
        jaga = "Dijaga swadaya"
    elif re.search(r"SWASTA", u):
        jaga = "Dijaga swasta"
    elif re.search(r"DIJAGA|TERJAGA", u):
        jaga = "Dijaga lainnya"
    else:
        jaga = None
    return "Sebidang", legal, jaga


def _kelas_warna(kategori, legal, jaga):
    if kategori == "Tidak sebidang":
        return "Tidak sebidang"
    if kategori == "Ditutup":
        return "Ditutup"
    if legal == "Liar":
        return "Liar"
    if jaga == "Dijaga PT KAI":
        return "Dijaga PT KAI"
    if jaga == "Dijaga Pemda/Dishub":
        return "Dijaga Pemda/Dishub"
    if jaga and jaga.startswith("Dijaga"):
        return "Dijaga swadaya/swasta/lainnya"
    if jaga == "Tidak dijaga":
        return "Tidak dijaga (resmi)"
    return "Status tidak tercatat"


def _baca_sheet(btp, ws, header_awal):
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) <= header_awal:
        return []
    n_kol = max(len(r) for r in rows)
    # baris data pertama = baris pertama setelah header yg diawali nomor urut DAN memuat teks
    # (baris penomoran kolom 1,2,3,... hanya angka). Bukan "baris pertama berkoordinat": baris
    # data pertama bisa tanpa koordinat (Surabaya/Bojonegoro: underpass) dan teksnya akan
    # terbaca sbg label header. Deteksi koordinat hanya cadangan.
    data_awal = None
    for i in range(header_awal + 1, min(len(rows), header_awal + 15)):
        r = rows[i]
        if (r and _f(r[0]) is not None and
                any(isinstance(v, str) and v.strip() and _f(v) is None for v in r[1:])):
            data_awal = i
            break
    for i in range(header_awal + 1, min(len(rows), header_awal + 15)) if data_awal is None else ():
        for v in rows[i]:
            if isinstance(v, str) and _koordinat_teks(v):
                data_awal = i
                break
        if data_awal is None:
            angka = [_f(v) for v in rows[i]]
            if any(_pasangan(a, b) for a, b in zip(angka, angka[1:]) if a is not None and b is not None):
                data_awal = i
        if data_awal is not None:
            break
    if data_awal is None:
        return []
    leaf, full = _label_kolom(rows[header_awal:data_awal], n_kol)
    k = _peta_kolom(leaf, full)
    kab_sheet = ws.title.strip() if re.match(r"^(KAB|KOTA)\b", ws.title.strip(), re.I) else None
    out = []
    for r in rows[data_awal:]:
        r = tuple(r) + (None,) * (n_kol - len(r))
        koord = None
        for a, b in ((k["lat"], k["lon"]), (k["x"], k["y"])):
            if a is not None and b is not None:
                koord = _pasangan(_f(r[a]), _f(r[b]))
                if koord:
                    break
        if not koord and k["koord_teks"] is not None and isinstance(r[k["koord_teks"]], str):
            koord = _koordinat_teks(r[k["koord_teks"]])
        if not koord:
            continue
        status_teks = " ; ".join(t for t in (_nilai(r, k["kategori"]), _nilai(r, k["status"])) if t)
        centang = " ; ".join(full[j] for j in k["centang"] if _isi(r[j]))
        kategori, legal, jaga = _normalisasi(status_teks + " ; " + centang)
        kelas = _nilai(r, k["kelas"])
        if not kelas and k["kelas_centang"]:
            kelas = next((leaf[j] for j in k["kelas_centang"] if _isi(r[j])), None)
        petak = " / ".join(t for t in (_nilai(r, k["lintas"]), _nilai(r, k["petak"])) if t) or None
        warna_kelas = _kelas_warna(kategori, legal, jaga)
        out.append({
            "lat": koord[0], "lon": koord[1],
            "attrs": {
                "BTP": btp,
                "No JPL": _nilai(r, k["jpl"]),
                "KM/HM": _nilai(r, k["km"]),
                "Lintas / Petak": petak,
                "Nama Jalan": _nilai(r, k["jalan"]),
                "Desa": _nilai(r, k["desa"]),
                "Kecamatan": _nilai(r, k["kecamatan"]),
                "Kab/Kota (sumber)": _nilai(r, k["kab"]) or kab_sheet,
                "Kelas / Status Jalan": kelas,
                "Lebar Jalan (m)": _nilai(r, k["lebar"]),
                "Kategori": kategori,
                "Legalitas": legal,
                "Penjagaan": jaga,
                "Status (sumber)": (status_teks or centang or None),
                "Kelas Warna": warna_kelas,
                "Sheet sumber": ws.title.strip(),
                "_warna": WARNA[warna_kelas],
            },
        })
    return out


def baca_semua():
    semua, ringkas = [], []
    for btp, nama, sheets, header_awal, lewati in SUMBER:
        path = SUMBER_DIR / nama
        if not path.exists():
            print(f"  [lewat] {nama} tidak ditemukan")
            continue
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        dipakai = [wb[s] for s in sheets] if sheets else [
            ws for ws in wb.worksheets if not ws.title.strip().upper().startswith(lewati)]
        titik, lihat = [], set()
        for ws in dipakai:
            for t in _baca_sheet(btp, ws, header_awal):
                kunci = (round(t["lat"], 5), round(t["lon"], 5), t["attrs"]["KM/HM"])
                if kunci in lihat:  # duplikat antar sheet (rekap vs rincian)
                    continue
                lihat.add(kunci)
                titik.append(t)
        ringkas.append((btp, len(titik)))
        semua.extend(titik)
    return semua, ringkas


def _pengayaan_spasial(cur, titik):
    if not titik:
        return
    cur.execute(
        """WITH p(i, lon, lat) AS (SELECT * FROM unnest(%s::int[], %s::float8[], %s::float8[])),
                g AS (SELECT i, ST_SetSRID(ST_Point(lon, lat), 4326) AS pt FROM p)
           SELECT g.i,
                  (SELECT m.attrs FROM map_layers m WHERE m.provinsi = 'BATAS KABUPATEN'
                     AND ST_Contains(m.geom, g.pt) LIMIT 1) AS kab,
                  (SELECT ST_Distance(m.geom::geography, g.pt::geography) FROM map_layers m
                     WHERE m.provinsi = 'TITIK POTONG JALAN-REL KA'
                     ORDER BY m.geom <-> g.pt LIMIT 1) AS jarak_potong
           FROM g""",
        (list(range(len(titik))), [t["lon"] for t in titik], [t["lat"] for t in titik]),
    )
    for r in cur.fetchall():
        a = titik[r["i"]]["attrs"]
        kab = r["kab"] or {}
        a["Kab/Kota (spasial)"] = kab.get("KABUPATEN_KOTA")
        a["Provinsi (spasial)"] = kab.get("PROVINSI")
        a["Kode Kab/Kota (BPS)"] = kab.get("KODE_KABUPATEN")
        jp = r["jarak_potong"]
        a["Titik potong jalan-rel <= 100 m"] = ("Ya" if jp is not None and jp <= 100 else "Tidak")


def main():
    titik, ringkas = baca_semua()
    for btp, n in ringkas:
        print(f"  {btp}: {n} perlintasan berkoordinat")
    with pg_cursor() as cur:
        _pengayaan_spasial(cur, titik)
        cur.execute("DELETE FROM map_layers WHERE provinsi=%s AND kabupaten=%s AND layer=%s",
                    (PROVINSI_BUCKET, KABUPATEN_BUCKET, LAYER_NAME))
        cur.executemany(
            "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
            "VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))",
            [(PROVINSI_BUCKET, KABUPATEN_BUCKET, LAYER_NAME,
              Json({k: v for k, v in t["attrs"].items() if v is not None}), t["lon"], t["lat"]) for t in titik],
        )
        cur.execute(
            """INSERT INTO map_layer_meta (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (provinsi, kabupaten, layer) DO UPDATE SET
                   label=EXCLUDED.label, feature_count=EXCLUDED.feature_count,
                   size_mb=EXCLUDED.size_mb, source_shp=EXCLUDED.source_shp, imported_at=now()""",
            (PROVINSI_BUCKET, KABUPATEN_BUCKET, LAYER_NAME, LABEL, len(titik),
             round(sum((SUMBER_DIR / s[1]).stat().st_size for s in SUMBER if (SUMBER_DIR / s[1]).exists()) / 1_048_576, 2),
             str(SUMBER_DIR.relative_to(REPO_ROOT))),
        )
    from collections import Counter
    print(f"Total: {len(titik)} titik")
    print("Kelas warna:", dict(Counter(t["attrs"]["Kelas Warna"] for t in titik).most_common()))
    print("Di luar poligon kab:", sum(1 for t in titik if not t["attrs"].get("Kab/Kota (spasial)")),
          "| dekat titik potong <=100 m:", sum(1 for t in titik if t["attrs"]["Titik potong jalan-rel <= 100 m"] == "Ya"))


if __name__ == "__main__":
    main()
