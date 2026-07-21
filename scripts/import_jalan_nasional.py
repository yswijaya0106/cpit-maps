# -*- coding: utf-8 -*-
"""Jalan Nasional (Aspek B Laporan Daerah Prioritas, kriteria "Konektivitas
Jaringan Jalan") -- sinyal KEDUA, lebih kuat dari sekadar "kabupaten punya
SHP jalan daerah" (scripts/import_konektivitas_jalan.py): kabupaten yang
DILEWATI ruas jalan NASIONAL.

Sumber: Maps/JALAN NASIONAL/Jalan Nasional.shp -- 3.306 ruas, kolom
`CITY_ID` = kode BPS kabupaten LANGSUNG (mis. 1105, 1173), 0 nilai kosong.
Tanpa perlu name-matching/spatial join sama sekali -- beda dari jalan
daerah yg skema atributnya berantakan. Sebelumnya cuma tersedia sbg 7 file
Geodatabase per pulau (.gdb.zip, driver OpenFileGDB) yg belum diproses;
sekarang sudah ada versi SHP proper.

CRS sumber Lambert Conformal Conic (bukan EPSG:4326) -- TIDAK relevan di
sini krn kita cuma pakai atribut CITY_ID, bukan geometri (makanya baca
`ignore_geometry=True`, jauh lebih cepat drpd 123MB geometri penuh).

UPSERT ke tabel yang sama dgn import_konektivitas_jalan.py
(konektivitas_jaringan_jalan) -- tidak menimpa kolom ada_jalan_daerah.

Usage (venv aktif):
    python scripts/import_jalan_nasional.py
"""

import io
import os
import sys
from pathlib import Path

import geopandas as gpd
import pymysql

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent
SHP_PATH = BASE_DIR / "Maps" / "JALAN NASIONAL" / "Jalan Nasional.shp"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_konektivitas_jalan.sql"

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


def main():
    conn = connect()
    try:
        run_schema(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT kode_kabupaten FROM penduduk_kecamatan")
            valid_kab = {r["kode_kabupaten"] for r in cur.fetchall()}

        gdf = gpd.read_file(SHP_PATH, ignore_geometry=True, engine="pyogrio")
        # CITY_ID kadang berisi >1 kode dipisah koma ("1401, 1471") -- ruas
        # yg melintasi >1 kabupaten. Dipecah, tiap kabupaten yg disebut
        # dihitung 1 ruas (bukan cuma kabupaten pertama).
        n_ruas_by_kab, n_invalid = {}, 0
        for kode_kab in gdf["CITY_ID"]:
            if kode_kab is None:
                n_invalid += 1
                continue
            parts = [p.strip() for p in str(kode_kab).split(",") if p.strip()]
            any_valid = False
            for p in parts:
                try:
                    kk = int(p)
                except ValueError:
                    continue
                if kk in valid_kab:
                    n_ruas_by_kab[kk] = n_ruas_by_kab.get(kk, 0) + 1
                    any_valid = True
            if not any_valid:
                n_invalid += 1
        rows = [(kk, n) for kk, n in n_ruas_by_kab.items()]

        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO konektivitas_jaringan_jalan (kode_kabupaten, ada_jalan_nasional, n_ruas_nasional) "
                "VALUES (%s, 1, %s) "
                "ON DUPLICATE KEY UPDATE ada_jalan_nasional=1, n_ruas_nasional=VALUES(n_ruas_nasional)",
                rows,
            )
        conn.commit()
        print(f"Total: {len(rows)} kabupaten/kota dgn jalan nasional dimuat "
              f"({n_invalid} CITY_ID tak dikenal/invalid dilewati)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
