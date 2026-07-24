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
import psycopg

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_XLSX = BASE_DIR / "docs" / "docs" / "5_IJD 2026 - DATA (Kemantapan Jalan per Kab-Kota).xlsx"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_kemantapan_ijd2026.sql"

DB_HOST = os.environ.get("PG_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("PG_PORT", "5432"))
DB_USER = os.environ.get("PG_USER", "postgres")
DB_PASS = os.environ.get("PG_PASS", "")
DB_NAME = os.environ.get("PG_DB", "route_gis")


def connect():
    return psycopg.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS, dbname=DB_NAME,
    )


def run_schema(conn):
    """Tabel sudah dibuat via scripts/migrate_pg_01_schema.py -- di sini
    cuma pastikan ada (lihat docs/migrasi_mysql_ke_postgresql.md)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='kemantapan_ijd_2026'"
        )
        if not cur.fetchone():
            raise RuntimeError(
                "Tabel kemantapan_ijd_2026 belum ada di PostgreSQL -- jalankan "
                "scripts/migrate_pg_01_schema.py dulu."
            )


def _ensure_bps_jalan_kolom_ijd(conn):
    """bps_kabupaten_jalan sudah ada dari scripts/extract_dalam_angka.py
    (kolom hasil ekstraksi PDF BPS) sebelum kolom pembanding
    tidak_mantap_pct_ijd ditambahkan -- ADD COLUMN IF NOT EXISTS native
    Postgres (tidak perlu cek information_schema manual spt MySQL 8)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='bps_kabupaten_jalan'"
        )
        if not cur.fetchone():
            return  # belum pernah diisi scripts/extract_dalam_angka.py --load -- tidak ada yang perlu di-update
        cur.execute("ALTER TABLE bps_kabupaten_jalan ADD COLUMN IF NOT EXISTS tidak_mantap_pct_ijd NUMERIC(6,2)")
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

    # Kolom L "Tidak mantap (%)" (row[11]) utk baris Kab./Kota saja -- juga
    # dititip ke bps_kabupaten_jalan.tidak_mantap_pct_ijd sbg pembanding
    # independen thd kondisi_*_km hasil ekstraksi PDF BPS (lihat
    # scripts/schema_bps_jalan.sql). kode_kab di sana CHAR(4), kode_wilayah
    # di baris Kab./Kota di file ini sudah 4 digit.
    jalan_updates = [
        (f"{r[1]:04d}", r[9])  # r[1]=kode_wilayah, r[9]=tidak_mantap_pct (row[11] asli)
        for r in out if r[4] in ("Kab.", "Kota")
    ]

    conn = connect()
    try:
        run_schema(conn)
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO kemantapan_ijd_2026 (kode_provinsi, kode_wilayah, provinsi, "
                "kabupaten_kota, jenis_adm, panjang_km, mantap_km, mantap_pct, tidak_mantap_km, "
                "tidak_mantap_pct, status_pkrms, rasio_kfd, kategori_fiskal) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (kode_provinsi, kode_wilayah, jenis_adm) DO UPDATE SET "
                "provinsi=EXCLUDED.provinsi, kabupaten_kota=EXCLUDED.kabupaten_kota, "
                "panjang_km=EXCLUDED.panjang_km, mantap_km=EXCLUDED.mantap_km, mantap_pct=EXCLUDED.mantap_pct, "
                "tidak_mantap_km=EXCLUDED.tidak_mantap_km, tidak_mantap_pct=EXCLUDED.tidak_mantap_pct, "
                "status_pkrms=EXCLUDED.status_pkrms, rasio_kfd=EXCLUDED.rasio_kfd, "
                "kategori_fiskal=EXCLUDED.kategori_fiskal",
                out,
            )
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM kemantapan_ijd_2026")
            total = cur.fetchone()[0]

        _ensure_bps_jalan_kolom_ijd(conn)
        n_jalan_updated = 0
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM information_schema.tables "
                        "WHERE table_schema='public' AND table_name='bps_kabupaten_jalan'")
            if cur.fetchone():
                cur.executemany(
                    "UPDATE bps_kabupaten_jalan SET tidak_mantap_pct_ijd = %s WHERE kode_kab = %s",
                    [(tmp, kk) for kk, tmp in jalan_updates],
                )
                n_jalan_updated = cur.rowcount
        conn.commit()
    finally:
        conn.close()

    print(f"Import kemantapan jalan: {len(out)} baris diproses ({skipped} dilewati), total di DB: {total}")
    print(f"bps_kabupaten_jalan.tidak_mantap_pct_ijd: {n_jalan_updated} baris terupdate "
          f"({len(jalan_updates)} kandidat kab/kota dari file)")


if __name__ == "__main__":
    main()
