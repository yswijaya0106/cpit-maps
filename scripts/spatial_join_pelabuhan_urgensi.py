# -*- coding: utf-8 -*-
"""Precompute parameter #3 "Kedekatan dengan Pelabuhan Lain" (skor
Urgensitas Penanganan Pelabuhan) -> isi pelabuhan_daerah.hirarki_kode +
jarak_sehirarki_terdekat_km sekali, disimpan -- pola sama dgn
spatial_join_koridor_radius.py (fakta spasial dihitung sekali via script
terpisah, scorer nanti tinggal baca kolom).

Lihat docs/kajian_implementasi_skor_urgensi_pelabuhan_laut.md dan
docs/checklist_implementasi_skor_urgensi_pelabuhan.md §Fase 1 tahap 1a.

hirarki_kode diturunkan dari hirarki_pelabuhan (teks bebas, mis. "Laut -
Pelabuhan Pengumpan Lokal (PL)") lewat kode 2 huruf di akhir string.
HANYA baris dgn hirarki_pelabuhan berawalan "Laut -" yang diberi
hirarki_kode -- kategori lain (Sungai/Danau, Penyeberangan, Tidak ada) di
luar cakupan kerangka ini, dibiarkan NULL. Per data saat ini cuma ada
PP/PR/PL (tidak ada PU, lihat checklist).

"Sehirarki terdekat" dihitung PER GRUP hirarki_kode (PP dibanding PP lain
saja, dst) via geography::ST_Distance, HANYA di antara baris yang punya
lat/lon (~66% dari total, lihat checklist "Temuan tambahan") -- baris
tanpa koordinat dibiarkan NULL, bukan error.

Idempotent: hanya mengisi baris yang jarak_sehirarki_terdekat_km-nya masih
NULL, kecuali --force (hitung ulang semua -- perlu setelah reimport
pelabuhan_daerah dgn koordinat baru).

Usage (venv aktif):
    python scripts/spatial_join_pelabuhan_urgensi.py
    python scripts/spatial_join_pelabuhan_urgensi.py --force
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

SCHEMA_FILE = Path(__file__).resolve().parent / "schema_pelabuhan_urgensi.sql"

# Radius & unit wilayah per hirarki utk parameter #6 Jumlah Penduduk
# (slide 5 pptx sumber) -- PP pakai kab/kota, PR/PL pakai kecamatan.
# PU (370km, 1 provinsi + kab/kota) TIDAK ada di data pelabuhan_daerah
# (lihat checklist "Temuan tambahan"), jadi tidak diimplementasi di sini.
PENDUDUK_RADIUS_KM = {"PP": 93, "PR": 60, "PL": 40}
PENDUDUK_UNIT = {"PP": "kabupaten", "PR": "kecamatan", "PL": "kecamatan"}
TAHUN_PENDUDUK = 2025  # satu-satunya tahun yg ada di penduduk_kecamatan saat ini


def _run_schema():
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    with db_cursor() as cur:
        cur.execute(sql)


def _isi_hirarki_kode():
    """hirarki_kode = 2 huruf terakhir dalam kurung, hanya utk baris
    'Laut - ...'. Selalu dihitung ulang (murah, murni turunan teks -- beda
    dari jarak yg mahal dan idempotent by design)."""
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE pelabuhan_daerah
            SET hirarki_kode = substring(hirarki_pelabuhan FROM '\\(([A-Z]{2})\\)$')
            WHERE hirarki_pelabuhan LIKE 'Laut -%'
            """
        )
        cur.execute(
            "UPDATE pelabuhan_daerah SET hirarki_kode = NULL WHERE hirarki_pelabuhan NOT LIKE 'Laut -%'"
        )


