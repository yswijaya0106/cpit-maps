# -*- coding: utf-8 -*-
"""Impor inventaris sarana/prasarana Puslat SDMPP BASARNAS (docs/New/6.
BASARNAS/6. Fasilitas Puslat SDMPP/Rekapitulasi Fasilitas Pusat Pendidikan
dan Pelatihan Pencarian dan Pertolongan.xlsx) ke basarnas_puslat_fasilitas.
Lihat scripts/schema_basarnas_puslat_fasilitas.sql. TIDAK terkait
usulan_inpres/IJD.

Header sumber ada di baris ke-3 (judul + baris kosong di atasnya) --
SARANA DARAT/SARANA LAUT: No, Kendaraan, Nomor Plat/No. Lambung, Merk/Type,
Tahun. PRASARANA LATIHAN cuma No, Prasarana (2 kolom).

Idempotent: DELETE+INSERT semua baris (tabel referensi kecil, tanpa
natural key stabil lintas sheet).

Usage (venv aktif):
    python scripts/import_basarnas_puslat_fasilitas.py
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import pandas as pd

from db import db_cursor as pg_cursor  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
XLSX_PATH = (
    REPO_ROOT / "docs" / "New" / "6. BASARNAS-20260820T015304Z-1-001" / "6. BASARNAS"
    / "6. Fasilitas Puslat SDMPP"
    / "Rekapitulasi Fasilitas Pusat Pendidikan dan Pelatihan Pencarian dan Pertolongan.xlsx"
)
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_basarnas_puslat_fasilitas.sql"


def _clean(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return str(v).strip()


def _load_sheet(xl, sheet, has_detail):
    df = pd.read_excel(xl, sheet_name=sheet, header=2)
    rows = []
    for _, r in df.iterrows():
        nama = _clean(r.iloc[1])
        if not nama:
            continue
        no_urut = _clean(r.iloc[0])
        if has_detail:
            nomor_plat = _clean(r.iloc[2]) if len(r) > 2 else None
            merk_type = _clean(r.iloc[3]) if len(r) > 3 else None
            tahun = _clean(r.iloc[4]) if len(r) > 4 else None
        else:
            nomor_plat = merk_type = tahun = None
        rows.append((sheet, int(no_urut) if no_urut else None, nama, nomor_plat, merk_type, tahun))
    return rows


def main():
    if not XLSX_PATH.exists():
        print(f"GAGAL: tidak ditemukan {XLSX_PATH}")
        sys.exit(1)

    with pg_cursor() as cur:
        cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

    print(f"Membaca {XLSX_PATH.name}...")
    xl = pd.ExcelFile(XLSX_PATH)
    rows = (
        _load_sheet(xl, "SARANA DARAT", True)
        + _load_sheet(xl, "SARANA LAUT", True)
        + _load_sheet(xl, "PRASARANA LATIHAN", False)
    )
    print(f"  {len(rows)} baris fasilitas")

    with pg_cursor() as cur:
        cur.execute("DELETE FROM basarnas_puslat_fasilitas")
        cur.executemany(
            "INSERT INTO basarnas_puslat_fasilitas (kategori, no_urut, nama, nomor_plat, merk_type, tahun) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            rows,
        )

    print(f"Selesai: {len(rows)} baris diimpor.")


if __name__ == "__main__":
    main()
