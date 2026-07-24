# -*- coding: utf-8 -*-
"""Import Indeks Penanaman (IP) per kabupaten/kota dari docs/docs/Kertas
Kerja.xlsx sheet "Kertas Kerja" -> tabel bps_kabupaten_indeks_penanaman
(scripts/schema_kertas_kerja.sql). Sub-parameter C.A2 (11%) yang sebelumnya
tidak punya sumber data ("Indeks Penanaman tidak dipublikasikan BPS").

Layout sheet "Kertas Kerja": header berlapis 2 baris (baris 4 label utama,
baris 5 sub-label/tahun), data mulai baris 7. Kolom (0-indexed):
  3  = C-KD (kode kabupaten BPS; akhiran 00 = baris total provinsi, skip)
  2  = DAERAH (nama kab, gaya "Kab. X"/"Kota X")
  21 = Lahan Baku Sawah (2024) -- disimpan referensi, TIDAK dipakai skoring
  22 = Indeks Penanaman (nilai numerik %)
  23 = kategori sumber (mis. "IP 100-150")

Usage (venv aktif):
    python scripts/import_kertas_kerja.py
"""

import os
import re
import sys
from pathlib import Path

import openpyxl
import psycopg
from psycopg.rows import dict_row

BASE_DIR = Path(__file__).resolve().parent.parent
DOCS_DIR = BASE_DIR / "docs" / "docs"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_kertas_kerja.sql"
XLSX_PATH = DOCS_DIR / "Kertas Kerja.xlsx"

DB_HOST = os.environ.get("PG_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("PG_PORT", "5432"))
DB_USER = os.environ.get("PG_USER", "postgres")
DB_PASS = os.environ.get("PG_PASS", "")
DB_NAME = os.environ.get("PG_DB", "route_gis")

TAHUN = 2024  # lihat catatan di schema_kertas_kerja.sql


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
            "WHERE table_schema='public' AND table_name='bps_kabupaten_indeks_penanaman'"
        )
        if not cur.fetchone():
            raise RuntimeError(
                "Tabel bps_kabupaten_indeks_penanaman belum ada di PostgreSQL -- "
                "jalankan scripts/migrate_pg_01_schema.py dulu."
            )


def _norm_nama(daerah):
    daerah = (daerah or "").strip()
    if daerah.startswith("Kab. "):
        return "Kabupaten " + daerah[len("Kab. "):]
    return daerah


def extract_rows():
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True, read_only=True)
    ws = wb["Kertas Kerja"]
    rows = []
    for row in ws.iter_rows(min_row=7, values_only=True):
        kode = row[3] if len(row) > 3 else None
        if not isinstance(kode, (int, float)):
            continue
        kode = int(kode)
        if kode % 100 == 0:
            continue  # baris total provinsi
        daerah = row[2] if len(row) > 2 else None
        lbs = row[21] if len(row) > 21 else None
        ip = row[22] if len(row) > 22 else None
        kategori = row[23] if len(row) > 23 else None
        if not isinstance(ip, (int, float)) and not isinstance(lbs, (int, float)):
            continue  # tidak ada data sama sekali utk baris ini
        # ambang resmi tertinggi cuma ">300%" (tanam >=3x/tahun, praktis batas
        # fisik lahan sawah kontinu) -- nilai > 500% hampir pasti data mentah
        # salah hitung (mis. dibagi luas panen yg nyaris nol di kota minim
        # lahan pertanian: Kota Kendari 1840%, Kota Pontianak 1712%, dst),
        # bukan IP asli. 43/446 baris kena filter ini (mayoritas "Kota").
        if isinstance(ip, (int, float)) and not (0 <= ip <= 500):
            print(f"  WARNING: IP={ip} di luar jangkauan wajar utk {kode} ({daerah}) — diabaikan (None)",
                  file=sys.stderr)
            ip = None
        rows.append((
            f"{kode:04d}", _norm_nama(daerah), TAHUN,
            float(ip) if isinstance(ip, (int, float)) else None,
            (str(kategori).strip() if kategori else None),
            float(lbs) if isinstance(lbs, (int, float)) else None,
        ))
    return rows


def main():
    conn = connect()
    try:
        run_schema(conn)
        rows = extract_rows()
        n_ip = sum(1 for r in rows if r[3] is not None)
        print(f"{len(rows)} baris kab/kota ({n_ip} punya Indeks Penanaman)")
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO bps_kabupaten_indeks_penanaman "
                "(kode_kab, nama_kab, tahun, indeks_penanaman_pct, kategori_sumber, lahan_baku_sawah_ha) "
                "VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (kode_kab, tahun) DO UPDATE SET nama_kab=EXCLUDED.nama_kab, "
                "indeks_penanaman_pct=EXCLUDED.indeks_penanaman_pct, "
                "kategori_sumber=EXCLUDED.kategori_sumber, "
                "lahan_baku_sawah_ha=EXCLUDED.lahan_baku_sawah_ha",
                rows,
            )
        conn.commit()
        print(f"Total: {len(rows)} baris dimuat ke bps_kabupaten_indeks_penanaman")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
