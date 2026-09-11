# -*- coding: utf-8 -*-
"""Impor titik lokasi rencana penanganan perlintasan sebidang (SS) KA
(docs/New/11092026/.../Railway Crossing per Tahap.shp, 136 titik dari KML
"Tahap 2"/"Tahap 3" dst.) ke map_layers -- pelengkap SPASIAL dari
penanganan_ss_ka_tahap (tabel, lihat schema_penanganan_ss_ka_tahap.sql),
TIDAK di-join ke tabel itu (notasi/urutan tidak cukup presisi utk
dicocokkan otomatis, lihat catatan di schema_penanganan_ss_ka_tahap.sql
dan docs/kajian_data_baru_11092026.md §3) -- murni titik + nama lokasi
mentah dari KML sumbernya.

Label "layer" KML sumbernya ("Tahap 2"/"Tahap I"/"Tahap III"/"Tahap 3")
tidak konsisten format (angka vs romawi utk tahap yang sama) --
dinormalisasi ke "I"/"II"/"III" di attrs["Tahap"] supaya bisa
difilter/dikelompokkan, TANPA mengubah field "Name" mentahnya.

Bucket nasional flat (provinsi="PERLINTASAN SEBIDANG KA", kabupaten="") --
136 titik tersebar lintas Jawa/Sumatera tanpa pembagian kabupaten alami,
pola sama dengan BASARNAS/JALAN DARURAT. TIDAK terkait usulan_inpres/IJD.

Idempotent: DELETE + reinsert penuh.

Usage (venv aktif):
    python scripts/import_railway_crossing_tahap_to_postgis.py
"""
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import geopandas as gpd
import shapely
from psycopg.types.json import Json

from db import db_cursor as pg_cursor  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SHP_PATH = REPO_ROOT / "docs" / "New" / "11092026" / "drive-download-20260911T021138Z-1-001" / "Railway Crossing per Tahap" / "Railway Crossing per Tahap.shp"

PROVINSI = "PERLINTASAN SEBIDANG KA"
KABUPATEN = ""
LAYER = "Rencana Penanganan SS KA (Titik JPL)"

_TAHAP_NORM = {"1": "I", "2": "II", "3": "III", "I": "I", "II": "II", "III": "III"}


def norm_tahap(raw: str) -> str:
    m = re.search(r"(I{1,3}|\d)\s*$", (raw or "").strip().upper())
    return _TAHAP_NORM.get(m.group(1), raw) if m else raw


def main():
    gdf = gpd.read_file(SHP_PATH, engine="pyogrio")
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    print(f"{len(gdf)} titik rencana penanganan SS KA dibaca dari SHP.")

    records = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        if geom.has_z:
            geom = shapely.force_2d(geom)
        attrs = {
            "Name": (row["Name"] or "").strip() or None,
            "Tahap": norm_tahap(row["layer"]),
        }
        attrs = {k: v for k, v in attrs.items() if v is not None}
        records.append((PROVINSI, KABUPATEN, LAYER, Json(attrs), geom.wkb_hex))

    with pg_cursor() as cur:
        cur.execute("DELETE FROM map_layers WHERE provinsi=%s AND kabupaten=%s AND layer=%s", (PROVINSI, KABUPATEN, LAYER))
        cur.executemany(
            "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
            "VALUES (%s, %s, %s, %s, ST_GeomFromWKB(decode(%s, 'hex'), 4326))",
            records,
        )
        cur.execute(
            """INSERT INTO map_layer_meta
                   (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (provinsi, kabupaten, layer) DO UPDATE SET
                   label=EXCLUDED.label, feature_count=EXCLUDED.feature_count,
                   size_mb=EXCLUDED.size_mb, source_shp=EXCLUDED.source_shp,
                   imported_at=now()""",
            (PROVINSI, KABUPATEN, LAYER, LAYER, len(records), 0, str(SHP_PATH.relative_to(REPO_ROOT))),
        )

    print(f"Selesai: {len(records)} titik diimpor ke map_layers (provinsi='{PROVINSI}').")


if __name__ == "__main__":
    main()
