"""Koneksi MySQL -- satu-satunya titik akses DB, dipakai app.py dan semua
modul yang diekstrak darinya (lihat docs/ARCHITECTURE.md soal alasan
db_cursor() jadi contextmanager, bukan koneksi global)."""
import os
from contextlib import contextmanager

import pymysql
from dotenv import load_dotenv

load_dotenv()

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASS = os.getenv("MYSQL_PASS", "")
MYSQL_DB = os.getenv("MYSQL_DB", "route_gis")


@contextmanager
def db_cursor():
    conn = pymysql.connect(
        host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASS,
        database=MYSQL_DB, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    finally:
        conn.close()
