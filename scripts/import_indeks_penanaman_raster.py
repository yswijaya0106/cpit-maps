# -*- coding: utf-8 -*-
"""Zonal statistics raster Indeks Penanaman (Dit. SDA, resmi -- sumber
"SHP Indeks Penanaman" yg dirujuk sheet Kumpulan Data baris 31, ternyata
dikirim sbg GeoTIFF raster bukan SHP vektor) -> per kabupaten/kota.

Sumber: Maps/IP2019-2024/IP_<tahun>.tif -- raster nasional 1-band uint8,
EPSG:4326, nodata=0. Nilai piksel HANYA {0,1,2,3} (dikonfirmasi user):
  0 = nodata/bukan lahan tanam terdeteksi
  1 = tanam 1x/tahun
  2 = tanam 2x/tahun
  3 = tanam 3x/tahun
Pemetaan ke ambang resmi Tabel 4 dokumen 14072026 ("Range IP >300% (Tanam
3x/tahun)" dst) -- nilai 1 & 3 cocok PERSIS teks dokumen ("Tanam 1x/tahun"
-> bucket 100-150%; "Tanam 3x/tahun" -> bucket >300%). Nilai 2 ambigu
(dokumen py 2 bucket yg sama-sama menyebut "2x": "1,5-2x/tahun" 150-199%
DAN "2-3x/tahun" 200-299%) -- dipilih bucket LEBIH RENDAH (150-199%) sbg
pendekatan konservatif, didokumentasikan jelas, BUKAN diklaim presisi.

Kabupaten/kota TIDAK punya poligon SHP sendiri (cuma ada Maps/BATAS
KECAMATAN, level kecamatan) -- dibangun dgn men-dissolve poligon kecamatan
per kabupaten, REUSE app.py:_batas_kec_index()/_batas_kec_layer_geojson()
(logika resolusi homonim yg sama persis dgn overlay peta) supaya tidak
menduplikasi heuristik itu.

Metode zonal: piksel non-nol di dalam poligon kabupaten -> kelas MODUS
(paling sering muncul). Kabupaten tanpa piksel valid (semua laut/nodata,
atau poligon gagal dibangun) dilewati -- TIDAK diisi 0.

Usage (venv aktif, butuh `pip install rasterio`):
    python scripts/import_indeks_penanaman_raster.py            # tahun 2024 saja
    python scripts/import_indeks_penanaman_raster.py --tahun 2019 2020 2021 2022 2023 2024
"""

import argparse
import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pymysql
import rasterio
import shapely.wkt
from rasterio.mask import mask as rio_mask
from functools import reduce

from app import _batas_kec_index, _batas_kec_layer_geojson  # noqa: E402


def _geojson_polygon_to_shapely(geojson):
    """GeoJSON Polygon/MultiPolygon -> geometri shapely lewat WKT.
    shapely.geometry.shape() men-TypeError pada kombinasi shapely/numpy di
    environment ini saat membangun MultiPolygon dari list koordinat
    Python (sama persis bug yg didokumentasikan di
    app.py:_geojson_line_to_shapely untuk MultiLineString) -- lewat WKT
    menghindari jalur kode vectorized creation yg tersedak itu."""
    def _ring_wkt(ring):
        return "(" + ", ".join(f"{c[0]} {c[1]}" for c in ring) + ")"
    if geojson["type"] == "Polygon":
        wkt = "POLYGON (" + ", ".join(_ring_wkt(r) for r in geojson["coordinates"]) + ")"
    elif geojson["type"] == "MultiPolygon":
        polys = ["(" + ", ".join(_ring_wkt(r) for r in poly) + ")" for poly in geojson["coordinates"]]
        wkt = "MULTIPOLYGON (" + ", ".join(polys) + ")"
    else:
        raise ValueError(f"Tipe geometri tak didukung: {geojson['type']}")
    return shapely.wkt.loads(wkt)

BASE_DIR = Path(__file__).resolve().parent.parent
RASTER_DIR = BASE_DIR / "Maps" / "IP2019-2024"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_indeks_penanaman_raster.sql"

DB_HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
DB_USER = os.environ.get("MYSQL_USER", "root")
DB_PASS = os.environ.get("MYSQL_PASS", "")
DB_NAME = os.environ.get("MYSQL_DB", "route_gis")


def connect():
    conn = pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS,
        charset="utf8mb4", autocommit=False, cursorclass=pymysql.cursors.DictCursor,
    )
    with conn.cursor() as cur:
        cur.execute(
            "CREATE DATABASE IF NOT EXISTS %s CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            % DB_NAME
        )
    conn.select_db(DB_NAME)
    return conn


