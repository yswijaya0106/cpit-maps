# -*- coding: utf-8 -*-
"""Impor titik pelabuhan penumpang nasional (docs/New/2. LAUT/
Koordinat_Data Pelabuhan Penumpang.xlsx, sheet "Data Dashboard") ke
PostgreSQL/PostGIS, skema generik map_layers. Lihat
docs/kajian_data_baru_docs_new.md §4.3 untuk hasil telaah datanya.

Layer ini murni overlay peta umum, TIDAK terkait usulan_inpres/IJD.

Koordinat lat/lon sudah desimal langsung di xlsx. Atribut jauh lebih
kaya dari layer pelabuhan SHP yang sudah ada -- hierarki resmi (PP/PL/
PR/PU), unit pengawasan (KSOP/UPP), operator, status operasional --
diimpor sebagai layer BARU terpisah (bukan menimpa layer "PELABUHAN"
existing) supaya sumber data lama & baru tidak tercampur.

Bucket flat nasional "PELABUHAN PENUMPANG" (pola sama dengan TERSUS/TUKS/
Terminal Tipe A) -- didaftarkan ke kategori existing "Simpul
Transportasi" di maps-overlay.js.

Idempotent: DELETE + INSERT ulang seluruh layer tiap run kecuali sudah
ada & tanpa --force.

Usage (venv aktif):
    python scripts/import_pelabuhan_penumpang_to_postgis.py
    python scripts/import_pelabuhan_penumpang_to_postgis.py --force
"""
import argparse
import io
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
    REPO_ROOT / "docs" / "New" / "2. LAUT -20260820T015256Z-1-001"
    / "2. LAUT" / "Koordinat_Data Pelabuhan Penumpang.xlsx"
)
PROVINSI_BUCKET = "PELABUHAN PENUMPANG"
KABUPATEN_BUCKET = ""
LAYER_NAME = "PELABUHAN PENUMPANG"
LABEL = "Pelabuhan Penumpang"

# Kolom sheet "Data Dashboard" (0-based tuple index): 0=OBJECTID_1,
# 1=KD_PROV, 2=PROV, 3=KD_KABKOT, 4=KABKOT, 5=Nama Pelabuhan,
# 6=Kode Pelabuhan, 7=lat, 8=lon, 9=hierarkis, 10=Unit Pengawasan,
# 11=Operator, 12=status


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _load_rows():
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True, read_only=True)
    ws = wb["Data Dashboard"]
    rows, n_bad = [], 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is None:
            continue
        lat, lon = _to_float(row[7]), _to_float(row[8])
        if lat is None or lon is None or not (-11 <= lat <= 6) or not (95 <= lon <= 141):
            n_bad += 1
            continue
        attrs = {
            "provinsi": row[2], "kabupaten_kota": row[4],
            "nama_pelabuhan": row[5], "kode_pelabuhan": row[6],
            "hierarki": row[9], "unit_pengawasan": row[10],
            "operator": (row[11] or "").strip() or None, "status": row[12],
        }
        rows.append((lat, lon, attrs))
    return rows, n_bad


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
    rows, n_bad = _load_rows()
    print(f"  {len(rows)} titik valid, {n_bad} baris dibuang (koordinat kosong/tak-terparse/di luar rentang Indonesia)")

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

    print(f"\nSelesai: {len(rows)} titik pelabuhan penumpang diimpor.")


if __name__ == "__main__":
    main()
