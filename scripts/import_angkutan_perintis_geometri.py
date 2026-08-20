# -*- coding: utf-8 -*-
"""Impor geometri rute/titik angkutan perintis (docs/New/0. DATA SHP/Multimoda/
ANGKUTAN PERINTIS.zip) ke map_layers (provinsi='ANGKUTAN PERINTIS') sebagai
overlay peta baru -- BUKAN join ke tabel angkutan_perintis (lihat catatan di
bawah kenapa).

Kenapa overlay terpisah, bukan mengisi kolom lat/lon di angkutan_perintis:
ID di SHP ini (trayek_id mis. "JP-31-T21", lintas_id mis. "PSP-59") memakai
skema penomoran internal SHP itu sendiri, BUKAN no_koridor_trayek dari xlsx
sumber angkutan_perintis (yang mayoritas NULL, dan yang terisi pun cuma
angka polos "1".."4" utk KSPN) -- sudah dicek manual, tidak ada kunci gabung
yang bisa diandalkan antar keduanya. Jadi overlay ini murni visual (rute
digambar di peta), dipisah dari tabel referensi angkutan_perintis yang tetap
tanpa koordinat sendiri (lihat GET /api/maps/cari-titik utk pendekatan lain,
pencocokan nama ke layer BANDARA/Pelabuhan Nasional).

UDARA pakai 4 file .gpkg gabungan/nasional (rute gabungan udara.gpkg,
Titik_Udara.gpkg, KABKOT TERLAYANI UDARA (PENUMPANG/BARANG).gpkg), BUKAN 8
folder regional Rute_*.shp/Titik_*.shp -- gpkg gabungan sudah mencakup semua
region dalam 1 file (255 rute, 4422 titik), pola sama dengan
import_peta_koridor_to_postgis.py yang memilih 1 shp nasional gabungan
drpd ribuan file per-koridor. LAUT: "GABUNGAN ANGKUTAN LAUT.shp" dan
"Titik Angkutan Penumpang Laut.shp" identik (2369 baris, kolom sama) --
begitu juga "GABUNGAN RUTE ANGKUTAN LAUT.shp" vs "Rute Angkutan Penumpang
Laut.shp" (157 baris) -- cuma salah satu yang diimpor, bukan berarti bug.

Resumable per (provinsi, kabupaten, layer) lewat map_layer_meta, sama
seperti import_maps_to_postgis.py -- --force utk impor ulang.

Usage (venv aktif):
    python scripts/import_angkutan_perintis_geometri.py
    python scripts/import_angkutan_perintis_geometri.py --force
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
SRC_DIR = (
    REPO_ROOT / "docs" / "New" / "0. DATA SHP-20260820T015255Z-1-001" / "0. DATA SHP"
    / "Multimoda" / "_extract_angkutan_perintis" / "ANGKUTAN PERINTIS"
)
PROVINSI = "ANGKUTAN PERINTIS"
INSERT_BATCH = 2000

# (kabupaten bucket, layer label, path relatif thd SRC_DIR, layer gpkg opsional)
SOURCES = [
    ("DARAT - BARANG", "Rute Angkutan Darat Barang", "DARAT/BARANG/Rute Angkutan Darat Barang.shp", None),
    ("DARAT - BARANG", "Titik Angkutan Darat Barang", "DARAT/BARANG/Titik Angkutan Darat Barang.shp", None),
    ("DARAT - JALAN PERINTIS", "Rute Jalan Perintis", "DARAT/PENUMPANG/JALAN PERINTIS/Rute Jalan Perintis.shp", None),
    ("DARAT - JALAN PERINTIS", "Titik Jalan Perintis", "DARAT/PENUMPANG/JALAN PERINTIS/Titik Jalan Perintis.shp", None),
    ("DARAT - KSPN", "Rute KSPN", "DARAT/PENUMPANG/KSPN/Rute KSPN.shp", None),
    ("DARAT - KSPN", "Titik KSPN", "DARAT/PENUMPANG/KSPN/Titik KSPN.shp", None),
    ("PENYEBERANGAN", "Rute Penyeberangan Perintis", "PENYEBERANGAN/Rute Penyeberangan Perintis.shp", None),
    ("PENYEBERANGAN", "Titik Penyeberangan Perintis", "PENYEBERANGAN/Titik Penyeberangan Perintis.shp", None),
    ("LAUT", "Titik Angkutan Penumpang Laut", "LAUT/Titik Angkutan Penumpang Laut.shp", None),
    ("LAUT", "Rute Angkutan Penumpang Laut", "LAUT/Rute Angkutan Penumpang Laut.shp", None),
    ("LAUT", "Titik Angkutan Barang Laut", "LAUT/Titik Angkutan Barang Laut.shp", None),
    ("LAUT", "Rute Angkutan Barang Laut", "LAUT/ANGKUTAN BARANG LAUT.shp", None),
    ("UDARA", "Rute Udara", "UDARA/rute gabungan udara.gpkg", "Rute_Udara"),
    ("UDARA", "Titik Udara", "UDARA/Titik_Udara.gpkg", "Titik_Udara"),
    ("UDARA", "Kabkot Terlayani Udara (Penumpang)", "UDARA/KABKOT TERLAYANI UDARA (PENUMPANG).gpkg",
     "KABKOT TERLAYANI UDARA (PENUMPANG)"),
    ("UDARA", "Kabkot Terlayani Udara (Barang)", "UDARA/KABKOT TERLAYANI UDARA (BARANG).gpkg",
     "KABKOT TERLAYANI UDARA (BARANG)"),
    ("KATEGORI WILAYAH", "Wilayah Prioritas", "KATEGORI WILAYAH/WILAYAH PRIORITAS.shp", None),
    ("KATEGORI WILAYAH", "Wilayah Strategis", "KATEGORI WILAYAH/WILAYAH STRATEGIS FIX.shp", None),
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


def _already_imported(cur, kabupaten, layer):
    cur.execute(
        "SELECT 1 FROM map_layer_meta WHERE provinsi=%s AND kabupaten=%s AND layer=%s",
        (PROVINSI, kabupaten, layer),
    )
    return cur.fetchone() is not None


def _delete_layer(cur, kabupaten, layer):
    cur.execute("DELETE FROM map_layers WHERE provinsi=%s AND kabupaten=%s AND layer=%s", (PROVINSI, kabupaten, layer))
    cur.execute("DELETE FROM map_layer_meta WHERE provinsi=%s AND kabupaten=%s AND layer=%s", (PROVINSI, kabupaten, layer))


def import_one(cur, kabupaten, layer, path: Path, gpkg_layer):
    kwargs = {"engine": "pyogrio", "on_invalid": "ignore"}
    if gpkg_layer:
        kwargs["layer"] = gpkg_layer
    gdf = gpd.read_file(path, **kwargs)
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
        rows.append((PROVINSI, kabupaten, layer, Json(attrs), wkb_hex))
    if n_bad:
        print(f"    ({n_bad} fitur geometri rusak/kosong dilewati)")

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
        (PROVINSI, kabupaten, layer, layer, len(rows),
         round(path.stat().st_size / 1_048_576, 2), str(path.relative_to(SRC_DIR))),
    )
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="impor ulang layer yang sudah ada")
    args = ap.parse_args()

    if not SRC_DIR.exists():
        print(f"GAGAL: {SRC_DIR} tidak ditemukan -- ekstrak dulu ANGKUTAN PERINTIS.zip ke folder ini.")
        return

    total_layers = total_features = total_skipped = 0
    for kabupaten, layer, rel_path, gpkg_layer in SOURCES:
        path = SRC_DIR / rel_path
        with pg_cursor() as cur:
            if not args.force and _already_imported(cur, kabupaten, layer):
                total_skipped += 1
                continue
            if not path.exists():
                print(f"  DILEWATI (file tidak ada): {kabupaten}/{layer} -> {rel_path}")
                continue
            if args.force:
                _delete_layer(cur, kabupaten, layer)
            try:
                n = import_one(cur, kabupaten, layer, path, gpkg_layer)
            except Exception as e:
                print(f"  GAGAL {kabupaten}/{layer}: {e}")
                continue
        total_layers += 1
        total_features += n
        print(f"  [{total_layers}] {kabupaten}/{layer} -> {n} fitur")

    print(f"\nSelesai: {total_layers} layer diimpor ({total_features} fitur total), "
          f"{total_skipped} layer dilewati (sudah ada)")


if __name__ == "__main__":
    main()
