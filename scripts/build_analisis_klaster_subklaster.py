# -*- coding: utf-8 -*-
"""Analisis konektivitas per Klaster/Subklaster Merauke (layer "SUBKLASTER",
32 poligon dari `scripts/import_subklaster_to_postgis.py`): bandara TERDEKAT,
pelabuhan TERDEKAT, koridor IJD TERDEKAT (layer "PETA KORIDOR"), ruas jalan
terdekat (dari SEMUA jaringan yang tersedia di sekitar Merauke -- Jalan
Nasional beserta kondisi IRI-nya, JARINGAN JALAN RTRW Papua Selatan, Jalan
Provinsi/Tol/Kabupaten-Kota) + jaraknya, PLUS rute jalan sungguhan (OSRM,
data OpenStreetMap -- jarak tempuh, estimasi durasi, geometri) ke bandara/
pelabuhan/koridor terdekat itu, dan daftar SEMUA bandara + pelabuhan di
pulau Papua (bukan cuma yang terdekat) dengan jarak garis lurusnya masing-
masing (25 Sep 2026, permintaan user).

**Kenapa rute jalan sungguhan cuma dihitung utk yang TERDEKAT, bukan
ke SEMUA ~106 bandara+pelabuhan di pulau**: memanggil OSRM ribuan kali
(32 subklaster x 106 target) tidak realistis (server demo publik, bukan
infrastruktur proyek ini) dan sebagian besar bandara perintis pedalaman
Papua memang TIDAK punya akses jalan sama sekali di OSM -- rutenya pasti
gagal ("NoRoute"). Jadi: SEMUA bandara/pelabuhan pulau ditampilkan sbg
titik dengan jarak garis lurus (murah, selalu ada), sedang rute jalan
sungguhan (jarak tempuh + durasi + polyline) hanya utk 3 target yang sudah
ditentukan sbg "terdekat" (bandara/pelabuhan/koridor) -- kalau OSRM tak
menemukan rute utk salah satunya, ditandai eksplisit "tidak ditemukan",
BUKAN fallback diam-diam ke garis lurus tanpa keterangan.

Hasil disimpan di:
  1. Tabel `subklaster_analisis_transportasi` (kunci klaster+subklaster) --
     ditampilkan di menu "Data".
  2. Atribut tambahan (jsonb merge) pada `map_layers.attrs` layer "SUBKLASTER"
     (32 poligon) DAN "SUBKLASTER DETAIL - <klaster>" (10.328 poligon,
     dicocokkan per (Klaster, Subklaster) yang sama -- nilai per grup, bukan
     dihitung ulang per poligon detail, karena semua poligon detail dalam
     satu grup Klaster+Subklaster cukup dekat utk berbagi hasil yang sama).
     Atribut berlabel jelas utk popup identify ("Bandara Terdekat", "Rute
     Jalan ke Bandara Terdekat", "Kondisi Jalan Terdekat", dst.) + koordinat/
     array tersembunyi (awalan "_", tak tampil di popup: `_bandara_rute`/
     `_pelabuhan_rute`/`_koridor_rute` = polyline OSRM, `_semua_bandara`/
     `_semua_pelabuhan` = array SEMUA titik pulau) dipakai frontend
     menggambar titik + rute saat poligon diklik -- lihat
     attachSubklasterAnalisis di map-tools.js.

Jarak "garis lurus" = geodesik (BUKAN jarak tempuh jalan), konsisten dgn
pola "terdekat" lain di repo ini (build_koridor_simpul_terdekat.py,
spatial_join_pelabuhan_urgensi.py); jarak "rute jalan" dari OSRM (lihat di
atas). "Kondisi jalan": hanya tersedia utk ruas Jalan Nasional (dari survei
IRI, sudah tergabung di attrs-nya oleh import_iri_ruas_nasional.py) dan
JARINGAN JALAN RTRW (Status Jaringan Rencana/Eksisting, BUKAN kondisi
fisik) -- jaringan lain (Provinsi/Tol/Kabupaten-Kota) tidak punya data
kondisi, ditandai apa adanya, bukan diasumsikan.

Idempotent (DELETE + reinsert tabel; attrs merge selalu menimpa kunci yang
sama). Butuh akses internet ke router.project-osrm.org (server demo publik
OSRM) -- runtime didominasi jeda OSRM (~96 panggilan x 0,3 dtk jeda +
latensi jaringan, biasanya 1-3 menit total). **Restart server / rerun
cukup** -- cache layer peta (app.py `_map_layer_payload`) berkunci
`imported_at`, yang di-bump skrip ini sendiri.

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

import requests  # noqa: E402
from psycopg.types.json import Json  # noqa: E402

from db import db_cursor  # noqa: E402

BUCKET = "KLASTER SUBKLASTER"
# Atribut tersembunyi yg hanya disimpan di layer SUBKLASTER, tidak di SUBKLASTER DETAIL - *
KUNCI_BERAT_DETAIL = ("_bandara_rute", "_pelabuhan_rute", "_koridor_rute", "_semua_bandara", "_semua_pelabuhan")
RADIUS_DERAJAT = 3.0  # ~330 km -- Merauke jauh dari jaringan jalan nasional/tol, radius longgar
FUNGSI_NAS_SQL = (
    "CASE attrs->>'ROAD_FUNCT' WHEN 'A' THEN 'Arteri' WHEN 'K1' THEN 'Kolektor 1' "
    "WHEN 'K2' THEN 'Kolektor 2' WHEN 'K3' THEN 'Kolektor 3' ELSE attrs->>'ROAD_FUNCT' END"
)
# "Pulau itu" (Papua) -- SHP RBI sumber layer BANDARA/PELABUHAN masih memakai label provinsi
# PRA-pemekaran 2022 ("Papua", "Papua Barat" saja), jadi 2 label ini SUDAH mencakup seluruh
# pulau (Papua Selatan/Tengah/Pegunungan/Barat Daya belum punya label sendiri di sumber ini).
PULAU_PROVINSI_BANDARA = ("Papua", "Papua Barat")
PULAU_PROVINSI_PELABUHAN = ("Papua", "Papua Barat")

OSRM_BASE = "https://router.project-osrm.org/route/v1/driving"
OSRM_TIMEOUT_DETIK = 8
OSRM_JEDA_DETIK = 0.3  # sopan ke server demo publik OSRM (OpenStreetMap), bukan API berbayar


def rute_osrm(lon1, lat1, lon2, lat2):
    """Rute jalan (OSRM, data OpenStreetMap) antara 2 titik -> (jarak_km, durasi_menit, [[lon,lat],...])
    atau None kalau OSRM tak menemukan rute (umum di Papua pedalaman -- banyak bandara perintis
    TANPA akses jalan sama sekali) / server tak terjangkau. Server demo publik OSRM, dipakai
    apa adanya (bukan infrastruktur milik proyek ini) -- jeda antar panggilan & timeout pendek
    supaya gagal cepat, bukan menggantung proses import."""
    try:
        r = requests.get(
            f"{OSRM_BASE}/{lon1},{lat1};{lon2},{lat2}",
            params={"overview": "full", "geometries": "geojson"}, timeout=OSRM_TIMEOUT_DETIK,
        )
        d = r.json()
        if d.get("code") != "Ok":
            return None
        leg = d["routes"][0]
        return leg["distance"] / 1000.0, leg["duration"] / 60.0, leg["geometry"]["coordinates"]
    except Exception:
        return None


def fmt(x, d=2):
    if x is None:
        return None
    s = f"{x:,.{d}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


CANDIDATE_MAX_COBA = 5  # coba OSRM ke N kandidat terdekat (garis lurus), berhenti di yang pertama tersambung


def pilih_reachable(kandidat):
    """kandidat: list baris terurut jarak garis lurus menaik (masing2 py 'ref_lat'/'ref_lon'/'lat'/'lon').
    Coba OSRM ke tiap kandidat (maks CANDIDATE_MAX_COBA) sampai yg PERTAMA tersambung -> (kandidat, rute).
    Kalau semua yg dicoba gagal, kembalikan (kandidat_terdekat, None) -- garis lurus tetap dipakai sbg
    fallback, tapi ditandai eksplisit "tidak ditemukan" (lihat label_rute), bukan diam-diam disembunyikan.
    Ini krn bandara/pelabuhan yg SECARA GEODESIK terdekat kadang tak punya akses jalan sama sekali
    (banyak bandara perintis pedalaman Papua), padahal kandidat berikutnya yg sedikit lebih jauh
    justru tersambung jalan -- ditemukan dari kasus nyata (Bandara Bade tak tersambung jalan dari satu
    subklaster, padahal Bandara Okaba yg sedikit lebih jauh justru bisa, 25 Sep 2026)."""
    if not kandidat:
        return None, None
    for kand in kandidat[:CANDIDATE_MAX_COBA]:
        rute = rute_osrm(kand["ref_lon"], kand["ref_lat"], kand["lon"], kand["lat"])
        time.sleep(OSRM_JEDA_DETIK)
        if rute:
            return kand, rute
    return kandidat[0], None


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
        for kol, tipe in (
            ("koridor_terdekat", "TEXT"), ("koridor_nama", "TEXT"), ("jarak_koridor_km", "NUMERIC(10,2)"),
            ("rute_bandara_jarak_km", "NUMERIC(10,2)"), ("rute_bandara_durasi_menit", "NUMERIC(10,1)"),
            ("rute_pelabuhan_jarak_km", "NUMERIC(10,2)"), ("rute_pelabuhan_durasi_menit", "NUMERIC(10,1)"),
            ("rute_koridor_jarak_km", "NUMERIC(10,2)"), ("rute_koridor_durasi_menit", "NUMERIC(10,1)"),
        ):
            cur.execute(f"ALTER TABLE subklaster_analisis_transportasi ADD COLUMN IF NOT EXISTS {kol} {tipe}")

    # DDL di atas SENGAJA di transaksi sendiri yg langsung commit: ALTER TABLE ... ADD COLUMN IF NOT
    # EXISTS selalu mengambil kunci ACCESS EXCLUSIVE (walau kolomnya sudah ada) yg baru lepas saat
    # commit. Kalau ikut transaksi panjang di bawah (OSRM + UPDATE map_layers, bisa puluhan menit),
    # SEMUA SELECT ke tabel ini ikut menggantung selama skrip jalan -- termasuk menu "Data" navbar
    # (/api/data/tables menghitung COUNT(*) tiap tabel), yg jadi tampak tidak bisa diklik.
    with db_cursor() as cur:
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

        # koridor IJD (layer "PETA KORIDOR") didissolve per NO_KORIDOR SEKALI di sini (bukan di
        # dalam loop per-subklaster) -- ST_Collect atas ~11.612 ruas nasional itu mahal; dipanggil
        # 32x dlm loop (versi awal) bikin skrip nyaris tak selesai dlm 280 dtk.
        cur.execute("""
            CREATE TEMP TABLE tmp_koridor_subklaster AS
            SELECT attrs->>'NO_KORIDOR' AS no_koridor, MAX(attrs->>'NAMA_KORID') AS nama_koridor, ST_Collect(geom) AS geom
            FROM map_layers WHERE layer = 'PETA KORIDOR' AND attrs->>'NO_KORIDOR' IS NOT NULL
            GROUP BY 1
        """)
        cur.execute("CREATE INDEX ON tmp_koridor_subklaster USING GIST (geom)")
        cur.execute("ANALYZE tmp_koridor_subklaster")
        cur.execute("SELECT count(*) n FROM tmp_koridor_subklaster")
        print(f"  tabel temp koridor siap: {cur.fetchone()['n']} koridor")

        cur.execute("""
            SELECT attrs->>'Klaster' AS klaster, attrs->>'Subklaster' AS subklaster,
                   attrs->>'Keterangan AOI' AS keterangan_aoi, (attrs->>'Luas (ha)')::numeric AS luas_ha,
                   ST_CollectionExtract(ST_MakeValid(geom), 3) AS g
            FROM map_layers WHERE provinsi = %s AND layer = 'SUBKLASTER'
        """, (BUCKET,))
        subklaster = cur.fetchall()
        print(f"  {len(subklaster)} subklaster (layer SUBKLASTER)")

        hasil = []
        t_osrm = time.time()
        n_osrm_ok = n_osrm_gagal = 0
        for i, row in enumerate(subklaster, 1):
            g = row["g"]
            cur.execute("""
                SELECT b.attrs->>'Name' AS nama, b.attrs->>'Kelas' AS kelas,
                       ST_Distance(b.geom::geography, %(g)s::geometry::geography) / 1000.0 AS jarak_km,
                       ST_Y(b.geom) AS lat, ST_X(b.geom) AS lon,
                       ST_Y(ST_ClosestPoint(%(g)s::geometry, b.geom)) AS ref_lat, ST_X(ST_ClosestPoint(%(g)s::geometry, b.geom)) AS ref_lon
                FROM map_layers b WHERE provinsi = 'BANDARA' AND layer = 'Bandara'
                ORDER BY b.geom <-> %(g)s::geometry LIMIT %(n)s
            """, {"g": g, "n": CANDIDATE_MAX_COBA})
            kandidat_bandara = cur.fetchall()

            cur.execute("""
                SELECT p.attrs->>'Name' AS nama, p.attrs->>'hierarki' AS hierarki,
                       ST_Distance(p.geom::geography, %(g)s::geometry::geography) / 1000.0 AS jarak_km,
                       ST_Y(p.geom) AS lat, ST_X(p.geom) AS lon,
                       ST_Y(ST_ClosestPoint(%(g)s::geometry, p.geom)) AS ref_lat, ST_X(ST_ClosestPoint(%(g)s::geometry, p.geom)) AS ref_lon
                FROM map_layers p WHERE provinsi = 'PELABUHAN' AND layer = 'Pelabuhan Nasional'
                ORDER BY p.geom <-> %(g)s::geometry LIMIT %(n)s
            """, {"g": g, "n": CANDIDATE_MAX_COBA})
            kandidat_pelabuhan = cur.fetchall()

            cur.execute("""
                SELECT jaringan, kode, nama, klasifikasi, kondisi,
                       ST_Distance(geom::geography, %(g)s::geometry::geography) / 1000.0 AS jarak_km
                FROM tmp_jalan_subklaster
                WHERE ST_DWithin(geom, %(g)s::geometry, %(radius)s)
                ORDER BY geom <-> %(g)s::geometry LIMIT 1
            """, {"g": g, "radius": RADIUS_DERAJAT})
            jalan = cur.fetchone()

            # koridor IJD terdekat (layer "PETA KORIDOR", overlay yang sama dipakai parameter D
            # skoring IJD) -- ambil dari tmp_koridor_subklaster (sudah didissolve per koridor +
            # ber-index sekali di atas, lihat komentarnya).
            cur.execute("""
                SELECT no_koridor, nama_koridor,
                       ST_Distance(geom::geography, %(g)s::geometry::geography) / 1000.0 AS jarak_km,
                       ST_Y(ST_ClosestPoint(geom, %(g)s::geometry)) AS lat, ST_X(ST_ClosestPoint(geom, %(g)s::geometry)) AS lon,
                       ST_Y(ST_ClosestPoint(%(g)s::geometry, geom)) AS ref_lat, ST_X(ST_ClosestPoint(%(g)s::geometry, geom)) AS ref_lon
                FROM tmp_koridor_subklaster
                ORDER BY geom <-> %(g)s::geometry LIMIT %(n)s
            """, {"g": g, "n": CANDIDATE_MAX_COBA})
            kandidat_koridor = cur.fetchall()

            # Bandara/pelabuhan/koridor yg SECARA GARIS LURUS terdekat kadang tak tersambung jalan
            # sama sekali -- coba beberapa kandidat terdekat berikutnya, pakai yg PERTAMA tersambung
            # (lihat pilih_reachable). "bandara"/"pelabuhan"/"koridor" di bawah = kandidat TERPILIH
            # (belum tentu yg tergeodesik terdekat kalau kandidat itu ternyata tak tersambung jalan).
            bandara, rute_b = pilih_reachable(kandidat_bandara)
            pelabuhan, rute_p = pilih_reachable(kandidat_pelabuhan)
            koridor, rute_k = pilih_reachable(kandidat_koridor)
            n_osrm_ok += sum(1 for x in (rute_b, rute_p, rute_k) if x)
            n_osrm_gagal += sum(1 for x in (rute_b, rute_p, rute_k) if x is None)

            # SEMUA bandara & pelabuhan di pulau Papua (jarak garis lurus saja -- rute jalan OSRM
            # hanya dihitung utk yang TERDEKAT di atas, memanggil OSRM ratusan kali lagi utk tiap
            # pasangan tidak realistis & kebanyakan bandara perintis pedalaman memang tanpa akses
            # jalan sama sekali).
            cur.execute("""
                SELECT attrs->>'Name' AS nama, attrs->>'Kelas' AS kelas,
                       ST_Y(geom) AS lat, ST_X(geom) AS lon,
                       ST_Distance(geom::geography, %(g)s::geometry::geography) / 1000.0 AS jarak_km
                FROM map_layers WHERE provinsi = 'BANDARA' AND layer = 'Bandara' AND attrs->>'provinsi' = ANY(%(prov)s)
                ORDER BY jarak_km
            """, {"g": g, "prov": list(PULAU_PROVINSI_BANDARA)})
            semua_bandara = cur.fetchall()
            cur.execute("""
                SELECT attrs->>'Name' AS nama, attrs->>'hierarki' AS hierarki,
                       ST_Y(geom) AS lat, ST_X(geom) AS lon,
                       ST_Distance(geom::geography, %(g)s::geometry::geography) / 1000.0 AS jarak_km
                FROM map_layers WHERE provinsi = 'PELABUHAN' AND layer = 'Pelabuhan Nasional' AND attrs->>'Provinsi' = ANY(%(prov)s)
                ORDER BY jarak_km
            """, {"g": g, "prov": list(PULAU_PROVINSI_PELABUHAN)})
            semua_pelabuhan = cur.fetchall()

            print(f"  [{i}/{len(subklaster)}] {row['klaster']} / {row['subklaster']}: "
                  f"rute OSRM {'bandara ok' if rute_b else 'bandara gagal'}, "
                  f"{'pelabuhan ok' if rute_p else 'pelabuhan gagal'}, {'koridor ok' if rute_k else 'koridor gagal'}")

            hasil.append({
                "row": row, "bandara": bandara, "pelabuhan": pelabuhan, "jalan": jalan, "koridor": koridor,
                "rute_b": rute_b, "rute_p": rute_p, "rute_k": rute_k,
                "semua_bandara": semua_bandara, "semua_pelabuhan": semua_pelabuhan,
                "kandidat_bandara": kandidat_bandara, "kandidat_pelabuhan": kandidat_pelabuhan,
                "kandidat_koridor": kandidat_koridor,
            })
        print(f"  OSRM: {n_osrm_ok} rute ditemukan, {n_osrm_gagal} tidak ({time.time() - t_osrm:.1f}s)")

        cur.execute("DELETE FROM subklaster_analisis_transportasi")
        insert_rows = []
        for h in hasil:
            r, b, p, j, k = h["row"], h["bandara"], h["pelabuhan"], h["jalan"], h["koridor"]
            rb, rp, rk = h["rute_b"], h["rute_p"], h["rute_k"]
            insert_rows.append((
                r["klaster"], r["subklaster"], r["keterangan_aoi"], r["luas_ha"],
                b["nama"] if b else None, b["kelas"] if b else None, round(b["jarak_km"], 2) if b else None,
                p["nama"] if p else None, p["hierarki"] if p else None, round(p["jarak_km"], 2) if p else None,
                j["jaringan"] if j else None, j["kode"] if j else None, j["nama"] if j else None,
                j["klasifikasi"] if j else None, j["kondisi"] if j else None, round(j["jarak_km"], 2) if j else None,
                k["no_koridor"] if k else None, k["nama_koridor"] if k else None, round(k["jarak_km"], 2) if k else None,
                round(rb[0], 2) if rb else None, round(rb[1], 1) if rb else None,
                round(rp[0], 2) if rp else None, round(rp[1], 1) if rp else None,
                round(rk[0], 2) if rk else None, round(rk[1], 1) if rk else None,
            ))
        cur.executemany(
            "INSERT INTO subklaster_analisis_transportasi ("
            "klaster, subklaster, keterangan_aoi, luas_ha, bandara_terdekat, kelas_bandara, jarak_bandara_km, "
            "pelabuhan_terdekat, hierarki_pelabuhan, jarak_pelabuhan_km, jalan_jaringan, jalan_kode, jalan_nama, "
            "jalan_klasifikasi, jalan_kondisi, jarak_jalan_km, koridor_terdekat, koridor_nama, jarak_koridor_km, "
            "rute_bandara_jarak_km, rute_bandara_durasi_menit, rute_pelabuhan_jarak_km, rute_pelabuhan_durasi_menit, "
            "rute_koridor_jarak_km, rute_koridor_durasi_menit"
            ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            insert_rows,
        )
        print(f"  tabel subklaster_analisis_transportasi: {len(insert_rows)} baris")

        # atribut ditambahkan ke layer SUBKLASTER (32) & SUBKLASTER DETAIL - * (per Klaster+Subklaster yg sama)
        n_ringkas = n_detail = 0
        for h in hasil:
            r, b, p, j, kor = h["row"], h["bandara"], h["pelabuhan"], h["jalan"], h["koridor"]
            rb, rp, rk = h["rute_b"], h["rute_p"], h["rute_k"]

            def label_rute(rute, nama_sasaran):
                if not rute:
                    return f"Rute jalan (OSRM/OpenStreetMap) tidak ditemukan ke {nama_sasaran} -- kemungkinan tak ada akses jalan"
                jarak, durasi, _ = rute
                jam = int(durasi // 60)
                menit = round(durasi % 60)
                lama = f"{jam} jam {menit} menit" if jam else f"{menit} menit"
                return f"{fmt(jarak)} km, ~{lama} (rute jalan OSRM/OpenStreetMap, estimasi berkendara)"

            def catatan_lompat(kandidat, dipilih, nama_jenis):
                """Catatan kalau kandidat TERPILIH (tersambung jalan) BUKAN yg tergeodesik terdekat --
                yg terdekat dilewati krn OSRM tak menemukan rute ke situ."""
                if not kandidat or not dipilih or kandidat[0]["nama"] == dipilih["nama"]:
                    return None
                terdekat = kandidat[0]
                return (f"{terdekat['nama']} sebenarnya lebih dekat garis lurus ({fmt(terdekat['jarak_km'])} km) tapi "
                        f"OSRM tak menemukan rute jalan ke situ -- dipakai {nama_jenis} berikutnya yg tersambung jalan")

            at = {
                "Bandara Terdekat": b["nama"] if b else None, "Kelas Bandara Terdekat": b["kelas"] if b else None,
                "Jarak Bandara Terdekat (km, garis lurus)": fmt(b["jarak_km"]) if b else None,
                "Rute Jalan ke Bandara Terdekat": label_rute(rb, b["nama"]) if b else None,
                "Catatan Bandara Terdekat": catatan_lompat(h["kandidat_bandara"], b, "bandara"),
                "Pelabuhan Terdekat": p["nama"] if p else None,
                "Hierarki Pelabuhan Terdekat": p["hierarki"] if p else None,
                "Jarak Pelabuhan Terdekat (km, garis lurus)": fmt(p["jarak_km"]) if p else None,
                "Rute Jalan ke Pelabuhan Terdekat": label_rute(rp, p["nama"]) if p else None,
                "Catatan Pelabuhan Terdekat": catatan_lompat(h["kandidat_pelabuhan"], p, "pelabuhan"),
                "Koridor IJD Terdekat": (f"{kor['no_koridor']} - {kor['nama_koridor']}" if kor and kor["nama_koridor"]
                                         else (kor["no_koridor"] if kor else None)),
                "Jarak Koridor IJD Terdekat (km, garis lurus)": fmt(kor["jarak_km"]) if kor else None,
                "Rute Jalan ke Koridor IJD Terdekat": label_rute(rk, kor["no_koridor"]) if kor else None,
                "Catatan Koridor IJD Terdekat": catatan_lompat(
                    [{"nama": x["no_koridor"], "jarak_km": x["jarak_km"]} for x in h["kandidat_koridor"]],
                    {"nama": kor["no_koridor"]} if kor else None, "koridor"),
                "Jaringan Jalan Terdekat": j["jaringan"] if j else None,
                "Ruas Jalan Terdekat": (j["nama"] or j["kode"]) if j else None,
                "Klasifikasi Jalan Terdekat": j["klasifikasi"] if j else None,
                "Kondisi Jalan Terdekat": (j["kondisi"] if j and j["kondisi"] else
                                           ("Data kondisi tidak tersedia utk jaringan ini" if j else None)),
                "Jarak Jalan Terdekat (km)": fmt(j["jarak_km"]) if j else None,
                "Catatan Jarak": "Jarak 'garis lurus' = geodesik, bukan jarak tempuh jalan; jarak 'rute jalan' dari OSRM (OpenStreetMap)",
                "_bandara_lat": b["lat"] if b else None, "_bandara_lon": b["lon"] if b else None,
                "_bandara_ref_lat": b["ref_lat"] if b else None, "_bandara_ref_lon": b["ref_lon"] if b else None,
                "_bandara_rute": [[round(x, 5), round(y, 5)] for x, y in rb[2]] if rb else None,
                "_pelabuhan_lat": p["lat"] if p else None, "_pelabuhan_lon": p["lon"] if p else None,
                "_pelabuhan_ref_lat": p["ref_lat"] if p else None, "_pelabuhan_ref_lon": p["ref_lon"] if p else None,
                "_pelabuhan_rute": [[round(x, 5), round(y, 5)] for x, y in rp[2]] if rp else None,
                "_koridor_lat": kor["lat"] if kor else None, "_koridor_lon": kor["lon"] if kor else None,
                "_koridor_ref_lat": kor["ref_lat"] if kor else None, "_koridor_ref_lon": kor["ref_lon"] if kor else None,
                "_koridor_rute": [[round(x, 5), round(y, 5)] for x, y in rk[2]] if rk else None,
                "_semua_bandara": [
                    {"nama": x["nama"], "kelas": x["kelas"], "lat": x["lat"], "lon": x["lon"], "jarak_km": round(x["jarak_km"], 1)}
                    for x in h["semua_bandara"]
                ],
                "_semua_pelabuhan": [
                    {"nama": x["nama"], "hierarki": x["hierarki"], "lat": x["lat"], "lon": x["lon"], "jarak_km": round(x["jarak_km"], 1)}
                    for x in h["semua_pelabuhan"]
                ],
            }
            at = {k2: v for k2, v in at.items() if v is not None}
            cur.execute(
                "UPDATE map_layers SET attrs = attrs || %s::jsonb "
                "WHERE provinsi=%s AND layer='SUBKLASTER' AND attrs->>'Klaster'=%s AND attrs->>'Subklaster'=%s",
                (Json(at), BUCKET, r["klaster"], r["subklaster"]))
            n_ringkas += cur.rowcount
            # Poligon DETAIL (10.328) TIDAK diberi array berat (rute OSRM + semua titik pulau,
            # ~50 KB/poligon): disalin ke semua poligon detail, attrs layer TANAMAN PANGAN jadi
            # ~91 MB dan membangun GeoJSON-nya membuat PostgreSQL staging kena OOM-kill
            # (4 Okt 2026). Frontend mengambilnya dari poligon induk di layer SUBKLASTER.
            at_detail = {k2: v for k2, v in at.items() if k2 not in KUNCI_BERAT_DETAIL}
            cur.execute(
                "UPDATE map_layers SET attrs = (attrs - %s::text[]) || %s::jsonb "
                "WHERE provinsi=%s AND layer LIKE 'SUBKLASTER DETAIL - %%' "
                "AND attrs->>'Klaster'=%s AND attrs->>'Subklaster'=%s",
                (list(KUNCI_BERAT_DETAIL), Json(at_detail), BUCKET, r["klaster"], r["subklaster"]))
            n_detail += cur.rowcount
        print(f"  atribut ditambahkan: {n_ringkas} poligon SUBKLASTER, {n_detail} poligon SUBKLASTER DETAIL")

        cur.execute(
            "UPDATE map_layer_meta SET imported_at = now() WHERE provinsi=%s AND (layer='SUBKLASTER' OR layer LIKE 'SUBKLASTER DETAIL - %%')",
            (BUCKET,))
    print(f"Selesai dlm {time.time() - t0:.1f}s.")


if __name__ == "__main__":
    main()
