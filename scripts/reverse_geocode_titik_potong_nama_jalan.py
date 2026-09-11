# -*- coding: utf-8 -*-
"""Lengkapi nama_jalan yang kosong di layer overlay "Titik Potong Jalan - Rel
KA" (map_layers, provinsi='TITIK POTONG JALAN-REL KA') lewat reverse
geocoding Google Maps -- ruas jalan kabupaten/kota sumbernya (Maps/<provinsi>/
<kabupaten>/*.shp) sering tidak mengisi kolom nama ruas sama sekali (lihat
scripts/build_jalan_rel_intersection.py), jadi utk titik2 itu nama jalan
diambil dari komponen "route" hasil Geocoding API Google berdasarkan
lat/lon titik itu sendiri -- BUKAN dari data ruas resmi, makanya ditandai
eksplisit lewat attrs["nama_jalan_sumber"]="Google Maps (reverse geocode)"
supaya beda dgn nama_jalan yang datang dari atribut shapefile asli.

Idempotent: hanya menyentuh baris dgn attrs->>'nama_jalan' IS NULL.

Usage (venv aktif, perlu GOOGLE_MAPS_API_KEY di .env):
    python scripts/reverse_geocode_titik_potong_nama_jalan.py
    python scripts/reverse_geocode_titik_potong_nama_jalan.py --limit 20   # uji coba
"""
import argparse
import os
import sys
import time
import urllib.parse
import urllib.request
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from psycopg.types.json import Json

from db import db_cursor as pg_cursor  # noqa: E402

load_dotenv()
PROVINSI = "TITIK POTONG JALAN-REL KA"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
SUMBER_LABEL = "Google Maps (reverse geocode)"


def reverse_geocode_route(lat, lon, api_key):
    qs = urllib.parse.urlencode({"latlng": f"{lat},{lon}", "key": api_key})
    with urllib.request.urlopen(f"{GEOCODE_URL}?{qs}", timeout=10) as r:
        data = json.load(r)
    if data.get("status") != "OK":
        return None, data.get("status")
    for result in data.get("results", []):
        for comp in result.get("address_components", []):
            if "route" in comp.get("types", []):
                return comp["long_name"], "OK"
    return None, "NO_ROUTE_COMPONENT"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="batasi jumlah baris (uji coba)")
    ap.add_argument("--sleep", type=float, default=0.05, help="jeda antar request (detik)")
    args = ap.parse_args()

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        print("GAGAL: GOOGLE_MAPS_API_KEY tidak ada di .env")
        return

    with pg_cursor() as cur:
        cur.execute(
            "SELECT id, ST_X(geom) AS lon, ST_Y(geom) AS lat FROM map_layers "
            "WHERE provinsi=%s AND attrs->>'nama_jalan' IS NULL ORDER BY id",
            (PROVINSI,),
        )
        rows = cur.fetchall()

    if args.limit:
        rows = rows[: args.limit]
    print(f"{len(rows)} titik tanpa nama_jalan akan di-reverse-geocode...")

    n_ok = n_none = n_err = 0
    for i, row in enumerate(rows, 1):
        try:
            nama, status = reverse_geocode_route(row["lat"], row["lon"], api_key)
        except Exception as e:
            nama, status = None, f"EXC:{e}"
        if nama:
            with pg_cursor() as cur:
                cur.execute(
                    "UPDATE map_layers SET attrs = attrs || %s::jsonb WHERE id=%s",
                    (Json({"nama_jalan": nama, "nama_jalan_sumber": SUMBER_LABEL}), row["id"]),
                )
            n_ok += 1
        elif status == "OK" or status == "NO_ROUTE_COMPONENT":
            n_none += 1
        else:
            n_err += 1
            print(f"  [warn] id={row['id']} status={status}")
        if i % 100 == 0:
            print(f"  ... {i}/{len(rows)} (ok={n_ok}, tanpa route={n_none}, error={n_err})")
        time.sleep(args.sleep)

    print(f"Selesai: {n_ok} terisi, {n_none} tidak ada komponen route, {n_err} error")


if __name__ == "__main__":
    main()
