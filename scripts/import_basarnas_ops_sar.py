# -*- coding: utf-8 -*-
"""Impor insiden operasi SAR nasional 2021-2025 (docs/New/6. BASARNAS/
4. Data Ops SAR/OPS <tahun>.xlsx, sheet "REKAPITULASI DETAIL") ke tabel
referensi basarnas_ops_sar. Lihat scripts/schema_basarnas_ops_sar.sql
untuk skema, dan docs/kajian_data_baru_docs_new.md §8.4 untuk hasil
telaah datanya. TIDAK terkait usulan_inpres/IJD.

HANYA sheet "REKAPITULASI DETAIL" per tahun yang diimpor -- 5 sheet
lain (PESAWAT/KAPAL/BENCANA/KMM/KPK) diverifikasi berisi baris IDENTIK
PERSIS dengan subset REKAPITULASI DETAIL (dikelompokkan ulang per jenis
kecelakaan, bukan data tambahan) -- mengimpornya juga akan
menduplikasi/mengganda-hitung insiden yang sama.

Baris dengan koordinat kosong/tak-terparse/di luar rentang Indonesia
dibuang (dicatat jumlahnya per tahun) -- lat/lon presisi tinggi adalah
nilai analitik utama dataset ini, baris tanpa koordinat valid tidak
berguna untuk itu.

Idempotent: DELETE + INSERT ulang seluruh tabel tiap run.

Usage (venv aktif):
    python scripts/import_basarnas_ops_sar.py
"""
import io
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import openpyxl

from db import db_cursor as pg_cursor  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE_DIR = (
    REPO_ROOT / "docs" / "New" / "6. BASARNAS-20260820T015304Z-1-001"
    / "6. BASARNAS" / "4. Data Ops SAR"
)
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_basarnas_ops_sar.sql"
YEARS = [2021, 2022, 2023, 2024, 2025]

# Kolom (0-based tuple index): 0=NO, 1=KANTOR SAR, 2=JENIS KECELAKAAN,
# 3=SUB JENIS KECELAKAAN, 4=deskripsi, 5=LONGITUDE, 6=LATITUDE,
# 7=WAKTU KEJADIAN, 8=WAKTU LAPOR, 9=WAKTU BERANGKAT, 10=WAKTU TIBA,
# 11=WAKTU SELESAI, 12=KORBAN, 13=S, 14=MD, 15=DP/H

_TS_FMT = "%Y-%m-%d %H:%M:%S"
# Ditemukan saat verifikasi: ~620 baris (terutama tahun sumber 2025)
# punya waktu_tiba korup persis "0001-11-30 00:00:00" (placeholder tahun
# 1 dari sumber, bukan bug parsing) -- menghasilkan response-time
# negatif ekstrem kalau tidak difilter. Rentang tahun wajar dataset ini
# 2021-2025; timestamp di luar rentang longgar ini diperlakukan sebagai
# NULL (data hilang), bukan dipaksa masuk.
_MIN_YEAR, _MAX_YEAR = 2015, 2030


def _to_ts(v):
    if not v:
        return None
    try:
        ts = datetime.strptime(str(v).strip(), _TS_FMT)
    except ValueError:
        return None
    if not (_MIN_YEAR <= ts.year <= _MAX_YEAR):
        return None
    return ts


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _text(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _load_year(tahun):
    wb = openpyxl.load_workbook(BASE_DIR / f"OPS {tahun}.xlsx", data_only=True, read_only=True)
    ws = wb["REKAPITULASI DETAIL"]
    rows, n_bad = [], 0
    for row in ws.iter_rows(min_row=3, values_only=True):
        no = row[0]
        if no is None:
            continue
        lon, lat = _to_float(row[5]), _to_float(row[6])
        if lon is None or lat is None or not (-11 <= lat <= 6) or not (95 <= lon <= 141):
            n_bad += 1
            continue
        rows.append((
            tahun, int(no), _text(row[1]), _text(row[2]), _text(row[3]), _text(row[4]),
            lon, lat,
            _to_ts(row[7]), _to_ts(row[8]), _to_ts(row[9]), _to_ts(row[10]), _to_ts(row[11]),
            int(row[12]) if isinstance(row[12], (int, float)) else None,
            int(row[13]) if isinstance(row[13], (int, float)) else None,
            int(row[14]) if isinstance(row[14], (int, float)) else None,
            int(row[15]) if isinstance(row[15], (int, float)) else None,
        ))
    return rows, n_bad


def main():
    with pg_cursor() as cur:
        cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

    all_rows = []
    for tahun in YEARS:
        path = BASE_DIR / f"OPS {tahun}.xlsx"
        if not path.exists():
            print(f"GAGAL: tidak ditemukan {path}")
            continue
        rows, n_bad = _load_year(tahun)
        print(f"  {tahun}: {len(rows)} insiden valid, {n_bad} dibuang (koordinat kosong/tak-valid)")
        all_rows.extend(rows)

    with pg_cursor() as cur:
        cur.execute("DELETE FROM basarnas_ops_sar")
        cur.executemany(
            """INSERT INTO basarnas_ops_sar
                   (tahun_sumber, no_urut, kantor_sar, jenis_kecelakaan, sub_jenis_kecelakaan,
                    deskripsi, lon, lat, waktu_kejadian, waktu_lapor, waktu_berangkat,
                    waktu_tiba, waktu_selesai, korban, selamat, meninggal_dunia,
                    dalam_pencarian_hilang)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            all_rows,
        )

    print(f"\nSelesai: {len(all_rows)} insiden di-refresh ke basarnas_ops_sar.")


if __name__ == "__main__":
    main()
