# -*- coding: utf-8 -*-
"""Impor 126 titik Terminal Penumpang Tipe A nasional dari lampiran PDF
Keputusan Menteri Perhubungan No. KM 109 Tahun 2019 (docs/New/5. DARAT/
KM_109_Tahun_2019_Penlok Terminal Tipe A.pdf) ke PostgreSQL/PostGIS,
skema generik map_layers. Lihat docs/kajian_data_baru_docs_new.md §7.4
untuk hasil telaah datanya.

Layer ini murni overlay peta umum, TIDAK terkait usulan_inpres/IJD.

PDF-nya BUKAN scan (teks vektor asli, PyMuPDF get_text() langsung
terbaca), dan tiap entri lampiran mencantumkan koordinat dalam DUA
format sekaligus (DMS dan desimal langsung setelah "/") -- diprioritaskan
regex desimal, fallback ke DMS untuk entri yang format desimalnya hilang/
rusak. Diverifikasi 125/126 entri berhasil diparse (120 lewat desimal, 5
lewat fallback DMS); 1 entri gagal total (No. 120, "Terminal Bolaang
Mongondow" -- teks terminal korup dari sumber PDF/OCR lama,
"125°59'54.89.1°E", dua desimal bertumpuk, tidak bisa
direkonstruksi otomatis) -- entri itu DILEWATI, dicatat di output run.

Entri dipisah dengan regex pada pola "\\nN.\\n" (nomor urut lampiran).
Provinsi tidak diulang di tiap entri pada PDF sumber (cuma muncul saat
berganti) -- dilacak lewat baris pertama tiap entri yang TIDAK diawali
kata "Terminal".

Idempotent: DELETE + INSERT ulang seluruh layer tiap run kecuali sudah
ada & tanpa --force.

Usage (venv aktif):
    python scripts/import_terminal_tipe_a_to_postgis.py
    python scripts/import_terminal_tipe_a_to_postgis.py --force
"""
import argparse
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import fitz
from psycopg.types.json import Json

from db import db_cursor as pg_cursor  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
PDF_PATH = (
    REPO_ROOT / "docs" / "New" / "5. DARAT-20260820T015302Z-1-001"
    / "5. DARAT" / "KM_109_Tahun_2019_Penlok Terminal Tipe A.pdf"
)
PROVINSI_BUCKET = "TERMINAL TIPE A"
KABUPATEN_BUCKET = ""
LAYER_NAME = "TERMINAL TIPE A"
LABEL = "Terminal Penumpang Tipe A (KM 109/2019)"
LAMPIRAN_START_PAGE = 4  # 0-based, halaman pertama daftar terminal (setelah diktum keputusan)

ENTRY_SPLIT_RE = re.compile(r"\n(\d{1,3})\s*\.\s*\n")
DEC_COORD_RE = re.compile(r"(-?\d{1,3}\.\d{3,})\s*,\s*(-?\d{1,3}\.\d{3,})")
DMS_COORD_RE = re.compile(
    r"(\d{1,3})\D+(\d{1,2})\D+([\d.]+)\D*([NSEW])\s+(\d{1,3})\D+(\d{1,2})\D+([\d.]+)\D*([NSEW])",
    re.IGNORECASE,
)
TERM_NAME_RE = re.compile(r"Terminal\s+[^\n]+", re.IGNORECASE)

# Rentang lat/lon kasar wilayah Indonesia -- dipakai memvalidasi hasil
# parse desimal maupun DMS, membuang hasil yang jelas salah tanpa
# menjatuhkan seluruh entri (fallback DMS baru dicoba kalau desimal gagal
# ATAU nilainya di luar rentang ini).
LAT_RANGE, LON_RANGE = (-11, 6), (95, 141)


def _dms_to_decimal(deg, minute, sec, hemi):
    try:
        val = float(deg) + float(minute) / 60 + float(sec) / 3600
    except ValueError:
        return None
    return -val if hemi.upper() in ("S", "W") else val


def _in_range(lat, lon):
    return LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]


