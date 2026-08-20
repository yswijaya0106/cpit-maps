# -*- coding: utf-8 -*-
"""Impor titik blackspot (rawan kecelakaan) Jalan Nasional 2020-2024 dari
Bina Marga (docs/New/8. KESELAMATAN/Blackspot Bina Marga Jalan Nasional
2020-2024.xlsx) ke PostgreSQL/PostGIS -- skema generik map_layers, sama
dengan import_basarnas_to_postgis.py. Lihat docs/kajian_data_baru_docs_new.md
§9.2 untuk hasil telaah datanya.

Layer ini murni overlay peta umum, TIDAK terkait usulan_inpres atau skoring
IJD -- ditumpangkan pada bucket "JALAN NASIONAL" yang sudah ada (bukan
bucket baru) supaya muncul sebagai toggle sejajar dengan layer garis jalan
nasional yang sudah ada, sesuai maksud "overlay pada JALAN NASIONAL".

Kolom sumber `LTG` (lintang/lat) dan `BJR` (bujur/lon) tersimpan sebagai
teks di xlsx. ~12% baris (115/955 pada saat kajian ditulis) punya nilai
kosong atau tak bisa di-parse -- baris itu DIBUANG (bukan disimpan dengan
geometri null), dicatat jumlahnya di akhir run.

Resumable via map_layer_meta (layer="BLACKSPOT KECELAKAAN") -- dilewati
kecuali --force.

Usage (venv aktif):
    python scripts/import_blackspot_to_postgis.py
    python scripts/import_blackspot_to_postgis.py --force
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
    REPO_ROOT / "docs" / "New" / "8. KESELAMATAN-20260820T015309Z-1-001"
    / "8. KESELAMATAN" / "Blackspot Bina Marga Jalan Nasional 2020-2024.xlsx"
)
PROVINSI_BUCKET = "JALAN NASIONAL"
KABUPATEN_BUCKET = ""
LAYER_NAME = "BLACKSPOT KECELAKAAN"
LABEL = "Blackspot Kecelakaan (Bina Marga 2020-2024)"


def _to_float(v):
    if v is None:
        return None
    try:
        f = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return f


def _load_rows():
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True, read_only=True)
    ws = wb["Sheet1"]
    rows, n_bad = [], 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        no, ltg, bjr, _id, prov, nama_ruas = row[1], row[2], row[3], row[4], row[5], row[6]
        if no is None:
            continue
        lat, lon = _to_float(ltg), _to_float(bjr)
        if lat is None or lon is None or not (-11 <= lat <= 6) or not (95 <= lon <= 141):
            n_bad += 1
            continue
        attrs = {"no": no, "prov": prov, "nama_ruas": nama_ruas}
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

    print(f"\nSelesai: {len(rows)} titik blackspot diimpor ke {PROVINSI_BUCKET}/{LAYER_NAME}.")


if __name__ == "__main__":
    main()
