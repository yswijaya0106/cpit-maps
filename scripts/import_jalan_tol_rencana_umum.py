# -*- coding: utf-8 -*-
"""Impor Rencana Umum Jaringan Jalan Tol / Jalan Bebas Hambatan (JBH RENCUM,
28 Feb 2023) sbg layer overlay baru di bucket nasional flat "JALAN TOL".

Sumber: SHP JBHRENCUM_28022023 (Google Drive tautan "Data SHP Jalan Tol",
deck "20261007 PENAMBAHAN PENYEMPURNAAN SIJALAN" slide 1), RAR di
docs/07102026/Jalan Tol/. 362 ruas: operasi, operasi sebagian, konstruksi,
dan rencana (~13.000 km rencana) -- jauh lebih lengkap dari layer lama
"Jalan_Tol" (48 ruas, 2020), yang TIDAK disentuh skrip ini.

Warna per status (_warna/_lebar), keluarga merah sesuai hierarki jalan deck
slide 3 (tol = merah): operasi merah tua tebal, operasi sebagian merah,
konstruksi oranye, rencana ungu tua (merah muda tenggelam di basemap OSM). Legenda: TOL_STATUS_LEGEND
(maps-overlay.js), warnanya HARUS sama dgn STATUS_GAYA di sini.

Setelah impor, skrip menjalankan pengisian wilayah_provinsi (bucket flat
dipecah per provinsi di tree Overlay Peta) utk baris baru saja.

Usage (venv aktif, PG_* di .env):
    python scripts/import_jalan_tol_rencana_umum.py [--shp PATH | --rar PATH]
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import geopandas as gpd  # noqa: E402
import shapely  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from psycopg.types.json import Json  # noqa: E402
from pyproj import Geod  # noqa: E402

load_dotenv(REPO_ROOT / ".env")
from db import db_cursor  # noqa: E402

RAR_BAWAAN = REPO_ROOT / "docs" / "07102026" / "Jalan Tol" / "JBHRENCUM 28022023.rar"
BUCKET, KABUPATEN, LAYER = "JALAN TOL", "", "Rencana Umum Jalan Tol (JBH 2023)"
STATUS_GAYA = {  # Stat_Bang -> (warna, lebar px)
    "Operasi": ("#991b1b", 4),
    "Operasi Sebagian": ("#dc2626", 3.5),
    "Konstruksi": ("#f97316", 3),
    "Rencana": ("#6d28d9", 2.4),  # ungu tua: merah muda tenggelam di warna jalan basemap OSM
}
GAYA_LAIN = ("#9ca3af", 2)
KOLOM = [  # (kolom SHP, label atribut)
    ("Nm_Dat_Das", "Nama Ruas Tol"), ("Rcn_Tol", "Rencana Tol"), ("Rcn_NmRuas", "Rencana Nama Ruas"),
    ("Rcn_Segmen", "Segmen"), ("Stat_Bang", "Status Pembangunan"), ("Stat_Urn", "Status Urusan"),
    ("Bujt", "BUJT"), ("Thn_Ppjt", "Tanggal PPJT"), ("Rcn_ThTrgt", "Target Tahun"),
    ("Rcn_Prts", "Prioritas (jangka)"), ("Rcn_Sumber", "Sumber Rencana"), ("Rcn_Lintas", "Lintas"),
    ("CLASS", "Kelas (antar/dalam kota)"), ("Pulau", "Pulau"), ("Provinsi", "Provinsi"),
    ("Kab_Kot", "Kab/Kota"), ("Ket", "Keterangan Sumber"),
]
GEOD = Geod(ellps="WGS84")


def baca_shp(args):
    if args.shp:
        return gpd.read_file(args.shp, engine="pyogrio")
    tmp = tempfile.mkdtemp(prefix="jbh_")
    # RAR v5: bsdtar (libarchive) bisa membacanya; unrar >= 5 juga bisa.
    for cmd in (["bsdtar", "-xf", str(args.rar), "-C", tmp], ["unrar", "x", "-y", str(args.rar), tmp + "/"]):
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            break
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    else:
        sys.exit(f"Gagal mengekstrak {args.rar}: butuh bsdtar atau unrar, atau pakai --shp.")
    shp = next(Path(tmp).rglob("JBHRENCUM*.shp"), None)
    if not shp:
        sys.exit("File JBHRENCUM*.shp tidak ditemukan di arsip.")
    return gpd.read_file(shp, engine="pyogrio")


def nilai(v):
    if v is None or (isinstance(v, float) and v != v):
        return None
    s = str(v).strip()
    return s or None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shp", type=Path)
    ap.add_argument("--rar", type=Path, default=RAR_BAWAAN)
    args = ap.parse_args()

    gdf = baca_shp(args)
    if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)
    fitur, dilewati, km_status = [], 0, {}
    for _, r in gdf.iterrows():
        g = r.geometry
        if g is None or g.is_empty:
            dilewati += 1
            continue
        g = shapely.force_2d(g)
        if not g.is_valid:
            g = shapely.make_valid(g)
        km = GEOD.geometry_length(g) / 1000
        status = nilai(r.get("Stat_Bang")) or "Tidak diketahui"
        warna, lebar = STATUS_GAYA.get(status, GAYA_LAIN)
        attrs = {label: nilai(r.get(kol)) for kol, label in KOLOM if nilai(r.get(kol))}
        attrs["Panjang geometri (km)"] = round(km, 2)
        attrs["Sumber"] = "JBH RENCUM 28-02-2023 (BPJT/Bina Marga)"
        attrs["_warna"], attrs["_lebar"] = warna, lebar
        km_status[status] = km_status.get(status, 0) + km
        fitur.append((Json(attrs), g.wkb_hex))

    with db_cursor() as cur:
        cur.execute("DELETE FROM map_layers WHERE provinsi=%s AND kabupaten=%s AND layer=%s", (BUCKET, KABUPATEN, LAYER))
        cur.executemany(
            "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
            "VALUES (%s, %s, %s, %s, ST_SetSRID(ST_GeomFromWKB(decode(%s, 'hex')), 4326))",
            [(BUCKET, KABUPATEN, LAYER, a, wkb) for a, wkb in fitur])
        cur.execute(
            """INSERT INTO map_layer_meta (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (provinsi, kabupaten, layer) DO UPDATE SET
                   label=EXCLUDED.label, feature_count=EXCLUDED.feature_count,
                   size_mb=EXCLUDED.size_mb, source_shp=EXCLUDED.source_shp, imported_at=now()""",
            (BUCKET, KABUPATEN, LAYER, LAYER, len(fitur), round(sum(len(w) for _, w in fitur) / 2 / 1_048_576, 2),
             str(args.shp or args.rar)))
    print(f"Diimpor: {len(fitur)} ruas ({dilewati} geometri kosong dilewati)")
    for s, km in sorted(km_status.items(), key=lambda x: -x[1]):
        print(f"  {s:20s} {km:10,.0f} km")
    print("Mengisi wilayah_provinsi utk baris baru...")
    subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "build_map_layer_wilayah.py")], check=True)


if __name__ == "__main__":
    main()