def _isi_penduduk_radius(force: bool):
    where_force = "" if force else "AND p.penduduk_radius_total IS NULL"
    t0 = time.time()
    for kode, radius_km in PENDUDUK_RADIUS_KM.items():
        radius_derajat = radius_km / 111.0
        unit = PENDUDUK_UNIT[kode]
        if unit == "kabupaten":
            sql = f"""
                WITH kab_penduduk AS (
                    SELECT kode_kabupaten, SUM(jumlah_penduduk) AS penduduk
                    FROM penduduk_kecamatan WHERE tahun = %(tahun)s GROUP BY kode_kabupaten
                ),
                target AS (
                    SELECT id, ST_SetSRID(ST_MakePoint(lon, lat), 4326) AS g
                    FROM pelabuhan_daerah p
                    WHERE hirarki_kode = %(kode)s AND lat IS NOT NULL AND lon IS NOT NULL {where_force}
                ),
                matched AS (
                    SELECT DISTINCT t.id AS pelabuhan_id,
                           (ml.attrs->>'KODE_KABUPATEN')::int AS kode_wilayah,
                           ml.attrs->>'KABUPATEN_KOTA' AS nama_wilayah
                    FROM target t
                    JOIN map_layers ml ON ml.provinsi = 'BATAS KABUPATEN' AND ST_DWithin(ml.geom, t.g, %(radius)s)
                ),
                agg AS (
                    SELECT m.pelabuhan_id,
                           SUM(COALESCE(kp.penduduk, 0)) AS total,
                           jsonb_agg(jsonb_build_object('kode', m.kode_wilayah, 'nama', m.nama_wilayah,
                                                         'penduduk', COALESCE(kp.penduduk, 0)) ORDER BY m.nama_wilayah) AS detail
                    FROM matched m
                    LEFT JOIN kab_penduduk kp ON kp.kode_kabupaten = m.kode_wilayah
                    GROUP BY m.pelabuhan_id
                )
                UPDATE pelabuhan_daerah p
                SET penduduk_radius_total = agg.total, penduduk_radius_wilayah_json = agg.detail
                FROM agg WHERE p.id = agg.pelabuhan_id
            """
        else:
            sql = f"""
                WITH target AS (
                    SELECT id, ST_SetSRID(ST_MakePoint(lon, lat), 4326) AS g
                    FROM pelabuhan_daerah p
                    WHERE hirarki_kode = %(kode)s AND lat IS NOT NULL AND lon IS NOT NULL {where_force}
                ),
                matched AS (
                    SELECT DISTINCT t.id AS pelabuhan_id,
                           (ml.attrs->>'KODE_KECAMATAN')::bigint AS kode_wilayah,
                           ml.attrs->>'KECAMATAN' AS nama_wilayah
                    FROM target t
                    JOIN map_layers ml ON ml.provinsi = 'BATAS KECAMATAN' AND ST_DWithin(ml.geom, t.g, %(radius)s)
                    WHERE ml.attrs->>'KODE_KECAMATAN' IS NOT NULL
                ),
                agg AS (
                    SELECT m.pelabuhan_id,
                           SUM(COALESCE(pk.jumlah_penduduk, 0)) AS total,
                           jsonb_agg(jsonb_build_object('kode', m.kode_wilayah, 'nama', m.nama_wilayah,
                                                         'penduduk', COALESCE(pk.jumlah_penduduk, 0)) ORDER BY m.nama_wilayah) AS detail
                    FROM matched m
                    LEFT JOIN penduduk_kecamatan pk ON pk.kode_kecamatan = m.kode_wilayah AND pk.tahun = %(tahun)s
                    GROUP BY m.pelabuhan_id
                )
                UPDATE pelabuhan_daerah p
                SET penduduk_radius_total = agg.total, penduduk_radius_wilayah_json = agg.detail
                FROM agg WHERE p.id = agg.pelabuhan_id
            """
        with db_cursor() as cur:
            cur.execute(sql, {"kode": kode, "radius": radius_derajat, "tahun": TAHUN_PENDUDUK})
            n = cur.rowcount
        print(f"  penduduk radius {kode} ({radius_km}km, unit {unit}): {n} baris di-update ({time.time() - t0:.1f}s)")


