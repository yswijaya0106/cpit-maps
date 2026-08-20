# -*- coding: utf-8 -*-
"""Impor jaringan rel kereta api ke PostgreSQL/PostGIS -- skema generik
map_layers, pola sama dengan import_basarnas_to_postgis.py. Sumbernya
docs/New/0. DATA SHP/Kereta Api/ (BUKAN folder "4. KERETA (KA)" --
lihat docs/kajian_data_baru_docs_new.md §6: folder itu cuma OD LRT
Jabodebek & peta skematik PDF, tidak menghasilkan data spasial siap
pakai).

Dua sumber dengan resolusi/atribut berbeda, diimpor sebagai 2 layer
terpisah di bucket flat nasional yang sama ("JALUR KERETA API", pola
sama dengan bucket BASARNAS):

- "Rel KA_2022.shp": SATU file nasional, 1.460 ruas garis, atribut
  minim (cuma KETLAIN/Kegiatan) tapi cakupannya benar2 nasional.
  -> layer="JALUR KERETA API"
- "Jalan_Rel_Aktif_BTP (P.Jawa).zip" + "...(P.Sumatera).zip": 7 file per
  wilayah kerja BTP (Balai Teknik Perkeretaapian) -- Jakarta/Semarang/
  Surabaya/Bandung/Medan/Padang/Palembang -- atribut jauh lebih detail
  (KM_START/KM_END, DAOPDIVREI, LINTASID, PETAK1/PETAK2 nama stasiun
  petak, STATUS aktif/tidak, JALUR, dst.) tapi cakupannya cuma 7 wilayah
  kerja itu, bukan nasional penuh. File Jawa berproyeksi EPSG:32748 (UTM
  48S), file Sumatera sudah EPSG:4326 -- direproyeksi otomatis per file.
  -> layer="JALUR KERETA API AKTIF (BTP)"

Layer ini murni overlay peta umum, TIDAK terkait usulan_inpres/IJD.

Resumable per layer via map_layer_meta -- dilewati kecuali --force.

Usage (venv aktif):
    python scripts/import_kereta_api_to_postgis.py
    python scripts/import_kereta_api_to_postgis.py --force
"""
import argparse
import io
import math
import os
import sys
import tempfile
import zipfile
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
KA_DIR = REPO_ROOT / "docs" / "New" / "0. DATA SHP-20260820T015255Z-1-001" / "0. DATA SHP" / "Kereta Api"
RELKA_SHP = KA_DIR / "Rel KA_2022.shp"
BTP_ZIPS = [KA_DIR / "Jalan_Rel_Aktif_BTP (P.Jawa).zip", KA_DIR / "Jalan_Rel_Aktif_BTP (P.Sumatera).zip"]

PROVINSI_BUCKET = "JALUR KERETA API"
KABUPATEN_BUCKET = ""
LAYER_NASIONAL = "JALUR KERETA API"
LAYER_BTP = "JALUR KERETA API AKTIF (BTP)"
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


def _rows_from_gdf(gdf, layer):
    attr_cols = [c for c in gdf.columns if c != "geometry"]
    rows, n_bad = [], 0
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
    return rows, n_bad


def _insert_rows(cur, rows):
    for i in range(0, len(rows), INSERT_BATCH):
        chunk = rows[i:i + INSERT_BATCH]
        cur.executemany(
            "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
            "VALUES (%s, %s, %s, %s, ST_GeomFromWKB(decode(%s, 'hex'), 4326))",
            chunk,
        )


def _write_meta(cur, layer, label, n, source):
    cur.execute(
        """INSERT INTO map_layer_meta
               (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (provinsi, kabupaten, layer) DO UPDATE SET
               label=EXCLUDED.label, feature_count=EXCLUDED.feature_count,
               size_mb=EXCLUDED.size_mb, source_shp=EXCLUDED.source_shp,
               imported_at=now()""",
        (PROVINSI_BUCKET, KABUPATEN_BUCKET, layer, label, n, None, source),
    )


def import_relka(cur) -> int:
    gdf = gpd.read_file(RELKA_SHP, engine="pyogrio")
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    rows, n_bad = _rows_from_gdf(gdf, LAYER_NASIONAL)
    if n_bad:
        print(f"    ({n_bad} fitur geometri rusak/kosong dilewati)")
    _insert_rows(cur, rows)
    _write_meta(cur, LAYER_NASIONAL, "Jalur Kereta Api (nasional, 2022)", len(rows),
                str(RELKA_SHP.relative_to(REPO_ROOT)))
    return len(rows)


def import_btp(cur) -> int:
    total_rows = []
    sources = []
    for zpath in BTP_ZIPS:
        if not zpath.exists():
            print(f"  GAGAL: tidak ditemukan {zpath}")
            continue
        with tempfile.TemporaryDirectory() as td:
            with zipfile.ZipFile(zpath) as zf:
                zf.extractall(td)
            shp_files = sorted(Path(td).glob("*.shp"))
            for shp in shp_files:
                gdf = gpd.read_file(shp, engine="pyogrio")
                if gdf.crs and gdf.crs.to_epsg() != 4326:
                    gdf = gdf.to_crs(epsg=4326)
                rows, n_bad = _rows_from_gdf(gdf, LAYER_BTP)
                if n_bad:
                    print(f"    ({shp.stem}: {n_bad} fitur geometri rusak/kosong dilewati)")
                total_rows.extend(rows)
                sources.append(shp.stem)
                print(f"    {shp.stem}: {len(rows)} fitur")
    _insert_rows(cur, total_rows)
    _write_meta(cur, LAYER_BTP, "Jalur Kereta Api Aktif per BTP (Jakarta/Semarang/Surabaya/"
                "Bandung/Medan/Padang/Palembang)", len(total_rows),
                "; ".join(str(z.relative_to(REPO_ROOT)) for z in BTP_ZIPS))
    return len(total_rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="impor ulang layer yang sudah ada di map_layer_meta")
    args = ap.parse_args()

    if not RELKA_SHP.exists():
        print(f"GAGAL: tidak ditemukan {RELKA_SHP}")
        sys.exit(1)

    with pg_cursor() as cur:
        if args.force or not _already_imported(cur, LAYER_NASIONAL):
            if args.force:
                _delete_layer(cur, LAYER_NASIONAL)
            n = import_relka(cur)
            print(f"  [1] {LAYER_NASIONAL} -> {n} fitur")
        else:
            print(f"  [lewat] {LAYER_NASIONAL} (sudah ada, pakai --force untuk impor ulang)")

    with pg_cursor() as cur:
        if args.force or not _already_imported(cur, LAYER_BTP):
            if args.force:
                _delete_layer(cur, LAYER_BTP)
            n = import_btp(cur)
            print(f"  [2] {LAYER_BTP} -> {n} fitur")
        else:
            print(f"  [lewat] {LAYER_BTP} (sudah ada, pakai --force untuk impor ulang)")

    print("\nSelesai.")


if __name__ == "__main__":
    main()
