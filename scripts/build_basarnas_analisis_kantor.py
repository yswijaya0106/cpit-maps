# -*- coding: utf-8 -*-
"""Bangun/refresh basarnas_analisis_kantor -- agregasi per Kantor/Pos SAR
menjawab tepat 13 kolom docs/Requierment/Analisis Basarnas (1).xlsx sheet
"Lembar1" (template kosong dari user), dicek satu-satu dari data BASARNAS
yang sudah ada di database (map_layers bucket "BASARNAS" + basarnas_ops_sar +
basarnas_rescuer_potensi -- lihat scripts/import_basarnas_to_postgis.py,
import_basarnas_ops_sar.py, import_basarnas_rescuer_potensi.py). Kolom yang
memang tidak ada sumber datanya (Termasuk Wilayah Rawan Bencana, dan seluruh
kolom operasional utk baris Pos SAR) dibiarkan NULL apa adanya -- lihat
penjelasan lengkap tiap kolom di schema_basarnas_analisis_kantor.sql.

Pencocokan Kantor SAR <-> basarnas_ops_sar/basarnas_rescuer_potensi/layer
WILAYAH TANGGUNG JAWAB SAR murni via nama kota (basarnas_ops_sar.kantor_sar
dan basarnas_rescuer_potensi.satuan_kerja tidak punya kode/ID yang sama
dengan titik KANTOR SAR) -- dinormalisasi ke huruf besar tanpa prefix
"KANTOR PENCARIAN DAN PERTOLONGAN"/spasi ganda, dengan satu alias manual utk
"PANGKAL PINANG" (basarnas_ops_sar) vs "PANGKALPINANG" (nama_kantor) yang
ditemukan saat verifikasi (lihat _NAMA_ALIAS di bawah). Wilayah tanggung
jawab (poligon) di-join by call_sign, bukan nama -- lebih presisi & memang
tersedia di kedua sumber.

Idempotent: DELETE + reinsert penuh (47 kantor + N pos, kecil, tidak ada
alasan utk upsert per-baris). Jalankan ulang setelah reimport salah satu
sumber di atas (mis. basarnas_ops_sar tahun baru).

Usage (venv aktif):
    python scripts/build_basarnas_analisis_kantor.py
"""
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from db import db_cursor as pg_cursor  # noqa: E402

SCHEMA_PATH = Path(__file__).resolve().parent / "schema_basarnas_analisis_kantor.sql"

TAHUN_SUMBER_N = 5  # basarnas_ops_sar mencakup persis 2021-2025

_NAMA_ALIAS = {"PANGKAL PINANG": "PANGKALPINANG"}


def norm(nama: str) -> str:
    s = re.sub(r"^KANTOR (PENCARIAN DAN PERTOLONGAN|SAR)\s+", "", (nama or "").upper())
    s = re.sub(r"\s+", " ", s).strip()
    return _NAMA_ALIAS.get(s, s)


