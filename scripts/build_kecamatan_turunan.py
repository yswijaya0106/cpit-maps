# -*- coding: utf-8 -*-
"""Bangun/refresh tabel kecamatan_data_turunan (dasar skor C.A1/C.A3 IJD +
disagregasi rasio kabupaten->kecamatan, gap G3/G13 analisa_gap_cpit.md).

Sumber: penduduk_kecamatan (kerangka nasional), bps_kecamatan_demografi
(kepadatan & kendaraan per kecamatan — provinsi yang bukunya ada di
dalam_angka/), bps_kabupaten_kendaraan (disagregasi proporsional penduduk,
flag kendaraan_estimasi=1), bps_kecamatan_potensi_tematik (flag ada/tidak
potensi Pertanian/Perkebunan/Peternakan/Perikanan, dasar IJD A3 — parsial,
lihat scripts/extract_dalam_angka.py).

Juga menambahkan kolom usulan_inpres.kode_kecamatan (relasi usulan ->
kecamatan; sementara diisi manual — spatial-join menunggu SHP batas
kecamatan, gap G16) bila belum ada.

Jalankan ulang setiap kali dalam_angka/ bertambah provinsi (setelah
extract_dalam_angka.py --load) atau master penduduk di-update.

Usage (venv aktif):
    python scripts/build_kecamatan_turunan.py
"""

import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

SCHEMA_PATH = Path(__file__).resolve().parent / "schema_kecamatan_turunan.sql"

DB_HOST = os.environ.get("PG_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("PG_PORT", "5432"))
DB_USER = os.environ.get("PG_USER", "postgres")
DB_PASS = os.environ.get("PG_PASS", "")
DB_NAME = os.environ.get("PG_DB", "route_gis")

TAHUN = 2025


def norm(s):
    return " ".join(t for t in re.split(r"[^A-Z0-9]+", str(s).upper()) if t)


def connect():
    return psycopg.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS,
        dbname=DB_NAME, row_factory=dict_row,
    )


