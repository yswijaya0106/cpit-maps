# -*- coding: utf-8 -*-
"""Sinkronisasi kepadatan penduduk per kabupaten/kota dari tabel dinamis
BPS Web API (webapi.bps.go.id) -> tabel bps_api_kepadatan_kabupaten
(lihat schema_bps_api_kepadatan_kabupaten.sql).

Sumber TAMBAHAN/cross-check utk C.A1 Kemanfaatan IJD -- BELUM disambungkan
ke _ijd_score_kemanfaatan() di app.py (itu keputusan terpisah, butuh
verifikasi manual dulu spt pola docs/verifikasi_*.md sebelum dipakai
skoring live -- lihat .claude/skills/ijd-scoring-parameter/).

Cara kerja per provinsi (var_id "Kepadatan Penduduk menurut Kabupaten
Kota" BEDA-BEDA per provinsi, dicari otomatis lewat keyword title):
  1. GET model=var, subject=12 (Kependudukan), domain=<kode_provinsi>00
  2. Cari var yang judulnya mengandung "kepadatan penduduk" DAN
     "kabupaten" (case-insensitive) -- skip provinsi kalau tidak ada.
  3. GET model=th utk var itu, ambil tahun TERBARU yang tersedia (BEDA
     per provinsi -- direkam apa adanya, bukan dipaksa sama).
  4. GET model=data -- vervar (list kab/kota) dan datacontent (nilai)
     urutannya SEJAJAR (dikonfirmasi manual 24 Jul 2026), di-zip()
     langsung, BUKAN parsing format key datacontent (tidak didokumentasi
     jelas & berisiko salah tafsir).
  5. Filter ke kode_kabupaten yang valid di master penduduk_kecamatan
     saja (tabel vervar BPS suka menyelipkan baris agregat "PROVINSI X"
     dgn kode tidak standar, mis. 1199 utk Aceh -- bukan kode_kabupaten
     asli).

Usage (venv aktif):
    BPS_API_KEY=xxxxx python scripts/sync_kepadatan_kabupaten_bps_api.py
    BPS_API_KEY=xxxxx python scripts/sync_kepadatan_kabupaten_bps_api.py --kode-provinsi 11
    BPS_API_KEY=xxxxx python scripts/sync_kepadatan_kabupaten_bps_api.py --dry-run
"""

import argparse
import os
import sys
import time
from pathlib import Path

import psycopg
import requests
from psycopg.rows import dict_row

SCHEMA_PATH = Path(__file__).resolve().parent / "schema_bps_api_kepadatan_kabupaten.sql"

DB_HOST = os.environ.get("PG_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("PG_PORT", "5432"))
DB_USER = os.environ.get("PG_USER", "postgres")
DB_PASS = os.environ.get("PG_PASS", "")
DB_NAME = os.environ.get("PG_DB", "route_gis")

BPS_API_KEY = os.environ.get("BPS_API_KEY", "")
BPS_API_BASE = "https://webapi.bps.go.id/v1/api/list"
SUBJECT_KEPENDUDUKAN = 12


def connect():
    return psycopg.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS,
        dbname=DB_NAME, row_factory=dict_row,
    )


def run_schema(conn):
    sql_text = SCHEMA_PATH.read_text(encoding="utf-8")
    code = "\n".join(l for l in sql_text.splitlines() if not l.strip().startswith("--"))
    with conn.cursor() as cur:
        for stmt in [s.strip() for s in code.split(";") if s.strip()]:
            cur.execute(stmt)
    conn.commit()