def main():
    with pg_cursor() as cur:
        cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

    with pg_cursor() as cur:
        cur.execute(
            "SELECT attrs->>'nama_kantor' AS nama, attrs->>'call_sign' AS call_sign, "
            "attrs->>'longitude' AS lon, attrs->>'latitude' AS lat "
            "FROM map_layers WHERE provinsi='BASARNAS' AND layer='KANTOR SAR' "
            "ORDER BY attrs->>'nama_kantor'"
        )
        kantor_rows = cur.fetchall()

        cur.execute(
            "SELECT attrs->>'Nama Pos SAR' AS nama, attrs->>'Nama Kantor SAR' AS kantor_induk, "
            "attrs->>'Longitude' AS lon, attrs->>'Latitude' AS lat "
            "FROM map_layers WHERE provinsi='BASARNAS' AND layer='POS SAR' "
            "ORDER BY attrs->>'Nama Pos SAR'"
        )
        pos_rows = cur.fetchall()

        # Provinsi per titik via point-in-polygon terhadap BATAS PROVINSI.
        def resolve_provinsi(lon, lat):
            if lon is None or lat is None:
                return None
            cur.execute(
                "SELECT attrs->>'PROVINSI' AS p FROM map_layers "
                "WHERE provinsi='BATAS PROVINSI' AND layer='Provinsi' "
                "AND ST_Contains(geom, ST_SetSRID(ST_MakePoint(%s, %s), 4326)) LIMIT 1",
                (float(lon), float(lat)),
            )
            r = cur.fetchone()
            return r["p"] if r else None

        # Luas wilayah tanggung jawab per call_sign.
        cur.execute(
            "SELECT attrs->>'Call Sign' AS call_sign, "
            "ST_Area(geography(geom)) / 1e6 AS luas_km2 "
            "FROM map_layers WHERE provinsi='BASARNAS' AND layer='WILAYAH TANGGUNG JAWAB SAR'"
        )
        luas_by_callsign = {r["call_sign"]: r["luas_km2"] for r in cur.fetchall() if r["call_sign"]}

        # Tenaga aktif per satuan kerja (basarnas_rescuer_potensi.satuan_kerja
        # sudah persis nama kota, cocok 100% dgn norm(nama_kantor) -- lihat
        # verifikasi di docstring atas).
        cur.execute("SELECT satuan_kerja, tenaga_total FROM basarnas_rescuer_potensi")
        tenaga_by_kota = {norm(r["satuan_kerja"]): r["tenaga_total"] for r in cur.fetchall()}

        def ops_agg(kota_norm, lon, lat):
            """Semua metrik turunan basarnas_ops_sar utk satu kantor sekaligus,
            supaya cuma 1 query per kantor (bukan 5)."""
            cur.execute(
                "SELECT jenis_kecelakaan, selamat, meninggal_dunia, dalam_pencarian_hilang, "
                "waktu_lapor, waktu_tiba, lon AS ilon, lat AS ilat "
                "FROM basarnas_ops_sar WHERE upper(regexp_replace(kantor_sar, "
                "'^KANTOR (PENCARIAN DAN PERTOLONGAN|SAR)\\s+', '', 'i')) = %s "
                "OR upper(regexp_replace(kantor_sar, '\\s+', ' ', 'g')) LIKE %s",
                (kota_norm, f"%{kota_norm}%"),
            )
            rows = cur.fetchall()
            if not rows:
                return {}

            jenis_count = {}
            selamat = md = hilang = 0
            for r in rows:
                if r["jenis_kecelakaan"]:
                    jenis_count[r["jenis_kecelakaan"]] = jenis_count.get(r["jenis_kecelakaan"], 0) + 1
                selamat += r["selamat"] or 0
                md += r["meninggal_dunia"] or 0
                hilang += r["dalam_pencarian_hilang"] or 0

            # MEDIAN (percentile_cont), bukan rata-rata aritmetik -- sumber
            # basarnas_ops_sar punya sedikit baris waktu_tiba dgn typo tahun
            # (mis. Ambon: satu baris waktu_tiba=2030, vs waktu_lapor di 2025)
            # yang membuat rata-rata jadi ribuan menit sementara mayoritas
            # baris lain wajar (puluhan-ratusan menit) -- median tahan
            # terhadap outlier tunggal seperti ini, rata-rata tidak.
            cur.execute(
                "SELECT percentile_cont(0.5) WITHIN GROUP ("
                "ORDER BY EXTRACT(EPOCH FROM (waktu_tiba - waktu_lapor)) / 60"
                ") AS median_menit FROM basarnas_ops_sar "
                "WHERE upper(regexp_replace(kantor_sar, "
                "'^KANTOR (PENCARIAN DAN PERTOLONGAN|SAR)\\s+', '', 'i')) = %s "
                "AND waktu_lapor IS NOT NULL AND waktu_tiba IS NOT NULL AND waktu_tiba >= waktu_lapor",
                (kota_norm,),
            )
            median_row = cur.fetchone()
            median_menit = median_row["median_menit"] if median_row else None

            max_jarak_m = None
            if lon is not None and lat is not None:
                cur.execute(
                    "SELECT MAX(ST_Distance(geography(ST_SetSRID(ST_MakePoint(%s,%s),4326)), "
                    "geography(ST_SetSRID(ST_MakePoint(lon,lat),4326)))) AS d "
                    "FROM basarnas_ops_sar WHERE upper(regexp_replace(kantor_sar, "
                    "'^KANTOR (PENCARIAN DAN PERTOLONGAN|SAR)\\s+', '', 'i')) = %s "
                    "AND lon IS NOT NULL AND lat IS NOT NULL",
                    (float(lon), float(lat), kota_norm),
                )
                d = cur.fetchone()
                max_jarak_m = d["d"] if d else None

            jenis_top = max(jenis_count.items(), key=lambda kv: kv[1])[0] if jenis_count else None
            korban_total = selamat + md + hilang
            return {
                "jenis_kejadian_terbanyak_5_tahun": jenis_top,
                "korban_selamat_5_tahun": selamat,
                "korban_meninggal_dunia_5_tahun": md,
                "korban_hilang_5_tahun": hilang,
                "rata_rata_operasi_per_tahun": round(len(rows) / TAHUN_SUMBER_N, 1),
                "rata_rata_rasio_keberhasilan_persen": round(selamat / korban_total * 100, 1) if korban_total else None,
                "waktu_respon_rata_rata_menit": round(float(median_menit), 1) if median_menit is not None else None,
                "jarak_tempuh_terjauh_km": round(max_jarak_m / 1000, 1) if max_jarak_m is not None else None,
            }

        out = []
        no = 1
        for r in kantor_rows:
            kota_norm = norm(r["nama"])
            provinsi = resolve_provinsi(r["lon"], r["lat"])
            luas = luas_by_callsign.get(r["call_sign"])
            tenaga = tenaga_by_kota.get(kota_norm)
            metrics = ops_agg(kota_norm, r["lon"], r["lat"])
            out.append({
                "no": no, "lokasi": r["nama"], "status": "Kantor Pencarian dan Pertolongan",
                "kantor_induk": None, "provinsi": provinsi,
                "luas_cakupan_wilayah_kerja_km2": round(luas, 2) if luas is not None else None,
                "termasuk_wilayah_rawan_bencana": None,
                "jumlah_tenaga_aktif": tenaga,
                **metrics,
            })
            no += 1

        for r in pos_rows:
            provinsi = resolve_provinsi(r["lon"], r["lat"])
            out.append({
                "no": no, "lokasi": r["nama"], "status": "Pos Pencarian dan Pertolongan",
                "kantor_induk": r["kantor_induk"], "provinsi": provinsi,
                "luas_cakupan_wilayah_kerja_km2": None, "termasuk_wilayah_rawan_bencana": None,
                "jumlah_tenaga_aktif": None,
            })
            no += 1

        cols = [
            "no", "lokasi", "status", "kantor_induk", "provinsi",
            "luas_cakupan_wilayah_kerja_km2", "termasuk_wilayah_rawan_bencana",
            "waktu_respon_rata_rata_menit", "jenis_kejadian_terbanyak_5_tahun",
            "korban_selamat_5_tahun", "korban_meninggal_dunia_5_tahun", "korban_hilang_5_tahun",
            "rata_rata_operasi_per_tahun", "rata_rata_rasio_keberhasilan_persen",
            "jarak_tempuh_terjauh_km", "jumlah_tenaga_aktif",
        ]
        records = [tuple(row.get(c) for c in cols) for row in out]

        cur.execute("DELETE FROM basarnas_analisis_kantor")
        col_sql = ", ".join(cols)
        ph_sql = ", ".join(["%s"] * len(cols))
        cur.executemany(
            f"INSERT INTO basarnas_analisis_kantor ({col_sql}) VALUES ({ph_sql})",
            records,
        )

    n_kantor = len(kantor_rows)
    n_pos = len(pos_rows)
    print(f"Selesai: {n_kantor} Kantor SAR + {n_pos} Pos SAR ({n_kantor + n_pos} baris) diisi ke basarnas_analisis_kantor.")


if __name__ == "__main__":
    main()