NORMALISASI_KABUPATEN_SQL = (
    "upper(trim(regexp_replace({col}, '^(Kab\\.|Kota|Provinsi)\\s+', '', 'i')))"
)


def _isi_klasifikasi_3tp(force: bool):
    """Parameter #4 versi kategorikal -- pencocokan NAMA kabupaten (bukan
    spasial), lihat catatan asumsi di schema_pelabuhan_urgensi.sql."""
    where_force = "" if force else "AND klasifikasi_3tp_kategori IS NULL"
    norm_p = NORMALISASI_KABUPATEN_SQL.format(col="p.kabupaten_kota")
    norm_l = NORMALISASI_KABUPATEN_SQL.format(col="l.kabupaten_lengkap")
    sql = f"""
        WITH program AS (
            SELECT {norm_l} AS nrm_kab,
                   jsonb_agg(DISTINCT status) AS statuses,
                   bool_or(status ILIKE '%Perbatasan%') AS ada_perbatasan,
                   bool_or(status ILIKE '%Tertinggal%') AS ada_tertinggal
            FROM list_lokpri_kawasan l
            WHERE kategori = '3TP'
            GROUP BY 1
        ),
        klas AS (
            SELECT p.id,
                   CASE
                       WHEN pr.ada_perbatasan AND pr.ada_tertinggal THEN 'Wilayah 3TP'
                       WHEN pr.ada_perbatasan THEN 'Wilayah Perbatasan'
                       WHEN pr.ada_tertinggal THEN 'Wilayah 3T'
                       ELSE 'Bukan 3TP'
                   END AS kategori,
                   pr.statuses
            FROM pelabuhan_daerah p
            LEFT JOIN program pr ON {norm_p} = pr.nrm_kab
            WHERE p.kabupaten_kota IS NOT NULL {where_force}
        )
        UPDATE pelabuhan_daerah p
        SET klasifikasi_3tp_kategori = k.kategori,
            klasifikasi_3tp_program_json = k.statuses
        FROM klas k WHERE p.id = k.id
    """
    with db_cursor() as cur:
        cur.execute(sql)
        n = cur.rowcount
    with db_cursor() as cur:
        cur.execute(
            "SELECT klasifikasi_3tp_kategori, count(*) n FROM pelabuhan_daerah "
            "WHERE klasifikasi_3tp_kategori IS NOT NULL GROUP BY 1 ORDER BY 1"
        )
        ringkasan = cur.fetchall()
    print(f"  klasifikasi 3TP: {n} baris di-update pada run ini.")
    for r in ringkasan:
        print(f"    {r['klasifikasi_3tp_kategori']}: {r['n']}")


NORMALISASI_PROVINSI_SQL = "upper(trim(regexp_replace({col}, '^Provinsi\\s+', '', 'i')))"


RUAS_SIMPLIFY_TOLERANSI_DERAJAT = 0.002  # ~220m, cukup utk cek "dalam radius 40-93km"


