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
tanpa koordinat dibiarkan NULL, bukan error. Pembandingnya ikut mencakup
daftar pelabuhan umum RIPN (tabel pelabuhan_ripn, import_pelabuhan_ripn.py, sejak 11 Okt 2026)
+ register lama layer PELABUHAN PENUMPANG yang tak punya padanan RIPN, lihat
sql_sehirarki_terdekat(). --banding menghitung pembanding lama vs baru TANPA menulis.

Koordinat kosong di sumber diisi dulu dari titik layer peta PELABUHAN RIPN / PELABUHAN /
PELABUHAN PENUMPANG (cocok nama + provinsi, ditandai di kolom
koordinat_sumber) -- import_pelabuhan_daerah.py (DELETE+INSERT) menghapusnya
lagi, jadi selalu jalankan skrip ini setelah reimpor.

Idempotent: hanya mengisi baris yang jarak_sehirarki_terdekat_km-nya masih
NULL, kecuali --force (hitung ulang semua -- perlu setelah reimport
pelabuhan_daerah dgn koordinat baru).

Usage (venv aktif):
    python scripts/spatial_join_pelabuhan_urgensi.py
    python scripts/spatial_join_pelabuhan_urgensi.py --force
    python scripts/spatial_join_pelabuhan_urgensi.py --banding   # dampak pembanding RIPN, tanpa menulis
