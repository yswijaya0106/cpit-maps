# -*- coding: utf-8 -*-
"""Import simpul transportasi (bandara/pelabuhan) -> MySQL, dari SHP publik
di Maps/KONEKTIVITAS SIMPUL TRANSPORTASI/ -- dasar "Konektivitas Simpul
Transportasi" (Aspek B Laporan Daerah Prioritas).

Cuma 2 dari 4 layer diimpor di sini (lihat schema_simpul_transportasi.sql
utk alasan 2 sisanya belum): Pelabuhan Nasional (nama kabupaten teks,
dicocokkan ke master spt kriteria lain) dan Pelabuhan Penyeberangan/PP.shp
(kolom KD_KABKOT = kode BPS kabupaten langsung, "11.72" -> 1172).

Usage (venv aktif):
    python scripts/import_simpul_transportasi.py
"""

import difflib
import os
import re
import sys
from pathlib import Path

import geopandas as gpd
import psycopg
from psycopg.rows import dict_row

BASE_DIR = Path(__file__).resolve().parent.parent
MAPS_DIR = BASE_DIR / "Maps" / "KONEKTIVITAS SIMPUL TRANSPORTASI"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_simpul_transportasi.sql"

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
            "WHERE table_schema='public' AND table_name='simpul_transportasi'"
        )
        if not cur.fetchone():
            raise RuntimeError(
                "Tabel simpul_transportasi belum ada di PostgreSQL -- jalankan "
                "scripts/migrate_pg_01_schema.py dulu."
            )


# Singkatan yang muncul di sumber (nama provinsi/kabupaten dari shapefile
# publik, bukan gaya penulisan master BPS) -- diperluas dulu sebelum
# normalisasi, supaya "Tj. Jabung Timur"/"Kep. Riau" bisa cocok ke
# "TANJUNG JABUNG TIMUR"/"KEPULAUAN RIAU" di master.
_ABBR_EXPAND = [
    (re.compile(r"\bTj\.?(\s|$)", re.I), "Tanjung "),
    (re.compile(r"\bKep\.?(\s|$)", re.I), "Kepulauan "),
]
_PROV_ALIAS = {
    "DKI": "DKI JAKARTA", "NTB": "NUSA TENGGARA BARAT", "NTT": "NUSA TENGGARA TIMUR",
}
# Sumber ini masih pakai pembagian provinsi Papua LAMA (2 provinsi, sebelum
# pemekaran 2022 jadi 6) -- kabupaten yg sekarang masuk provinsi baru
# (Papua Tengah/Papua Selatan/Papua Pegunungan/Papua Barat Daya) gagal match
# kalau dicari cuma di provinsi lama. Fallback: kalau provinsi sumbernya
# persis "PAPUA"/"PAPUA BARAT", coba cocokkan nama kabupaten ke SEMUA 6
# provinsi pemekaran Papua, bukan cuma satu.
_PAPUA_LAMA = {"PAPUA", "PAPUA BARAT"}
_PAPUA_BARU_KODE = {94, 91, 96, 95, 97, 92}  # Papua/Papua Barat/Tengah/Selatan/Pegunungan/Barat Daya


def _expand_abbr(s):
    for rx, repl in _ABBR_EXPAND:
        s = rx.sub(repl, s)
    return s


def norm(s):
    return " ".join(t for t in re.split(r"[^A-Z0-9]+", _expand_abbr(str(s)).upper()) if t)


def norm_prov(s):
    base = norm(s)
    if base in _PROV_ALIAS:
        base = _PROV_ALIAS[base]
    toks = [t for t in re.split(r"[^A-Z0-9]+", base) if t]
    toks = ["DI" if t in ("DI", "D", "DAERAH") else t for t in toks]
    return " ".join(t for t in toks if t not in ("I", "ISTIMEWA"))


def strip_kab_prefix(s):
    n = norm(s)
    for p in ("KABUPATEN ", "KAB ", "KOTA "):
        if n.startswith(p):
            return n[len(p):]
    return n


def clean(v):
    # pandas/geopandas kirim NaN (float) utk sel kosong, BUKAN None -- kalau
    # dilewatkan begitu saja ke str() hasilnya string literal "nan" yang
    # lolos truthiness check, bukan benar-benar kosong.
    if v is None or (isinstance(v, float) and v != v):
        return None
    s = str(v).strip()
    return s or None


