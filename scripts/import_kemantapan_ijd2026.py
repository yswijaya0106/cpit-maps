# -*- coding: utf-8 -*-
"""Import kemantapan jalan daerah per provinsi/kab-kota (docs/docs/5_IJD 2026
- DATA (Kemantapan Jalan per Kab-Kota).xlsx, sheet IJD-26) -> MySQL.

Basis parameter G8.A2 Pagu Provinsi (bobot 30) — lihat _pagu_provinsi() di
app.py. Idempoten: upsert per (kode_provinsi, kode_wilayah, jenis_adm).

Usage (venv aktif):
    python scripts/import_kemantapan_ijd2026.py
    python scripts/import_kemantapan_ijd2026.py path/ke/file.xlsx
"""

import os
import sys
from pathlib import Path

import openpyxl
import pymysql

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_XLSX = BASE_DIR / "docs" / "docs" / "5_IJD 2026 - DATA (Kemantapan Jalan per Kab-Kota).xlsx"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_kemantapan_ijd2026.sql"

DB_HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
DB_USER = os.environ.get("MYSQL_USER", "root")
DB_PASS = os.environ.get("MYSQL_PASS", "")
DB_NAME = os.environ.get("MYSQL_DB", "route_gis")


def connect():
    conn = pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS,
        charset="utf8mb4", autocommit=False,
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


def _num(v):
    if v is None or str(v).strip() in ("", "-"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


_ADM_NORM = {"KAB.": "Kab.", "KAB": "Kab.", "KOTA": "Kota", "PROV": "Prov"}


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_XLSX
    if not path.exists():
        sys.exit(f"File tidak ditemukan: {path}")

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["IJD-26"]
    rows = ws.iter_rows(values_only=True)
    # header ada di baris 4 (3 baris judul kelompok kolom di atasnya)
    header = None
    for row in rows:
        if row and str(row[0]).strip() == "No.":
            header = row
            break
    if header is None:
        sys.exit('Baris header "No." tidak ditemukan')

    out, skipped = [], 0
    for row in rows:
        if not row or not row[1] or not row[6]:
            continue
        kp, kd, prov, kabkota, jenis = row[1], row[2], row[3], row[4], row[6]
        try:
            kode_provinsi = int(str(kp).strip())
            kode_wilayah = int(str(kd).strip())
        except (TypeError, ValueError):
            skipped += 1
            continue
        jenis_norm = _ADM_NORM.get(str(jenis).strip().upper(), str(jenis).strip())
        out.append((
            kode_provinsi, kode_wilayah, str(prov).strip(), str(kabkota).strip(), jenis_norm,
            _num(row[7]), _num(row[8]), _num(row[9]), _num(row[10]), _num(row[11]),
            (str(row[12]).strip() if row[12] else None),
            _num(row[13]),
            (str(row[14]).strip() if len(row) > 14 and row[14] else None),
        ))

    conn = connect()
    try:
        run_schema(conn)
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO kemantapan_ijd_2026 (kode_provinsi, kode_wilayah, provinsi, "
                "kabupaten_kota, jenis_adm, panjang_km, mantap_km, mantap_pct, tidak_mantap_km, "
                "tidak_mantap_pct, status_pkrms, rasio_kfd, kategori_fiskal) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE provinsi=VALUES(provinsi), kabupaten_kota=VALUES(kabupaten_kota), "
                "panjang_km=VALUES(panjang_km), mantap_km=VALUES(mantap_km), mantap_pct=VALUES(mantap_pct), "
                "tidak_mantap_km=VALUES(tidak_mantap_km), tidak_mantap_pct=VALUES(tidak_mantap_pct), "
                "status_pkrms=VALUES(status_pkrms), rasio_kfd=VALUES(rasio_kfd), "
                "kategori_fiskal=VALUES(kategori_fiskal)",
                out,
            )
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM kemantapan_ijd_2026")
            total = cur.fetchone()[0]
    finally:
        conn.close()

    print(f"Import kemantapan jalan: {len(out)} baris diproses ({skipped} dilewati), total di DB: {total}")


if __name__ == "__main__":
    main()
