# -*- coding: utf-8 -*-
"""Impor 3 layer titik/polygon BASARNAS (docs/New/6. BASARNAS/1. Titik
koordinat lokasi Kantor SAR, Balai Pendidikan, dan Pos SAR/) ke PostgreSQL/
PostGIS -- skema generik map_layers yang sama dengan
import_peta_koridor_to_postgis.py (provinsi/kabupaten/layer/attrs JSONB/
geom), tapi sumbernya di luar Maps/ (lihat docs/kajian_data_baru_docs_new.md
§8.1 untuk hasil telaah datanya).

Layer ini murni overlay peta umum (identify/legend), TIDAK terkait
usulan_inpres atau skoring IJD.

Ketiganya dipakai sebagai flat national bucket (provinsi="BASARNAS",
kabupaten="") -- pola sama dengan JALAN PROVINSI/JALAN TOL, bukan pola
per-kabupaten seperti PETA KORIDOR/BATAS KECAMATAN -- karena sumbernya
memang satu file nasional tanpa pembagian kabupaten alami (Kantor SAR
melingkupi wilayah lintas-kabupaten).

Sumber GPKG (bukan SHP) karena kolom lebih lengkap/tidak terpotong
(nama_kantor vs nama_kanto di SHP) dan tidak perlu urus sidecar file.
Layer polygon (Wilayah Tanggung Jawab) WAJIB dibaca dengan
engine="pyogrio" -- engine default fiona gagal dengan
`TypeError: ufunc 'create_collection' not supported...`, bug shapely/numpy
MultiPolygon-from-dict yang sama dengan Maps/BATAS_ADMINISTRASI.gdb
(lihat CLAUDE.md). Dipakai untuk ketiga layer demi konsistensi.

Resumable per layer via map_layer_meta -- layer yang sudah ada dilewati
kecuali --force.

Usage (venv aktif):
    python scripts/import_basarnas_to_postgis.py
    python scripts/import_basarnas_to_postgis.py --force
"""
import argparse
import io
import math
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("SHAPE_RESTORE_SHX", "YES")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from psycopg.types.json import Json

from db import db_cursor as pg_cursor  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
BASARNAS_DIR = (
    REPO_ROOT / "docs" / "New"
    / "6. BASARNAS-20260820T015304Z-1-001" / "6. BASARNAS"
    / "1. Titik koordinat lokasi Kantor SAR, Balai Pendidikan, dan Pos SAR"
)
PROVINSI_BUCKET = "BASARNAS"
KABUPATEN_BUCKET = ""
INSERT_BATCH = 2000

# (layer, path relatif thd BASARNAS_DIR, label tampilan)
DATASETS = [
    (
        "KANTOR SAR",
        "Titik Koordinat Lokasi Kantor Pencarian dan Pertolongan/"
        "Titik Koordinat Lokasi Kantor Pencarian dan Pertolongan.gpkg",
        "Kantor SAR",
    ),
    (
        "POS SAR",
        "Titik Koordinat Lokasi POS Pencarian dan Pertolongan/"
        "Titik Koordinat Lokasi Pos Pencarian dan Pertolongan.gpkg",
        "Pos SAR",
    ),
    (
        "WILAYAH TANGGUNG JAWAB SAR",
        "Wilayah Tanggung Jawab Kantor Pencarian Dan Pertolongan/"
        "Wilayah Tanggung Jawab Kantor Pencarian Dan Pertolongan.gpkg",
        "Wilayah Tanggung Jawab SAR",
    ),
]


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


def _already_imported(cur, layer):
    cur.execute(
        "SELECT 1 FROM map_layer_meta WHERE provinsi=%s AND kabupaten=%s AND layer=%s",
        (PROVINSI_BUCKET, KABUPATEN_BUCKET, layer),
    )
    return cur.fetchone() is not None


def _delete_layer(cur, layer):
    cur.execute(
        "DELETE FROM map_layers WHERE provinsi=%s AND kabupaten=%s AND layer=%s",
        (PROVINSI_BUCKET, KABUPATEN_BUCKET, layer),
    )
    cur.execute(
        "DELETE FROM map_layer_meta WHERE provinsi=%s AND kabupaten=%s AND layer=%s",
        (PROVINSI_BUCKET, KABUPATEN_BUCKET, layer),
    )


def import_dataset(cur, layer: str, gpkg_path: Path, label: str) -> int:
    gdf = gpd.read_file(gpkg_path, engine="pyogrio")
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    attr_cols = [c for c in gdf.columns if c != "geometry"]

    rows = []
    n_bad = 0
    for _, row in gdf.iterrows():
        try:
            geom = row.geometry
            if geom is None or geom.is_empty or not geom.is_valid:
                n_bad += 1
                continue
            if geom.has_z:
                geom = shapely.force_2d(geom)
            wkb_hex = geom.wkb_hex
        except Exception:
            n_bad += 1
            continue
        attrs = {c: _clean_value(row[c]) for c in attr_cols}
        rows.append((PROVINSI_BUCKET, KABUPATEN_BUCKET, layer, Json(attrs), wkb_hex))
    if n_bad:
        print(f"    ({n_bad} fitur geometri rusak/kosong dilewati)")

    for i in range(0, len(rows), INSERT_BATCH):
        chunk = rows[i:i + INSERT_BATCH]
        cur.executemany(
            "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
            "VALUES (%s, %s, %s, %s, ST_GeomFromWKB(decode(%s, 'hex'), 4326))",
            chunk,
        )

    approx_bytes = sum(len(str(r[3].obj)) + len(r[4]) for r in rows) if rows else 0
    cur.execute(
        """INSERT INTO map_layer_meta
               (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (provinsi, kabupaten, layer) DO UPDATE SET
               label=EXCLUDED.label, feature_count=EXCLUDED.feature_count,
               size_mb=EXCLUDED.size_mb, source_shp=EXCLUDED.source_shp,
               imported_at=now()""",
        (PROVINSI_BUCKET, KABUPATEN_BUCKET, layer, label,
         len(rows), round(approx_bytes / 1_048_576, 2),
         str(gpkg_path.relative_to(REPO_ROOT))),
    )
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="impor ulang layer yang sudah ada di map_layer_meta")
    args = ap.parse_args()

    t0 = time.time()
    total_layer = total_features = total_skipped = 0

    for layer, rel_path, label in DATASETS:
        gpkg_path = BASARNAS_DIR / rel_path
        if not gpkg_path.exists():
            print(f"  GAGAL {layer}: tidak ditemukan {gpkg_path}")
            continue
        with pg_cursor() as cur:
            if not args.force and _already_imported(cur, layer):
                print(f"  [lewat] {layer} (sudah ada, pakai --force untuk impor ulang)")
                total_skipped += 1
                continue
            if args.force:
                _delete_layer(cur, layer)
            try:
                n = import_dataset(cur, layer, gpkg_path, label)
            except Exception as e:
                print(f"  GAGAL {layer}: {e}")
                continue
        total_layer += 1
        total_features += n
        print(f"  [{total_layer}] {layer} -> {n} fitur")

    dt = time.time() - t0
    print(f"\nSelesai: {total_layer} layer diimpor ({total_features} fitur total), "
          f"{total_skipped} layer dilewati (sudah ada), {dt:.1f}s")


if __name__ == "__main__":
    main()