def build_master_index(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT kode_provinsi, provinsi, kode_kabupaten, kabupaten_kota FROM penduduk_kecamatan")
        kab_master = cur.fetchall()
    kab_idx = {(norm_prov(m["provinsi"]), strip_kab_prefix(m["kabupaten_kota"])): m for m in kab_master}
    # Master TIDAK menyimpan prefiks "Kabupaten"/"Kota" sama sekali (mis.
    # "KOTABARU" polos) -- kalau sumber menulis "Kota Baru" (spasi, seolah
    # "Kota" itu prefiks admin), strip_kab_prefix salah potong jadi "BARU".
    # Index tanpa-spasi ini jadi fallback: "KOTABARU" (dari "Kota Baru" tanpa
    # potong prefiks, spasi dibuang) baru ketemu lewat sini.
    kab_compact = {}
    for m in kab_master:
        key = (norm_prov(m["provinsi"]), norm(m["kabupaten_kota"]).replace(" ", ""))
        kab_compact.setdefault(key, m)
    kab_name_list_by_prov = {}
    for m in kab_master:
        kab_name_list_by_prov.setdefault(norm_prov(m["provinsi"]), []).append(
            (strip_kab_prefix(m["kabupaten_kota"]), m))
    valid_kab_codes = {m["kode_kabupaten"] for m in kab_master}
    # Nama kabupaten -> daftar kandidat di SEMUA provinsi (dipakai fallback
    # Papua lama/baru -- lihat _PAPUA_LAMA di atas).
    kab_name_all_prov = {}
    for m in kab_master:
        kab_name_all_prov.setdefault(strip_kab_prefix(m["kabupaten_kota"]), []).append(m)
    return kab_idx, kab_compact, kab_name_list_by_prov, kab_name_all_prov, valid_kab_codes


def _match_kabupaten(provinsi, kabupaten, kab_idx, kab_compact, kab_name_list_by_prov, kab_name_all_prov):
    prov_key = norm_prov(provinsi)
    m = kab_idx.get((prov_key, strip_kab_prefix(kabupaten)))
    if m:
        return m, "exact"
    m = kab_compact.get((prov_key, norm(kabupaten).replace(" ", "")))
    if m:
        return m, "compact"
    if prov_key in _PAPUA_LAMA:
        cands = [m for m in kab_name_all_prov.get(strip_kab_prefix(kabupaten), [])
                 if m["kode_provinsi"] in _PAPUA_BARU_KODE]
        if len(cands) == 1:
            return cands[0], "papua_pemekaran"
    candidates = kab_name_list_by_prov.get(prov_key) or []
    names = [n for n, _ in candidates]
    close = difflib.get_close_matches(strip_kab_prefix(kabupaten), names, n=1, cutoff=0.82)
    if close:
        return next(mm for n, mm in candidates if n == close[0]), "fuzzy"
    return None, None


def import_pelabuhan_nasional(kab_idx, kab_compact, kab_name_list_by_prov, kab_name_all_prov):
    path = MAPS_DIR / "pelabuhan" / "Pelabuhan Nasional.shp"
    gdf = gpd.read_file(path)
    out = []
    n_by_method = {"exact": 0, "compact": 0, "fuzzy": 0, "papua_pemekaran": 0}
    for _, row in gdf.iterrows():
        nama = clean(row.get("Name"))
        provinsi = clean(row.get("Provinsi"))
        kabupaten = clean(row.get("KABUPATEN"))
        m, method = (None, None)
        if nama and provinsi and kabupaten:
            m, method = _match_kabupaten(provinsi, kabupaten, kab_idx, kab_compact,
                                          kab_name_list_by_prov, kab_name_all_prov)
            if method:
                n_by_method[method] += 1
        out.append(("PELABUHAN_NASIONAL", nama, provinsi, kabupaten,
                     m["kode_provinsi"] if m else None, m["kode_kabupaten"] if m else None,
                     "Pelabuhan Nasional.shp"))
    print(f"  Pelabuhan Nasional: {len(out)} baris, {n_by_method} match, "
          f"{sum(1 for r in out if r[5] is None)} tidak match")
    return out


def import_pelabuhan_penyeberangan(valid_kab_codes):
    path = MAPS_DIR / "Pelabuhan Penyeberangan" / "SHP PP" / "PP.shp"
    gdf = gpd.read_file(path)
    out, n_match = [], 0
    for _, row in gdf.iterrows():
        nama = clean(row.get("NAMOBJ"))
        provinsi = clean(row.get("PROV"))
        kabupaten = clean(row.get("KABKOT"))
        kd = clean(row.get("KD_KABKOT"))
        kode_kab = None
        if kd:
            digits = kd.replace(".", "")
            if digits.isdigit():
                cand = int(digits)
                if cand in valid_kab_codes:
                    kode_kab = cand
        if kode_kab:
            n_match += 1
        out.append(("PELABUHAN_PENYEBERANGAN", nama, provinsi, kabupaten,
                     kode_kab // 100 if kode_kab else None, kode_kab, "PP.shp"))
    print(f"  Pelabuhan Penyeberangan: {len(out)} baris, {n_match} match via KD_KABKOT, "
          f"{sum(1 for r in out if r[5] is None)} tidak match")
    return out


def main():
    conn = connect()
    try:
        run_schema(conn)
        kab_idx, kab_compact, kab_name_list_by_prov, kab_name_all_prov, valid_kab_codes = build_master_index(conn)

        all_rows = []
        all_rows += import_pelabuhan_nasional(kab_idx, kab_compact, kab_name_list_by_prov, kab_name_all_prov)
        all_rows += import_pelabuhan_penyeberangan(valid_kab_codes)

        with conn.cursor() as cur:
            cur.execute("DELETE FROM simpul_transportasi WHERE jenis IN ('PELABUHAN_NASIONAL','PELABUHAN_PENYEBERANGAN')")
            cur.executemany(
                "INSERT INTO simpul_transportasi (jenis, nama, provinsi_asli, kabupaten_asli, "
                "kode_provinsi, kode_kabupaten, sumber_file) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                all_rows,
            )
        conn.commit()
        print(f"\nTotal: {len(all_rows)} baris dimuat ke simpul_transportasi")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
