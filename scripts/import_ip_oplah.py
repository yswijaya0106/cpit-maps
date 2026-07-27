# -*- coding: utf-8 -*-
"""Sinkronkan bps_kabupaten_indeks_penanaman.indeks_penanaman_pct (tahun
2026 skoring: DIPAKAI = tahun=2024) dengan docs/docs/IP 2019-2024,
OPLAH.xlsx sheet "IP TOTAL" kolom L (IP 2024) -- menjadikan OPLAH sumber
data valid utk tabel ini, MENGGANTIKAN nilai lama dari Kertas Kerja.xlsx
(scripts/import_kertas_kerja.py) untuk setiap kabupaten/kota yang
namanya berhasil dicocokkan.

Kenapa OPLAH, bukan Kertas Kerja: docs/perbandingan_ip_oplah_vs_
bps_kabupaten_indeks_penanaman.md membuktikan Kertas Kerja (SEKUNDER,
Luas Panen administratif -- rawan nilai 0 palsu kalau laporan sumbernya
kosong, lihat kasus Kab. Pandeglang di dokumen itu) sering menyimpang
jauh dari sumber PRIMER (raster Dit. SDA, bps_kabupaten_indeks_
penanaman_raster) -- cuma 23,6% baris cocok bucket ambang Tabel 4.
Sebaliknya OPLAH (Luas Tanam citra satelit AOI Kementan + ML utk Jawa)
cocok 84,4% dengan sumber PRIMER yang sama. OPLAH jadi kandidat SEKUNDER
yang jauh lebih baik daripada Kertas Kerja -- keputusan ini sudah dibahas
& disetujui user 27 Jul 2026.

Pencocokan: by NAMA terhadap baris yang SUDAH ADA di
bps_kabupaten_indeks_penanaman (bukan membangun index nama->kode baru
dari nol) -- sengaja, supaya TIDAK mengulang bug tabrakan nama Kabupaten/
Kota yang identik setelah dihilangkan prefiksnya (lihat temuan "Kabupaten
Serang vs Kota Serang" di docs/analisa_a3_tematik_tambahan_vs_lokus_
bappenas_xlsx.md §3) -- kode_kab tiap baris tabel ini SUDAH benar dari
Kertas Kerja, jadi pencocokan nama di sini cuma MENCARI NILAI OPLAH untuk
kode yang sudah pasti, bukan MENENTUKAN kode dari nama. Kabupaten/kota
yang gagal cocok (varian ejaan, mis. "Pematang Siantar" vs
"Pematangsiantar", 5 Kota Administrasi DKI Jakarta, dst. -- daftar
lengkap di docs/perbandingan_ip_oplah...md §2) TETAP pakai nilai Kertas
Kerja lama (tidak disentuh, bukan di-NULL-kan) -- OPLAH jadi sumber utama
HANYA utk yang cocok, bukan penggantian seluruh tabel.

lahan_baku_sawah_ha DIISI dari sheet "IP OPLAH" (BUKAN "IP TOTAL") kolom
D "Luas LBS (ha)" -- ditemukan 27 Jul 2026: workbook ini py 2 sheet
komputasi paralel dgn header sama tapi angka beda ("IP TOTAL"/"Tabel IP
TOTAL" vs "IP OPLAH"/"Tabel IP OPLAH", lihat "Lokasi OPLAH" utk sumber
mentahnya) -- "IP TOTAL" kolom D kosong di level kabupaten (makanya
sempat dikira LBS tak tersedia sama sekali di file ini), TAPI "IP OPLAH"
py kolom D terisi PENUH per kabupaten (mis. Aceh Timur = 8.205,95 ha).
IP 2024 tetap dari sheet "IP TOTAL" kolom L sesuai instruksi awal (dua
sheet ini punya IP2024 yg beda juga -- Aceh Timur "IP TOTAL"=168,34% vs
"IP OPLAH"=175,48% -- BUKAN dikombinasikan, cuma LBS-nya yang diambil
dari "IP OPLAH", indeks_penanaman_pct tetap dari "IP TOTAL").

kategori_sumber dihitung ULANG dari nilai IP baru memakai ambang Tabel 4
dokumen 14072026 (sama persis label yang sudah dipakai kolom ini: "IP <
100"/"IP 100-150"/"IP 150-200"/"IP 200-300"/"IP >= 300"), supaya kolom
ini tetap konsisten dgn indeks_penanaman_pct-nya sendiri (bukan label
lama dari Kertas Kerja yang sudah tidak match angka barunya).

Usage (venv aktif):
    python scripts/import_ip_oplah.py              # sinkronkan (upsert)
    python scripts/import_ip_oplah.py --dry-run     # tampilkan apa yang AKAN diubah, tanpa menulis ke DB
"""

