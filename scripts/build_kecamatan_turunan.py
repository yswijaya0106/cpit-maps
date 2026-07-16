# -*- coding: utf-8 -*-
"""Bangun/refresh tabel kecamatan_data_turunan (dasar skor C.A1/C.A3 IJD +
disagregasi rasio kabupaten->kecamatan, gap G3/G13 analisa_gap_cpit.md).

Sumber: penduduk_kecamatan (kerangka nasional), bps_kecamatan_demografi
(kepadatan & kendaraan per kecamatan — provinsi yang bukunya ada di
dalam_angka/), bps_kabupaten_kendaraan (disagregasi proporsional penduduk,
flag kendaraan_estimasi=1).

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

import pymysql

SCHEMA_PATH = Path(__file__).resolve().parent / "schema_kecamatan_turunan.sql"

DB_HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
DB_USER = os.environ.get("MYSQL_USER", "root")
DB_PASS = os.environ.get("MYSQL_PASS", "")
DB_NAME = os.environ.get("MYSQL_DB", "route_gis")

TAHUN = 2025


def norm(s):
    return " ".join(t for t in re.split(r"[^A-Z0-9]+", str(s).upper()) if t)


def connect():
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS,
        database=DB_NAME, charset="utf8mb4", autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
    )


def run_schema(conn):
    sql_text = SCHEMA_PATH.read_text(encoding="utf-8")
    code = "\n".join(l for l in sql_text.splitlines() if not l.strip().startswith("--"))
    with conn.cursor() as cur:
        for stmt in [s.strip() for s in code.split(";") if s.strip()]:
            cur.execute(stmt)
        cur.execute(
            "SELECT COUNT(*) n FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = 'usulan_inpres' "
            "AND column_name = 'kode_kecamatan'",
            (DB_NAME,),
        )
        if cur.fetchone()["n"] == 0:
            cur.execute(
                "ALTER TABLE usulan_inpres ADD COLUMN kode_kecamatan INT UNSIGNED NULL "
                "COMMENT 'Kode BPS kecamatan lokasi ruas (interim: manual; menunggu SHP batas kecamatan)'"
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

        # total penduduk per kabupaten (kunci alokasi disagregasi)
        pop_kab = defaultdict(int)
        for m in master:
            pop_kab[m["kode_kabupaten"]] += m["jumlah_penduduk"] or 0

        rows, n_kepadatan, n_kend_bps, n_kend_est, unmatched_bps = [], 0, 0, 0, 0
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
            rows.append((m["kode_kecamatan"], TAHUN, m["kode_kabupaten"], m["kecamatan"],
                         m["jumlah_penduduk"], kepadatan, luas, kendaraan, kend_est))

        unmatched_bps = [k for k in bps_idx if k not in matched_keys]

        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO kecamatan_data_turunan (kode_kecamatan, tahun, kode_kabupaten, "
                "kecamatan, jumlah_penduduk, kepadatan_per_km2, luas_km2, kendaraan_total, "
                "kendaraan_estimasi) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE kode_kabupaten=VALUES(kode_kabupaten), "
                "kecamatan=VALUES(kecamatan), jumlah_penduduk=VALUES(jumlah_penduduk), "
                "kepadatan_per_km2=VALUES(kepadatan_per_km2), luas_km2=VALUES(luas_km2), "
                "kendaraan_total=VALUES(kendaraan_total), kendaraan_estimasi=VALUES(kendaraan_estimasi)",
                rows,
            )
        conn.commit()

        print(f"kecamatan_data_turunan: {len(rows)} kecamatan (tahun {TAHUN})")
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