def run_schema(conn):
    sql_text = SCHEMA_PATH.read_text(encoding="utf-8")
    code = "\n".join(l for l in sql_text.splitlines() if not l.strip().startswith("--"))
    with conn.cursor() as cur:
        for stmt in [s.strip() for s in code.split(";") if s.strip()]:
            cur.execute(stmt)
    conn.commit()


def build_kabupaten_polygons():
    """{kode_kabupaten: shapely geom (union kecamatan, EPSG:4326)} -- reuse
    resolusi homonim yg sama dgn overlay peta BATAS KECAMATAN."""
    index = _batas_kec_index()
    polys = {}
    total_prov_kab = sum(len(kabs) for kabs in index.values())
    done, n_err = 0, 0
    contoh_error = None
    for prov, kabs in index.items():
        for kab_label, entries in kabs.items():
            done += 1
            if done % 50 == 0:
                print(f"  membangun poligon kabupaten... {done}/{total_prov_kab}")
            kode_kab_set = {e["kode_kecamatan"] // 1000 for e in entries if e["kode_kecamatan"]}
            if len(kode_kab_set) != 1:
                continue  # kecamatan campur >1 kabupaten (harusnya tidak terjadi) -- skip, jangan tebak
            kode_kab = next(iter(kode_kab_set))
            try:
                geo = _batas_kec_layer_geojson(prov, kab_label)
                geoms = [_geojson_polygon_to_shapely(f["geometry"]) for f in geo["features"] if f.get("geometry")]
                if not geoms:
                    continue
                # unary_union(list) HIT bug yg sama (konversi list->array
                # internal shapely/numpy) -- union berpasangan (binary .union())
                # tiap panggilan menghindari jalur vectorized-creation itu.
                polys[kode_kab] = reduce(lambda a, b: a.union(b), geoms)
            except Exception as e:
                n_err += 1
                if contoh_error is None:
                    contoh_error = f"{prov}/{kab_label}: {e}"
    if n_err:
        print(f"  PERINGATAN: {n_err} kabupaten gagal dibangun poligonnya. Contoh: {contoh_error}")
    return polys


# Peta kelas raster {1,2,3} -> sub_kode ijd_scoring_rules (A2IP_*) yg sudah
# ada (schema_ijd_scoring_2026.sql) -- 2 dipetakan konservatif ke bucket
# lebih rendah (100-150%) krn ambigu antara 2 kategori dokumen, lihat
# docstring modul.
KELAS_TO_BUCKET = {1: "100-150", 2: "150-199", 3: "GT300"}


def zonal_kelas_dominan(raster_path, polys):
    """{kode_kab: (kelas_dominan 1-3, n_piksel_valid)} -- modus piksel
    non-nol di dalam tiap poligon kabupaten."""
    out = {}
    with rasterio.open(raster_path) as ds:
        for i, (kode_kab, geom) in enumerate(polys.items(), 1):
            if i % 100 == 0:
                print(f"    zonal stats... {i}/{len(polys)}")
            try:
                arr, _ = rio_mask(ds, [geom], crop=True, nodata=0)
            except Exception:
                continue
            band = arr[0]
            valid = band[band != 0]
            if valid.size == 0:
                continue
            vals, counts = np.unique(valid, return_counts=True)
            kelas = int(vals[np.argmax(counts)])
            if kelas not in (1, 2, 3):
                continue
            out[kode_kab] = (kelas, int(valid.size))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tahun", type=int, nargs="+", default=[2024])
    args = ap.parse_args()

    conn = connect()
    try:
        run_schema(conn)
        print("Membangun poligon kabupaten (dissolve dari BATAS KECAMATAN)...")
        polys = build_kabupaten_polygons()
        print(f"  {len(polys)} kabupaten/kota punya poligon")

        for tahun in args.tahun:
            raster_path = RASTER_DIR / f"IP_{tahun}.tif"
            if not raster_path.exists():
                print(f"  SKIP {tahun}: {raster_path} tidak ada")
                continue
            print(f"Zonal statistics tahun {tahun}...")
            hasil = zonal_kelas_dominan(raster_path, polys)
            rows = [
                (f"{kk:04d}", tahun, kelas, KELAS_TO_BUCKET[kelas], n)
                for kk, (kelas, n) in hasil.items()
            ]
            with conn.cursor() as cur:
                cur.execute("DELETE FROM bps_kabupaten_indeks_penanaman_raster WHERE tahun = %s", (tahun,))
                cur.executemany(
                    "INSERT INTO bps_kabupaten_indeks_penanaman_raster "
                    "(kode_kab, tahun, kelas_tanam, bucket_ip, n_piksel_valid) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    rows,
                )
            conn.commit()
            print(f"  {tahun}: {len(rows)} kabupaten/kota dimuat")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