def _parse_coord(chunk):
    m = DEC_COORD_RE.search(chunk)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        if _in_range(lat, lon):
            return lat, lon, "desimal"
    m = DMS_COORD_RE.search(chunk)
    if m:
        d1, m1, s1, h1, d2, m2, s2, h2 = m.groups()
        lat, lon = _dms_to_decimal(d1, m1, s1, h1), _dms_to_decimal(d2, m2, s2, h2)
        if lat is not None and lon is not None and _in_range(lat, lon):
            return lat, lon, "dms"
    return None


def _extract_lampiran_text():
    doc = fitz.open(PDF_PATH)
    text = ""
    for p in range(LAMPIRAN_START_PAGE, len(doc)):
        text += doc[p].get_text() + "\n"
    return text


def _load_rows():
    text = _extract_lampiran_text()
    parts = ENTRY_SPLIT_RE.split(text)
    current_provinsi = None
    rows, failed = [], []

    for i in range(1, len(parts), 2):
        no = parts[i]
        content = parts[i + 1]
        lines = [l.strip() for l in content.split("\n") if l.strip()]
        if not lines:
            continue
        if not lines[0].lower().startswith("terminal"):
            current_provinsi = lines[0]

        name_match = TERM_NAME_RE.search(content)
        nama = name_match.group(0).strip() if name_match else None
        parsed = _parse_coord(content)
        if parsed is None:
            failed.append((no, nama))
            continue
        lat, lon, sumber = parsed
        attrs = {"no": int(no), "provinsi": current_provinsi, "nama_terminal": nama,
                 "sumber_koordinat": sumber}
        rows.append((lat, lon, attrs))
    return rows, failed


def _already_imported(cur):
    cur.execute(
        "SELECT 1 FROM map_layer_meta WHERE provinsi=%s AND kabupaten=%s AND layer=%s",
        (PROVINSI_BUCKET, KABUPATEN_BUCKET, LAYER_NAME),
    )
    return cur.fetchone() is not None


def _delete_layer(cur):
    cur.execute(
        "DELETE FROM map_layers WHERE provinsi=%s AND kabupaten=%s AND layer=%s",
        (PROVINSI_BUCKET, KABUPATEN_BUCKET, LAYER_NAME),
    )
    cur.execute(
        "DELETE FROM map_layer_meta WHERE provinsi=%s AND kabupaten=%s AND layer=%s",
        (PROVINSI_BUCKET, KABUPATEN_BUCKET, LAYER_NAME),
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="impor ulang meski sudah ada di map_layer_meta")
    args = ap.parse_args()

    if not PDF_PATH.exists():
        print(f"GAGAL: tidak ditemukan {PDF_PATH}")
        sys.exit(1)

    print(f"Membaca {PDF_PATH.name}...")
    rows, failed = _load_rows()
    print(f"  {len(rows)} titik valid, {len(failed)} entri gagal diparse")
    for no, nama in failed:
        print(f"    [gagal] No. {no}: {nama}")

    with pg_cursor() as cur:
        if not args.force and _already_imported(cur):
            print(f"  [lewat] {LAYER_NAME} (sudah ada, pakai --force untuk impor ulang)")
            return
        if args.force:
            _delete_layer(cur)

        cur.executemany(
            "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
            "VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))",
            [(PROVINSI_BUCKET, KABUPATEN_BUCKET, LAYER_NAME, Json(attrs), lon, lat)
             for lat, lon, attrs in rows],
        )
        cur.execute(
            """INSERT INTO map_layer_meta
                   (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (provinsi, kabupaten, layer) DO UPDATE SET
                   label=EXCLUDED.label, feature_count=EXCLUDED.feature_count,
                   size_mb=EXCLUDED.size_mb, source_shp=EXCLUDED.source_shp,
                   imported_at=now()""",
            (PROVINSI_BUCKET, KABUPATEN_BUCKET, LAYER_NAME, LABEL,
             len(rows), round(PDF_PATH.stat().st_size / 1_048_576, 2),
             str(PDF_PATH.relative_to(REPO_ROOT))),
        )

    print(f"\nSelesai: {len(rows)} titik Terminal Tipe A diimpor.")


if __name__ == "__main__":
    main()