import os
import re
import sys
from pathlib import Path

import openpyxl
import psycopg
from psycopg.rows import dict_row

BASE_DIR = Path(__file__).resolve().parent.parent
XLSX_PATH = BASE_DIR / "docs" / "docs" / "IP 2019-2024, OPLAH.xlsx"

DB_HOST = os.environ.get("PG_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("PG_PORT", "5432"))
DB_USER = os.environ.get("PG_USER", "postgres")
DB_PASS = os.environ.get("PG_PASS", "")
DB_NAME = os.environ.get("PG_DB", "route_gis")

TAHUN = 2024


def connect():
    return psycopg.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS,
        dbname=DB_NAME, row_factory=dict_row,
    )


def norm_nama(s) -> str:
    if not s:
        return ""
    s = str(s).upper()
    # \s+ (BUKAN \s*) -- \s* pernah salah memotong nama yg SECARA KEBETULAN
    # diawali kata "Kota"/"Kab" tanpa spasi sbg bagian nama itu sendiri (mis.
    # "Kotabaru" jadi "BARU", gagal cocok dgn "Kabupaten Kotabaru").
    s = re.sub(r"^(KABUPATEN|KOTA|KAB\.?)\s+", "", s)
    return re.sub(r"[^A-Z0-9]+", " ", s).strip()


def norm_nama_tanpa_spasi(s) -> str:
    """Fallback kalau norm_nama tidak cocok -- hilangkan semua spasi,
    menangani varian penulisan kata majemuk (mis. OPLAH "Kota
    Pematangsiantar" vs DB "Kota Pematang Siantar", "Bukittinggi" vs
    "Bukit Tinggi", "Parepare" vs "Pare Pare", "Muko Muko" vs
    "Mukomuko") -- TIDAK menyelesaikan beda ejaan sesungguhnya (mis.
    "Sidempuan" vs "Sidimpuan"), cuma beda spasi."""
    return norm_nama(s).replace(" ", "")


def kategori_tabel4(ip: float) -> str:
    if ip > 300:
        return "IP >= 300"
    if ip >= 200:
        return "IP 200-300"
    if ip >= 150:
        return "IP 150-200"
    if ip >= 100:
        return "IP 100-150"
    return "IP < 100"


