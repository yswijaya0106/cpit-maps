# -*- coding: utf-8 -*-
"""Analisis konektivitas per Klaster/Subklaster Merauke (layer "SUBKLASTER",
32 poligon dari `scripts/import_subklaster_to_postgis.py`): bandara terdekat,
pelabuhan terdekat, ruas jalan terdekat (dari SEMUA jaringan yang tersedia di
sekitar Merauke -- Jalan Nasional beserta kondisi IRI-nya, JARINGAN JALAN
RTRW Papua Selatan, Jalan Provinsi/Tol/Kabupaten-Kota) + jaraknya.

Hasil disimpan di:
  1. Tabel `subklaster_analisis_transportasi` (kunci klaster+subklaster) --
     ditampilkan di menu "Data".
  2. Atribut tambahan (jsonb merge) pada `map_layers.attrs` layer "SUBKLASTER"
     (32 poligon) DAN "SUBKLASTER DETAIL - <klaster>" (10.328 poligon,
     dicocokkan per (Klaster, Subklaster) yang sama -- nilai per grup, bukan
     dihitung ulang per poligon detail, karena semua poligon detail dalam
     satu grup Klaster+Subklaster cukup dekat utk berbagi hasil yang sama).
     Atribut berlabel jelas utk popup identify ("Bandara Terdekat", "Jarak
     Pelabuhan Terdekat (km)", "Kondisi Jalan Terdekat", dst.) + koordinat
     tersembunyi (awalan "_", tak tampil di popup, dipakai frontend
     menggambar titik bandara/pelabuhan & garis rute lurus saat poligon
     diklik -- lihat attachSubklasterAnalisis di map-tools.js).

Jarak SEMUA garis lurus (geodesik, BUKAN jarak tempuh jalan) -- konsisten
dgn pola "terdekat" lain di repo ini (build_koridor_simpul_terdekat.py,
spatial_join_pelabuhan_urgensi.py). "Kondisi jalan": hanya tersedia utk ruas
Jalan Nasional (dari survei IRI, sudah tergabung di attrs-nya oleh
import_iri_ruas_nasional.py) dan JARINGAN JALAN RTRW (Status Jaringan
Rencana/Eksisting, BUKAN kondisi fisik) -- jaringan lain (Provinsi/Tol/
Kabupaten-Kota) tidak punya data kondisi, ditandai apa adanya, bukan
diasumsikan.

Idempotent (DELETE + reinsert tabel; attrs merge selalu menimpa kunci yang
sama). **Restart server / rerun cukup** -- cache layer peta (app.py
_map_layer_payload) berkunci `imported_at`, yang di-bump skrip ini sendiri.

Usage (venv aktif):
    python scripts/build_analisis_klaster_subklaster.py
"""
import io
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from psycopg.types.json import Json  # noqa: E402

from db import db_cursor  # noqa: E402

BUCKET = "KLASTER SUBKLASTER"
RADIUS_DERAJAT = 3.0  # ~330 km -- Merauke jauh dari jaringan jalan nasional/tol, radius longgar
FUNGSI_NAS_SQL = (
    "CASE attrs->>'ROAD_FUNCT' WHEN 'A' THEN 'Arteri' WHEN 'K1' THEN 'Kolektor 1' "
    "WHEN 'K2' THEN 'Kolektor 2' WHEN 'K3' THEN 'Kolektor 3' ELSE attrs->>'ROAD_FUNCT' END"
)


