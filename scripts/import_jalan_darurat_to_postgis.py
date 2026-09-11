# -*- coding: utf-8 -*-
"""Impor layer "Jalan Darurat" (docs/New/11092026/JalanDarurat_Lebar11meter/)
ke map_layers -- 42 ruas jalan nasional dengan lebar permukaan (Mean_SurfW)
>= 11m, hasil filter RNI (Road Network Inventory) 2023 Bina Marga (lihat
metadata .shp.xml: AppendEvents dari RNI_2_2023 pada kolom SURF_WIDTH/
MED_WIDTH). Lebar ini cukup untuk difungsikan sebagai landasan darurat
pesawat saat bencana/darurat -- dual-use Jalan<->Udara, lihat
docs/kajian_data_baru_11092026.md §1. TIDAK terkait usulan_inpres/IJD.

Sumber SHP-nya berproyeksi "Indonesia Lambert Conformal Conic" (meter),
bukan WGS84 -- direproyeksi ke EPSG:4326 sebelum disimpan (map_layers
selalu WGS84, sama seperti setiap import_*_to_postgis.py lain).

Bucket nasional flat (provinsi="JALAN DARURAT", kabupaten="") -- 42 ruas
tersebar lintas provinsi tanpa pembagian kabupaten alami, pola sama dengan
JALAN NASIONAL/JALAN TOL/BASARNAS. Terdaftar di kategori tree "Simpul
Transportasi" (static/js/maps-overlay.js MAP_LAYER_CATEGORIES) supaya
tampil berdampingan dengan BANDARA -- menegaskan sifat dual-use-nya, bukan
kategori "Jalan" biasa.

Idempotent: DELETE + reinsert penuh (42 baris, tidak ada alasan utk upsert
per-baris).

Usage (venv aktif):
    python scripts/import_jalan_darurat_to_postgis.py
"""
import io
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
SHP_PATH = REPO_ROOT / "docs" / "New" / "11092026" / "JalanDarurat_Lebar11meter" / "JalanDarurat_Lebar11meter.shp"

PROVINSI = "JALAN DARURAT"
KABUPATEN = ""
LAYER = "Jalan Darurat (Landas Pacu Darurat, Lebar >=11m)"


def main():
    gdf = gpd.read_file(SHP_PATH, engine="pyogrio")
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    print(f"{len(gdf)} ruas jalan darurat dibaca dari SHP.")

    records = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        if geom.has_z:
            geom = shapely.force_2d(geom)
        attrs = {
            "Name": f"Ruas #{int(row['id'])}",
            "Panjang (km)": round(float(row["Panjang"]), 2),
            "Lebar Median (m)": round(float(row["Mean_Med_W"]), 2),
            "Lebar Perkerasan (m)": round(float(row["Mean_SurfW"]), 2),
            "Sumber": "RNI 2023 (Bina Marga) -- lebar perkerasan >=11m, kandidat landas pacu darurat",
        }
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

    print(f"Selesai: {len(records)} ruas jalan darurat diimpor ke map_layers (provinsi='{PROVINSI}').")


if __name__ == "__main__":
    main()
