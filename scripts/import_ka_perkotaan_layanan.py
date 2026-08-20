# -*- coding: utf-8 -*-
"""Impor kapasitas/realisasi trip/realisasi penumpang per layanan KA
perkotaan (docs/New/5. DARAT/Rekap Data Daerah.xlsx, sheet
"(KEN TITIP 1)" [2020-2024] + "(KEN TITIP 2)" [2025-2029]) ke tabel
ka_perkotaan_layanan. Lihat scripts/schema_ka_perkotaan_layanan.sql
untuk skema & alasan kenapa 2 sheet ini (sebelumnya dilewati) sekarang
diimpor terpisah dari rekap_penumpang_ka_nasional. TIDAK terkait
usulan_inpres/IJD.

Baris "Total"/"Total Realisasi Cap" SENGAJA dilewati (agregat turunan).
Nilai placeholder '\xa0' (layanan belum beroperasi tahun itu) disimpan
sebagai NULL, bukan 0.

Idempotent: UPSERT per (nama_layanan, tahun).

Usage (venv aktif):
    python scripts/import_ka_perkotaan_layanan.py
"""
import io
import re
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
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_ka_perkotaan_layanan.sql"

# (nama_sheet, sumber, [tahun per grup kolom], baris_data_awal, baris_data_akhir_inklusif)
SHEETS = [
    ("(KEN TITIP 1)", "KEN_TITIP_1", [2020, 2021, 2022, 2023, 2024], 3, 21),
    ("(KEN TITIP 2)", "KEN_TITIP_2", [2025, 2026, 2027, 2028, 2029], 3, 21),
]
# Tiap grup tahun = 3 kolom (Kapasitas, Realisasi Trip, Realisasi/Cap),
# grup dimulai di kolom (0-based) 1, 4, 7, 10, 13.
YEAR_COL_START = [1, 4, 7, 10, 13]

_STRIP_ANNOTASI = re.compile(r"\s*\*\)\s*$")


def _num(v):
    if v is None:
        return None
    if isinstance(v, str) and v.strip() in ("", "\xa0", "-"):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _load_sheet_rows(ws, sumber, tahun_list, baris_awal, baris_akhir):
    rows = []
    for row in ws.iter_rows(min_row=baris_awal, max_row=baris_akhir, values_only=True):
        nama = row[0]
        if not nama or not str(nama).strip():
            continue
        nama = _STRIP_ANNOTASI.sub("", str(nama).strip())
        if nama.lower().startswith("total"):
            continue
        for tahun, col in zip(tahun_list, YEAR_COL_START):
            kapasitas = _num(row[col])
            realisasi_trip = _num(row[col + 1])
            realisasi_penumpang = _num(row[col + 2])
            if kapasitas is None and realisasi_trip is None and realisasi_penumpang is None:
                continue
            rows.append((nama, tahun, kapasitas, realisasi_trip, realisasi_penumpang, sumber))
    return rows


def main():
    if not XLSX_PATH.exists():
        print(f"GAGAL: tidak ditemukan {XLSX_PATH}")
        sys.exit(1)

    with pg_cursor() as cur:
        cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True, read_only=True)
    semua_rows = []
    for sheet_name, sumber, tahun_list, baris_awal, baris_akhir in SHEETS:
        ws = wb[sheet_name]
        rows = _load_sheet_rows(ws, sumber, tahun_list, baris_awal, baris_akhir)
        print(f"{sheet_name}: {len(rows)} baris (layanan x tahun)")
        semua_rows.extend(rows)

    with pg_cursor() as cur:
        cur.executemany(
            """INSERT INTO ka_perkotaan_layanan
                   (nama_layanan, tahun, kapasitas, realisasi_trip, realisasi_penumpang, sumber)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (nama_layanan, tahun) DO UPDATE SET
                   kapasitas=EXCLUDED.kapasitas,
                   realisasi_trip=EXCLUDED.realisasi_trip,
                   realisasi_penumpang=EXCLUDED.realisasi_penumpang,
                   sumber=EXCLUDED.sumber,
                   imported_at=now()""",
            semua_rows,
        )

    print(f"\nSelesai: {len(semua_rows)} baris di-upsert ke ka_perkotaan_layanan.")


if __name__ == "__main__":
    main()