def _api_get(**params):
    params["key"] = BPS_API_KEY
    r = requests.get(BPS_API_BASE, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "OK":
        return None
    return data


def find_var_kepadatan_kabupaten(domain: str):
    """Cari var_id 'Kepadatan Penduduk menurut Kabupaten Kota' utk 1
    provinsi -- var_id-nya beda per provinsi, dicari via keyword judul."""
    page = 1
    while True:
        data = _api_get(model="var", lang="ind", subject=SUBJECT_KEPENDUDUKAN,
                         domain=domain, page=page)
        if not data:
            return None
        meta, items = data["data"][0], data["data"][1]
        for v in items:
            title = v["title"].lower()
            if "kepadatan penduduk" in title and "kabupaten" in title:
                return v["var_id"], v["title"]
        if page >= int(meta.get("pages", 1) or 1):
            return None
        page += 1


def latest_th(domain: str, var_id: int):
    data = _api_get(model="th", lang="ind", domain=domain, var=var_id)
    if not data or not data["data"][1]:
        return None
    # Diasumsikan terurut terbaru dulu (konsisten dgn semua sampel yg
    # dicek manual) -- ambil elemen pertama.
    th = data["data"][1][0]
    return th["th_id"], th["th"]


def fetch_data(domain: str, var_id: int, th_id: int):
    data = _api_get(model="data", lang="ind", domain=domain, var=var_id, th=th_id)
    if not data:
        return []
    vervar = data.get("vervar", [])
    values = list(data.get("datacontent", {}).values())
    if len(vervar) != len(values):
        print(f"  WARNING domain {domain}: vervar ({len(vervar)}) != datacontent "
              f"({len(values)}), dilewati (format respons tak terduga)", file=sys.stderr)
        return []
    return list(zip(vervar, values))


def sync_provinsi(conn, kode_provinsi: int, valid_kab_codes: set, dry_run: bool):
    domain = f"{kode_provinsi:02d}00"
    found = find_var_kepadatan_kabupaten(domain)
    if not found:
        print(f"{domain}: tidak ada tabel 'Kepadatan Penduduk menurut Kabupaten' -- dilewati")
        return 0
    var_id, judul = found
    th = latest_th(domain, var_id)
    if not th:
        print(f"{domain}: var {var_id} ketemu tapi tidak ada data tahun -- dilewati")
        return 0
    th_id, tahun = th
    pairs = fetch_data(domain, var_id, th_id)

    rows = []
    for vv, val in pairs:
        kode_kab = vv.get("val")
        if kode_kab not in valid_kab_codes:
            continue  # baris agregat provinsi atau kode non-standar, skip
        try:
            kepadatan = float(val)
        except (TypeError, ValueError):
            continue
        rows.append((kode_kab, vv.get("label", ""), int(tahun), kepadatan, var_id))

    print(f"{domain}: var {var_id} '{judul}' tahun {tahun} -> {len(rows)} kab/kota valid")
    if dry_run:
        for r in rows[:3]:
            print(f"    {r}")
        return len(rows)

    if rows:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO bps_api_kepadatan_kabupaten "
                "(kode_kabupaten, nama_kabupaten, tahun, kepadatan_per_km2, var_id) "
                "VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT (kode_kabupaten) DO UPDATE SET "
                "nama_kabupaten=EXCLUDED.nama_kabupaten, tahun=EXCLUDED.tahun, "
                "kepadatan_per_km2=EXCLUDED.kepadatan_per_km2, var_id=EXCLUDED.var_id, "
                "disinkron_at=now()",
                rows,
            )
        conn.commit()
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kode-provinsi", type=int, default=None,
                     help="hanya sinkron 1 provinsi (kode BPS 2 digit)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not BPS_API_KEY:
        sys.exit("BPS_API_KEY belum diset.")

    conn = connect()
    try:
        run_schema(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT kode_kabupaten FROM penduduk_kecamatan")
            valid_kab_codes = {r["kode_kabupaten"] for r in cur.fetchall()}
            if args.kode_provinsi:
                provinsi = [args.kode_provinsi]
            else:
                cur.execute("SELECT DISTINCT kode_provinsi FROM penduduk_kecamatan ORDER BY 1")
                provinsi = [r["kode_provinsi"] for r in cur.fetchall()]

        total = 0
        for kp in provinsi:
            try:
                total += sync_provinsi(conn, kp, valid_kab_codes, args.dry_run)
            except Exception as e:
                print(f"  GAGAL provinsi {kp}: {e}", file=sys.stderr)
            time.sleep(0.3)

        print(f"\nTotal: {total} baris kabupaten/kota disinkron"
              f"{' (dry-run)' if args.dry_run else ''}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
