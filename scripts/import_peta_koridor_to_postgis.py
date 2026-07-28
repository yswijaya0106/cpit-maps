# -*- coding: utf-8 -*-
"""Impor Maps/PETA KORIDOR/ (layer overlay ruas koridor IJD per kab/kota) ke
PostgreSQL/PostGIS -- pola sama dgn import_maps_to_postgis.py (skema generik
map_layers: provinsi/kabupaten/layer/attrs JSONB/geom), tapi script
TERPISAH karena sumber datanya berbeda bentuk:

Maps/PETA KORIDOR/<PROVINSI>/<KABUPATEN>/SHP_PER_KORIDOR/<nama koridor>/
<kode>.shp -- satu .shp per koridor (10.624 file nasional, 3 level lebih
dalam dari provinsi/[kabupaten]/*.shp yang di-walk import_maps_to_postgis.py)
-- TIDAK dipakai di sini. Sumbernya justru
Maps/PETA KORIDOR/GABUNGAN_KORIDOR_SELURUH_INDONESIA/
seluruh_ruas_koridor_indonesia.shp: SATU file nasional berisi seluruh
11.612 ruas koridor (kolom PROVINSI/KABUPATEN_ sudah persis format folder
Maps/<provinsi>/<kabupaten>/ yang dipakai layer lain), diverifikasi bersih
(0 geometri null/kosong, 0 NO_KORIDOR null, 0 duplikat (NO_KORIDOR,
ID_RUAS)) -- lihat docs/ percakapan analisis 28 Jul 2026. Jauh lebih
sederhana & aman drpd walk ribuan file per-koridor yang isinya subset data
yang sama.

RUAS_KML_KMZ/*.kml (per-ruas, mentah) dan *.gpkg per-koridor (duplikat isi
.shp) SENGAJA dilewati -- shp gabungan nasional ini sudah versi terproses.

Satu layer "PETA KORIDOR" per (provinsi, kabupaten) -- BUKAN satu layer per
koridor -- supaya tidak membanjiri picker overlay dgn ribuan entri (pola
sama dgn BATAS KECAMATAN: banyak fitur dalam satu layer, dibedakan lewat
attrs, di sini attrs->>'NO_KORIDOR'). Beda dari BATAS KECAMATAN yang
provinsi-nya dipatok konstan "BATAS KECAMATAN" (flat national bucket) --
PETA KORIDOR pakai skema navigasi provinsi/kabupaten/layer standar spt
layer lain, karena memang overlay per-kabupaten biasa, bukan base layer
nasional.

Resumable per (provinsi, kabupaten) via map_layer_meta (layer="PETA
KORIDOR") -- baris yang sudah ada dilewati kecuali --force.

Usage (venv aktif):
    python scripts/import_peta_koridor_to_postgis.py
    python scripts/import_peta_koridor_to_postgis.py --provinsi ACEH
    python scripts/import_peta_koridor_to_postgis.py --force --provinsi ACEH
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

MAPS_DIR = Path(__file__).resolve().parent.parent / "Maps"
SHP_PATH = MAPS_DIR / "PETA KORIDOR" / "GABUNGAN_KORIDOR_SELURUH_INDONESIA" / \
    "seluruh_ruas_koridor_indonesia.shp"
LAYER_NAME = "PETA KORIDOR"
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


def _already_imported(cur, provinsi, kabupaten):
    cur.execute(
        "SELECT 1 FROM map_layer_meta WHERE provinsi=%s AND kabupaten=%s AND layer=%s",
        (provinsi, kabupaten, LAYER_NAME),
    )
    return cur.fetchone() is not None


def _delete_layer(cur, provinsi, kabupaten):
    cur.execute(
        "DELETE FROM map_layers WHERE provinsi=%s AND kabupaten=%s AND layer=%s",
        (provinsi, kabupaten, LAYER_NAME),
    )
    cur.execute(
        "DELETE FROM map_layer_meta WHERE provinsi=%s AND kabupaten=%s AND layer=%s",
        (provinsi, kabupaten, LAYER_NAME),
    )


def import_kabupaten(cur, provinsi: str, kabupaten: str, gdf_kab, attr_cols) -> int:
    # Sengaja per-fitur (bukan vektorisasi) -- sama alasan dgn
    # import_maps_to_postgis.py: sebagian kecil geometri sumber RBI/SITIA
    # bisa degenerate dan menggagalkan operasi vektorisasi utk seluruh layer.
    rows = []
    n_bad = 0
    for _, row in gdf_kab.iterrows():
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
        rows.append((provinsi, kabupaten, LAYER_NAME, Json(attrs), wkb_hex))
    if n_bad:
        print(f"    ({n_bad} fitur geometri rusak/kosong dilewati)")

    for i in range(0, len(rows), INSERT_BATCH):
        chunk = rows[i:i + INSERT_BATCH]
        cur.executemany(
            "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
            "VALUES (%s, %s, %s, %s, ST_GeomFromWKB(decode(%s, 'hex'), 4326))",
            chunk,
        )

    # size_mb TIDAK dihitung dari SHP_PATH.stat().st_size seperti
    # import_maps_to_postgis.py -- di sana itu valid krn 1 file = 1 layer,
    # di sini SATU file sumber dipecah jadi ratusan layer (per kabupaten),
    # jadi ukuran file sumber utuh menyesatkan. Dipakai perkiraan kasar dari
    # payload yang benar2 tersimpan utk kabupaten ini (WKB hex + JSON attrs).
    approx_bytes = sum(len(str(r[3].obj)) + len(r[4]) for r in rows) if rows else 0
    n_koridor = gdf_kab["NO_KORIDOR"].nunique()
    cur.execute(
        """INSERT INTO map_layer_meta
               (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (provinsi, kabupaten, layer) DO UPDATE SET
               label=EXCLUDED.label, feature_count=EXCLUDED.feature_count,
               size_mb=EXCLUDED.size_mb, source_shp=EXCLUDED.source_shp,
               imported_at=now()""",
        (provinsi, kabupaten, LAYER_NAME, f"Peta Koridor ({n_koridor} koridor)",
         len(rows), round(approx_bytes / 1_048_576, 2),
         str(SHP_PATH.relative_to(MAPS_DIR))),
    )
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provinsi", action="append", help="batasi ke provinsi ini (bisa diulang); default semua")
    ap.add_argument("--force", action="store_true", help="impor ulang kabupaten yang sudah ada di map_layer_meta")
    args = ap.parse_args()

    if not SHP_PATH.exists():
        print(f"GAGAL: tidak ditemukan {SHP_PATH}")
        sys.exit(1)

    only_provinsi = set(args.provinsi) if args.provinsi else None

    print(f"Membaca {SHP_PATH.name}...")
    gdf = gpd.read_file(SHP_PATH, engine="pyogrio", on_invalid="ignore")
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    attr_cols = [c for c in gdf.columns if c != "geometry"]
    # KABUPATEN_ dari shp ini all-caps ("KABUPATEN ACEH BARAT"); konvensi
    # folder Maps/<provinsi>/<kabupaten>/ yang dipakai layer RBI lain (dan
    # dibaca apa adanya oleh maps_kabupaten()) title-case ("Kabupaten Aceh
    # Barat") -- tanpa normalisasi ini, tiap kabupaten pecah jadi 2 baris
    # kabupaten terpisah di map_layer_meta (satu isi layer RBI, satu isi
    # PETA KORIDOR doang), bikin entri "kosong" nyempil di tree kategori
    # "Jalan" (lihat maps-overlay.js exclude_layer). .title() bukan solusi
    # sempurna (sebagian folder Maps/ lama punya prefiks kode wilayah spt
    # "7505 - Kabupaten Gorontalo Utara", provinsi lain malah belum py
    # folder Maps/ sama sekali) -- tapi cukup utk mayoritas kasus & tidak
    # memperburuk apapun utk sisanya (tetap kebentuk kabupaten baru yang
    # rapi, bukan tambah 1 lagi varian casing).
    gdf["KABUPATEN_"] = gdf["KABUPATEN_"].str.strip().str.title()
    print(f"  {len(gdf)} fitur, {gdf['PROVINSI'].nunique()} provinsi, "
          f"{gdf.groupby(['PROVINSI', 'KABUPATEN_']).ngroups} kombinasi provinsi/kabupaten")

    t0 = time.time()
    total_kab = total_features = total_skipped = 0

    for (provinsi, kabupaten), gdf_kab in gdf.groupby(["PROVINSI", "KABUPATEN_"], sort=True):
        if only_provinsi and provinsi not in only_provinsi:
            continue
        with pg_cursor() as cur:
            if not args.force and _already_imported(cur, provinsi, kabupaten):
                total_skipped += 1
                continue
            if args.force:
                _delete_layer(cur, provinsi, kabupaten)
            try:
                n = import_kabupaten(cur, provinsi, kabupaten, gdf_kab, attr_cols)
            except Exception as e:
                print(f"  GAGAL {provinsi}/{kabupaten}: {e}")
                continue
        total_kab += 1
        total_features += n
        print(f"  [{total_kab}] {provinsi}/{kabupaten} -> {n} fitur")

    dt = time.time() - t0
    print(f"\nSelesai: {total_kab} kabupaten diimpor ({total_features} fitur total), "
          f"{total_skipped} kabupaten dilewati (sudah ada), {dt:.1f}s")


if __name__ == "__main__":
    main()