def _isi_ruas_ijd_terdekat(force: bool):
    """Parameter #7 versi cakupan-terbatas -- ruas usulan_inpres terdekat
    dalam radius yg sama dgn PENDUDUK_RADIUS_KM (1b), lihat catatan
    cakupan di schema_pelabuhan_urgensi.sql.

    PERFORMA -- geometri usulan_inpres SANGAT padat titik (rata-rata
    ~2.364 vertex/ruas, total >7 juta titik nasional, jauh lebih padat dari
    ruas biasa krn KML mentah hasil GPS-logging) -- ST_Distance/ST_DWithin
    langsung thd geometri mentah (via ST_GeomFromGeoJSON on-the-fly) tanpa
    index spasial TIDAK LAYAK (>5 menit utk 1 grup hirarki saja, diukur
    saat uji coba, dihentikan paksa). Perbaikan (2 lapis, dites eksplisit,
    bukan tebakan):
      1. ST_Simplify tiap ruas SEKALI ke tabel TEMP + index GiST (bukan
         di-cast ulang tiap query) -- turun dari >7 juta jadi ~320rb
         vertex nasional, build ~35s (didominasi parse JSON, bukan
         simplify-nya sendiri).
      2. Prasaring provinsi (dinormalisasi) sebelum ST_DWithin -- turun
         kandidat/pelabuhan dari ~3.000 jadi puluhan. Kombinasi keduanya:
         <0.1s per grup hirarki (diukur), dari semula timeout.
      Tabel TEMP di-scope ke SATU koneksi (SATU `with db_cursor()` di
      SELURUH fungsi ini, bukan per grup hirarki spt fungsi lain di file
      ini) krn TEMP TABLE hilang saat koneksi ditutup -- db_cursor() buka
      koneksi baru tiap dipanggil (lihat db.py).

    ASUMSI/keterbatasan (didokumentasikan, bukan disembunyikan):
    prasaring provinsi bisa melewatkan ruas yg sebenarnya lebih dekat tapi
    ada di provinsi tetangga (pelabuhan dekat batas provinsi); toleransi
    simplify ~220m bisa geser jarak hasil sedikit (dapat diterima utk
    skala radius puluhan km disini)."""
    where_force = "" if force else "AND p.ruas_ijd_terdekat_id IS NULL"
    norm_p = NORMALISASI_PROVINSI_SQL.format(col="provinsi")
    norm_r = NORMALISASI_PROVINSI_SQL.format(col="provinsi")
    t0 = time.time()
    with db_cursor() as cur:
        cur.execute(
            f"""
            CREATE TEMP TABLE tmp_ruas_ijd AS
            SELECT id, nama_ruas, {norm_r} AS provinsi_norm, kondisi_baik_km, kondisi_sedang_km,
                   kondisi_ringan_km, kondisi_berat_km, lebar_jalan_m,
                   ST_Simplify(ST_SetSRID(ST_GeomFromGeoJSON(geom_geojson), 4326), %(tol)s) AS g
            FROM usulan_inpres
            WHERE geom_geojson IS NOT NULL
            """,
            {"tol": RUAS_SIMPLIFY_TOLERANSI_DERAJAT},
        )
        cur.execute("CREATE INDEX ON tmp_ruas_ijd USING GIST (g)")
        cur.execute("ANALYZE tmp_ruas_ijd")
        print(f"  tabel temp ruas IJD (simplified+index) siap dlm {time.time() - t0:.1f}s")

        for kode, radius_km in PENDUDUK_RADIUS_KM.items():
            radius_deg = radius_km / 111.0
            t1 = time.time()
            cur.execute(
                f"""
                WITH target AS MATERIALIZED (
                    SELECT id, {norm_p} AS provinsi_norm, ST_SetSRID(ST_MakePoint(lon, lat), 4326) AS g
                    FROM pelabuhan_daerah p
                    WHERE hirarki_kode = %(kode)s AND lat IS NOT NULL AND lon IS NOT NULL {where_force}
                ),
                terdekat AS (
                    SELECT t.id AS pelabuhan_id, r.*, r.d * 111.0 AS jarak_km
                    FROM target t
                    JOIN LATERAL (
                        SELECT ru.*, ST_Distance(t.g, ru.g) AS d
                        FROM tmp_ruas_ijd ru
                        WHERE ru.provinsi_norm = t.provinsi_norm AND ST_DWithin(t.g, ru.g, %(radius_deg)s)
                        ORDER BY d LIMIT 1
                    ) r ON true
                )
                UPDATE pelabuhan_daerah p
                SET ruas_ijd_terdekat_id = td.id, ruas_ijd_terdekat_nama = td.nama_ruas,
                    ruas_ijd_terdekat_jarak_km = round(td.jarak_km::numeric, 3),
                    ruas_ijd_kondisi_baik_km = td.kondisi_baik_km, ruas_ijd_kondisi_sedang_km = td.kondisi_sedang_km,
                    ruas_ijd_kondisi_ringan_km = td.kondisi_ringan_km, ruas_ijd_kondisi_berat_km = td.kondisi_berat_km,
                    ruas_ijd_lebar_jalan_m = td.lebar_jalan_m
                FROM terdekat td WHERE p.id = td.pelabuhan_id
                """,
                {"kode": kode, "radius_deg": radius_deg},
            )
            n = cur.rowcount
            print(f"  ruas IJD terdekat {kode} ({radius_km}km): {n} baris di-update ({time.time() - t1:.2f}s)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="hitung ulang termasuk yang sudah terisi")
    args = ap.parse_args()

    _run_schema()
    _isi_hirarki_kode()

    where_force = "" if args.force else "AND p.jarak_sehirarki_terdekat_km IS NULL"
    t0 = time.time()
    with db_cursor() as cur:
        cur.execute(
            f"""
            WITH kandidat AS MATERIALIZED (
                SELECT id, hirarki_kode, nama_pelabuhan,
                       ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography AS g
                FROM pelabuhan_daerah
                WHERE hirarki_kode IS NOT NULL AND lat IS NOT NULL AND lon IS NOT NULL
            ),
            terdekat AS (
                SELECT p.id,
                       t.id AS terdekat_id,
                       t.nama_pelabuhan AS terdekat_nama,
                       ST_Distance(p.g, t.g) / 1000.0 AS jarak_km
                FROM kandidat p
                JOIN LATERAL (
                    SELECT k.id, k.nama_pelabuhan, k.g
                    FROM kandidat k
                    WHERE k.hirarki_kode = p.hirarki_kode AND k.id <> p.id
                    ORDER BY k.g <-> p.g
                    LIMIT 1
                ) t ON true
            )
            UPDATE pelabuhan_daerah p
            SET pelabuhan_sehirarki_terdekat_id = t.terdekat_id,
                pelabuhan_sehirarki_terdekat_nama = t.terdekat_nama,
                jarak_sehirarki_terdekat_km = round(t.jarak_km::numeric, 3)
            FROM terdekat t
            WHERE p.id = t.id {where_force}
            """
        )
        n_updated = cur.rowcount

    with db_cursor() as cur:
        cur.execute(
            "SELECT hirarki_kode, count(*) n, count(*) FILTER (WHERE jarak_sehirarki_terdekat_km IS NOT NULL) terisi "
            "FROM pelabuhan_daerah WHERE hirarki_kode IS NOT NULL GROUP BY 1 ORDER BY 1"
        )
        ringkasan = cur.fetchall()

    print(f"Selesai jarak_sehirarki_terdekat dlm {time.time() - t0:.1f}s: {n_updated} baris di-update pada run ini.")
    print("Ringkasan per hirarki (total vs terisi jarak_sehirarki_terdekat_km):")
    for r in ringkasan:
        print(f"  {r['hirarki_kode']}: {r['terisi']}/{r['n']}")

    print("\nMenghitung penduduk dalam radius per hirarki (parameter #6)...")
    _isi_penduduk_radius(args.force)

    print("\nMengklasifikasi wilayah 3TP kategorikal (parameter #4)...")
    _isi_klasifikasi_3tp(args.force)

    print("\nMencari ruas usulan IJD terdekat per hirarki (parameter #7)...")
    _isi_ruas_ijd_terdekat(args.force)

    with db_cursor() as cur:
        cur.execute(
            "SELECT hirarki_kode, count(*) n, count(*) FILTER (WHERE penduduk_radius_total IS NOT NULL) terisi "
            "FROM pelabuhan_daerah WHERE hirarki_kode IS NOT NULL GROUP BY 1 ORDER BY 1"
        )
        ringkasan2 = cur.fetchall()
    print("Ringkasan per hirarki (total vs terisi penduduk_radius_total):")
    for r in ringkasan2:
        print(f"  {r['hirarki_kode']}: {r['terisi']}/{r['n']}")


if __name__ == "__main__":
    main()
