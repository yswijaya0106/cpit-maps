# -*- coding: utf-8 -*-
"""Impor komposisi tenaga & potensi SAR per satuan kerja
(docs/New/6. BASARNAS/3. Data Rescuer dan Potensi/
Komposisi_Rescuer_dan_Potensi_Juli_2026.xlsx) ke tabel referensi
basarnas_rescuer_potensi. Lihat
scripts/schema_basarnas_rescuer_potensi.sql untuk skema, dan
docs/kajian_data_baru_docs_new.md §8.3. TIDAK terkait usulan_inpres/IJD.

Idempotent: DELETE + INSERT ulang seluruh tabel tiap run.

Usage (venv aktif):
    python scripts/import_basarnas_rescuer_potensi.py
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
    REPO_ROOT / "docs" / "New" / "6. BASARNAS-20260820T015304Z-1-001"
    / "6. BASARNAS" / "3. Data Rescuer dan Potensi"
    / "Komposisi_Rescuer_dan_Potensi_Juli_2026.xlsx"
)
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_basarnas_rescuer_potensi.sql"

# Kolom (0-based tuple index): 0=No, 1=Kode Daerah, 2=Satuan Kerja,
# 3=Rescuer, 4=ABK, 5=Operator Komunikasi, 6=Medis, 7=Total Tenaga,
# 8=Literasi, 9=Terlatih, 10=Kompeten, 11=Total Potensi, 12=Grand Total


def _int(v):
    return int(v) if isinstance(v, (int, float)) else None


def _load_rows():
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True, read_only=True)
    ws = wb["Sheet2 (2)"]
    rows = []
    for row in ws.iter_rows(min_row=6, values_only=True):
        no, kode_daerah, satuan_kerja = row[0], row[1], row[2]
        if not satuan_kerja:
            continue
        kode_daerah_int = _int(kode_daerah)
        rows.append((
            _int(no), str(kode_daerah_int) if kode_daerah_int is not None else None,
            str(satuan_kerja).strip(),
            _int(row[3]), _int(row[4]), _int(row[5]), _int(row[6]), _int(row[7]),
            _int(row[8]), _int(row[9]), _int(row[10]), _int(row[11]), _int(row[12]),
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
    print(f"  {len(rows)} satuan kerja")

    with pg_cursor() as cur:
        cur.execute("DELETE FROM basarnas_rescuer_potensi")
        cur.executemany(
            """INSERT INTO basarnas_rescuer_potensi
                   (no, kode_daerah, satuan_kerja, tenaga_rescuer, tenaga_abk,
                    tenaga_operator_komunikasi, tenaga_medis, tenaga_total,
                    potensi_literasi, potensi_terlatih, potensi_kompeten,
                    potensi_total, grand_total)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            rows,
        )

    print("\nSelesai: basarnas_rescuer_potensi di-refresh.")


if __name__ == "__main__":
    main()