"""
import argparse
import io
import math
import re
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

# Parameter #3: pembanding "sehirarki terdekat" = pelabuhan_daerah + register pelabuhan
# nasional (layer PELABUHAN PENUMPANG, 546 titik ber-hierarki PU/PP/PR/PL). Sebelum 8 Okt
# 2026 pembandingnya pelabuhan_daerah saja (cuma 17 PP berkoordinat se-Indonesia), sehingga
# Meulaboh (PP) mendapat Pulau Tello 522 km padahal Calang (PP, UPP Kemenhub) hanya ~83 km --
# Calang tidak ada di pelabuhan_daerah. Titik layer yg merupakan pelabuhan itu SENDIRI
# dikecualikan: <= SAMA_TITIK_KM dari pelabuhan, atau nama sama (huruf/angka saja) dalam
# SAMA_NAMA_KM (koordinat xlsx sumber bisa meleset beberapa km dari titik register).
SAMA_TITIK_KM = 2.0  # 1 km masih meloloskan Pulau Balai -> "P. Banyak" (1,0 km, pelabuhan yg sama)
SAMA_NAMA_KM = 30.0
# 11 Okt 2026: daftar RIPN (pelabuhan_ripn, versi resmi Kemenhub 22-09-2026, 634 pelabuhan umum
# berkoordinat) jadi pembanding utama; hierarkinya dipakai bila beda dgn register lama (60 dari
# 499 titik register lama beda hierarki dgn RIPN di lokasi yg sama). Titik register lama tetap
# ikut HANYA bila tak ada pelabuhan RIPN dalam REGISTER_DUPLIKAT_KM (58 titik), supaya cakupan
# tidak berkurang. ripn=False -> pembanding lama (register saja), utk --banding.
REGISTER_DUPLIKAT_KM = 5.0
_PEMBANDING_REGISTER = """
                SELECT NULL::bigint, m.attrs->>'hierarki',
                       (m.attrs->>'nama_pelabuhan') || ' (register Kemenhub)',
                       ST_Y(m.geom)::numeric, ST_X(m.geom)::numeric, m.geom::geography,
                       regexp_replace(lower(m.attrs->>'nama_pelabuhan'), '[^a-z0-9]', '', 'g'), true
                FROM map_layers m
                WHERE m.provinsi = 'PELABUHAN PENUMPANG' AND m.layer = 'PELABUHAN PENUMPANG'
                  AND m.attrs->>'hierarki' IN ('PU', 'PP', 'PR', 'PL')
                  AND GeometryType(m.geom) = 'POINT'"""
_PEMBANDING_RIPN = f"""
                SELECT NULL::bigint, r.hierarki, r.nama_pelabuhan || ' (RIPN)',
                       r.lat::numeric, r.lon::numeric, ST_SetSRID(ST_MakePoint(r.lon, r.lat), 4326)::geography,
                       regexp_replace(lower(r.nama_pelabuhan), '[^a-z0-9]', '', 'g'), true
                FROM pelabuhan_ripn r
                WHERE r.tipe = 'Umum' AND r.hierarki IN ('PU', 'PP', 'PR', 'PL') AND r.lat IS NOT NULL
                UNION ALL
                SELECT * FROM ({_PEMBANDING_REGISTER}) reg(id, hirarki_kode, nama, lat, lon, g, kunci, dari_layer)
                WHERE NOT EXISTS (SELECT 1 FROM pelabuhan_ripn r2
                                  WHERE r2.tipe = 'Umum' AND r2.lat IS NOT NULL
                                    AND ST_DWithin(ST_SetSRID(ST_MakePoint(r2.lon, r2.lat), 4326)::geography,
                                                   reg.g, {REGISTER_DUPLIKAT_KM * 1000}))"""


def sql_sehirarki_terdekat(ripn=True):
    return SQL_SEHIRARKI_TERDEKAT.replace("__PEMBANDING_LAYER__", _PEMBANDING_RIPN if ripn else _PEMBANDING_REGISTER)


SQL_SEHIRARKI_TERDEKAT = f"""
            kandidat AS MATERIALIZED (
                SELECT id, hirarki_kode, nama_pelabuhan, lat, lon,
                       ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography AS g,
                       regexp_replace(lower(nama_pelabuhan), '[^a-z0-9]', '', 'g') AS kunci
                FROM pelabuhan_daerah
                WHERE hirarki_kode IS NOT NULL AND lat IS NOT NULL AND lon IS NOT NULL
            ),
            pembanding AS MATERIALIZED (
                SELECT id, hirarki_kode, nama_pelabuhan, lat, lon, g, kunci, false AS dari_layer
                FROM kandidat
                UNION ALL
                __PEMBANDING_LAYER__
            ),
            terdekat AS (
                SELECT p.id,
                       t.id AS terdekat_id,
                       t.nama_pelabuhan AS terdekat_nama,
                       ST_Distance(p.g, t.g) / 1000.0 AS jarak_km
                FROM kandidat p
                JOIN LATERAL (
                    SELECT k.id, k.nama_pelabuhan, k.g
                    FROM pembanding k
                    WHERE k.hirarki_kode = p.hirarki_kode AND k.id IS DISTINCT FROM p.id
                      -- koordinat identik = duplikat/salin-tempel di sumber, bukan pelabuhan tetangga
                      AND (k.lat, k.lon) IS DISTINCT FROM (p.lat, p.lon)
                      -- titik register yg sebenarnya pelabuhan ini sendiri
                      AND NOT (k.dari_layer AND (
                          ST_DWithin(k.g, p.g, {SAMA_TITIK_KM * 1000})
                          OR ((k.kunci = p.kunci
                               -- nama saling memuat ("Sikabaluan" vs RIPN "Sikabaluan / Pokai", 6,3 km)
                               OR (length(p.kunci) >= 5 AND strpos(k.kunci, p.kunci) > 0)
                               OR (length(k.kunci) >= 5 AND strpos(p.kunci, k.kunci) > 0))
                              AND ST_DWithin(k.g, p.g, {SAMA_NAMA_KM * 1000}))))
                    ORDER BY k.g <-> p.g
                    LIMIT 1
                ) t ON true
            )
