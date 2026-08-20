# -*- coding: utf-8 -*-
"""Isi lat/lon + provinsi/kabupaten/kecamatan tabel maskapai_organisasi
lewat Google Maps Geocoding API atas alamat_perusahaan (alamat kantor
hasil scrape dari hubud.kemenhub.go.id, lihat
scrape_maskapai_organisasi.py) -- BUKAN lokasi operasional bandara
maskapai, cuma alamat kantor terdaftar.

Dipakai bukan spatial join PostGIS (beda dari lhr_spatial_join.py)
karena alamat kantor tidak punya geometri pembanding apapun di DB --
murni teks alamat bebas, cocoknya digeocode.

Idempotent: skip baris yang geo_status sudah terisi, kecuali --force.

Usage (venv aktif, perlu GOOGLE_MAPS_API_KEY di .env):
    python scripts/geocode_maskapai_organisasi.py
    python scripts/geocode_maskapai_organisasi.py --force
"""
import argparse
import io
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import requests
from dotenv import load_dotenv

from db import db_cursor as pg_cursor  # noqa: E402

load_dotenv()

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_maskapai_organisasi.sql"
JEDA_ANTAR_REQUEST_DETIK = 0.15


def _ambil_komponen(components, tipe):
    for c in components:
        if tipe in c.get("types", []):
            return c.get("long_name")
    return None


def _kecamatan(components):
    # Google sering tidak konsisten memetakan kecamatan Indonesia --
    # coba beberapa tipe dari yang paling spesifik.
    for tipe in ("administrative_area_level_3", "sublocality_level_1", "sublocality"):
        nilai = _ambil_komponen(components, tipe)
        if nilai:
            return nilai
    return None


def _geocode(alamat):
    resp = requests.get(
        GEOCODE_URL,
        params={"address": alamat, "region": "id", "language": "id", "key": GOOGLE_MAPS_API_KEY},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    status = data.get("status")
    if status != "OK" or not data.get("results"):
        return {"status": status, "lat": None, "lon": None, "provinsi": None,
                "kabupaten": None, "kecamatan": None, "formatted_address": None}
    hasil = data["results"][0]
    loc = hasil["geometry"]["location"]
    components = hasil.get("address_components", [])
    return {
        "status": status,
        "lat": loc["lat"],
        "lon": loc["lng"],
        "provinsi": _ambil_komponen(components, "administrative_area_level_1"),
        "kabupaten": _ambil_komponen(components, "administrative_area_level_2"),
        "kecamatan": _kecamatan(components),
        "formatted_address": hasil.get("formatted_address"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Geocode ulang semua baris, bukan cuma yang belum")
    args = parser.parse_args()

    if not GOOGLE_MAPS_API_KEY:
        print("GAGAL: GOOGLE_MAPS_API_KEY tidak ditemukan di .env")
        sys.exit(1)

    with pg_cursor() as cur:
        cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
        if args.force:
            cur.execute(
                "SELECT kode_organisasi, alamat_perusahaan FROM maskapai_organisasi "
                "WHERE alamat_perusahaan IS NOT NULL ORDER BY kode_organisasi"
            )
        else:
            cur.execute(
                "SELECT kode_organisasi, alamat_perusahaan FROM maskapai_organisasi "
                "WHERE alamat_perusahaan IS NOT NULL AND geo_status IS NULL ORDER BY kode_organisasi"
            )
        rows = cur.fetchall()

    total = len(rows)
    print(f"Menggeocode {total} baris...", flush=True)
    if total == 0:
        print("Tidak ada baris yang perlu digeocode (sudah lengkap, pakai --force untuk ulang semua).")
        return

    ok = 0
    with pg_cursor() as cur:
        for i, row in enumerate(rows, start=1):
            kode = row["kode_organisasi"]
            hasil = _geocode(row["alamat_perusahaan"])
            cur.execute(
                """UPDATE maskapai_organisasi SET
                       lat = %(lat)s, lon = %(lon)s,
                       geo_provinsi = %(provinsi)s, geo_kabupaten = %(kabupaten)s,
                       geo_kecamatan = %(kecamatan)s, geo_formatted_address = %(formatted_address)s,
                       geo_status = %(status)s, geocoded_at = now()
                   WHERE kode_organisasi = %(kode)s""",
                {**hasil, "kode": kode},
            )
            if hasil["status"] == "OK":
                ok += 1
            print(
                f"[{i}/{total}] ({i/total*100:.1f}%) {kode}: {hasil['status']}"
                + (f" -> {hasil['kecamatan']}, {hasil['kabupaten']}, {hasil['provinsi']}" if hasil["status"] == "OK" else ""),
                flush=True,
            )
            time.sleep(JEDA_ANTAR_REQUEST_DETIK)

    print(f"\nSelesai: {ok}/{total} berhasil digeocode.")


if __name__ == "__main__":
    main()
