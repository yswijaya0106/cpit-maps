# -*- coding: utf-8 -*-
"""Konektivitas Jaringan Jalan (Aspek B Laporan Daerah Prioritas) -- proksi
"kabupaten/kota ini punya jaringan jalan terpetakan (SHP)" dari struktur
folder Maps/<PROVINSI>/<Kabupaten X>/ yang sudah dipakai overlay peta.

Dicocokkan lewat NAMA FOLDER (bukan atribut isi file) -- skema kolom file
jalan sangat beragam per sumber (149/234 py kolom Propinsi/Kab_Kot
konsisten, 85 sisanya beda-beda: ada yg cuma Kecamatan, ada yg tanpa kolom
wilayah sama sekali) sementara struktur foldernya SENDIRI sudah rapi
1-file-per-kabupaten dan sudah terbukti reliable dipakai fitur overlay peta
topbar (app.py:maps_kabupaten()).

Usage (venv aktif):
    python scripts/import_konektivitas_jalan.py
"""

import io
import os
import difflib
import re
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent
MAPS_DIR = BASE_DIR / "Maps"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_konektivitas_jalan.sql"

# Folder-folder khusus di Maps/ yang BUKAN provinsi/kabupaten reguler --
# dilewati (batas kecamatan, layer titik nasional, raster, folder jalan
# nasional flat/mentah).
SKIP_DIRS = {
    "BATAS KECAMATAN", "KONEKTIVITAS SIMPUL TRANSPORTASI", "IP2019-2024",
    "JALAN", "JALAN (mentah, belum diproses)", "JALAN PROVINSI", "JALAN TOL",
}

DB_HOST = os.environ.get("PG_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("PG_PORT", "5432"))
DB_USER = os.environ.get("PG_USER", "postgres")
DB_PASS = os.environ.get("PG_PASS", "")
DB_NAME = os.environ.get("PG_DB", "route_gis")


def connect():
    return psycopg.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS,
        dbname=DB_NAME, row_factory=dict_row,
    )


def run_schema(conn):
    """Tabel sudah dibuat via scripts/migrate_pg_01_schema.py -- di sini
    cuma pastikan ada (lihat docs/migrasi_mysql_ke_postgresql.md)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='konektivitas_jaringan_jalan'"
        )
        if not cur.fetchone():
            raise RuntimeError(
                "Tabel konektivitas_jaringan_jalan belum ada di PostgreSQL -- "
                "jalankan scripts/migrate_pg_01_schema.py dulu."
            )


def norm(s):
    return " ".join(t for t in re.split(r"[^A-Z0-9]+", str(s).upper()) if t)


def norm_prov(s):
    toks = [t for t in re.split(r"[^A-Z0-9]+", str(s).upper()) if t]
    toks = ["DI" if t in ("DI", "D", "DAERAH") else t for t in toks]
    return " ".join(t for t in toks if t not in ("I", "ISTIMEWA"))


def strip_kab_prefix(s):
    # Sebagian folder diberi prefiks kode BPS ("7505 - Kabupaten Gorontalo
    # Utara") -- dibuang dulu sebelum cek prefiks admin biasa.
    n = re.sub(r"^\d+\s*-\s*", "", str(s).strip())
    n = norm(n)
    for p in ("KABUPATEN ", "KABUAPTEN ", "KABUPTEN ", "KAB ", "KOTA "):
        if n.startswith(p):
            return n[len(p):]
    return n


def is_kota_folder(s):
    return norm(s).startswith("KOTA ")


def main():
    conn = connect()
    try:
        run_schema(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT kode_provinsi, provinsi, kode_kabupaten, kabupaten_kota FROM penduduk_kecamatan")
            kab_master = cur.fetchall()
        # Master TIDAK simpan prefiks Kabupaten/Kota (mis. Kab. Bekasi &
        # Kota Bekasi sama-sama "BEKASI") -- dibedakan via konvensi kode BPS
        # (2 digit terakhir >=71 = Kota), key = (prov, is_kota, nama dasar).
        # Nama folder Maps/ SUDAH eksplisit "Kabupaten X"/"Kota X" jadi
        # is_kota folder bisa dipakai langsung sbg pembeda.
        kab_idx = {}
        kab_names_by_prov_kota = {}
        for m in kab_master:
            is_kota = (m["kode_kabupaten"] % 100) >= 71
            key = (norm_prov(m["provinsi"]), is_kota, strip_kab_prefix(m["kabupaten_kota"]))
            kab_idx[key] = m
            kab_names_by_prov_kota.setdefault((key[0], key[1]), []).append((key[2], m))

        def _match(prov, is_kota, nama):
            m = kab_idx.get((norm_prov(prov), is_kota, strip_kab_prefix(nama)))
            if m:
                return m
            cands = kab_names_by_prov_kota.get((norm_prov(prov), is_kota)) or []
            close = difflib.get_close_matches(strip_kab_prefix(nama), [n for n, _ in cands], n=1, cutoff=0.85)
            if close:
                return next(mm for n, mm in cands if n == close[0])
            return None

        rows, n_match, n_nomatch = [], 0, 0
        nomatch_samples = []
        for prov_dir in sorted(MAPS_DIR.iterdir()):
            if not prov_dir.is_dir() or prov_dir.name in SKIP_DIRS:
                continue
            for kab_dir in sorted(prov_dir.iterdir()):
                if not kab_dir.is_dir():
                    continue
                shp_files = [f for f in kab_dir.glob("*.shp")
                             if "jalan" in f.name.lower() or "jaringan" in f.name.lower()]
                if not shp_files:
                    continue
                m = _match(prov_dir.name, is_kota_folder(kab_dir.name), kab_dir.name)
                if m:
                    n_match += 1
                    rows.append((m["kode_kabupaten"], prov_dir.name, kab_dir.name, shp_files[0].name))
                else:
                    n_nomatch += 1
                    if len(nomatch_samples) < 10:
                        nomatch_samples.append(f"{prov_dir.name}/{kab_dir.name}")

        with conn.cursor() as cur:
            # UPSERT (bukan DELETE+INSERT polos) -- tabel ini digabung dgn
            # sumber NASIONAL (scripts/import_jalan_nasional.py), jangan
            # timpa baris yg cuma py data nasional saja.
            cur.executemany(
                "INSERT INTO konektivitas_jaringan_jalan "
                "(kode_kabupaten, ada_jalan_daerah, provinsi_folder, kabupaten_folder, sumber_file) "
                "VALUES (%s, TRUE, %s, %s, %s) "
                "ON CONFLICT (kode_kabupaten) DO UPDATE SET ada_jalan_daerah=TRUE, "
                "provinsi_folder=EXCLUDED.provinsi_folder, "
                "kabupaten_folder=EXCLUDED.kabupaten_folder, sumber_file=EXCLUDED.sumber_file",
                rows,
            )
        conn.commit()
        print(f"Total: {len(rows)} kabupaten/kota dimuat ({n_match} match, {n_nomatch} folder tak dikenal)")
        if nomatch_samples:
            print("Contoh folder tak match:", nomatch_samples)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
