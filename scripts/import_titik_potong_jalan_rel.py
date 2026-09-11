# -*- coding: utf-8 -*-
"""Impor titik potong jalan x rel KA (docs/New/titik_potong_jalan_rel_ka.shp,
dihasilkan oleh scripts/build_jalan_rel_intersection.py) ke map_layers
sebagai overlay peta baru, bucket nasional datar (provinsi=PROVINSI,
kabupaten="") -- pola yang sama dipakai JALAN NASIONAL/JALAN TOL karena
sumbernya juga satu file nasional, bukan per-provinsi/kabupaten.

Resumable via map_layer_meta (skip kalau sudah ada, kecuali --force).

Usage (venv aktif):
    python scripts/build_jalan_rel_intersection.py   # generate ulang shp-nya dulu kalau perlu
    python scripts/import_titik_potong_jalan_rel.py
    python scripts/import_titik_potong_jalan_rel.py --force
"""
import argparse
import math
import os
import sys
from pathlib import Path

os.environ.setdefault("SHAPE_RESTORE_SHX", "YES")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from psycopg.types.json import Json

from db import db_cursor as pg_cursor  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_SHP = REPO_ROOT / "docs" / "New" / "titik_potong_jalan_rel_ka.shp"
PROVINSI = "TITIK POTONG JALAN-REL KA"
KABUPATEN = ""
LAYER = "Titik Potong Jalan - Rel KA"
INSERT_BATCH = 2000


def _clean_value(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return None if math.isnan(v) else float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    if isinstance(v, str) and not v:
        return None
    return v


# Nama kolom dipendekkan jadi <=10 karakter oleh format DBF saat ditulis --
# dikembalikan ke nama yang jelas di attrs JSON sebelum disimpan.
COLUMN_RELABEL = {
    "jenis_jala": "jenis_jalan",
}


def _already_imported(cur):
    cur.execute(
        "SELECT 1 FROM map_layer_meta WHERE provinsi=%s AND kabupaten=%s AND layer=%s",
        (PROVINSI, KABUPATEN, LAYER),
    )
    return cur.fetchone() is not None


def _delete_layer(cur):
    cur.execute("DELETE FROM map_layers WHERE provinsi=%s AND kabupaten=%s AND layer=%s", (PROVINSI, KABUPATEN, LAYER))
    cur.execute("DELETE FROM map_layer_meta WHERE provinsi=%s AND kabupaten=%s AND layer=%s", (PROVINSI, KABUPATEN, LAYER))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="impor ulang layer yang sudah ada")
    args = ap.parse_args()

    if not SRC_SHP.exists():
        print(f"GAGAL: {SRC_SHP} tidak ditemukan -- jalankan scripts/build_jalan_rel_intersection.py dulu.")
        return

    with pg_cursor() as cur:
        if not args.force and _already_imported(cur):
            print("Sudah diimpor sebelumnya, dilewati (pakai --force untuk impor ulang).")
            return
        if args.force:
            _delete_layer(cur)

        gdf = gpd.read_file(SRC_SHP, engine="pyogrio", on_invalid="ignore")
        if gdf.crs and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)

        attr_cols = [c for c in gdf.columns if c != "geometry"]
        rows = []
        n_bad = 0
        for _, row in gdf.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty or not geom.is_valid:
                n_bad += 1
                continue
            if geom.has_z:
                geom = shapely.force_2d(geom)
            attrs = {COLUMN_RELABEL.get(c, c): _clean_value(row[c]) for c in attr_cols}
            rows.append((PROVINSI, KABUPATEN, LAYER, Json(attrs), geom.wkb_hex))
        if n_bad:
            print(f"  ({n_bad} fitur geometri rusak/kosong dilewati)")

        for i in range(0, len(rows), INSERT_BATCH):
            chunk = rows[i:i + INSERT_BATCH]
            cur.executemany(
                "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
                "VALUES (%s, %s, %s, %s, ST_GeomFromWKB(decode(%s, 'hex'), 4326))",
                chunk,
            )

        cur.execute(
            """INSERT INTO map_layer_meta
                   (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (provinsi, kabupaten, layer) DO UPDATE SET
                   label=EXCLUDED.label, feature_count=EXCLUDED.feature_count,
                   size_mb=EXCLUDED.size_mb, source_shp=EXCLUDED.source_shp,
                   imported_at=now()""",
            (PROVINSI, KABUPATEN, LAYER, LAYER, len(rows),
             round(sum(p.stat().st_size for p in SRC_SHP.parent.glob(SRC_SHP.stem + ".*")) / 1_048_576, 2),
             SRC_SHP.name),
        )

    print(f"Selesai: {len(rows)} titik diimpor ke map_layers ({PROVINSI} / {LAYER}).")


if __name__ == "__main__":
    main()
