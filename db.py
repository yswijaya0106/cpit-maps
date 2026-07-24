"""Koneksi PostgreSQL -- satu-satunya titik akses DB, dipakai app.py dan
semua modul yang diekstrak darinya (lihat docs/ARCHITECTURE.md soal alasan
db_cursor() jadi contextmanager, bukan koneksi global).

Migrasi dari MySQL 24 Jul 2026 (lihat docs/migrasi_mysql_ke_postgresql.md)
-- placeholder %s TIDAK berubah (psycopg pakai gaya sama dgn PyMySQL), jadi
ribuan query parameterized di app.py/scripts/*.py tidak perlu diubah
placeholder-nya, cuma sintaks SQL spesifik-MySQL (ON DUPLICATE KEY UPDATE,
DIV, dst.) yang perlu ditulis ulang satu-satu di titik pemakaiannya."""
import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()

PG_HOST = os.getenv("PG_HOST", "127.0.0.1")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASS = os.getenv("PG_PASS", "")
PG_DB = os.getenv("PG_DB", "route_gis")


@contextmanager
def db_cursor():
    conn = psycopg.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASS,
        dbname=PG_DB, row_factory=dict_row,
    )
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    finally:
        conn.close()