def fmt(x, d=2):
    if x is None:
        return None
    s = f"{x:,.{d}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def main():
    t0 = time.time()
    with db_cursor() as cur:
        cur.execute("""
CREATE TABLE IF NOT EXISTS subklaster_analisis_transportasi (
  klaster TEXT NOT NULL, subklaster TEXT NOT NULL, keterangan_aoi TEXT, luas_ha NUMERIC(12, 2),
  bandara_terdekat TEXT, kelas_bandara TEXT, jarak_bandara_km NUMERIC(10, 2),
  pelabuhan_terdekat TEXT, hierarki_pelabuhan TEXT, jarak_pelabuhan_km NUMERIC(10, 2),
  jalan_jaringan TEXT, jalan_kode TEXT, jalan_nama TEXT, jalan_klasifikasi TEXT,
  jalan_kondisi TEXT, jarak_jalan_km NUMERIC(10, 2),
  PRIMARY KEY (klaster, subklaster)
)""")

        cur.execute(f"""
            CREATE TEMP TABLE tmp_jalan_subklaster AS
            SELECT 'Nasional' AS jaringan, attrs->>'LINKID' AS kode,
                   NULLIF(trim(attrs->>'LINK_NAME'), '') AS nama,
                   'Jalan Nasional' || COALESCE(' - ' || NULLIF({FUNGSI_NAS_SQL}, ''), '') AS klasifikasi,
                   CASE WHEN attrs ? 'IRI rata-rata' THEN
                       'Mantap ' || COALESCE(attrs->>'Kondisi Mantap (%)', '-') || '% - Tidak mantap '
                       || COALESCE(attrs->>'Kondisi Tidak mantap (%)', '-') || '% (IRI rata-rata '
                       || COALESCE(attrs->>'IRI rata-rata', '-') || ', survei ' || COALESCE(attrs->>'Survei IRI', '-') || ')'
                   ELSE NULL END AS kondisi,
                   geom
            FROM map_layers WHERE provinsi = 'JALAN NASIONAL' AND layer = 'Jalan Nasional'
            UNION ALL
            SELECT 'RTRW Papua Selatan', NULL, NULLIF(trim(attrs->>'Name'), ''),
                   'Jaringan Jalan RTRW' || COALESCE(' - ' || NULLIF(attrs->>'Jenis', ''), ''),
                   CASE WHEN attrs->>'Status Jaringan' IS NOT NULL THEN
                       'Status jaringan RTRW: ' || (attrs->>'Status Jaringan')
                       || ' (rencana tata ruang, BUKAN kondisi fisik jalan)'
                   ELSE NULL END,
                   geom
            FROM map_layers WHERE layer = 'JARINGAN JALAN RTRW'
            UNION ALL
            SELECT 'Provinsi', COALESCE(NULLIF(trim(attrs->>'NOMOR'), ''), attrs->>'KEYIRMS'),
                   NULLIF(trim(attrs->>'RUAS'), ''),
                   'Jalan Provinsi' || COALESCE(' - ' || NULLIF(trim(attrs->>'FUNGSI'), ''), ''), NULL, geom
            FROM map_layers WHERE provinsi = 'JALAN PROVINSI'
            UNION ALL
            SELECT 'Tol', attrs->>'NRUAS',
                   COALESCE(NULLIF(trim(attrs->>'NAMA_JALAN'), ''), NULLIF(trim(attrs->>'RRUAS_NAMA'), '')),
                   'Jalan Tol', NULL, geom
            FROM map_layers WHERE provinsi = 'JALAN TOL'
            UNION ALL
            SELECT 'Kabupaten/Kota', NULL, NULL, 'Jalan Kabupaten/Kota', NULL, geom
            FROM map_layers WHERE layer ILIKE 'JALAN%' AND provinsi NOT LIKE 'JALAN%%'
        """)

        cur.execute("CREATE INDEX ON tmp_jalan_subklaster USING GIST (geom)")
        cur.execute("ANALYZE tmp_jalan_subklaster")
        cur.execute("SELECT jaringan, count(*) n FROM tmp_jalan_subklaster GROUP BY 1 ORDER BY 1")
        print(f"  tabel temp jalan siap: {[(r['jaringan'], r['n']) for r in cur.fetchall()]}")

        cur.execute("""
            SELECT attrs->>'Klaster' AS klaster, attrs->>'Subklaster' AS subklaster,
                   attrs->>'Keterangan AOI' AS keterangan_aoi, (attrs->>'Luas (ha)')::numeric AS luas_ha,
                   ST_CollectionExtract(ST_MakeValid(geom), 3) AS g
            FROM map_layers WHERE provinsi = %s AND layer = 'SUBKLASTER'
        """, (BUCKET,))
        subklaster = cur.fetchall()
        print(f"  {len(subklaster)} subklaster (layer SUBKLASTER)")

        hasil = []
        for row in subklaster:
            g = row["g"]
            cur.execute("""
                SELECT b.attrs->>'Name' AS nama, b.attrs->>'Kelas' AS kelas,
                       ST_Distance(b.geom::geography, %(g)s::geometry::geography) / 1000.0 AS jarak_km,
                       ST_Y(b.geom) AS lat, ST_X(b.geom) AS lon,
                       ST_Y(ST_ClosestPoint(%(g)s::geometry, b.geom)) AS ref_lat, ST_X(ST_ClosestPoint(%(g)s::geometry, b.geom)) AS ref_lon
                FROM map_layers b WHERE provinsi = 'BANDARA' AND layer = 'Bandara'
                ORDER BY b.geom <-> %(g)s::geometry LIMIT 1
            """, {"g": g})
            bandara = cur.fetchone()

            cur.execute("""
                SELECT p.attrs->>'Name' AS nama, p.attrs->>'hierarki' AS hierarki,
                       ST_Distance(p.geom::geography, %(g)s::geometry::geography) / 1000.0 AS jarak_km,
                       ST_Y(p.geom) AS lat, ST_X(p.geom) AS lon,
                       ST_Y(ST_ClosestPoint(%(g)s::geometry, p.geom)) AS ref_lat, ST_X(ST_ClosestPoint(%(g)s::geometry, p.geom)) AS ref_lon
                FROM map_layers p WHERE provinsi = 'PELABUHAN' AND layer = 'Pelabuhan Nasional'
                ORDER BY p.geom <-> %(g)s::geometry LIMIT 1
            """, {"g": g})
            pelabuhan = cur.fetchone()

            cur.execute("""
                SELECT jaringan, kode, nama, klasifikasi, kondisi,
                       ST_Distance(geom::geography, %(g)s::geometry::geography) / 1000.0 AS jarak_km
                FROM tmp_jalan_subklaster
                WHERE ST_DWithin(geom, %(g)s::geometry, %(radius)s)
                ORDER BY geom <-> %(g)s::geometry LIMIT 1
            """, {"g": g, "radius": RADIUS_DERAJAT})
            jalan = cur.fetchone()

            hasil.append({"row": row, "bandara": bandara, "pelabuhan": pelabuhan, "jalan": jalan})

        cur.execute("DELETE FROM subklaster_analisis_transportasi")
        insert_rows = []
        for h in hasil:
            r, b, p, j = h["row"], h["bandara"], h["pelabuhan"], h["jalan"]
            insert_rows.append((
                r["klaster"], r["subklaster"], r["keterangan_aoi"], r["luas_ha"],
                b["nama"] if b else None, b["kelas"] if b else None, round(b["jarak_km"], 2) if b else None,
                p["nama"] if p else None, p["hierarki"] if p else None, round(p["jarak_km"], 2) if p else None,
                j["jaringan"] if j else None, j["kode"] if j else None, j["nama"] if j else None,
                j["klasifikasi"] if j else None, j["kondisi"] if j else None, round(j["jarak_km"], 2) if j else None,
            ))
        cur.executemany(
            "INSERT INTO subklaster_analisis_transportasi VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            insert_rows,
        )
        print(f"  tabel subklaster_analisis_transportasi: {len(insert_rows)} baris")

        # atribut ditambahkan ke layer SUBKLASTER (32) & SUBKLASTER DETAIL - * (per Klaster+Subklaster yg sama)
        n_ringkas = n_detail = 0
        for h in hasil:
            r, b, p, j = h["row"], h["bandara"], h["pelabuhan"], h["jalan"]
            at = {
                "Bandara Terdekat": b["nama"] if b else None, "Kelas Bandara Terdekat": b["kelas"] if b else None,
                "Jarak Bandara Terdekat (km)": fmt(b["jarak_km"]) if b else None,
                "Pelabuhan Terdekat": p["nama"] if p else None,
                "Hierarki Pelabuhan Terdekat": p["hierarki"] if p else None,
                "Jarak Pelabuhan Terdekat (km)": fmt(p["jarak_km"]) if p else None,
                "Jaringan Jalan Terdekat": j["jaringan"] if j else None,
                "Ruas Jalan Terdekat": (j["nama"] or j["kode"]) if j else None,
                "Klasifikasi Jalan Terdekat": j["klasifikasi"] if j else None,
                "Kondisi Jalan Terdekat": (j["kondisi"] if j and j["kondisi"] else
                                           ("Data kondisi tidak tersedia utk jaringan ini" if j else None)),
                "Jarak Jalan Terdekat (km)": fmt(j["jarak_km"]) if j else None,
                "Catatan Jarak": "Seluruh jarak garis lurus (geodesik), bukan jarak tempuh jalan",
                "_bandara_lat": b["lat"] if b else None, "_bandara_lon": b["lon"] if b else None,
                "_bandara_ref_lat": b["ref_lat"] if b else None, "_bandara_ref_lon": b["ref_lon"] if b else None,
                "_pelabuhan_lat": p["lat"] if p else None, "_pelabuhan_lon": p["lon"] if p else None,
                "_pelabuhan_ref_lat": p["ref_lat"] if p else None, "_pelabuhan_ref_lon": p["ref_lon"] if p else None,
            }
            at = {k: v for k, v in at.items() if v is not None}
            cur.execute(
                "UPDATE map_layers SET attrs = attrs || %s::jsonb "
                "WHERE provinsi=%s AND layer='SUBKLASTER' AND attrs->>'Klaster'=%s AND attrs->>'Subklaster'=%s",
                (Json(at), BUCKET, r["klaster"], r["subklaster"]))
            n_ringkas += cur.rowcount
            cur.execute(
                "UPDATE map_layers SET attrs = attrs || %s::jsonb "
                "WHERE provinsi=%s AND layer LIKE 'SUBKLASTER DETAIL - %%' "
                "AND attrs->>'Klaster'=%s AND attrs->>'Subklaster'=%s",
                (Json(at), BUCKET, r["klaster"], r["subklaster"]))
            n_detail += cur.rowcount
        print(f"  atribut ditambahkan: {n_ringkas} poligon SUBKLASTER, {n_detail} poligon SUBKLASTER DETAIL")

        cur.execute(
            "UPDATE map_layer_meta SET imported_at = now() WHERE provinsi=%s AND (layer='SUBKLASTER' OR layer LIKE 'SUBKLASTER DETAIL - %%')",
            (BUCKET,))
    print(f"Selesai dlm {time.time() - t0:.1f}s.")


if __name__ == "__main__":
    main()
