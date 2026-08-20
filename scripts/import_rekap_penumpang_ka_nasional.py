# -*- coding: utf-8 -*-
"""Impor jumlah penumpang kereta api nasional per kategori/sistem
2020-2025 (docs/New/5. DARAT/Rekap Data Daerah.xlsx, sheet
"(KEN TITIP 3)") ke tabel referensi rekap_penumpang_ka_nasional. Lihat
scripts/schema_rekap_penumpang_ka_nasional.sql untuk skema & alasan
kenapa cuma sheet ini yang diimpor dari file sumbernya, dan
docs/kajian_data_baru_docs_new.md §7.3. TIDAK terkait usulan_inpres/IJD.

Nilai placeholder '-' pada sumber (sistem belum beroperasi di tahun
itu) disimpan sebagai NULL, bukan 0 -- beda makna (tidak ada layanan vs.
nol penumpang).

Idempotent: UPSERT per (uraian, tahun).

Usage (venv aktif):
    python scripts/import_rekap_penumpang_ka_nasional.py
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
    REPO_ROOT / "docs" / "New" / "5. DARAT-20260820T015302Z-1-001"
    / "5. DARAT" / "Rekap Data Daerah.xlsx"
)
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_rekap_penumpang_ka_nasional.sql"
YEAR_COLS = [1, 2, 3, 4, 5, 6]  # idx dlm row tuple -> 2020..2025*
YEAR_LABELS = ["2020", "2021", "2022", "2023", "2024", "2025*"]


def _num(v):
    if v is None or v == "" or str(v).strip() == "-":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _load_rows():
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True, read_only=True)
    ws = wb["(KEN TITIP 3)"]
    rows = []
    for row in ws.iter_rows(min_row=4, values_only=True):
        uraian = row[0]
        if not uraian:
            continue
        for col, label in zip(YEAR_COLS, YEAR_LABELS):
            nilai = _num(row[col])
            rows.append((str(uraian).strip(), label, nilai))
    return rows


def main():
    if not XLSX_PATH.exists():
        print(f"GAGAL: tidak ditemukan {XLSX_PATH}")
        sys.exit(1)

    with pg_cursor() as cur:
        cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

    print(f"Membaca {XLSX_PATH.name} (sheet KEN TITIP 3)...")
    rows = _load_rows()
    print(f"  {len(rows)} baris (uraian x tahun)")

    with pg_cursor() as cur:
        cur.executemany(
            """INSERT INTO rekap_penumpang_ka_nasional (uraian, tahun, jumlah_penumpang)
               VALUES (%s, %s, %s)
               ON CONFLICT (uraian, tahun) DO UPDATE SET
                   jumlah_penumpang=EXCLUDED.jumlah_penumpang, imported_at=now()""",
            rows,
        )

    print(f"\nSelesai: {len(rows)} baris di-upsert ke rekap_penumpang_ka_nasional.")


if __name__ == "__main__":
    main()
