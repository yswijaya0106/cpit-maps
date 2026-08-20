# -*- coding: utf-8 -*-
"""Impor matriks OD penumpang LRT Jabodebek 2025 per bulan
(docs/New/4. KERETA (KA)/OD LRT Jabodebek 2025.xlsx, sheet "2025") ke
tabel referensi long/tidy od_lrt_jabodebek. Lihat
scripts/schema_od_lrt_jabodebek.sql untuk skema & cakupan (10 bulan
Jan-Okt saja, alasan blok lain dilewati). TIDAK terkait usulan_inpres/
IJD.

Sheet sumber menumpuk blok matriks 18x18 per bulan, 21 baris per blok
(1 header + 18 stasiun + 1 baris Total + 1 baris kosong) -- diverifikasi
lewat posisi baris header "O/D (<bulan>)" tiap 21 baris.

Idempotent: DELETE + INSERT ulang seluruh tabel tiap run.

Usage (venv aktif):
    python scripts/import_od_lrt_jabodebek.py
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
    REPO_ROOT / "docs" / "New" / "4. KERETA (KA)-20260820T015300Z-1-001"
    / "4. KERETA (KA)" / "OD LRT Jabodebek 2025.xlsx"
)
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_od_lrt_jabodebek.sql"
TAHUN = 2025
BLOCK_HEIGHT = 21
N_MONTHS = 10  # Januari - Oktober; blok "Rata-Rata" & 2 blok trailing (bukan ridership) dilewati


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _load_rows():
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True, read_only=True)
    ws = wb["2025"]
    all_rows = list(ws.iter_rows(min_row=1, max_row=N_MONTHS * BLOCK_HEIGHT, values_only=True))

    rows = []
    for block_idx in range(N_MONTHS):
        base = block_idx * BLOCK_HEIGHT
        header = all_rows[base]
        bulan_label = str(header[0]).replace("O/D (", "").rstrip(")")
        destinasi = [str(c).strip() for c in header[1:19]]  # 18 kolom stasiun tujuan
        for r in range(1, 19):  # 18 baris stasiun asal
            row = all_rows[base + r]
            asal = str(row[0]).strip()
            if asal.lower() == "total":
                continue
            for i, tujuan in enumerate(destinasi):
                nilai = _num(row[1 + i])
                if nilai is None:
                    continue
                rows.append((TAHUN, bulan_label, asal, tujuan, nilai))
    return rows


def main():
    if not XLSX_PATH.exists():
        print(f"GAGAL: tidak ditemukan {XLSX_PATH}")
        sys.exit(1)

    with pg_cursor() as cur:
        cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

    print(f"Membaca {XLSX_PATH.name}...")
    rows = _load_rows()
    print(f"  {len(rows)} pasangan asal-tujuan ({N_MONTHS} bulan x 18x18 stasiun)")

    with pg_cursor() as cur:
        cur.execute("DELETE FROM od_lrt_jabodebek")
        cur.executemany(
            "INSERT INTO od_lrt_jabodebek (tahun, bulan, stasiun_asal, stasiun_tujuan, jumlah_penumpang) "
            "VALUES (%s, %s, %s, %s, %s)",
            rows,
        )

    print(f"\nSelesai: {len(rows)} baris di-refresh ke od_lrt_jabodebek.")


if __name__ == "__main__":
    main()
