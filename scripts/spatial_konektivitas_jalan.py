# -*- coding: utf-8 -*-
"""Validasi spasial "Konektivitas Jaringan Jalan" (Aspek B Laporan Daerah
Prioritas): utk tiap usulan yang punya geometri KML ter-cache
(usulan_inpres.geom_geojson), cek apakah jalurnya berada dalam jarak
AMBANG_METER dari ruas Jalan Nasional/Provinsi/Tol -- BEDA dari proksi
administratif sebelumnya (scripts/import_konektivitas_jalan.py +
import_jalan_nasional.py, "kabupaten punya data jalan terpetakan"): ini
validasi spasial NYATA per usulan, request eksplisit user
(docs/spec/laporan prioritas.md).

Sumber jalan:
  - Maps/JALAN NASIONAL/Jalan Nasional.shp  (3.306 ruas, dipakai file
    gabungan saja -- 6 file per-pulau isinya subset yg sama, tidak perlu
    diproses dobel)
  - Maps/JALAN PROVINSI/Jalan Provinsi_up.shp (1.879 ruas)
  - Maps/JALAN TOL/Jalan_Tol.shp (48 ruas)

Metode: semua geometri (jalan + usulan) direproyeksi ke EPSG:3857 (metrik,
distorsi kecil di lintang Indonesia) supaya jarak bisa diukur dalam meter.
STRtree dibangun dari gabungan ketiga layer jalan (ditandai kolom `jenis`
per index array terpisah, BUKAN 1 GeoDataFrame gabungan -- skema kolom
ketiganya beda total). Query per usulan: cari kandidat dlm bbox usulan +
ambang, ambil jarak minimum sungguhan (bukan cuma bbox), tandai jenis mana
saja yg dalam ambang.

Ambang jarak default 100 meter (dikonfirmasi user 21 Jul 2026) -- cukup
ketat utk memastikan benar-benar berdekatan di titik pertemuan, toleran
thd selisih presisi digitasi antar sumber data beda tahun/skala.

Usage (venv aktif):
    python scripts/spatial_konektivitas_jalan.py
    python scripts/spatial_konektivitas_jalan.py --ambang 150
"""

import argparse
import io
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import geopandas as gpd
import psycopg
from psycopg.rows import dict_row
from shapely.strtree import STRtree

from app import _geojson_line_to_shapely  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_spatial_konektivitas_jalan.sql"

ROAD_SOURCES = {
    "NASIONAL": BASE_DIR / "Maps" / "JALAN NASIONAL" / "Jalan Nasional.shp",
    "PROVINSI": BASE_DIR / "Maps" / "JALAN PROVINSI" / "Jalan Provinsi_up.shp",
    "TOL": BASE_DIR / "Maps" / "JALAN TOL" / "Jalan_Tol.shp",
}

DB_HOST = os.environ.get("PG_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("PG_PORT", "5432"))
DB_USER = os.environ.get("PG_USER", "postgres")
DB_PASS = os.environ.get("PG_PASS", "")
DB_NAME = os.environ.get("PG_DB", "route_gis")


def connect():
    return psycopg.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS,
        dbname=DB_NAME, row_factory=dict_row,
    )


