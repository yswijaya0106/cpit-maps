# -*- coding: utf-8 -*-
"""Migrasi layer peta referensi Maps/ (SHP RBI per provinsi/kabupaten +
layer nasional JALAN PROVINSI/JALAN TOL/BATAS KECAMATAN/BANDARA/PELABUHAN*/
KONEKTIVITAS SIMPUL TRANSPORTASI dst.) ke PostgreSQL/PostGIS, menggantikan
pembacaan .shp langsung dari disk per-request oleh /api/maps/* di app.py.

Struktur folder di-walk dengan aturan yang SAMA dengan maps_provinces()/
maps_kabupaten()/maps_layers() lama di app.py: provinsi = folder level-1,
kabupaten = sub-folder level-2 (kabupaten="" kalau provinsi tidak punya
sub-folder dan .shp ada langsung di dalamnya, mis. Maps/JALAN TOL/).

Skema generik (map_layers: provinsi/kabupaten/layer/attrs JSONB/geom) karena
tiap file .shp RBI punya kolom atribut berbeda -- lihat
scripts/schema_map_layers_postgis.sql. map_layer_meta jadi index cepat utk
listing provinsi/kabupaten/layer (dulu Path.iterdir()/glob()).

Dilewati (bukan bug, sengaja):
  - Maps/IP2019-2024/     : raster .tif (Indeks Penanaman), bukan .shp --
    sudah ada jalur impor sendiri (scripts/import_indeks_penanaman_raster.py).
  - Maps/JALAN (mentah, belum diproses)/ : eksplisit ditandai "belum
    diproses" (ada file .sr.lock ArcGIS aktif) -- duplikat mentah dari
    Maps/JALAN NASIONAL/ yang sudah diproses; jangan ikut termigrasi ke
    produksi. Pakai --include-mentah kalau memang mau ikutkan.

Resumable per (provinsi, kabupaten, layer): baris yang sudah ada di
map_layer_meta dilewati kecuali --force. Bisa dijalankan bertahap per
provinsi via --provinsi (bisa diulang).

Usage (venv aktif):
    python scripts/import_maps_to_postgis.py --provinsi ACEH
    python scripts/import_maps_to_postgis.py --provinsi ACEH --provinsi BALI
    python scripts/import_maps_to_postgis.py                    # semua provinsi
    python scripts/import_maps_to_postgis.py --force --provinsi ACEH
"""
import argparse
import io
import math
import os
import sys
import time
from pathlib import Path

# Beberapa .shp sumber kehilangan sidecar .shx (mis. JAWA BARAT/Kabupaten
# Bandung Barat/JALANKABUPATENBANDUNGBARAT_LN_50K) -- tanpa ini GDAL menolak
# membuka file sama sekali, padahal .shx bisa dibangun ulang dari .shp.
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
from map_layer_labels import map_layer_label  # noqa: E402

MAPS_DIR = Path(__file__).resolve().parent.parent / "Maps"
SKIP_DIRNAMES = {"JALAN (mentah, belum diproses)"}
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


def _iter_provinsi_kabupaten(only_provinsi):
    for prov_dir in sorted(MAPS_DIR.iterdir()):
        if not prov_dir.is_dir() or prov_dir.name in SKIP_DIRNAMES:
            continue
        if only_provinsi and prov_dir.name not in only_provinsi:
            continue
        subdirs = sorted(d for d in prov_dir.iterdir() if d.is_dir())
        if subdirs:
            for kab_dir in subdirs:
                yield prov_dir.name, kab_dir.name, kab_dir
        else:
            yield prov_dir.name, "", prov_dir


def _already_imported(cur, provinsi, kabupaten, layer):
    cur.execute(
        "SELECT 1 FROM map_layer_meta WHERE provinsi=%s AND kabupaten=%s AND layer=%s",
        (provinsi, kabupaten, layer),
    )
    return cur.fetchone() is not None


def _delete_layer(cur, provinsi, kabupaten, layer):
    cur.execute(
        "DELETE FROM map_layers WHERE provinsi=%s AND kabupaten=%s AND layer=%s",
        (provinsi, kabupaten, layer),
    )
    cur.execute(
        "DELETE FROM map_layer_meta WHERE provinsi=%s AND kabupaten=%s AND layer=%s",
        (provinsi, kabupaten, layer),
    )


def import_shp(cur, provinsi: str, kabupaten: str, shp_path: Path) -> int:
    layer = shp_path.stem
    # on_invalid="ignore": tanpa ini, GDAL melempar exception saat PARSING
    # (bukan cuma validasi shapely) utk geometri degenerate spt LineString 1
    # titik -- menggagalkan seluruh layer sebelum sempat jadi GeoDataFrame,
    # jadi tidak bisa ditangani per-baris di sisi Python sama sekali.
    gdf = gpd.read_file(shp_path, engine="pyogrio", on_invalid="ignore")
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    # Sengaja per-fitur (bukan operasi vektorisasi geopandas/shapely spt
    # gdf.geometry.is_valid atau shapely.force_2d(array)) -- sebagian kecil
    # .shp sumber punya geometri degenerate (mis. LineString 1 titik) yang
    # membuat operasi vektorisasi itu sendiri melempar exception dan
    # menggagalkan SELURUH layer, bukan cuma baris yang rusak.
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
        rows.append((provinsi, kabupaten, layer, Json(attrs), wkb_hex))
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
        (provinsi, kabupaten, layer, map_layer_label(layer), len(rows),
         round(shp_path.stat().st_size / 1_048_576, 2),
         str(shp_path.relative_to(MAPS_DIR))),
    )
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provinsi", action="append", help="batasi ke provinsi ini (bisa diulang); default semua")
    ap.add_argument("--force", action="store_true", help="impor ulang layer yang sudah ada di map_layer_meta")
    ap.add_argument("--include-mentah", action="store_true",
                     help="ikutkan Maps/JALAN (mentah, belum diproses)/ (dilewati secara default)")
    args = ap.parse_args()

    global SKIP_DIRNAMES
    if args.include_mentah:
        SKIP_DIRNAMES = set()

    only_provinsi = set(args.provinsi) if args.provinsi else None
    t0 = time.time()
    total_layers = total_features = total_skipped = 0

    for provinsi, kabupaten, dir_path in _iter_provinsi_kabupaten(only_provinsi):
        shp_files = sorted(dir_path.glob("*.shp"))
        if not shp_files:
            continue
        for shp_path in shp_files:
            layer = shp_path.stem
            with pg_cursor() as cur:
                if not args.force and _already_imported(cur, provinsi, kabupaten, layer):
                    total_skipped += 1
                    continue
                if args.force:
                    _delete_layer(cur, provinsi, kabupaten, layer)
                try:
                    n = import_shp(cur, provinsi, kabupaten, shp_path)
                except Exception as e:
                    print(f"  GAGAL {provinsi}/{kabupaten}/{layer}: {e}")
                    continue
            total_layers += 1
            total_features += n
            label = f"{provinsi}/{kabupaten}/{layer}" if kabupaten else f"{provinsi}/{layer}"
            print(f"  [{total_layers}] {label} -> {n} fitur")

    dt = time.time() - t0
    print(f"\nSelesai: {total_layers} layer diimpor ({total_features} fitur total), "
          f"{total_skipped} layer dilewati (sudah ada), {dt:.1f}s")


if __name__ == "__main__":
    main()
