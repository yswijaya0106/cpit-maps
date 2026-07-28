# -*- coding: utf-8 -*-
"""Spatial-join geometri usulan Inpres x geometri Peta Koridor (radius
<50m) -> isi usulan_inpres.koridor_radius_50m sekali, disimpan -- BUKAN
dihitung ulang tiap kali skor IJD di-request.

Ditambahkan 28 Jul 2026 (request eksplisit user) menggantikan live query
spasial di _ijd_score_koridor_v2()/_ijd_score_bulk_rows(): live query itu
sendiri sudah dioptimasi (280s -> ~53s per batch nasional, lihat CLAUDE.md),
tapi tetap kena hitung ulang tiap _ijd_bulk_cache kosong (restart server).
Pola precompute-simpan-kolom ini SAMA PERSIS dgn usulan_inpres.kode_kecamatan
(spatial_join_kecamatan.py) dan usulan_kecamatan_dilalui
(spatial_join_kecamatan_multi.py) -- fakta spasial dihitung sekali via
script terpisah, disimpan, scorer tinggal baca kolom (O(1), tanpa query
spasial sama sekali lagi saat scoring).

Sumber:
  - usulan_inpres.geom_geojson : jalur usulan hasil scripts/fetch_kml_massal.py
  - map_layers (layer='PETA KORIDOR') : geometri koridor, sudah di PostGIS
    (scripts/import_peta_koridor_to_postgis.py) -- BEDA dari
    spatial_join_kecamatan.py yang masih baca SHP mentah dari disk lewat
    geopandas/shapely, di sini spatial join-nya dikerjakan di SQL
    (ST_DWithin) krn kedua sisi sudah sama-sama di database.

Kolom baru koridor_radius_50m (TEXT, nullable) menyimpan NO_KORIDOR dari
koridor TERDEKAT dalam radius 50m (kalau ada beberapa), NULL kalau tidak
ada koridor manapun dalam radius itu. Dihitung utk SEMUA usulan bergeometri
(bukan cuma yang kode_koridor-nya belum match bappenas_koridor) -- ini
fakta spasial independen, keputusan "dipakai sbg fallback 'tidak langsung'
kalau kode_koridor tak match" tetap di sisi _ijd_score_koridor_v2(), bukan
di sini (sama pemisahan tanggung jawab dgn kode_kecamatan vs C.A1 scorer).

Radius (planar/derajat, BUKAN ::geography) & alasan performanya SAMA PERSIS
dgn app.py _D_V2_RADIUS_TIDAK_LANGSUNG_DERAJAT -- lihat komentar di situ.

Hanya mengisi baris yang koridor_radius_50m-nya masih NULL (idempotent);
pakai --force untuk menghitung ulang semuanya (mis. setelah reimport Peta
Koridor dgn geometri baru).

Usage (venv aktif):
    python scripts/spatial_join_koridor_radius.py
    python scripts/spatial_join_koridor_radius.py --force
"""
import argparse
import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from db import db_cursor  # noqa: E402

PETA_KORIDOR_LAYER = "PETA KORIDOR"
RADIUS_M = 50
RADIUS_DERAJAT = RADIUS_M / 111_000  # sama pendekatan dgn app.py, lihat catatan di situ
BATCH_SIZE = 300  # secukupnya per query -- hindari 1 statement raksasa utk ~3.000 usulan sekaligus


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="hitung ulang termasuk yang sudah terisi")
    args = ap.parse_args()

    with db_cursor() as cur:
        cur.execute(
            "ALTER TABLE usulan_inpres ADD COLUMN IF NOT EXISTS koridor_radius_50m TEXT"
        )

    where = "" if args.force else "AND koridor_radius_50m IS NULL"
    with db_cursor() as cur:
        cur.execute(f"SELECT id FROM usulan_inpres WHERE geom_geojson IS NOT NULL {where}")
        ids = [r["id"] for r in cur.fetchall()]

    print(f"Antrian spatial-join radius {RADIUS_M}m: {len(ids)} usulan bergeometri")
    if not ids:
        print("Tidak ada baris yang perlu diproses.")
        return

    t0 = time.time()
    total_match = 0
    for i in range(0, len(ids), BATCH_SIZE):
        batch = ids[i:i + BATCH_SIZE]
        with db_cursor() as cur:
            cur.execute(
                """
                WITH usulan_geom AS MATERIALIZED (
                    SELECT id, ST_Simplify(ST_SetSRID(ST_GeomFromGeoJSON(geom_geojson), 4326), 0.0001) AS g
                    FROM usulan_inpres
                    WHERE id = ANY(%s)
                )
                SELECT DISTINCT ON (ug.id) ug.id AS usulan_id, ml.attrs->>'NO_KORIDOR' AS no_koridor
                FROM usulan_geom ug
                JOIN map_layers ml
                  ON ml.layer = %s
                 AND ST_DWithin(ml.geom, ug.g, %s)
                ORDER BY ug.id, ST_Distance(ml.geom, ug.g)
                """,
                (batch, PETA_KORIDOR_LAYER, RADIUS_DERAJAT),
            )
            matches = {r["usulan_id"]: r["no_koridor"] for r in cur.fetchall()}
            # Baris tanpa match TETAP di-UPDATE ke NULL (bukan dibiarkan) supaya
            # --force benar-benar menghapus hasil lama yg mungkin sudah tidak
            # valid lagi (mis. koridor lama dihapus dari import terbaru).
            rows = [(matches.get(uid), uid) for uid in batch]
            cur.executemany("UPDATE usulan_inpres SET koridor_radius_50m = %s WHERE id = %s", rows)
        total_match += len(matches)
        print(f"  ...{min(i + BATCH_SIZE, len(ids))}/{len(ids)} ({time.time() - t0:.1f}s)")

    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) n FROM usulan_inpres WHERE koridor_radius_50m IS NOT NULL")
        terisi = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) n FROM usulan_inpres")
        total = cur.fetchone()["n"]

    print(f"\nSelesai dlm {time.time() - t0:.1f}s: {total_match}/{len(ids)} usulan pada run ini "
          f"ketemu koridor dlm radius {RADIUS_M}m; total terisi (match) {terisi}/{total} nasional.")


if __name__ == "__main__":
    main()
