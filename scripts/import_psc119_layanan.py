# -*- coding: utf-8 -*-
"""Impor survei kapasitas layanan PSC 119 per kab/kota
(docs/New/8. KESELAMATAN/Data layanan PSC 119 2025 survey.xlsx, sheet
" Data layana PSC ") ke tabel referensi psc119_layanan. Lihat
scripts/schema_psc119_layanan.sql untuk skema, dan
docs/kajian_data_baru_docs_new.md §9.4. TIDAK terkait usulan_inpres/IJD.

**REDAKSI PRIVASI WAJIB dan DISENGAJA**: kolom sumber index 5-8 (Nama
Penanggung Jawab, Nomor WA Kontak Penanggung Jawab, Nama PIC Tim
Teknis, Nomor WA Kontak Tim Teknis) BERISI DATA PRIBADI -- kolom-kolom
itu TIDAK PERNAH dibaca/disimpan di script ini sama sekali (bukan cuma
di-null-kan setelah dibaca). Jangan tambahkan kolom itu ke import ini
tanpa keputusan eksplisit soal penanganan data pribadi.

Data self-reported (Google Form survey) -- disclaimer itu perlu
ditampilkan di UI mana pun tabel ini dipakai.

Idempotent: DELETE + INSERT ulang seluruh tabel tiap run.

Usage (venv aktif):
    python scripts/import_psc119_layanan.py
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
XLSX_PATH = (
    REPO_ROOT / "docs" / "New" / "8. KESELAMATAN-20260820T015309Z-1-001"
    / "8. KESELAMATAN" / "Data layanan PSC 119 2025 survey.xlsx"
)
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_psc119_layanan.sql"
SHEET_NAME = " Data layana PSC "

# Kolom sumber (0-based) yang DIPAKAI -- lompatan index dari 4 ke 9 SENGAJA
# (5,6,7,8 = data pribadi, tidak pernah dibaca):
# 0=Timestamp, 1=Nama PSC, 2=Provinsi, 3=Kab/Kota, 4=Lokasi PSC,
# 9=Nomor Lokal PSC, 10=Email Resmi, 11=Status Operasional 2026,
# 12=Status PSC, 13..37=data substantif (lihat _load_rows).


def _int(v):
    return int(v) if isinstance(v, (int, float)) else None


def _text(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _load_rows():
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True, read_only=True)
    ws = wb[SHEET_NAME]
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        nama_psc = row[1]
        if not nama_psc:
            continue
        ts = row[0] if isinstance(row[0], datetime) else None
        rows.append((
            ts, _text(row[1]), _text(row[2]), _text(row[3]), _text(row[4]),
            _text(row[9]), _text(row[10]), _text(row[11]), _text(row[12]),
            _int(row[13]), _int(row[14]), _int(row[15]),
            _text(row[16]), _text(row[17]), _text(row[18]),
            _int(row[19]), _int(row[20]), _int(row[21]),
            _int(row[22]), _int(row[23]), _int(row[24]),
            _int(row[25]), _int(row[26]),
            _int(row[27]), _int(row[28]), _int(row[29]), _int(row[30]),
            _int(row[31]), _int(row[32]), _int(row[33]), _int(row[34]),
            _text(row[35]), _text(row[36]), _int(row[37]),
        ))
    return rows


def main():
    if not XLSX_PATH.exists():
        print(f"GAGAL: tidak ditemukan {XLSX_PATH}")
        sys.exit(1)

    with pg_cursor() as cur:
        cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

    print(f"Membaca {XLSX_PATH.name} (kolom kontak personal dilewati, tidak pernah dibaca)...")
    rows = _load_rows()
    print(f"  {len(rows)} PSC")

    with pg_cursor() as cur:
        cur.execute("DELETE FROM psc119_layanan")
        cur.executemany(
            """INSERT INTO psc119_layanan
                   (waktu_submit, nama_psc, provinsi, kabupaten_kota, lokasi_psc,
                    nomor_lokal_psc, email_resmi_psc, status_operasional_2026, status_psc,
                    jumlah_operator_call_center, jumlah_personel_lapangan, jumlah_ambulans_aktif,
                    kesediaan_gps_tracking, sudah_siap_psc, integrasi_rumah_sakit,
                    kasus_ibu_ditangani, rujukan_ibu_hamil_risti, kematian_ibu_dalam_perjalanan,
                    kasus_bayi_ditangani, rujukan_nicu_picu, kematian_bayi_dalam_perjalanan,
                    kasus_anak_ditangani, kematian_anak_pra_rs,
                    kasus_kecelakaan_ditangani, kasus_luka_berat, kasus_luka_ringan,
                    meninggal_kecelakaan_perjalanan, kasus_jantung_ditangani,
                    meninggal_jantung_perjalanan, kasus_stroke_ditangani, meninggal_stroke_perjalanan,
                    rata_rata_waktu_respon, kendala_tantangan, estimasi_anggaran_pertahun)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            rows,
        )

    print(f"\nSelesai: {len(rows)} baris di-refresh ke psc119_layanan (kolom personal tidak diimpor).")


if __name__ == "__main__":
    main()