"""


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


# --- Koordinat pengganti dari layer peta (27 Sep 2026) -----------------------------------------
# 216 pelabuhan laut tanpa koordinat di xlsx sumber ("Tidak input data") -> jarak, penduduk radius,
# ruas jalan terdekat semuanya kosong. Diisi dari titik layer peta yg NAMA + PROVINSI-nya cocok.
# Konservatif: kandidat ganda dalam satu provinsi hanya dipakai bila titiknya berdekatan (<= 5 km)
# atau kabupatennya bisa membedakan; selebihnya dibiarkan kosong, tidak ditebak.
KOORDINAT_LAYER = [
    # (provinsi map_layers, layer, kolom nama, kolom provinsi, kolom kabupaten, label sumber)
    # daftar RIPN resmi (import_pelabuhan_ripn.py) didahulukan; provinsi/kab = BPS dari titik
    ("PELABUHAN RIPN", "Pelabuhan Umum (RIPN)", "Nama Pelabuhan", "Provinsi", "Kabupaten/Kota",
     "Daftar pelabuhan RIPN Kemenhub (cocok nama)"),
    ("PELABUHAN PENUMPANG", "PELABUHAN PENUMPANG", "nama_pelabuhan", "provinsi", "kabupaten_kota",
     "Layer peta PELABUHAN PENUMPANG (cocok nama)"),
    ("PELABUHAN", "Pelabuhan Nasional", "Name", "Provinsi", "KABUPATEN",
     "Layer peta Pelabuhan Nasional (cocok nama)"),
]
KOORDINAT_SUMBER_ASLI = "Sumber data (Titik Koordinat Lokasi)"
_KATA_UMUM_PELABUHAN = r"\b(PELABUHAN|TERMINAL|DERMAGA|TAMBATAN PERAHU|TAMBATAN|PPI|RORO|LAUT|RAKYAT)\b"
_ALIAS_PROVINSI = {"NTB": "NUSATENGGARABARAT", "NTT": "NUSATENGGARATIMUR", "DKI": "DKIJAKARTA"}


def _norm_nama_pelabuhan(s):
    s = re.sub(_KATA_UMUM_PELABUHAN, " ", (s or "").upper())
    return re.sub(r"[^A-Z0-9]+", "", s)


def _norm_provinsi(s):
    s = (s or "").upper().strip()
    s = re.sub(r"^PROVINSI\s+", "", s)
    s = re.sub(r"^KEP\.\s*", "KEPULAUAN ", s)
    s = re.sub(r"[^A-Z]+", "", s)
    s = _ALIAS_PROVINSI.get(s, s)
    # layer peta sebagian masih memakai provinsi Papua sebelum pemekaran 2022
    return "PAPUA*" if s.startswith("PAPUA") else s


def _norm_kabupaten(s):
    s = (s or "").upper()
    s = re.sub(r"^(KAB\.|KABUPATEN|KOTA)\s+", "", s.strip())
    return re.sub(r"[^A-Z]+", "", s)


def _jarak_km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def _isi_koordinat_dari_layer():
    """Isi lat/lon pelabuhan laut yg kosong dari titik layer peta (cocok nama + provinsi).
    Mengembalikan jumlah baris yg baru diisi."""
    with db_cursor() as cur:
        cur.execute("ALTER TABLE pelabuhan_daerah ADD COLUMN IF NOT EXISTS koordinat_sumber TEXT")
        cur.execute(
            "UPDATE pelabuhan_daerah SET koordinat_sumber = %s WHERE lat IS NOT NULL AND koordinat_sumber IS NULL",
            (KOORDINAT_SUMBER_ASLI,),
        )
        cur.execute(
            "SELECT id, nama_pelabuhan, provinsi, kabupaten_kota FROM pelabuhan_daerah "
            "WHERE hirarki_kode IS NOT NULL AND (lat IS NULL OR lon IS NULL)"
        )
        target = cur.fetchall()
        indeks = {}  # (nama_norm, provinsi_norm) -> [kandidat]
        for prov_ml, layer, k_nama, k_prov, k_kab, label in KOORDINAT_LAYER:
            cur.execute(
                f"SELECT attrs->>'{k_nama}' AS nama, attrs->>'{k_prov}' AS prov, attrs->>'{k_kab}' AS kab, "
                "ST_Y(geom) AS lat, ST_X(geom) AS lon FROM map_layers "
                "WHERE provinsi = %s AND layer = %s AND GeometryType(geom) = 'POINT'",
                (prov_ml, layer),
            )
            for t in cur.fetchall():
                # satu titik bisa punya dua nama ("Bintuhan/ Linau") -> daftarkan tiap bagian
                for bagian in re.split(r"[/,]", t["nama"] or ""):
                    kunci = _norm_nama_pelabuhan(bagian)
                    if len(kunci) < 4:
                        continue
                    indeks.setdefault((kunci, _norm_provinsi(t["prov"])), []).append({**t, "sumber": label})

    isi, ambigu, tak_cocok = [], [], 0
    for p in target:
        kand = indeks.get((_norm_nama_pelabuhan(p["nama_pelabuhan"]), _norm_provinsi(p["provinsi"])))
        if not kand:
            tak_cocok += 1
            continue
        kab = _norm_kabupaten(p["kabupaten_kota"])
        if len(kand) > 1 and kab and not kab.startswith("PROVINSI"):
            sekab = [k for k in kand if _norm_kabupaten(k["kab"]) == kab]
            if sekab:
                kand = sekab
        titik0 = (kand[0]["lat"], kand[0]["lon"])
        if any(_jarak_km(titik0, (k["lat"], k["lon"])) > 5.0 for k in kand[1:]):
            ambigu.append(p["nama_pelabuhan"])
            continue
        isi.append((kand[0]["lat"], kand[0]["lon"], kand[0]["sumber"], p["id"]))

    if isi:
        with db_cursor() as cur:
            cur.executemany(
                "UPDATE pelabuhan_daerah SET lat = %s, lon = %s, koordinat_sumber = %s WHERE id = %s", isi
            )
    print(f"  koordinat dari layer peta: {len(isi)} diisi, {len(ambigu)} ambigu (dilewati), "
          f"{tak_cocok} tanpa padanan nama+provinsi")
    if ambigu:
        print(f"    ambigu: {', '.join(ambigu)}")
    return len(isi)


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


# --- Ruas jalan terdekat (semua jaringan) -- menggantikan tampilan "Ruas IJD Terdekat" ------------
# Permintaan 24 Sep 2026: yang ditampilkan di preview/export Skor Urgensitas Pelabuhan adalah ruas
# jalan terdekat (BUKAN hanya ruas usulan IJD) + klasifikasi jalan + nama jalan. Skor Akses tetap
# memakai kondisi/lebar ruas usulan IJD (ruas_ijd_*), karena kondisi jalan hanya ada di sana.
#
# Jaringan (layer map_layers): Jalan Nasional (LINK_NAME/ROAD_FUNCT/ROAD_CLASS), Jalan Provinsi
# (RUAS/FUNGSI), Jalan Tol, dan seluruh layer jalan kab/kota per-kabupaten (202 layer; skema atribut
# SANGAT beragam antar layer -- nama ruas tersebar di 20-an nama kolom, jadi dipilih lewat daftar
# kolom cadangan; bila tak ada nama, kolom nama dibiarkan NULL). Cakupan jalan kab/kota parsial
# (202 dari 514 kab/kota) dan kualitas atribut tidak seragam -- best-effort, bukan data resmi lengkap.
JALAN_RADIUS_DERAJAT = 0.5  # ~55 km; di luar itu tidak ada ruas jalan yang dilaporkan

_NAMA_KAB = ["Nm_Ruas", "Nama_Ruas", "NAMA_RUAS", "NM_RUAS", "Nm_Ruas_1", "Nama_Ruas_", "nama_ruas",
             "NAMA_JALAN", "Nama_Jalan", "Ruas", "NAME", "Name", "NAMA", "NAMA_UNSUR"]
_STATUS_KAB = ["Status", "STATUS", "STATUS_JAL", "STATUS0", "Klasifikas", "klas_jal_1"]
_FUNGSI_KAB = ["Fungsi", "FUNGSI", "FUNGSI_JAL", "Fungsi_Jal", "JLN_FUNGSI", "FUNGSI2016", "FGSRJL", "Kelas"]
_KODE_KAB = ["No_Ruas", "NO_RUAS", "Kode_Ruas", "Nomor_Ruas", "no_ruas"]


def _pilih(keys, extra_null=("", "-", "0", "0.0")):
    """SQL: nilai atribut pertama yang terisi dari daftar kolom (nilai kosong/'-'/'0' dianggap kosong)."""
    nulls = ", ".join(f"'{n}'" for n in extra_null)
    parts = [f"CASE WHEN trim(attrs->>'{k}') IN ({nulls}) THEN NULL ELSE trim(attrs->>'{k}') END" for k in keys]
    return "COALESCE(" + ", ".join(parts) + ")"


def _isi_jalan_terdekat(force: bool):
    where_force = "" if force else "AND p.jalan_terdekat_jaringan IS NULL"
    fungsi_nas = ("CASE attrs->>'ROAD_FUNCT' WHEN 'A' THEN 'Arteri' WHEN 'K1' THEN 'Kolektor 1' "
                  "WHEN 'K2' THEN 'Kolektor 2' WHEN 'K3' THEN 'Kolektor 3' ELSE attrs->>'ROAD_FUNCT' END")
    status_raw = _pilih(_STATUS_KAB)
    # sebagian layer menulis status dgn kode huruf (K/P/N); kode lain (D, JP, JSK, ...) maknanya belum
    # terdokumentasi -> tidak ditebak, ditampilkan apa adanya sebagai "kode status sumber".
    status_kab = (f"CASE WHEN {status_raw} IS NULL THEN NULL WHEN upper({status_raw}) = 'K' THEN 'Kabupaten' "
                  f"WHEN upper({status_raw}) = 'P' THEN 'Provinsi' WHEN upper({status_raw}) = 'N' THEN 'Nasional' "
                  f"WHEN length({status_raw}) <= 3 THEN NULL ELSE {status_raw} END")
    fungsi_kab = _pilih(_FUNGSI_KAB)
    t0 = time.time()
    with db_cursor() as cur:
        for kol, tipe in (("jalan_terdekat_kode", "TEXT"), ("jalan_terdekat_nama", "TEXT"),
                          ("jalan_terdekat_jaringan", "TEXT"), ("jalan_terdekat_klasifikasi", "TEXT"),
                          ("jalan_terdekat_jarak_km", "NUMERIC(10,3)")):
            cur.execute(f"ALTER TABLE pelabuhan_daerah ADD COLUMN IF NOT EXISTS {kol} {tipe}")
        cur.execute(
            f"""
            CREATE TEMP TABLE tmp_jalan AS
            SELECT 'Nasional' AS jaringan, attrs->>'LINKID' AS kode, NULLIF(trim(attrs->>'LINK_NAME'), '') AS nama,
                   'Jalan Nasional' || COALESCE(' · ' || NULLIF({fungsi_nas}, ''), '')
                     || COALESCE(' · Kelas ' || NULLIF(attrs->>'ROAD_CLASS', ''), '') AS klasifikasi, geom
            FROM map_layers WHERE provinsi = 'JALAN NASIONAL' AND layer = 'Jalan Nasional'
            UNION ALL
            SELECT 'Provinsi', COALESCE(NULLIF(trim(attrs->>'NOMOR'), ''), attrs->>'KEYIRMS'),
                   NULLIF(trim(attrs->>'RUAS'), ''),
                   'Jalan Provinsi' || COALESCE(' · ' || NULLIF(trim(attrs->>'FUNGSI'), ''), ''), geom
            FROM map_layers WHERE provinsi = 'JALAN PROVINSI'
            UNION ALL
            SELECT 'Tol', attrs->>'NRUAS', COALESCE(NULLIF(trim(attrs->>'NAMA_JALAN'), ''), NULLIF(trim(attrs->>'RRUAS_NAMA'), '')),
                   'Jalan Tol', geom
            FROM map_layers WHERE provinsi = 'JALAN TOL'
            UNION ALL
            SELECT 'Kabupaten/Kota', {_pilih(_KODE_KAB)}, {_pilih(_NAMA_KAB)},
                   CASE WHEN {status_kab} IS NULL THEN 'Jalan Kabupaten/Kota'
                          || COALESCE(' (kode status sumber: ' || {status_raw} || ')', '')
                        WHEN lower({status_kab}) LIKE 'jalan%%' THEN {status_kab}
                        ELSE 'Jalan ' || {status_kab} END
                     || COALESCE(' · ' || {fungsi_kab}, ''), geom
            FROM map_layers WHERE layer ILIKE 'JALAN%%' AND provinsi NOT LIKE 'JALAN%%'
            """
        )
        cur.execute("CREATE INDEX ON tmp_jalan USING GIST (geom)")
        cur.execute("ANALYZE tmp_jalan")
        cur.execute("SELECT jaringan, count(*) AS n FROM tmp_jalan GROUP BY 1 ORDER BY 1")
        print("  tabel temp jalan siap dlm %.1fs: %s" % (time.time() - t0, {r["jaringan"]: r["n"] for r in cur.fetchall()}))
        t1 = time.time()
        cur.execute(
            f"""
            WITH target AS MATERIALIZED (
                SELECT id, ST_SetSRID(ST_MakePoint(lon, lat), 4326) AS g
                FROM pelabuhan_daerah p WHERE lat IS NOT NULL AND lon IS NOT NULL {where_force}
            ),
            terdekat AS (
                SELECT t.id AS pelabuhan_id, r.*
                FROM target t
                JOIN LATERAL (
                    SELECT j.jaringan, j.kode, j.nama, j.klasifikasi,
                           ST_Distance(j.geom::geography, t.g::geography) / 1000.0 AS jarak_km
                    FROM tmp_jalan j
                    WHERE ST_DWithin(j.geom, t.g, %(radius)s)
                    ORDER BY j.geom <-> t.g LIMIT 1
                ) r ON true
            )
            UPDATE pelabuhan_daerah p
            SET jalan_terdekat_jaringan = td.jaringan, jalan_terdekat_kode = td.kode,
                jalan_terdekat_nama = regexp_replace(td.nama, '\s+', ' ', 'g'),
                jalan_terdekat_klasifikasi = regexp_replace(td.klasifikasi, '\s+', ' ', 'g'),
                jalan_terdekat_jarak_km = round(td.jarak_km::numeric, 3)
            FROM terdekat td WHERE p.id = td.pelabuhan_id
            """,
            {"radius": JALAN_RADIUS_DERAJAT},
        )
        print(f"  jalan terdekat: {cur.rowcount} pelabuhan di-update ({time.time() - t1:.1f}s)")
        cur.execute(
            "SELECT jalan_terdekat_jaringan AS j, count(*) AS n, count(jalan_terdekat_nama) AS bernama "
            "FROM pelabuhan_daerah WHERE lat IS NOT NULL GROUP BY 1 ORDER BY 2 DESC"
        )
        for r in cur.fetchall():
            print(f"    {r['j'] or '(tidak ada jalan dalam radius)'}: {r['n']} pelabuhan, {r['bernama']} dengan nama jalan")


def _tandai_koordinat_kembar():
    """Isi koordinat_kembar_dengan = nama pelabuhan lain (semua hirarki) yg lat/lon-nya identik
    persis. Dihitung ulang penuh tiap run (murah, ~1000 baris) supaya koreksi di sumber ikut
    terhapus. Per 28 Sep 2026: 31 baris (semua hirarki), 10 di antaranya sebelumnya ber-jarak
    sehirarki terdekat 0 km, mis. Cera (Provinsi Maluku Utara) & Cera (Kab. Halmahera Utara) --
    baris dobel; Dermaga Peres & Pulopanjang-Puloampel -- koordinat salin-tempel."""
    with db_cursor() as cur:
        cur.execute(
            """
            UPDATE pelabuhan_daerah p
            SET koordinat_kembar_dengan = k.nama
            FROM (
                SELECT a.id, string_agg(b.nama_pelabuhan || ' (' || COALESCE(b.kabupaten_kota, '-') || ')',
                                        '; ' ORDER BY b.nama_pelabuhan) AS nama
                FROM pelabuhan_daerah a
                LEFT JOIN pelabuhan_daerah b ON b.id <> a.id AND b.lat = a.lat AND b.lon = a.lon
                GROUP BY a.id
            ) k
            WHERE p.id = k.id AND p.koordinat_kembar_dengan IS DISTINCT FROM k.nama
            """
        )
        cur.execute("SELECT count(*) AS n FROM pelabuhan_daerah WHERE koordinat_kembar_dengan IS NOT NULL")
        n = cur.fetchone()["n"]
    print(f"  {n} pelabuhan berkoordinat identik dgn pelabuhan lain (dikecualikan dari 'terdekat' satu sama lain)")
    return n


def _banding_pembanding():
    """Pelabuhan sehirarki terdekat dgn pembanding lama vs RIPN, koordinat SAAT INI, tanpa menulis."""
    hasil = {}
    with db_cursor() as cur:
        for label, ripn in (("lama", False), ("ripn", True)):
            cur.execute(f"WITH {sql_sehirarki_terdekat(ripn)} SELECT id, terdekat_nama, jarak_km FROM terdekat")
            hasil[label] = {r["id"]: r for r in cur.fetchall()}
        cur.execute("SELECT id, nama_pelabuhan, hirarki_kode FROM pelabuhan_daerah WHERE hirarki_kode IS NOT NULL")
        info = {r["id"]: r for r in cur.fetchall()}
    berubah = []
    for i, b in hasil["ripn"].items():
        a = hasil["lama"].get(i)
        if a is None or a["terdekat_nama"] != b["terdekat_nama"] or abs(a["jarak_km"] - b["jarak_km"]) > 0.05:
            berubah.append((info[i]["hirarki_kode"], info[i]["nama_pelabuhan"], a and a["terdekat_nama"],
                            a and round(a["jarak_km"], 1), b["terdekat_nama"], round(b["jarak_km"], 1)))
    print(f"Pelabuhan berkoordinat dgn pembanding: lama {len(hasil['lama'])}, RIPN {len(hasil['ripn'])}; "
          f"terdekat berubah {len(berubah)}")
    for hk in ("PP", "PR", "PL"):
        n = [x for x in berubah if x[0] == hk]
        lebih_dekat = sum(1 for x in n if x[3] is not None and x[5] < x[3])
        print(f"  {hk}: {len(n)} berubah ({lebih_dekat} jadi lebih dekat)")
    for x in sorted(berubah, key=lambda x: -(abs((x[3] or 0) - x[5])))[:15]:
        print(f"    {x[0]} {x[1]}: {x[2]} {x[3]} km -> {x[4]} {x[5]} km")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="hitung ulang termasuk yang sudah terisi")
    ap.add_argument("--hanya-jalan", action="store_true",
                    help="hanya hitung ruas jalan terdekat (semua jaringan), tanpa langkah lain")
    ap.add_argument("--banding", action="store_true",
                    help="bandingkan pelabuhan sehirarki terdekat: pembanding lama (register) vs RIPN, tanpa menulis")
    args = ap.parse_args()

    with db_cursor() as cur:
        cur.execute("SELECT to_regclass('pelabuhan_ripn') IS NOT NULL AS ada")
        ada_ripn = cur.fetchone()["ada"]
    if not ada_ripn:
        print("PERINGATAN: tabel pelabuhan_ripn belum ada -> pembanding register lama saja "
              "(jalankan import_pelabuhan_ripn.py)")

    if args.banding:
        _banding_pembanding()
        return

    if args.hanya_jalan:
        print("Mencari ruas jalan terdekat (semua jaringan)...")
        _isi_jalan_terdekat(args.force)
        return

    _run_schema()
    _isi_hirarki_kode()

    print("Mengisi koordinat kosong dari layer peta (cocok nama + provinsi)...")
    n_koordinat_baru = _isi_koordinat_dari_layer()

    print("Menandai pelabuhan dengan koordinat identik (duplikat / salin-tempel di sumber)...")
    n_kembar = _tandai_koordinat_kembar()

    # Titik baru bisa menjadi "sehirarki terdekat" bagi pelabuhan LAIN -> jarak dihitung ulang semua.
    # Baris ber-koordinat kembar selalu dihitung ulang: hasil lama (sebelum pengecualian kembar) = 0 km.
    where_force = ("" if (args.force or n_koordinat_baru)
                   else "AND (p.jarak_sehirarki_terdekat_km IS NULL OR p.koordinat_kembar_dengan IS NOT NULL)")
    t0 = time.time()
    with db_cursor() as cur:
        # Hasil lama baris kembar (0 km ke kembarannya) dikosongkan dulu: kalau tak ada pelabuhan
        # sehirarki lain yg berbeda lokasi, JOIN LATERAL di bawah tidak menghasilkan baris dan
        # nilai lama akan tertinggal -> NULL = "tidak ada pembanding" (ditangani scorer).
        cur.execute(
            "UPDATE pelabuhan_daerah SET pelabuhan_sehirarki_terdekat_id = NULL, "
            "pelabuhan_sehirarki_terdekat_nama = NULL, jarak_sehirarki_terdekat_km = NULL "
            "WHERE koordinat_kembar_dengan IS NOT NULL"
        )
        cur.execute(
            f"""
            WITH {sql_sehirarki_terdekat(ada_ripn)}
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

    print("\nMencari ruas jalan terdekat, semua jaringan (tampilan; skor Akses tetap memakai ruas IJD)...")
    _isi_jalan_terdekat(args.force)

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
