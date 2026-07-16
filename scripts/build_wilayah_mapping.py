# -*- coding: utf-8 -*-
"""Bangun/refresh pemetaan wilayah SITIA -> kode BPS (tabel wilayah_mapping).

Master kode: penduduk_kecamatan (jalankan scripts/import_penduduk_kecamatan.py
dulu). Matcher deterministik:
  - provinsi dicocokkan persis (kedua sumber sudah huruf besar & senama);
  - kabupaten/kota SITIA berprefiks "KABUPATEN "/"KOTA ", master BPS memakai
    nama polos — prefiks menentukan jenis dan dicek terhadap konvensi kode
    BPS (2 digit terakhir kode kabupaten >= 71 berarti kota) supaya pasangan
    senama (mis. KABUPATEN BOGOR vs KOTA BOGOR) tidak tertukar;
  - nama dinormalisasi ringan (tanda baca -> spasi) tanpa fuzzy.

Baris metode='MANUAL' tidak pernah ditimpa — pakai untuk koreksi pasangan
yang gagal match: isi kode_provinsi/kode_kabupaten via SQL lalu set
metode='MANUAL'. Jalankan ulang script ini setiap kali ada tarikan usulan
baru (pasangan wilayah baru otomatis ditambahkan).

Usage (venv aktif):
    python scripts/build_wilayah_mapping.py
"""

import os
import re
import sys
from pathlib import Path

import pymysql

SCHEMA_PATH = Path(__file__).resolve().parent / "schema_wilayah_mapping.sql"

DB_HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
DB_USER = os.environ.get("MYSQL_USER", "root")
DB_PASS = os.environ.get("MYSQL_PASS", "")
DB_NAME = os.environ.get("MYSQL_DB", "route_gis")


def norm(s):
    return " ".join(t for t in re.split(r"[^A-Z0-9]+", str(s).upper()) if t)


# Varian ejaan yang tidak tertangkap penyamaan spasi (huruf berbeda).
_NAME_ALIASES = {
    "PADANGSIDEMPUAN": "PADANGSIDIMPUAN",
}


def norm_compact(s):
    """Kunci pencocokan longgar: tanpa spasi, 'KEP' diekspansi, tanpa token
    KEPULAUAN — menyamakan varian 'MUKO MUKO'/'MUKOMUKO', 'KEP. SIAU ...'
    dsb. Tetap deterministik (bukan fuzzy)."""
    toks = [("KEPULAUAN" if t == "KEP" else t) for t in norm(s).split()]
    compact = "".join(t for t in toks if t != "KEPULAUAN")
    return _NAME_ALIASES.get(compact, compact)


def connect():
    conn = pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS,
        database=DB_NAME, charset="utf8mb4", autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
    )
    return conn


def run_schema(conn):
    sql_text = SCHEMA_PATH.read_text(encoding="utf-8")
    code = "\n".join(l for l in sql_text.splitlines() if not l.strip().startswith("--"))
    with conn.cursor() as cur:
        for stmt in [s.strip() for s in code.split(";") if s.strip()]:
            cur.execute(stmt)
    conn.commit()


def is_kota(kode_kabupaten):
    return kode_kabupaten % 100 >= 71


def main():
    conn = connect()
    try:
        run_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT kode_provinsi, provinsi, kode_kabupaten, kabupaten_kota "
                "FROM penduduk_kecamatan"
            )
            master = cur.fetchall()
            if not master:
                sys.exit("Master penduduk_kecamatan kosong — jalankan "
                         "scripts/import_penduduk_kecamatan.py dulu.")
            cur.execute("SELECT DISTINCT provinsi, kabupaten_kota FROM usulan_inpres")
            pairs = cur.fetchall()
            cur.execute("SELECT provinsi_sitia, kabupaten_kota_sitia, metode FROM wilayah_mapping")
            manual = {(r["provinsi_sitia"], r["kabupaten_kota_sitia"])
                      for r in cur.fetchall() if r["metode"] == "MANUAL"}

        # index master: (prov_norm, jenis, nama_norm) -> baris master;
        # idx2 = kunci longgar (tanpa spasi) untuk varian ejaan
        idx, idx2 = {}, {}
        for m in master:
            jenis = "KOTA" if is_kota(m["kode_kabupaten"]) else "KABUPATEN"
            prov = norm(m["provinsi"])
            idx.setdefault((prov, jenis, norm(m["kabupaten_kota"])), []).append(m)
            idx2.setdefault((prov, jenis, norm_compact(m["kabupaten_kota"])), []).append(m)

        rows, unmatched = [], []
        for p in pairs:
            key = (p["provinsi"], p["kabupaten_kota"])
            if key in manual:
                continue
            kab_norm = norm(p["kabupaten_kota"])
            jenis = "KABUPATEN"
            for prefix in ("KOTA ", "KABUPATEN "):
                if kab_norm.startswith(prefix):
                    jenis = prefix.strip()
                    kab_norm = kab_norm[len(prefix):]
                    break
            hits = idx.get((norm(p["provinsi"]), jenis, kab_norm), [])
            catatan_ok = None
            if len(hits) != 1:
                loose = idx2.get((norm(p["provinsi"]), jenis, norm_compact(kab_norm)), [])
                if len(loose) == 1:
                    hits, catatan_ok = loose, "varian ejaan"
            if len(hits) == 1:
                m = hits[0]
                rows.append((p["provinsi"], p["kabupaten_kota"], m["kode_provinsi"],
                             m["kode_kabupaten"], m["kabupaten_kota"], "AUTO", catatan_ok))
            else:
                catatan = "ambigu di master" if len(hits) > 1 else "tidak ditemukan di master"
                rows.append((p["provinsi"], p["kabupaten_kota"], None, None, None, "AUTO", catatan))
                unmatched.append((p["provinsi"], p["kabupaten_kota"], catatan))

        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO wilayah_mapping (provinsi_sitia, kabupaten_kota_sitia, "
                "kode_provinsi, kode_kabupaten, kabupaten_kota_bps, metode, catatan) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE kode_provinsi=VALUES(kode_provinsi), "
                "kode_kabupaten=VALUES(kode_kabupaten), "
                "kabupaten_kota_bps=VALUES(kabupaten_kota_bps), metode=VALUES(metode), "
                "catatan=VALUES(catatan)",
                rows,
            )
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) n FROM usulan_inpres u JOIN wilayah_mapping w "
                "ON w.provinsi_sitia = u.provinsi AND w.kabupaten_kota_sitia = u.kabupaten_kota "
                "WHERE w.kode_kabupaten IS NOT NULL"
            )
            covered = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) n FROM usulan_inpres")
            total = cur.fetchone()["n"]

        ok = sum(1 for r in rows if r[3] is not None)
        print(f"Pemetaan wilayah: {ok}/{len(rows)} pasangan match otomatis"
              f"{f' (+{len(manual)} manual dipertahankan)' if manual else ''}")
        print(f"Cakupan usulan: {covered}/{total} baris usulan_inpres punya kode BPS "
              f"({covered / total * 100:.1f}%)")
        if unmatched:
            print("Belum terpetakan (isi manual di tabel wilayah_mapping, set metode='MANUAL'):")
            for prov, kab, ket in unmatched:
                print(f"  - {prov} | {kab} ({ket})")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
