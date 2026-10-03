# -*- coding: utf-8 -*-
"""Isi map_layers.wilayah_provinsi utk bucket overlay NASIONAL FLAT (kabupaten="").

Dasar pemecahan per provinsi di tree "Overlay Peta": bucket nasional flat
(JALAN NASIONAL, PELABUHAN, TITIK POTONG JALAN-REL KA, dst.) dulunya hanya bisa
dimuat utuh satu Indonesia (Jalan Nasional mentah ~118 MB). Skrip ini menandai
tiap fitur dgn provinsi yang dilaluinya (array -- ruas yang melintas batas
provinsi masuk ke semua provinsi itu, TIDAK dipotong, supaya atributnya utuh).
app.py (maps_kabupaten(per_provinsi=True) / _map_layer_payload) lalu
menyajikan "<bucket> / <provinsi>" sbg entri virtual di tingkat kabupaten.

Provinsi = poligon layer BATAS PROVINSI (attrs PROVINSI), di-ST_Subdivide supaya
ST_Intersects cepat. Fitur yang tak menyentuh poligon mana pun (titik pelabuhan
sedikit di laut, dsb.) diberi provinsi TERDEKAT bila jaraknya <= ~11 km
(TOLERANSI_DERAJAT); sisanya diberi array kosong '{}' (= sudah dihitung, tidak
masuk provinsi mana pun -- tetap tampil di entri "Seluruh Indonesia").

Kolom NULL = belum dihitung: app.py menyembunyikan pemecahan bucket yang masih
punya baris NULL (mis. baru diimpor ulang lewat DELETE+INSERT) dan kembali ke
tampilan nasional saja. Jadi JALANKAN ULANG skrip ini setelah mengimpor ulang
bucket nasional flat mana pun. Skrip juga memperbarui map_layer_meta.imported_at
bucket yang diproses supaya cache disk payload layer (.cache/maplayer/) ikut
basi otomatis (lihat komentar _MAP_LAYER_CACHE_DIR di app.py).

Usage (venv aktif):
    python scripts/build_map_layer_wilayah.py            # hanya baris NULL
    python scripts/build_map_layer_wilayah.py --force    # hitung ulang semua
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

BUCKET_PROVINSI = "BATAS PROVINSI"
TOLERANSI_DERAJAT = 0.1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="hitung ulang semua baris, bukan hanya yang NULL")
    args = ap.parse_args()
    t0 = time.time()

    with db_cursor() as cur:
        cur.execute("ALTER TABLE map_layers ADD COLUMN IF NOT EXISTS wilayah_provinsi text[]")
        cur.execute(
            "SELECT provinsi FROM map_layer_meta WHERE provinsi <> %s "
            "GROUP BY provinsi HAVING bool_and(kabupaten = '') ORDER BY provinsi",
            (BUCKET_PROVINSI,),
        )
        buckets = [r["provinsi"] for r in cur.fetchall()]
        print(f"Bucket nasional flat: {len(buckets)}")

        cur.execute(
            "CREATE TEMP TABLE tmp_prov ON COMMIT DROP AS "
            "SELECT attrs->>'PROVINSI' AS nama, ST_Subdivide(geom, 256) AS geom "
            "FROM map_layers WHERE provinsi = %s AND kabupaten = ''",
            (BUCKET_PROVINSI,),
        )
        cur.execute("CREATE INDEX ON tmp_prov USING gist (geom)")
        cur.execute("ANALYZE tmp_prov")

        if args.force:
            cur.execute("UPDATE map_layers SET wilayah_provinsi = NULL "
                        "WHERE kabupaten = '' AND provinsi = ANY(%s)", (buckets,))

        cur.execute(
            """UPDATE map_layers m SET wilayah_provinsi = s.arr
               FROM (SELECT m.id, array_agg(DISTINCT p.nama ORDER BY p.nama) AS arr
                     FROM map_layers m JOIN tmp_prov p ON ST_Intersects(m.geom, p.geom)
                     WHERE m.kabupaten = '' AND m.provinsi = ANY(%s) AND m.wilayah_provinsi IS NULL
                     GROUP BY m.id) s
               WHERE m.id = s.id""",
            (buckets,),
        )
        n_potong = cur.rowcount
        cur.execute(
            """UPDATE map_layers m SET wilayah_provinsi = COALESCE(
                   (SELECT ARRAY[p.nama] FROM tmp_prov p
                    WHERE ST_DWithin(m.geom, p.geom, %s)
                    ORDER BY m.geom <-> p.geom LIMIT 1), '{}')
               WHERE m.kabupaten = '' AND m.provinsi = ANY(%s) AND m.wilayah_provinsi IS NULL""",
            (TOLERANSI_DERAJAT, buckets),
        )
        n_terdekat = cur.rowcount
        cur.execute(
            "SELECT provinsi, count(*) FILTER (WHERE wilayah_provinsi = '{}') AS tanpa, "
            "count(*) AS total FROM map_layers WHERE kabupaten = '' AND provinsi = ANY(%s) "
            "GROUP BY provinsi ORDER BY provinsi",
            (buckets,),
        )
        for r in cur.fetchall():
            catatan = f" ({r['tanpa']} di luar semua provinsi)" if r["tanpa"] else ""
            print(f"  {r['provinsi']}: {r['total']} fitur{catatan}")

        if n_potong or n_terdekat:
            cur.execute("UPDATE map_layer_meta SET imported_at = now() WHERE kabupaten = '' AND provinsi = ANY(%s)",
                        (buckets,))
        cur.execute("CREATE INDEX IF NOT EXISTS idx_map_layers_wilayah_provinsi "
                    "ON map_layers USING gin (wilayah_provinsi)")

    print(f"Selesai: {n_potong} fitur via irisan poligon, {n_terdekat} via provinsi terdekat/tanpa provinsi "
          f"({time.time() - t0:.0f} dtk)")


if __name__ == "__main__":
    main()
