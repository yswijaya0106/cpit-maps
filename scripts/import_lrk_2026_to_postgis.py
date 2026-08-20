# -*- coding: utf-8 -*-
"""Impor titik Lokasi Rawan Kecelakaan (LRK) program 2026 Bina Marga
(docs/New/8. KESELAMATAN/REKAP LRK - Tahun 2025 dan 2026.xlsx, sheet
"LRK 2026") ke PostgreSQL/PostGIS, skema generik map_layers. Lihat
docs/kajian_data_baru_docs_new.md §9.5 untuk hasil telaah datanya.

Layer ini murni overlay peta umum, TIDAK terkait usulan_inpres/IJD.

**Kualitas sumber jauh lebih buruk dari sampel awal kajian** (yang cuma
melihat 4 baris rapi provinsi Aceh) -- diverifikasi penuh saat
implementasi: format koordinat di kolom "Nama Ruas" sangat tidak
konsisten antar provinsi/BPTD -- kombinasi (a) pasangan desimal dalam
kurung "(lat, lon)", (b) pasangan desimal tanpa kurung, (c) koma sebagai
pemisah desimal (notasi Indonesia, "lat,xxx lon,xxx"), (d) format DMS
dengan simbol derajat, (e) SATU baris dengan >1 titik LRK (multi-baris
dalam satu sel), dan (f) banyak baris TANPA koordinat sama sekali (cuma
nama ruas + panjang km, atau catatan "Yang sudah selesai pembangunan").
Beberapa entri juga korup tak terpulihkan (mis. "-1806569,115838" --
titik desimal hilang dari sumber, tidak bisa direkonstruksi otomatis).

Empat pola regex dicoba berurutan (desimal-berkurung -> desimal-koma ->
desimal-bebas -> DMS-berpasangan), SEMUA kecocokan valid per baris
diambil (`finditer`, bukan `search`) karena satu ruas bisa punya
beberapa titik LRK. Baris tanpa kecocokan apa pun DILEWATI (bukan
kegagalan parsing -- banyak yang memang tidak mencantumkan koordinat).
Hasil akhir: 55 titik valid dari ~130 baris ruas (49 baris berkontribusi
>=1 titik) -- cakupan parsial, jauh lebih kecil dari estimasi awal
kajian (129 titik "kalau semua baris berkoordinat"), tapi konsisten
dengan prioritas rendah yang sudah ditetapkan sebelumnya (satu tahun
program, jauh lebih kecil dari Blackspot §9.2 yang 5 tahun/839 titik).

Idempotent: DELETE + INSERT ulang seluruh layer tiap run kecuali sudah
ada & tanpa --force.

Usage (venv aktif):
    python scripts/import_lrk_2026_to_postgis.py
    python scripts/import_lrk_2026_to_postgis.py --force
"""
import argparse
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import openpyxl
from psycopg.types.json import Json

from db import db_cursor as pg_cursor  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
XLSX_PATH = (
    REPO_ROOT / "docs" / "New" / "8. KESELAMATAN-20260820T015309Z-1-001"
    / "8. KESELAMATAN" / "REKAP LRK - Tahun 2025 dan 2026.xlsx"
)
# Ditumpangkan pada bucket "JALAN NASIONAL" yang sudah ada (bukan bucket
# baru) -- pola sama dengan BLACKSPOT KECELAKAAN (Fase 2), supaya tidak
# perlu registrasi kategori baru di maps-overlay.js.
PROVINSI_BUCKET = "JALAN NASIONAL"
KABUPATEN_BUCKET = ""
LAYER_NAME = "LOKASI RAWAN KECELAKAAN 2026"
LABEL = "Lokasi Rawan Kecelakaan (LRK) 2026"

LAT_RANGE, LON_RANGE = (-11, 6), (95, 141)
_PAREN_DEC = re.compile(r"\((-?\d{1,3}\.\d{3,}),?\s+(-?\d{1,3}\.\d{3,})\)")
_COMMA_DEC = re.compile(r"(-?\d{1,2},\d{4,})\s+(-?\d{2,3},\d{4,})")
_BARE_DEC = re.compile(r"(-?\d{1,2}\.\d{4,})\D{1,3}(-?\d{2,3}\.\d{4,})")
_DMS_PAIR = re.compile(
    r"(\d{1,3})\D+(\d{1,2})\D+([\d.]+)\D*([NSEW])\s+(\d{1,3})\D+(\d{1,2})\D+([\d.]+)\D*([NSEW])",
    re.IGNORECASE,
)


def _dms_to_decimal(deg, minute, sec, hemi):
    try:
        val = float(deg) + float(minute) / 60 + float(sec) / 3600
    except ValueError:
        return None
    return -val if hemi.upper() in ("S", "W") else val


def _in_range(lat, lon):
    return LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]


def _extract_all_coords(text):
    found = []
    for m in _PAREN_DEC.finditer(text):
        found.append((float(m.group(1)), float(m.group(2))))
    if not found:
        for m in _COMMA_DEC.finditer(text):
            found.append((float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))))
    if not found:
        for m in _BARE_DEC.finditer(text):
            found.append((float(m.group(1)), float(m.group(2))))
    if not found:
        for m in _DMS_PAIR.finditer(text):
            d1, m1, s1, h1, d2, m2, s2, h2 = m.groups()
            lat, lon = _dms_to_decimal(d1, m1, s1, h1), _dms_to_decimal(d2, m2, s2, h2)
            if lat is not None and lon is not None:
                found.append((lat, lon))
    return [(lat, lon) for lat, lon in found if _in_range(lat, lon)]


def _load_rows():
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True, read_only=True)
    ws = wb["LRK 2026"]
    current_provinsi = None
    rows, n_rows_no_coord = [], 0
    for row in ws.iter_rows(min_row=3, values_only=True):
        provinsi, nama_ruas = row[1], row[2]
        if provinsi:
            current_provinsi = provinsi
        if not nama_ruas:
            continue
        coords = _extract_all_coords(str(nama_ruas))
        if not coords:
            n_rows_no_coord += 1
            continue
        for idx, (lat, lon) in enumerate(coords, start=1):
            attrs = {"provinsi": current_provinsi, "nama_ruas": str(nama_ruas).strip(),
                     "titik_ke": idx if len(coords) > 1 else None}
            rows.append((lat, lon, attrs))
    return rows, n_rows_no_coord


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

    if not XLSX_PATH.exists():
        print(f"GAGAL: tidak ditemukan {XLSX_PATH}")
        sys.exit(1)

    print(f"Membaca {XLSX_PATH.name}...")
    rows, n_rows_no_coord = _load_rows()
    print(f"  {len(rows)} titik valid, {n_rows_no_coord} baris ruas tanpa koordinat yang bisa dikenali (dilewati)")

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
             len(rows), round(XLSX_PATH.stat().st_size / 1_048_576, 2),
             str(XLSX_PATH.relative_to(REPO_ROOT))),
        )

    print(f"\nSelesai: {len(rows)} titik LRK 2026 diimpor.")


if __name__ == "__main__":
    main()
