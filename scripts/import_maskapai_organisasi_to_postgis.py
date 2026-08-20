# -*- coding: utf-8 -*-
"""Impor titik maskapai (dari tabel maskapai_organisasi, hasil
scrape_maskapai_organisasi.py + geocode_maskapai_organisasi.py) ke
map_layers sebagai overlay peta baru (provinsi="MASKAPAI") -- BEDA dari
import_*_to_postgis.py lain: sumbernya tabel database sendiri (sudah
punya lat/lon dari geocoding alamat perusahaan), bukan file .shp/xlsx.
TIDAK terkait usulan_inpres/IJD.

Cuma baris yang sudah punya koordinat (lat/lon dari geocoding, bisa gagal
utk sebagian alamat) yang diimpor -- lihat GET /api/maskapai-organisasi
soal cakupan geocoding. attrs.Name diisi nama_maskapai supaya konsisten
dgn konvensi layer titik lain (BANDARA dkk, dipakai identify popup).

Idempotent: DELETE + reinsert penuh (tabel kecil, ~130 baris bergeokode,
tidak ada alasan utk upsert per-baris).

Usage (venv aktif):
    python scripts/import_maskapai_organisasi_to_postgis.py
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from psycopg.types.json import Json

from db import db_cursor as pg_cursor  # noqa: E402

PROVINSI = "MASKAPAI"
KABUPATEN = ""
LAYER = "Maskapai"


def main():
    with pg_cursor() as cur:
        cur.execute(
            "SELECT kode_organisasi, kategori, nama_maskapai, nama_perusahaan, dba_name, "
            "alamat_perusahaan, telepon, fax, email, perpanjangan_terakhir_sertifikat, "
            "status_operasi, detail_url, geo_provinsi, geo_kabupaten, geo_kecamatan, "
            "geo_formatted_address, lat, lon "
            "FROM maskapai_organisasi WHERE lat IS NOT NULL AND lon IS NOT NULL"
        )
        rows = cur.fetchall()
    print(f"{len(rows)} maskapai punya koordinat (dari geocoding alamat perusahaan).")

    records = []
    for r in rows:
        attrs = {
            "Name": r["nama_maskapai"],
            "Kode Organisasi": r["kode_organisasi"],
            "Kategori": r["kategori"],
            "Nama Perusahaan": r["nama_perusahaan"],
            "DBA Name": r["dba_name"],
            "Alamat Perusahaan": r["alamat_perusahaan"],
            "Telepon": r["telepon"],
            "Fax": r["fax"],
            "Email": r["email"],
            "Perpanjangan Terakhir Sertifikat": r["perpanjangan_terakhir_sertifikat"],
            "Status Operasi": r["status_operasi"],
            "Detail URL": r["detail_url"],
            "Provinsi (Geocode)": r["geo_provinsi"],
            "Kabupaten (Geocode)": r["geo_kabupaten"],
            "Kecamatan (Geocode)": r["geo_kecamatan"],
            "Alamat Tergeokode": r["geo_formatted_address"],
        }
        attrs = {k: v for k, v in attrs.items() if v is not None}
        records.append((PROVINSI, KABUPATEN, LAYER, Json(attrs), float(r["lon"]), float(r["lat"])))

    with pg_cursor() as cur:
        cur.execute("DELETE FROM map_layers WHERE provinsi=%s AND kabupaten=%s AND layer=%s", (PROVINSI, KABUPATEN, LAYER))
        cur.executemany(
            "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
            "VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))",
            records,
        )
        cur.execute(
            """INSERT INTO map_layer_meta
                   (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (provinsi, kabupaten, layer) DO UPDATE SET
                   label=EXCLUDED.label, feature_count=EXCLUDED.feature_count,
                   size_mb=EXCLUDED.size_mb, source_shp=EXCLUDED.source_shp,
                   imported_at=now()""",
            (PROVINSI, KABUPATEN, LAYER, LAYER, len(records), 0, "tabel maskapai_organisasi (bukan file)"),
        )

    print(f"Selesai: {len(records)} titik maskapai diimpor ke map_layers (provinsi='{PROVINSI}').")


if __name__ == "__main__":
    main()