def _load_sheet_kolom_by_nama(sheet: str, kolom_idx: int) -> tuple:
    """Generik: {nama ternormalisasi: nilai kolom_idx} utk 1 sheet, baris
    kabupaten/kota saja (baris provinsi py row[1] terisi, di-skip).
    Return (by_nama, by_nama_tanpa_spasi)."""
    wb = openpyxl.load_workbook(XLSX_PATH, read_only=True, data_only=True)
    ws = wb[sheet]
    by_nama, by_nama_tanpa_spasi = {}, {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[1]:  # baris provinsi (agregat) -- skip
            continue
        if not row[2]:
            continue
        nilai = row[kolom_idx]
        if nilai is not None:
            by_nama[norm_nama(row[2])] = float(nilai)
            by_nama_tanpa_spasi[norm_nama_tanpa_spasi(row[2])] = float(nilai)
    wb.close()
    return by_nama, by_nama_tanpa_spasi


def load_oplah_ip_by_nama() -> tuple:
    """Sheet 'IP TOTAL' kolom L (indeks 11) = IP 2024."""
    return _load_sheet_kolom_by_nama("IP TOTAL", 11)


def load_oplah_lbs_by_nama() -> tuple:
    """Sheet 'IP OPLAH' (BUKAN 'IP TOTAL') kolom D (indeks 3) = Luas LBS
    (ha) -- lihat catatan di docstring modul kenapa sheet-nya beda."""
    return _load_sheet_kolom_by_nama("IP OPLAH", 3)


def main():
    dry_run = "--dry-run" in sys.argv

    ip_by_nama, ip_by_nama_tanpa_spasi = load_oplah_ip_by_nama()
    print(f"OPLAH 'IP TOTAL': {len(ip_by_nama)} kabupaten/kota (kolom L, IP 2024)")
    lbs_by_nama, lbs_by_nama_tanpa_spasi = load_oplah_lbs_by_nama()
    print(f"OPLAH 'IP OPLAH': {len(lbs_by_nama)} kabupaten/kota (kolom D, Luas LBS ha)")

    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT kode_kab, nama_kab, indeks_penanaman_pct AS ip_lama, "
                "kategori_sumber AS kategori_lama, lahan_baku_sawah_ha AS lbs_lama "
                "FROM bps_kabupaten_indeks_penanaman WHERE tahun = %s",
                (TAHUN,),
            )
            rows = cur.fetchall()

        updates = []
        tak_cocok_ip, tak_cocok_lbs = [], []
        n_fallback_tanpa_spasi = 0
        for r in rows:
            nama_norm = norm_nama(r["nama_kab"])
            ip_baru = ip_by_nama.get(nama_norm)
            if ip_baru is None:
                ip_baru = ip_by_nama_tanpa_spasi.get(norm_nama_tanpa_spasi(r["nama_kab"]))
                if ip_baru is not None:
                    n_fallback_tanpa_spasi += 1
            if ip_baru is None:
                tak_cocok_ip.append(r["nama_kab"])

            lbs_baru = lbs_by_nama.get(nama_norm)
            if lbs_baru is None:
                lbs_baru = lbs_by_nama_tanpa_spasi.get(norm_nama_tanpa_spasi(r["nama_kab"]))
            if lbs_baru is None:
                tak_cocok_lbs.append(r["nama_kab"])

            if ip_baru is None and lbs_baru is None:
                continue
            updates.append((
                r["kode_kab"], r["nama_kab"],
                r["ip_lama"], ip_baru if ip_baru is not None else r["ip_lama"],
                r["kategori_lama"],
                kategori_tabel4(ip_baru) if ip_baru is not None else r["kategori_lama"],
                r["lbs_lama"], lbs_baru if lbs_baru is not None else r["lbs_lama"],
            ))

        print(f"IP cocok (akan diupdate dari 'IP TOTAL'): {len(rows) - len(tak_cocok_ip)}/{len(rows)}"
              f" (termasuk {n_fallback_tanpa_spasi} via fallback tanpa-spasi)")
        print(f"IP tidak cocok (tetap Kertas Kerja lama): {len(tak_cocok_ip)} -> {tak_cocok_ip}")
        print(f"LBS cocok (akan diupdate dari 'IP OPLAH'): {len(rows) - len(tak_cocok_lbs)}/{len(rows)}")
        print(f"LBS tidak cocok (tetap nilai lama): {len(tak_cocok_lbs)} -> {tak_cocok_lbs}")

        n_beda_kategori = sum(1 for u in updates if u[4] != u[5])
        print(f"Dari yang diupdate, {n_beda_kategori} berubah kategori ambang Tabel 4.")

        if dry_run:
            print("\n--dry-run: TIDAK menulis ke database. Contoh 10 baris pertama:")
            for u in updates[:10]:
                print(f"  {u[0]} {u[1]}: IP {u[2]} -> {u[3]:.2f}  |  kategori {u[4]!r} -> {u[5]!r}"
                      f"  |  LBS {u[6]} -> {u[7]}")
            return

        with conn.cursor() as cur:
            for kode_kab, nama_kab, ip_lama, ip_baru, kat_lama, kat_baru, lbs_lama, lbs_baru in updates:
                cur.execute(
                    "UPDATE bps_kabupaten_indeks_penanaman "
                    "SET indeks_penanaman_pct = %s, kategori_sumber = %s, lahan_baku_sawah_ha = %s "
                    "WHERE kode_kab = %s AND tahun = %s",
                    (round(ip_baru, 2), kat_baru,
                     round(lbs_baru, 2) if lbs_baru is not None else None,
                     kode_kab, TAHUN),
                )
        conn.commit()
        print(f"\nSelesai -- {len(updates)} baris di-update dari sumber OPLAH (IP dan/atau LBS).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
