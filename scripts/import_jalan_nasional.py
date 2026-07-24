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
import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent
SHP_PATH = BASE_DIR / "Maps" / "JALAN NASIONAL" / "Jalan Nasional.shp"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_konektivitas_jalan.sql"

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
            "WHERE table_schema='public' AND table_name='konektivitas_jaringan_jalan'"
        )
        if not cur.fetchone():
            raise RuntimeError(
                "Tabel konektivitas_jaringan_jalan belum ada di PostgreSQL -- "
                "jalankan scripts/migrate_pg_01_schema.py dulu."
            )


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
                "VALUES (%s, TRUE, %s) "
                "ON CONFLICT (kode_kabupaten) DO UPDATE SET ada_jalan_nasional=TRUE, "
                "n_ruas_nasional=EXCLUDED.n_ruas_nasional",
                rows,
            )
        conn.commit()
        print(f"Total: {len(rows)} kabupaten/kota dgn jalan nasional dimuat "
              f"({n_invalid} CITY_ID tak dikenal/invalid dilewati)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