def run_schema(conn):
    """Tabel sudah dibuat via scripts/migrate_pg_01_schema.py -- di sini
    cuma pastikan ada (lihat docs/migrasi_mysql_ke_postgresql.md)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='usulan_konektivitas_jalan'"
        )
        if not cur.fetchone():
            raise RuntimeError(
                "Tabel usulan_konektivitas_jalan belum ada di PostgreSQL -- "
                "jalankan scripts/migrate_pg_01_schema.py dulu."
            )


def load_road_trees():
    """{jenis: (STRtree, geopandas_crs_3857)} -- tiap jenis pohon terpisah
    supaya bisa tahu jenis mana yg cocok, bukan cuma "ada jalan terdekat"."""
    trees = {}
    for jenis, path in ROAD_SOURCES.items():
        if not path.exists():
            print(f"  SKIP {jenis}: {path} tidak ditemukan")
            continue
        gdf = gpd.read_file(path, engine="pyogrio")
        gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty & gdf.geometry.is_valid]
        gdf = gdf.to_crs(3857)
        # Jalan Nasional.shp sumbernya "Measured 3D LineString" -> dibaca
        # sbg LineString Z (Z=0 semu). Geometri Z dicampur .distance() dgn
        # geometri 2D (usulan) bikin GEOS segfault (native crash, bukan
        # Python exception) -- sama akar masalah dgn fix maps_layer().
        if gdf.geometry.has_z.any():
            import shapely
            gdf["geometry"] = shapely.force_2d(gdf.geometry.values)
        # Filter kedua stlh reproyeksi -- transform proj bisa hasilkan
        # inf/NaN utk titik ekstrem di luar domain valid CRS metrik.
        gdf = gdf[gdf.geometry.is_valid & (gdf.geometry.length > 0)]
        trees[jenis] = STRtree(gdf.geometry.values)
        print(f"  {jenis}: {len(gdf)} ruas dimuat", flush=True)
    return trees


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ambang", type=float, default=100.0, help="ambang jarak meter (default 100)")
    args = ap.parse_args()
    ambang = args.ambang

    conn = connect()
    try:
        run_schema(conn)
        print("Memuat layer jalan (Nasional/Provinsi/Tol)...")
        trees = load_road_trees()
        if not trees:
            sys.exit("Tidak ada layer jalan yang berhasil dimuat -- batal.")

        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, kode_kecamatan, geom_geojson FROM usulan_inpres "
                "WHERE geom_geojson IS NOT NULL"
            )
            usulan_rows = cur.fetchall()
        print(f"Memproses {len(usulan_rows)} usulan...")

        import json
        import shapely.wkt
        from pyproj import Transformer
        to_3857 = Transformer.from_crs(4326, 3857, always_xy=True)

        def reproject(geom):
            """LineString/MultiLineString EPSG:4326 -> EPSG:3857. Lewat WKT
            (bukan shapely.ops.transform) -- transform() internal membangun
            ulang MultiLineString dari list Python, HIT bug shapely/numpy yg
            sama dgn _geojson_line_to_shapely/build_kabupaten_polygons
            (TypeError create_collection)."""
            def _line_wkt(coords):
                xs, ys = to_3857.transform([c[0] for c in coords], [c[1] for c in coords])
                return "(" + ", ".join(f"{x} {y}" for x, y in zip(xs, ys)) + ")"
            if geom.geom_type == "LineString":
                return shapely.wkt.loads("LINESTRING " + _line_wkt(geom.coords))
            lines = ", ".join(_line_wkt(ls.coords) for ls in geom.geoms)
            return shapely.wkt.loads(f"MULTILINESTRING ({lines})")

        def parse_usulan_line(geojson):
            """LineString/MultiLineString -> shapely (reuse
            _geojson_line_to_shapely). Sebagian kecil usulan tergambar sbg
            Polygon (jalur digambar sbg area, bukan garis) -- dilewati,
            bukan target validasi konektivitas ini (minoritas, sudah
            terdokumentasi sejak fetch_kml_massal.py)."""
            t = geojson.get("type")
            if t == "MultiLineString":
                return _geojson_line_to_shapely(geojson)
            if t == "LineString":
                return _geojson_line_to_shapely({"type": "MultiLineString", "coordinates": [geojson["coordinates"]]})
            return None

        rows_out = []
        n_terhubung = 0
        for i, r in enumerate(usulan_rows, 1):
            if i % 25 == 0:
                print(f"  ... {i}/{len(usulan_rows)} (usulan id {r['id']})", flush=True)
            try:
                geom = parse_usulan_line(json.loads(r["geom_geojson"]))
                if geom is None or geom.is_empty:
                    continue
                geom_m = reproject(geom)
                # Geometri KML degradasi (titik dobel/kolaps, koordinat
                # NaN/inf dari parsing yg buruk) bikin GEOS SEGFAULT native
                # di .distance()/.buffer() -- TIDAK tertangkap try/except
                # Python biasa, jadi harus disaring PROAKTIF sebelum dipakai.
                if geom_m.is_empty or not geom_m.is_valid or geom_m.length == 0:
                    continue
                coords = (list(geom_m.coords) if geom_m.geom_type == "LineString"
                          else [c for ls in geom_m.geoms for c in ls.coords])
                if not all(math.isfinite(x) and math.isfinite(y) for x, y in coords):
                    continue
                # Sebagian kecil usulan py geometri KML RUSAK (data korup,
                # bukan rute sungguhan -- mis. usulan 239705/239723, MASING
                # 283.558 titik self-intersecting; usulan wajar di sampel
                # manual maks ~3.300 titik). simplify() SENDIRI cepat (<1s)
                # tapi hasilnya (51.745 titik, TETAP self-intersecting utk
                # kasus ini) msh bikin .buffer() HANG (bukan crash/exception,
                # GEOS jalan tak berhenti -- diverifikasi manual timeout
                # >40s utk 1 usulan). Simplify tak menolong kasus separah
                # ini, jadi DILEWATI langsung (bukan dipaksa proses) --
                # "tidak dapat divalidasi", bukan "tidak terhubung".
                if len(coords) > 10000:
                    print(f"  SKIP usulan {r['id']}: geometri {len(coords)} titik, "
                          f"terlalu besar utk divalidasi (kemungkinan data korup)", flush=True)
                    continue
                if len(coords) > 2000:
                    geom_m = geom_m.simplify(10, preserve_topology=False)
            except Exception:
                continue

            hasil = {"NASIONAL": None, "PROVINSI": None, "TOL": None}
            for jenis, tree in trees.items():
                idx = tree.query(geom_m.buffer(ambang))
                if len(idx) == 0:
                    continue
                jarak_min = min(geom_m.distance(tree.geometries[j]) for j in idx)
                if jarak_min <= ambang:
                    hasil[jenis] = round(jarak_min, 1)

            terhubung = any(v is not None for v in hasil.values())
            if terhubung:
                n_terhubung += 1
            rows_out.append((
                r["id"], r["kode_kecamatan"],
                hasil["NASIONAL"] is not None, hasil["NASIONAL"],
                hasil["PROVINSI"] is not None, hasil["PROVINSI"],
                hasil["TOL"] is not None, hasil["TOL"],
                terhubung, ambang,
            ))

        with conn.cursor() as cur:
            cur.execute("DELETE FROM usulan_konektivitas_jalan")
            cur.executemany(
                "INSERT INTO usulan_konektivitas_jalan "
                "(usulan_id, kode_kecamatan, terhubung_nasional, jarak_nasional_m, "
                "terhubung_provinsi, jarak_provinsi_m, terhubung_tol, jarak_tol_m, "
                "terhubung, ambang_m) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                rows_out,
            )
        conn.commit()
        print(f"\nTotal: {len(rows_out)} usulan diproses, {n_terhubung} terhubung "
              f"(dlm {ambang}m dari jalan nasional/provinsi/tol)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
