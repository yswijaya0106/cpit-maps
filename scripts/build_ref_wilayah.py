"""Bangun tabel referensi wilayah berbasis ID (ref_wilayah) dari penduduk_kecamatan, lalu
isi kode_provinsi/kode_kabupaten di usulan_inpres dan usulan_inpres_riwayat.

Idempotent -- aman dijalankan ulang (TRUNCATE + INSERT ref_wilayah, UPDATE hanya baris yang
berubah). Jalankan setelah: import penduduk_kecamatan, build_wilayah_mapping.py, import usulan
(2026) atau import_usulan_riwayat.py.

Usage (venv aktif):
    python scripts/build_ref_wilayah.py

Lihat wilayah_id.py dan docs/kajian_validasi_id_wilayah.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import wilayah_id  # noqa: E402
from db import db_cursor  # noqa: E402


def main():
    with db_cursor() as cur:
        n = wilayah_id.build_ref_wilayah(cur)
        print(f"ref_wilayah: {n} kecamatan")
        cur.execute("SELECT COUNT(DISTINCT kode_provinsi) AS p, COUNT(DISTINCT kode_kabupaten) AS k FROM ref_wilayah")
        r = cur.fetchone()
        print(f"  {r['p']} provinsi, {r['k']} kabupaten/kota")
        print("usulan_inpres: baris diperbarui kode wilayahnya =", wilayah_id.isi_kode_usulan(cur))
        cur.execute("SELECT to_regclass('public.usulan_inpres_riwayat') AS t")
        if cur.fetchone()["t"]:
            print("usulan_inpres_riwayat:", wilayah_id.isi_kode_riwayat(cur))
        else:
            print("usulan_inpres_riwayat belum ada -- dilewati")


if __name__ == "__main__":
    main()
