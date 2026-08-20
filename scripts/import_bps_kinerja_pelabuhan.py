# -*- coding: utf-8 -*-
"""Impor kinerja tahunan per pelabuhan (docs/New/2. LAUT/(DATA) KINERJA
PELABUHAN - STATISTIK TRANSPORTASI LAUT BPS.xlsx, sheet "Data") ke tabel
referensi bps_kinerja_pelabuhan. Lihat
scripts/schema_bps_kinerja_pelabuhan.sql untuk skema, dan
docs/kajian_data_baru_docs_new.md §4.1. TIDAK terkait usulan_inpres/IJD.

Kolom 18+ pada sumber (artefak pivot-table) diabaikan -- cuma kolom 0-17
(Pelabuhan..Keterangan) yang diimpor. 2 baris duplikat persis (Nongsa &
Telaga Punggur, Kepulauan Riau, 2020) di sumber -- UPSERT
(ON CONFLICT DO UPDATE) menangani tanpa error.

Idempotent: UPSERT per (pelabuhan, provinsi, tahun).

Usage (venv aktif):
    python scripts/import_bps_kinerja_pelabuhan.py
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
    / "2. LAUT" / "(DATA) KINERJA PELABUHAN - STATISTIK TRANSPORTASI LAUT BPS.xlsx"
)
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_bps_kinerja_pelabuhan.sql"


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _load_rows():
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True, read_only=True)
    ws = wb["Data"]
    rows = []
    for row in ws.iter_rows(min_row=6, values_only=True):
        pelabuhan, provinsi, tahun = row[0], row[1], row[2]
        if not pelabuhan:
            continue
        try:
            tahun_int = int(tahun)
        except (TypeError, ValueError):
            continue
        rows.append((
            str(pelabuhan).strip(), str(provinsi).strip() if provinsi else None, tahun_int,
            _num(row[3]), _num(row[4]), _num(row[5]),
            _num(row[6]), _num(row[7]), _num(row[8]),
            _num(row[9]), _num(row[10]), _num(row[11]), _num(row[12]),
            _num(row[13]), _num(row[14]), _num(row[15]), _num(row[16]),
            row[17],
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
    print(f"  {len(rows)} baris (pelabuhan x provinsi x tahun)")

    with pg_cursor() as cur:
        cur.executemany(
            """INSERT INTO bps_kinerja_pelabuhan
                   (pelabuhan, provinsi, tahun, unit_dn, gt_dn, avg_gt_dn,
                    unit_ln, gt_ln, avg_gt_ln, penumpang_datang_dn, penumpang_berangkat_dn,
                    penumpang_datang_ln, penumpang_berangkat_ln, bongkar_dn_ton, muat_dn_ton,
                    bongkar_ln_ton, muat_ln_ton, keterangan)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (pelabuhan, provinsi, tahun) DO UPDATE SET
                   unit_dn=EXCLUDED.unit_dn, gt_dn=EXCLUDED.gt_dn, avg_gt_dn=EXCLUDED.avg_gt_dn,
                   unit_ln=EXCLUDED.unit_ln, gt_ln=EXCLUDED.gt_ln, avg_gt_ln=EXCLUDED.avg_gt_ln,
                   penumpang_datang_dn=EXCLUDED.penumpang_datang_dn,
                   penumpang_berangkat_dn=EXCLUDED.penumpang_berangkat_dn,
                   penumpang_datang_ln=EXCLUDED.penumpang_datang_ln,
                   penumpang_berangkat_ln=EXCLUDED.penumpang_berangkat_ln,
                   bongkar_dn_ton=EXCLUDED.bongkar_dn_ton, muat_dn_ton=EXCLUDED.muat_dn_ton,
                   bongkar_ln_ton=EXCLUDED.bongkar_ln_ton, muat_ln_ton=EXCLUDED.muat_ln_ton,
                   keterangan=EXCLUDED.keterangan, imported_at=now()""",
            rows,
        )

    print(f"\nSelesai: {len(rows)} baris di-upsert ke bps_kinerja_pelabuhan.")


if __name__ == "__main__":
    main()
