# -*- coding: utf-8 -*-
"""Jalankan berurutan seluruh pipeline yang perlu di-refresh setelah usulan
Inpres berubah (reimport xlsx baru, atau geometri usulan diperbarui):

  1. import_usulan_inpres.py <xlsx>  -- upsert usulan_inpres (lewati kalau
     import sudah dilakukan lewat /api/usulan-inpres/import di browser,
     xlsx argumen opsional)
  2. fetch_kml_massal.py             -- isi geom_geojson yang masih kosong
  3. spatial_join_kecamatan.py       -- isi kode_kecamatan (dominan)
  4. spatial_join_kecamatan_multi.py -- isi usulan_kecamatan_dilalui (semua
     kecamatan yang dilewati, bukan cuma yang dominan)
  5. spatial_join_koridor_radius.py  -- isi koridor_radius_50m (IJD D
     "tidak langsung")

Cuma pembungkus urutan -- TIDAK ada logika baru di sini, tiap langkah
tetap script aslinya (dipanggil via subprocess, python venv yang sama).
Aman dijalankan berulang, tapi kecepatannya BEDA per langkah: 2/3/5
(fetch_kml_massal, spatial_join_kecamatan, spatial_join_koridor_radius)
idempotent -- cuma proses baris yang kolomnya masih NULL kecuali --force,
jadi usulan lama yang datanya sudah lengkap otomatis dilewati. Langkah 4
(spatial_join_kecamatan_multi) BUKAN pola itu -- dia DELETE + hitung ulang
usulan_kecamatan_dilalui utk SEMUA usulan bergeometri tiap kali dijalankan
(desain aslinya, bukan keputusan di wrapper ini), jadi durasinya relatif
konstan tidak peduli seberapa banyak yang benar-benar baru.

Berhenti di langkah pertama yang gagal (exit code != 0) -- tidak lanjut ke
langkah berikutnya kalau satu gagal, supaya tidak menganggap pipeline utuh
padahal ada yang kepotong di tengah.

Usage (venv aktif):
    python scripts/sync_usulan_pipeline.py docs/usulan_terbaru.xlsx
    python scripts/sync_usulan_pipeline.py                      # skip step 1 (xlsx sudah diimpor lewat browser)
    python scripts/sync_usulan_pipeline.py --force-kecamatan --force-koridor
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent


def _run(label: str, args: list[str]) -> None:
    print(f"\n{'=' * 60}\n{label}\n{'=' * 60}", flush=True)
    t0 = time.time()
    result = subprocess.run([sys.executable, *args], cwd=SCRIPTS_DIR.parent)
    dt = time.time() - t0
    if result.returncode != 0:
        sys.exit(f"\nGAGAL di langkah '{label}' (exit code {result.returncode}, {dt:.1f}s) — berhenti, langkah setelahnya tidak dijalankan.")
    print(f"-- selesai '{label}' dlm {dt:.1f}s --", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xlsx", nargs="?", default=None,
                     help="path xlsx SITIA utk diimpor (opsional -- lewati kalau sudah diimpor lewat browser)")
    ap.add_argument("--fetch-workers", type=int, default=6, help="paralelisme fetch KML (diteruskan ke fetch_kml_massal.py)")
    ap.add_argument("--force-kecamatan", action="store_true", help="hitung ulang kode_kecamatan yg sudah terisi juga")
    ap.add_argument("--force-koridor", action="store_true", help="hitung ulang koridor_radius_50m yg sudah terisi juga")
    args = ap.parse_args()

    t_mulai = time.time()

    if args.xlsx:
        _run("1/5 Import usulan_inpres (xlsx)", ["scripts/import_usulan_inpres.py", args.xlsx])
    else:
        print("Melewati langkah 1 (import xlsx) -- tidak ada file diberikan, asumsi sudah diimpor lewat browser.")

    _run("2/5 Fetch geometri KML (geom_geojson)", ["scripts/fetch_kml_massal.py", "--workers", str(args.fetch_workers)])
    _run("3/5 Spatial join kecamatan dominan (kode_kecamatan)",
         ["scripts/spatial_join_kecamatan.py", *(["--force"] if args.force_kecamatan else [])])
    _run("4/5 Spatial join kecamatan dilalui (usulan_kecamatan_dilalui)",
         ["scripts/spatial_join_kecamatan_multi.py"])
    _run("5/5 Spatial join radius koridor (koridor_radius_50m)",
         ["scripts/spatial_join_koridor_radius.py", *(["--force"] if args.force_koridor else [])])

    print(f"\nPipeline selesai dlm {time.time() - t_mulai:.1f}s total.")


if __name__ == "__main__":
    main()
