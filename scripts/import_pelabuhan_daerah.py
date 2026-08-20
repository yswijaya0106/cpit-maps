# -*- coding: utf-8 -*-
"""Impor database pelabuhan lokal (docs/New/0. DATA SHP/Pelabuhan Laut/
Database Pelabuhan Daerah.xls, sheet "Masterr") ke tabel pelabuhan_daerah.
Lihat scripts/schema_pelabuhan_daerah.sql. TIDAK terkait usulan_inpres/IJD.

Sheet "Koordinat" di file yang sama SENGAJA tidak dipakai -- kolom Y/X di
situ skalanya tidak konsisten antar baris (kadang perlu dibagi 1e6, kadang
1e15, tidak bisa diprogram scalanya) -- kolom "Titik Koordinat Lokasi" di
sheet "Masterr" sudah teks "lat, lon" desimal bersih, dipakai sbg sumber
lat/lon.

Idempotent: DELETE+INSERT semua baris (tabel referensi kecil, ~1000 baris
form pendataan, tidak ada natural key yang stabil utk UPSERT per baris --
"Nama Pelabuhan" bisa duplikat lintas kabupaten).

Usage (venv aktif):
    python scripts/import_pelabuhan_daerah.py
"""
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import pandas as pd
from psycopg.types.json import Json

from db import db_cursor as pg_cursor  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
XLSX_PATH = (
    REPO_ROOT / "docs" / "New" / "0. DATA SHP-20260820T015255Z-1-001" / "0. DATA SHP"
    / "Pelabuhan Laut" / "Database Pelabuhan Daerah.xls"
)
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_pelabuhan_daerah.sql"

# Kolom yang dipetakan ke kolom SQL rigid -- sisanya (rincian dermaga/
# terminal/gudang per fasilitas, puluhan kolom bernomor) masuk detail_fasilitas JSONB.
CURATED_COLS = {
    "No": "no", "Wilayah": "wilayah", "Kd Prov": "kode_provinsi", "WADMPR": "provinsi",
    "Kd Kab/Kota": "kode_kabupaten", "WADMKK": "kabupaten_kota", "Kd Kec": "kode_kecamatan",
    "Kecamatan": "kecamatan", "RIPN": "ripn", "Nama Pelabuhan": "nama_pelabuhan",
    "Kewenangan": "kewenangan", "Aktifitas Pelabuhan": "aktifitas_pelabuhan",
    "Unit Kerja": "unit_kerja", "Jenis": "jenis", "Alamat Pelabuhan/Kantor": "alamat",
    "Kondisi Pelabuhan": "kondisi_pelabuhan", "Hirarki Pelabuhan": "hirarki_pelabuhan",
    "Komoditas": "komoditas",
    "Penumpang 2021 (Org)": "penumpang_2021", "Barang 2021 (Ton)": "barang_2021",
    "Penumpang 2022 (Org)": "penumpang_2022", "Barang 2022 (Ton)": "barang_2022",
    "Penumpang 2023 (Org)": "penumpang_2023", "Barang 2023 (Ton)": "barang_2023",
    "Penumpang 2024 (Org)": "penumpang_2024", "Barang 2024 (Ton)": "barang_2024",
    "Status asset": "status_asset",
}
COORD_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


def _clean(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        if not v or v == "Tidak input data":
            return None
        return v
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def _num(v):
    v = _clean(v)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v):
    n = _num(v)
    return int(n) if n is not None else None


def _parse_koordinat(v):
    v = _clean(v)
    if not v:
        return None, None
    m = COORD_RE.match(str(v))
    if not m:
        return None, None
    return float(m.group(1)), float(m.group(2))


def main():
    if not XLSX_PATH.exists():
        print(f"GAGAL: tidak ditemukan {XLSX_PATH}")
        sys.exit(1)

    with pg_cursor() as cur:
        cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

    print(f"Membaca {XLSX_PATH.name} (sheet Masterr)...")
    df = pd.read_excel(XLSX_PATH, sheet_name="Masterr")
    detail_cols = [c for c in df.columns if c not in CURATED_COLS and c != "Titik Koordinat Lokasi" and c != "Koordinat"]

    rows = []
    for _, r in df.iterrows():
        nama = _clean(r.get("Nama Pelabuhan"))
        if not nama:
            continue
        lat, lon = _parse_koordinat(r.get("Titik Koordinat Lokasi"))
        detail = {c: _clean(r.get(c)) for c in detail_cols}
        detail = {k: v for k, v in detail.items() if v is not None}
        rows.append((
            _int(r.get("No")), _clean(r.get("Wilayah")), _int(r.get("Kd Prov")), _clean(r.get("WADMPR")),
            _int(r.get("Kd Kab/Kota")), _clean(r.get("WADMKK")), _num(r.get("Kd Kec")), _clean(r.get("Kecamatan")),
            _clean(r.get("RIPN")), nama, _clean(r.get("Kewenangan")), _clean(r.get("Aktifitas Pelabuhan")),
            _clean(r.get("Unit Kerja")), _clean(r.get("Jenis")), _clean(r.get("Alamat Pelabuhan/Kantor")),
            _clean(r.get("Kondisi Pelabuhan")), _clean(r.get("Hirarki Pelabuhan")), _clean(r.get("Komoditas")),
            _num(r.get("Penumpang 2021 (Org)")), _num(r.get("Barang 2021 (Ton)")),
            _num(r.get("Penumpang 2022 (Org)")), _num(r.get("Barang 2022 (Ton)")),
            _num(r.get("Penumpang 2023 (Org)")), _num(r.get("Barang 2023 (Ton)")),
            _num(r.get("Penumpang 2024 (Org)")), _num(r.get("Barang 2024 (Ton)")),
            _clean(r.get("Status asset")), lat, lon, Json(detail),
        ))
    print(f"  {len(rows)} baris pelabuhan daerah")

    with pg_cursor() as cur:
        cur.execute("DELETE FROM pelabuhan_daerah")
        cur.executemany(
            """INSERT INTO pelabuhan_daerah
                   (no, wilayah, kode_provinsi, provinsi, kode_kabupaten, kabupaten_kota,
                    kode_kecamatan, kecamatan, ripn, nama_pelabuhan, kewenangan, aktifitas_pelabuhan,
                    unit_kerja, jenis, alamat, kondisi_pelabuhan, hirarki_pelabuhan, komoditas,
                    penumpang_2021, barang_2021, penumpang_2022, barang_2022,
                    penumpang_2023, barang_2023, penumpang_2024, barang_2024,
                    status_asset, lat, lon, detail_fasilitas)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            rows,
        )

    n_koordinat = sum(1 for r in rows if r[27] is not None)
    print(f"Selesai: {len(rows)} baris diimpor, {n_koordinat} punya koordinat.")


if __name__ == "__main__":
    main()
