# -*- coding: utf-8 -*-
"""Impor titik pelabuhan penyeberangan yang BENAR-BENAR beroperasi
(docs/New/5. DARAT/Pelabuhan Penyeberangan Operasi.xlsx, sheet "Sheet1")
ke PostgreSQL/PostGIS, skema generik map_layers. Lihat
docs/kajian_data_baru_docs_new.md §7.2 untuk hasil telaah datanya.

Layer ini murni overlay peta umum, TIDAK terkait usulan_inpres/IJD.

Granularitas kecamatan (lebih detail dari layer pelabuhan penyeberangan
SHP existing), status operasi eksplisit, dan pengelola (PemProv/BPTD/
dll.) -- upgrade atribut, diimpor sebagai layer BARU terpisah (bukan
menimpa layer "PELABUHAN PENYEBRANGAN" existing) supaya tidak
mencampur sumber data yang berbeda granularitas/tanggal.

Baris dikelompokkan per provinsi dengan baris header angka romawi
("I", "ACEH", None, ...) -- baris itu dilewati (kolom pertama string,
bukan angka urut). Koordinat DMS dengan variasi format (simbol derajat/
menit/detik tidak konsisten, sebagian pakai N/S/E/W, sebagian LU/LS/BT/
BB, satu baris pakai koma sbg desimal) -- lihat _parse_dms(), semua 235
baris berhasil diparse & tervalidasi ada dalam rentang lat/lon Indonesia
saat kajian ditulis.

Bucket flat nasional "PELABUHAN PENYEBERANGAN OPERASI" (ejaan benar,
beda dari bucket lama "PELABUHAN PENYEBRANGAN" yang sumbernya SHP RBI)
-- didaftarkan ke kategori existing "Simpul Transportasi" di
maps-overlay.js.

Idempotent: DELETE + INSERT ulang seluruh layer tiap run kecuali sudah
ada & tanpa --force.

Usage (venv aktif):
    python scripts/import_pelabuhan_penyeberangan_operasi_to_postgis.py
    python scripts/import_pelabuhan_penyeberangan_operasi_to_postgis.py --force
"""
import argparse
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import openpyxl
from psycopg.types.json import Json

from db import db_cursor as pg_cursor  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
XLSX_PATH = (
    REPO_ROOT / "docs" / "New" / "5. DARAT-20260820T015302Z-1-001"
    / "5. DARAT" / "Pelabuhan Penyeberangan Operasi.xlsx"
)
PROVINSI_BUCKET = "PELABUHAN PENYEBERANGAN OPERASI"
KABUPATEN_BUCKET = ""
LAYER_NAME = "PELABUHAN PENYEBERANGAN OPERASI"
LABEL = "Pelabuhan Penyeberangan Operasi"

# Kolom sheet "Sheet1" (0-based tuple index): 0=No/roman-numeral-provinsi,
# 1=Kabupaten/Kota, 2=Kecamatan, 3=Nama Pelabuhan, 4=Koordinat DMS (Lat),
# 5=Koordinat DMS (Long), 6=Status Pencapaian, 7=Pengelola

_DMS_RE = re.compile(r"(\d+)\D+(\d+)\D+([\d.,]+)\D*(N|S|E|W|LU|LS|BT|BB)", re.IGNORECASE)
_NEGATIVE_HEMI = {"S", "W", "LS", "BB"}


def _parse_dms(s):
    if not s:
        return None
    m = _DMS_RE.search(str(s))
    if not m:
        return None
    deg, minute, sec, hemi = m.groups()
    sec = sec.replace(",", ".")
    try:
        val = float(deg) + float(minute) / 60 + float(sec) / 3600
    except ValueError:
        return None
    if hemi.upper() in _NEGATIVE_HEMI:
        val = -val
    return val


def _load_rows():
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True, read_only=True)
    ws = wb["Sheet1"]
    current_provinsi = None
    rows, n_bad = [], 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        no, kab, kec, nama, dms_lat, dms_lon, status, pengelola = row[:8]
        if isinstance(no, str):
            current_provinsi = kab  # baris header provinsi (romawi), col1 = nama provinsi
            continue
        if no is None:
            continue
        lat, lon = _parse_dms(dms_lat), _parse_dms(dms_lon)
        if lat is None or lon is None or not (-11 <= lat <= 6) or not (95 <= lon <= 141):
            n_bad += 1
            continue
        attrs = {
            "provinsi": current_provinsi, "kabupaten_kota": kab, "kecamatan": kec,
            "nama_pelabuhan": nama, "status": status, "pengelola": pengelola,
        }
        rows.append((lat, lon, attrs))
    return rows, n_bad


def _already_imported(cur):
    cur.execute(
        "SELECT 1 FROM map_layer_meta WHERE provinsi=%s AND kabupaten=%s AND layer=%s",
        (PROVINSI_BUCKET, KABUPATEN_BUCKET, LAYER_NAME),
    )
    return cur.fetchone() is not None


def _delete_layer(cur):
    cur.execute(
        "DELETE FROM map_layers WHERE provinsi=%s AND kabupaten=%s AND layer=%s",
        (PROVINSI_BUCKET, KABUPATEN_BUCKET, LAYER_NAME),
    )
    cur.execute(
        "DELETE FROM map_layer_meta WHERE provinsi=%s AND kabupaten=%s AND layer=%s",
        (PROVINSI_BUCKET, KABUPATEN_BUCKET, LAYER_NAME),
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="impor ulang meski sudah ada di map_layer_meta")
    args = ap.parse_args()

    if not XLSX_PATH.exists():
        print(f"GAGAL: tidak ditemukan {XLSX_PATH}")
        sys.exit(1)

    print(f"Membaca {XLSX_PATH.name}...")
    rows, n_bad = _load_rows()
    print(f"  {len(rows)} titik valid, {n_bad} baris dibuang (koordinat kosong/tak-terparse/di luar rentang Indonesia)")

    with pg_cursor() as cur:
        if not args.force and _already_imported(cur):
            print(f"  [lewat] {LAYER_NAME} (sudah ada, pakai --force untuk impor ulang)")
            return
        if args.force:
            _delete_layer(cur)

        cur.executemany(
            "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
            "VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))",
            [(PROVINSI_BUCKET, KABUPATEN_BUCKET, LAYER_NAME, Json(attrs), lon, lat)
             for lat, lon, attrs in rows],
        )
        cur.execute(
            """INSERT INTO map_layer_meta
                   (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (provinsi, kabupaten, layer) DO UPDATE SET
                   label=EXCLUDED.label, feature_count=EXCLUDED.feature_count,
                   size_mb=EXCLUDED.size_mb, source_shp=EXCLUDED.source_shp,
                   imported_at=now()""",
            (PROVINSI_BUCKET, KABUPATEN_BUCKET, LAYER_NAME, LABEL,
             len(rows), round(XLSX_PATH.stat().st_size / 1_048_576, 2),
             str(XLSX_PATH.relative_to(REPO_ROOT))),
        )

    print(f"\nSelesai: {len(rows)} titik pelabuhan penyeberangan operasi diimpor.")


if __name__ == "__main__":
    main()
