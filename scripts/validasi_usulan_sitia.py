"""Validasi kualitas data usulan SITIA 2023-2026 (usulan_inpres_riwayat) dan data lokus
Bappenas yang dipakai Laporan Prioritas/LOKPRI.

Dibuat 30 Sep 2026 dari "Kerangka Berpikir Jalan" (docs/30092026/): evaluasi data LOKPRI
(nama kab/kota tak baku, nama kembar Kab/Kota) dan biaya per km utk menilai usulan baru.

Read-only. Pemeriksaan:
  V1 biaya/km ekstrem (alokasi Pemda / panjang penanganan Pemda > 50 atau < 0,3 Rp M/km)
  V2 panjang penanganan > panjang ruas (toleransi 5%)
  V3 alokasi Kompetensi > 1,5x usulan Pemda
  V4 total kondisi (baik+sedang+ringan+berat) > panjang ruas (toleransi 5%; file 2024-2026)
  V5 alokasi Pemda terisi tapi panjang penanganan Pemda kosong/0
  V6 ruas yang sama (kab/kota + nama ruas) punya Kode Ruas berbeda antartahun  [informasi]
  V7 panjang ruas yang sama berubah >10% antartahun                          [informasi]
  V8 baris lokus Bappenas / kawasan tematik yang kab/kota-nya tidak tercocokkan
  V9 baris lokus bernama kembar Kab/Kota TANPA awalan Kab./Kota (diputuskan
     lewat konvensi "tanpa awalan = Kabupaten" -- perlu konfirmasi pemilik data)
  V10 usulan tanpa kab/kota terpetakan ke kode BPS (2023/2024: baris tanpa provinsi & kab/kota)
V1-V5 hanya utk penanganan jalan (jenis tanpa "Jembatan").

Usage (venv aktif):
    python scripts/validasi_usulan_sitia.py
    python scripts/validasi_usulan_sitia.py --xlsx validasi_sitia.xlsx   # + rincian per baris

Laporan saja: exit 0 walau ada temuan (temuan = masalah data sumber, bukan kegagalan skrip).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
from db import db_cursor  # noqa: E402

JALAN = "jenis_penanganan NOT ILIKE '%%jembatan%%'"
NAMA_KUNCI = "regexp_replace(upper(coalesce(nama_ruas, '')), '[^A-Z0-9]', '', 'g')"
KOLOM_USULAN = ("tahun, id, provinsi, kabupaten_kota, kode_ruas, nama_ruas, jenis_penanganan, "
                "panjang_ruas_km, panjang_penanganan_pemda, alokasi_usulan_pemda, alokasi_usulan_kompetensi")

CEK_USULAN = [
    ("V1", "Biaya/km ekstrem (>50 atau <0,3 Rp M/km, basis Pemda)",
     f"SELECT {KOLOM_USULAN}, round(alokasi_usulan_pemda / panjang_penanganan_pemda / 1e9, 2) AS rp_m_per_km "
     f"FROM usulan_inpres_riwayat WHERE {JALAN} AND panjang_penanganan_pemda > 0 AND alokasi_usulan_pemda > 0 "
     "AND (alokasi_usulan_pemda / panjang_penanganan_pemda / 1e9 > 50 "
     "OR alokasi_usulan_pemda / panjang_penanganan_pemda / 1e9 < 0.3)"),
    ("V2", "Panjang penanganan Pemda > panjang ruas (+5%)",
     f"SELECT {KOLOM_USULAN} FROM usulan_inpres_riwayat WHERE {JALAN} AND panjang_ruas_km > 0 "
     "AND panjang_penanganan_pemda > panjang_ruas_km * 1.05"),
    ("V3", "Alokasi Kompetensi > 1,5x usulan Pemda",
     f"SELECT {KOLOM_USULAN}, round(alokasi_usulan_kompetensi / alokasi_usulan_pemda, 2) AS rasio "
     f"FROM usulan_inpres_riwayat WHERE {JALAN} AND alokasi_usulan_pemda > 0 "
     "AND alokasi_usulan_kompetensi > alokasi_usulan_pemda * 1.5"),
    ("V4", "Total kondisi (B+S+RR+RB) > panjang ruas (+5%)",
     f"SELECT {KOLOM_USULAN}, kondisi_baik_km, kondisi_sedang_km, kondisi_ringan_km, kondisi_berat_km "
     f"FROM usulan_inpres_riwayat WHERE {JALAN} AND panjang_ruas_km > 0 AND "
     "coalesce(kondisi_baik_km,0)+coalesce(kondisi_sedang_km,0)+coalesce(kondisi_ringan_km,0)+coalesce(kondisi_berat_km,0)"
     " > panjang_ruas_km * 1.05"),
    ("V5", "Alokasi Pemda terisi tapi panjang penanganan Pemda kosong/0",
     f"SELECT {KOLOM_USULAN} FROM usulan_inpres_riwayat WHERE {JALAN} AND alokasi_usulan_pemda > 0 "
     "AND coalesce(panjang_penanganan_pemda, 0) <= 0"),
    ("V10", "Usulan tanpa kab/kota yang bisa dipetakan ke kode BPS (semua jenis penanganan)",
     f"SELECT {KOLOM_USULAN} FROM usulan_inpres_riwayat WHERE kode_kabupaten IS NULL"),
]

CEK_INFO = [
    ("V6", "Ruas sama (kab/kota + nama) dengan Kode Ruas berbeda antartahun",
     f"SELECT kode_kabupaten, min(kabupaten_kota) AS kabupaten_kota, min(nama_ruas) AS nama_ruas, "
     "string_agg(DISTINCT tahun || ':' || kode_ruas, ', ') AS kode_per_tahun "
     f"FROM usulan_inpres_riwayat WHERE kode_kabupaten IS NOT NULL AND {NAMA_KUNCI} <> '' "
     f"GROUP BY kode_kabupaten, {NAMA_KUNCI} HAVING count(DISTINCT kode_ruas) > 1"),
    ("V7", "Panjang ruas yang sama berubah >10% antartahun",
     f"SELECT kode_kabupaten, min(kabupaten_kota) AS kabupaten_kota, min(nama_ruas) AS nama_ruas, "
     "min(panjang_ruas_km) AS min_km, max(panjang_ruas_km) AS max_km, "
     "string_agg(DISTINCT tahun || ':' || panjang_ruas_km, ', ') AS km_per_tahun "
     f"FROM usulan_inpres_riwayat WHERE kode_kabupaten IS NOT NULL AND {NAMA_KUNCI} <> '' AND panjang_ruas_km > 0 "
     f"GROUP BY kode_kabupaten, {NAMA_KUNCI} HAVING max(panjang_ruas_km) > min(panjang_ruas_km) * 1.1"),
]

# nama kab/kota yang dipakai Kab DAN Kota (master tidak menyimpan awalan)
KEMBAR = ("SELECT kabupaten_kota FROM (SELECT DISTINCT kabupaten_kota, kode_kabupaten FROM penduduk_kecamatan) t "
          "GROUP BY 1 HAVING count(*) > 1")
AWALAN = r"^\s*(KAB(UPATEN)?\.?|KOTA)\s"
CEK_LOKUS = [
    ("V8", "Baris lokus/kawasan tematik tanpa kab/kota tercocokkan",
     "SELECT 'bappenas_lokus_a' AS tabel, kriteria AS kategori, provinsi_asli, kabupaten_asli, kecamatan_asli, sumber_sheet "
     "FROM bappenas_lokus_a WHERE level <> 'PROVINSI' AND kode_kabupaten IS NULL "
     "UNION ALL SELECT 'kawasan_tematik', kategori, provinsi_asli, kabupaten_asli, kecamatan_asli, sumber_sheet "
     "FROM kawasan_tematik WHERE kode_kabupaten IS NULL"),
    ("V9", "Lokus bernama kembar Kab/Kota tanpa awalan & tanpa kecamatan (konvensi -> Kabupaten, perlu konfirmasi)",
     "SELECT 'bappenas_lokus_a' AS tabel, kriteria AS kategori, provinsi_asli, kabupaten_asli, kode_kabupaten, sumber_sheet "
     f"FROM bappenas_lokus_a WHERE kriteria <> 'LOKPRI_RPJMN' AND kode_kecamatan IS NULL AND kabupaten_asli !~* %(awalan)s "
     f"AND upper(trim(kabupaten_asli)) IN ({KEMBAR}) "
     "UNION ALL SELECT 'kawasan_tematik', kategori, provinsi_asli, kabupaten_asli, kode_kabupaten, sumber_sheet "
     f"FROM kawasan_tematik WHERE kode_kecamatan IS NULL AND kabupaten_asli !~* %(awalan)s AND upper(trim(kabupaten_asli)) IN ({KEMBAR})"),
]
# LOKPRI_RPJMN dikecualikan dari V9: kabupaten_asli-nya diisi nama MASTER (bukan teks sumber),
# jenis Kab/Kota-nya sudah diputuskan importer dari teks kawasan (lihat _saring_kembar).


def q(sql, args=None):
    with db_cursor() as cur:
        cur.execute(sql, args)
        return [dict(r) for r in cur.fetchall()]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--xlsx", help="tulis rincian per baris ke file xlsx ini")
    args = ap.parse_args()
    if not q("SELECT to_regclass('public.usulan_inpres_riwayat') AS t")[0]["t"]:
        sys.exit("usulan_inpres_riwayat belum ada -- jalankan scripts/import_usulan_riwayat.py dulu")

    hasil = {}
    print("Usulan SITIA (penanganan jalan), jumlah temuan per tahun")
    for kode, judul, sql in CEK_USULAN:
        rows = q(sql)
        hasil[kode] = (judul, rows)
        per = {t: sum(1 for r in rows if r["tahun"] == t) for t in (2023, 2024, 2025, 2026)}
        print(f"  {kode} {judul}: {len(rows)}  " + "  ".join(f"{t}={n}" for t, n in per.items()))
    print("\nKonsistensi ruas lintas tahun (informasi)")
    for kode, judul, sql in CEK_INFO:
        rows = q(sql)
        hasil[kode] = (judul, rows)
        print(f"  {kode} {judul}: {len(rows)} ruas")
    print("\nData lokus Bappenas / kawasan tematik")
    for kode, judul, sql in CEK_LOKUS:
        rows = q(sql, {"awalan": AWALAN})
        hasil[kode] = (judul, rows)
        print(f"  {kode} {judul}: {len(rows)} baris")
        for r in rows[:8]:
            print(f"      {r['tabel']}/{r['kategori']}: {r['provinsi_asli']} | {r['kabupaten_asli']}")

    if args.xlsx:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Ringkasan"
        ws.append(["Kode", "Pemeriksaan", "Jumlah"])
        for kode, (judul, rows) in hasil.items():
            ws.append([kode, judul, len(rows)])
        for kode, (judul, rows) in hasil.items():
            if not rows:
                continue
            sh = wb.create_sheet(kode)
            sh.append([judul])
            sh.append(list(rows[0].keys()))
            for r in rows:
                sh.append([float(v) if hasattr(v, "is_finite") else v for v in r.values()])
        wb.save(args.xlsx)
        print(f"\nRincian ditulis ke {args.xlsx}")


if __name__ == "__main__":
    main()
