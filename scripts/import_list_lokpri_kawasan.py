# -*- coding: utf-8 -*-
"""Impor daftar kabupaten Lokasi Prioritas (Lokpri) lintas program
nasional (docs/New/2. LAUT/Dukungan Kawasan_R Pelabuhan Sandingan
RPJMN-RKP-SBPI.xlsx, sheet "List Lokpri") ke tabel referensi
list_lokpri_kawasan. Lihat scripts/schema_list_lokpri_kawasan.sql untuk
skema, dan docs/kajian_data_baru_docs_new.md §4.2. Data referensi
lintas-sektor umum, TIDAK terkait usulan_inpres/IJD.

Idempotent: DELETE + INSERT ulang seluruh tabel tiap run (tidak ada
primary key alami di sumber -- satu kabupaten muncul berkali-kali
dengan status program berbeda).

Usage (venv aktif):
    python scripts/import_list_lokpri_kawasan.py
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import openpyxl

from db import db_cursor as pg_cursor  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
XLSX_PATH = (
    REPO_ROOT / "docs" / "New" / "2. LAUT -20260820T015256Z-1-001"
    / "2. LAUT" / "Dukungan Kawasan_R Pelabuhan Sandingan RPJMN-RKP-SBPI.xlsx"
)
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_list_lokpri_kawasan.sql"


def _load_rows():
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True, read_only=True)
    ws = wb["List Lokpri"]
    rows = []
    for row in ws.iter_rows(min_row=1, values_only=True):
        no, kab_lengkap, kab, status, kategori = row[0], row[1], row[2], row[3], row[4]
        if not kab:
            continue
        rows.append((
            int(no) if isinstance(no, (int, float)) else None,
            str(kab_lengkap).strip() if kab_lengkap else None,
            str(kab).strip(),
            str(status).strip() if status else None,
            str(kategori).strip() if kategori else None,
        ))
    return rows


def main():
    if not XLSX_PATH.exists():
        print(f"GAGAL: tidak ditemukan {XLSX_PATH}")
        sys.exit(1)

    with pg_cursor() as cur:
        cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

    print(f"Membaca {XLSX_PATH.name}...")
    rows = _load_rows()
    print(f"  {len(rows)} baris")

    with pg_cursor() as cur:
        cur.execute("DELETE FROM list_lokpri_kawasan")
        cur.executemany(
            "INSERT INTO list_lokpri_kawasan (no_urut, kabupaten_lengkap, kabupaten, status, kategori) "
            "VALUES (%s, %s, %s, %s, %s)",
            rows,
        )

    print(f"\nSelesai: {len(rows)} baris di-refresh ke list_lokpri_kawasan.")


if __name__ == "__main__":
    main()