def run_schema(conn):
    """Tabel-tabel inti sudah dibuat via scripts/migrate_pg_01_schema.py --
    di sini cuma pastikan ada + tambahkan kolom belakangan (ADD COLUMN IF
    NOT EXISTS native Postgres, tidak perlu cek information_schema manual
    spt MySQL 8)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='kecamatan_data_turunan'"
        )
        if not cur.fetchone():
            raise RuntimeError(
                "Tabel kecamatan_data_turunan belum ada di PostgreSQL -- jalankan "
                "scripts/migrate_pg_01_schema.py dulu."
            )
        cur.execute(
            "ALTER TABLE usulan_inpres ADD COLUMN IF NOT EXISTS kode_kecamatan INT"
        )
        cur.execute(
            "ALTER TABLE kecamatan_data_turunan "
            "ADD COLUMN IF NOT EXISTS potensi_pertanian BOOLEAN, "
            "ADD COLUMN IF NOT EXISTS potensi_perkebunan BOOLEAN, "
            "ADD COLUMN IF NOT EXISTS potensi_peternakan BOOLEAN, "
            "ADD COLUMN IF NOT EXISTS potensi_perikanan BOOLEAN"
        )
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='bps_kecamatan_potensi_tematik'"
        )
        if cur.fetchone():
            cur.execute(
                "ALTER TABLE bps_kecamatan_potensi_tematik "
                "ADD COLUMN IF NOT EXISTS kode_kecamatan INT"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_bps_kecamatan_potensi_tematik_kode_kecamatan "
                "ON bps_kecamatan_potensi_tematik (kode_kecamatan)"
            )
            cur.execute(
                "ALTER TABLE bps_kecamatan_potensi_tematik "
                "ADD COLUMN IF NOT EXISTS peternakan_produksi_telur_kg NUMERIC(12,2)"
            )
    conn.commit()


def main():
    conn = connect()
    try:
        run_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT kode_kecamatan, kode_kabupaten, kecamatan, jumlah_penduduk "
                "FROM penduduk_kecamatan WHERE tahun = %s", (TAHUN,)
            )
            master = cur.fetchall()
            cur.execute(
                "SELECT kode_kab, kecamatan, kepadatan_per_km2, luas_km2_derived, "
                "total_kendaraan FROM bps_kecamatan_demografi WHERE tahun = %s", (TAHUN,)
            )
            bps_kec = cur.fetchall()
            cur.execute(
                "SELECT kode_kab, kecamatan, pertanian_ada, perkebunan_ada, "
                "peternakan_ada, perikanan_ada FROM bps_kecamatan_potensi_tematik "
                "WHERE tahun = %s", (TAHUN,)
            )
            potensi_kec = cur.fetchall()
            # kendaraan kabupaten: pakai tahun terbaru yang jumlahnya terisi
            cur.execute(
                "SELECT kode_kab, jumlah FROM bps_kabupaten_kendaraan b "
                "WHERE jumlah IS NOT NULL AND tahun = ("
                "  SELECT MAX(tahun) FROM bps_kabupaten_kendaraan b2 "
                "  WHERE b2.kode_kab = b.kode_kab AND b2.jumlah IS NOT NULL)"
            )
            kab_kendaraan = {int(r["kode_kab"]): r["jumlah"] for r in cur.fetchall()}

        bps_idx = {(int(r["kode_kab"]), norm(r["kecamatan"])): r for r in bps_kec}
        # fallback varian ejaan spasi (GUNUNGKENCANA vs GUNUNG KENCANA dsb.)
        bps_idx_compact = {}
        for r in bps_kec:
            key = (int(r["kode_kab"]), norm(r["kecamatan"]).replace(" ", ""))
            bps_idx_compact.setdefault(key, []).append(r)

        potensi_idx = {(int(r["kode_kab"]), norm(r["kecamatan"])): r for r in potensi_kec}
        potensi_idx_compact = {}
        for r in potensi_kec:
            key = (int(r["kode_kab"]), norm(r["kecamatan"]).replace(" ", ""))
            potensi_idx_compact.setdefault(key, []).append(r)

        # total penduduk per kabupaten (kunci alokasi disagregasi)
        pop_kab = defaultdict(int)
        for m in master:
            pop_kab[m["kode_kabupaten"]] += m["jumlah_penduduk"] or 0

        rows, n_kepadatan, n_kend_bps, n_kend_est, unmatched_bps = [], 0, 0, 0, 0
        potensi_kode_updates = []  # (kode_kecamatan, kode_kab, kecamatan_asli_bps) utk UPDATE balik
        matched_keys = set()
        for m in master:
            b = bps_idx.get((m["kode_kabupaten"], norm(m["kecamatan"])))
            if not b:
                loose = bps_idx_compact.get(
                    (m["kode_kabupaten"], norm(m["kecamatan"]).replace(" ", "")), [])
                b = loose[0] if len(loose) == 1 else None
            kepadatan = luas = kendaraan = kend_est = None
            if b:
                matched_keys.add((int(b["kode_kab"]), norm(b["kecamatan"])))
                kepadatan = b["kepadatan_per_km2"]
                luas = b["luas_km2_derived"]
                if b["total_kendaraan"] is not None:
                    kendaraan, kend_est = b["total_kendaraan"], 0
            if kepadatan is not None:
                n_kepadatan += 1
            if kendaraan is None and m["kode_kabupaten"] in kab_kendaraan and pop_kab[m["kode_kabupaten"]]:
                share = (m["jumlah_penduduk"] or 0) / pop_kab[m["kode_kabupaten"]]
                kendaraan, kend_est = round(kab_kendaraan[m["kode_kabupaten"]] * share), 1
                n_kend_est += 1
            elif kend_est == 0:
                n_kend_bps += 1

            p = potensi_idx.get((m["kode_kabupaten"], norm(m["kecamatan"])))
            if not p:
                loose = potensi_idx_compact.get(
                    (m["kode_kabupaten"], norm(m["kecamatan"]).replace(" ", "")), [])
                p = loose[0] if len(loose) == 1 else None
            potensi_pertanian = p["pertanian_ada"] if p else None
            potensi_perkebunan = p["perkebunan_ada"] if p else None
            potensi_peternakan = p["peternakan_ada"] if p else None
            potensi_perikanan = p["perikanan_ada"] if p else None
            if p:
                potensi_kode_updates.append(
                    (m["kode_kecamatan"], p["kode_kab"], p["kecamatan"], TAHUN))

            rows.append((m["kode_kecamatan"], TAHUN, m["kode_kabupaten"], m["kecamatan"],
                         m["jumlah_penduduk"], kepadatan, luas, kendaraan, kend_est,
                         potensi_pertanian, potensi_perkebunan, potensi_peternakan, potensi_perikanan))

        unmatched_bps = [k for k in bps_idx if k not in matched_keys]

        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO kecamatan_data_turunan (kode_kecamatan, tahun, kode_kabupaten, "
                "kecamatan, jumlah_penduduk, kepadatan_per_km2, luas_km2, kendaraan_total, "
                "kendaraan_estimasi, potensi_pertanian, potensi_perkebunan, potensi_peternakan, "
                "potensi_perikanan) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (kode_kecamatan, tahun) DO UPDATE SET "
                "kode_kabupaten=EXCLUDED.kode_kabupaten, "
                "kecamatan=EXCLUDED.kecamatan, jumlah_penduduk=EXCLUDED.jumlah_penduduk, "
                "kepadatan_per_km2=EXCLUDED.kepadatan_per_km2, luas_km2=EXCLUDED.luas_km2, "
                "kendaraan_total=EXCLUDED.kendaraan_total, kendaraan_estimasi=EXCLUDED.kendaraan_estimasi, "
                "potensi_pertanian=EXCLUDED.potensi_pertanian, potensi_perkebunan=EXCLUDED.potensi_perkebunan, "
                "potensi_peternakan=EXCLUDED.potensi_peternakan, potensi_perikanan=EXCLUDED.potensi_perikanan",
                rows,
            )
            if potensi_kode_updates:
                cur.executemany(
                    "UPDATE bps_kecamatan_potensi_tematik SET kode_kecamatan = %s "
                    "WHERE kode_kab = %s AND kecamatan = %s AND tahun = %s",
                    potensi_kode_updates,
                )
        conn.commit()

        print(f"kecamatan_data_turunan: {len(rows)} kecamatan (tahun {TAHUN})")
        print(f"  bps_kecamatan_potensi_tematik.kode_kecamatan terisi : {len(potensi_kode_updates)}")
        print(f"  kepadatan (Dalam Angka)        : {n_kepadatan}")
        print(f"  kendaraan per kec (BPS)        : {n_kend_bps}")
        print(f"  kendaraan disagregasi estimasi : {n_kend_est}")
        if unmatched_bps:
            print(f"  baris Dalam Angka tak terpetakan ke master ({len(unmatched_bps)}):")
            for kode_kab, nama in unmatched_bps:
                print(f"    - {kode_kab} {nama}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
