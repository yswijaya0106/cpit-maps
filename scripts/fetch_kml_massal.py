# -*- coding: utf-8 -*-
"""Fetch massal geometri KML usulan Inpres dari SITIA Bina Marga (gap G19).

Mengisi usulan_inpres.geom_geojson untuk semua usulan yang punya
kml_original_url tapi geometrinya belum ter-cache — logika parse sama dengan
endpoint /api/usulan-inpres/{id}/geometry (_parse_kml_linestrings di app.py).
Aman diulang: baris yang sudah ter-cache dilewati, jadi sekaligus berfungsi
melanjutkan fetch yang terputus.

Usage (venv aktif, dari root repo):
    python scripts/fetch_kml_massal.py              # fetch semua yang belum
    python scripts/fetch_kml_massal.py --limit 100  # coba sebagian dulu
    python scripts/fetch_kml_massal.py --workers 4  # atur paralelisme
"""

import argparse
import io
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app import _parse_usulan_geometry, db_cursor  # noqa: E402


def fetch_one(session: requests.Session, usulan_id: int, url: str):
    """Return (usulan_id, geojson|None, alasan_gagal|None)."""
    try:
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        return usulan_id, None, f"HTTP: {type(e).__name__}"
    geojson = _parse_usulan_geometry(resp.content)
    if not geojson:
        return usulan_id, None, "KML/KMZ/SHP tanpa geometri jalur terbaca"
    return usulan_id, geojson, None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=0, help="maksimal usulan yang di-fetch (0 = semua)")
    ap.add_argument("--workers", type=int, default=6, help="jumlah fetch paralel (default 6)")
    args = ap.parse_args()

    with db_cursor() as cur:
        cur.execute(
            "SELECT id, kml_original_url FROM usulan_inpres "
            "WHERE kml_original_url IS NOT NULL AND geom_geojson IS NULL ORDER BY id"
        )
        antrian = cur.fetchall()
        cur.execute("SELECT COUNT(*) n FROM usulan_inpres WHERE kml_original_url IS NULL")
        tanpa_kml = cur.fetchone()["n"]

    if args.limit:
        antrian = antrian[: args.limit]
    print(f"Antrian fetch: {len(antrian)} usulan ({tanpa_kml} usulan tidak punya URL KML sama sekali)")

    gagal = Counter()
    gagal_ids = []
    ok = 0
    session = requests.Session()
    session.headers["User-Agent"] = "RouteGIS-CPIT/1.0 (cache geometri usulan IJD)"

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fetch_one, session, r["id"], r["kml_original_url"]): r["id"] for r in antrian}
        selesai = 0
        batch = []
        for fut in as_completed(futures):
            usulan_id, geojson, alasan = fut.result()
            selesai += 1
            if geojson:
                batch.append((json.dumps(geojson, ensure_ascii=False), usulan_id))
                ok += 1
            else:
                gagal[alasan] += 1
                gagal_ids.append((usulan_id, alasan))
            if len(batch) >= 50:
                with db_cursor() as cur:
                    cur.executemany(
                        "UPDATE usulan_inpres SET geom_geojson = %s, geom_fetched_at = NOW() WHERE id = %s",
                        batch,
                    )
                batch.clear()
            if selesai % 200 == 0:
                print(f"  ...{selesai}/{len(antrian)} (ok={ok}, gagal={sum(gagal.values())})")

    if batch:
        with db_cursor() as cur:
            cur.executemany(
                "UPDATE usulan_inpres SET geom_geojson = %s, geom_fetched_at = NOW() WHERE id = %s",
                batch,
            )

    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) n FROM usulan_inpres WHERE geom_geojson IS NOT NULL")
        total_cache = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) n FROM usulan_inpres")
        total = cur.fetchone()["n"]

    print(f"\nSelesai: {ok} geometri baru ter-cache; total {total_cache}/{total} usulan bergeometri.")
    print(f"Tanpa URL KML: {tanpa_kml} usulan.")
    if gagal:
        print("Gagal per alasan:")
        for alasan, n in gagal.most_common():
            print(f"  {alasan}: {n}")
        print("Contoh ID gagal:", [i for i, _ in gagal_ids[:15]])
        print("(jalankan ulang script ini untuk mencoba lagi yang gagal)")


if __name__ == "__main__":
    main()
