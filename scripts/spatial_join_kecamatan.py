# -*- coding: utf-8 -*-
"""Spatial-join geometri usulan Inpres x poligon batas kecamatan -> isi
usulan_inpres.kode_kecamatan otomatis (gap G16; menggantikan input manual
interim Fase 5 dan menghidupkan skor C.A1 kepadatan penduduk).

Sumber:
  - usulan_inpres.geom_geojson  : jalur usulan hasil scripts/fetch_kml_massal.py
  - Maps/BATAS KECAMATAN/*.shp  : poligon kecamatan nasional (Dukcapil 2019,
                                  atribut hanya NAMA kecamatan)
  - penduduk_kecamatan + wilayah_mapping : penerjemah nama poligon -> kode BPS

Metode per usulan: sampai 12 titik contoh di sepanjang jalur di-query ke
STRtree poligon; kecamatan pemenang = terbanyak menaungi titik. Nama poligon
diterjemahkan ke kode BPS lewat kabupaten usulan (wilayah_mapping) dulu —
ini sekaligus menyelesaikan homonim nasional (poligon senama tergabung di
SHP sumber) — fallback nama yang unik nasional.

Hanya mengisi baris yang kode_kecamatan-nya masih NULL (isian manual tidak
ditimpa); pakai --force untuk menghitung ulang semuanya.

Usage (venv aktif):
    python scripts/spatial_join_kecamatan.py
    python scripts/spatial_join_kecamatan.py --force
"""

import argparse
import io
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import geopandas as gpd
from shapely.strtree import STRtree

from app import _batas_kec_shp, _geojson_line_to_shapely, db_cursor  # noqa: E402


def norm(s):
    return " ".join(t for t in re.split(r"[^A-Z0-9]+", str(s).upper()) if t)


def norm_compact(s):
    """Kunci pencocokan longgar tanpa spasi -- SHP Dukcapil dan master BPS
    penduduk_kecamatan tidak selalu setuju soal spasi dalam nama kecamatan
    (mis. 'GUNUNGKENCANA' vs 'GUNUNG KENCANA', 'BALONGBENDO' vs 'BALONG
    BENDO' -- ±216 nama nasional kena pola ini, ditemukan 26 Jul 2026 lewat
    validasi usulan Sampay-Gunung Kencana yang kehilangan kecamatan tujuannya
    di usulan_kecamatan_dilalui). norm() saja tidak menangkap ini karena cuma
    menyeragamkan huruf besar/tanda baca, bukan spasi."""
    return norm(s).replace(" ", "")


def sample_points(geom, n=12):
    """Titik contoh tersebar merata di sepanjang LineString/MultiLineString."""
    lines = [geom] if geom.geom_type == "LineString" else list(geom.geoms)
    total = sum(l.length for l in lines) or 1
    pts = []
    for l in lines:
        k = max(1, round(n * l.length / total))
        for i in range(k):
            pts.append(l.interpolate((i + 0.5) / k, normalized=True))
    return pts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="hitung ulang termasuk yang sudah terisi")
    args = ap.parse_args()

    shp = _batas_kec_shp()
    if not shp:
        sys.exit("SHP batas kecamatan tidak ditemukan di Maps/BATAS KECAMATAN")
    print("Memuat poligon kecamatan (sekali, ±90MB)...")
    gdf = gpd.read_file(shp, engine="pyogrio")
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    gdf = gdf[gdf["KECAMATAN"].notna() & gdf.geometry.notna()]
    poly_names = [str(v) for v in gdf["KECAMATAN"]]
    tree = STRtree(list(gdf.geometry))
    print(f"  {len(poly_names)} poligon siap di-query")

    with db_cursor() as cur:
        cur.execute(
            "SELECT provinsi_sitia, kabupaten_kota_sitia, kode_kabupaten FROM wilayah_mapping "
            "WHERE kode_kabupaten IS NOT NULL"
        )
        kab_map = {(r["provinsi_sitia"], r["kabupaten_kota_sitia"]): r["kode_kabupaten"] for r in cur.fetchall()}
        cur.execute("SELECT kode_kabupaten, kecamatan, kode_kecamatan FROM penduduk_kecamatan")
        master = cur.fetchall()
        where = "" if args.force else "AND kode_kecamatan IS NULL"
        cur.execute(
            f"SELECT id, provinsi, kabupaten_kota, geom_geojson FROM usulan_inpres "
            f"WHERE geom_geojson IS NOT NULL {where}"
        )
        usulan = cur.fetchall()

    by_kab_nama = {}   # (kode_kab, norm_nama) -> kode_kecamatan
    by_nama = defaultdict(set)  # norm_nama -> {kode_kecamatan}
    by_kab_compact = {}   # (kode_kab, norm_compact) -> kode_kecamatan -- fallback varian spasi
    by_compact = defaultdict(set)  # norm_compact -> {kode_kecamatan}
    for m in master:
        by_kab_nama[(m["kode_kabupaten"], norm(m["kecamatan"]))] = m["kode_kecamatan"]
        by_nama[norm(m["kecamatan"])].add(m["kode_kecamatan"])
        by_kab_compact[(m["kode_kabupaten"], norm_compact(m["kecamatan"]))] = m["kode_kecamatan"]
        by_compact[norm_compact(m["kecamatan"])].add(m["kode_kecamatan"])

    print(f"Antrian spatial-join: {len(usulan)} usulan bergeometri")
    updates, alasan = [], Counter()
    for i, u in enumerate(usulan, start=1):
        try:
            geom = _geojson_line_to_shapely(json.loads(u["geom_geojson"]))
        except Exception:
            alasan["geometri tidak valid"] += 1
            continue
        votes = Counter()
        for pt in sample_points(geom):
            for idx in tree.query(pt, predicate="intersects"):
                votes[poly_names[idx]] += 1
        if not votes:
            alasan["di luar cakupan poligon"] += 1
            continue
        kode_kab = kab_map.get((u["provinsi"], u["kabupaten_kota"]))
        kode_kec = None
        for nama, _n in votes.most_common():
            n = norm(nama)
            kode_kec = by_kab_nama.get((kode_kab, n))
            if kode_kec is None and len(by_nama.get(n, ())) == 1:
                kode_kec = next(iter(by_nama[n]))
            if kode_kec is None:
                nc = norm_compact(nama)
                kode_kec = by_kab_compact.get((kode_kab, nc))
                if kode_kec is None and len(by_compact.get(nc, ())) == 1:
                    kode_kec = next(iter(by_compact[nc]))
            if kode_kec is not None:
                break
        if kode_kec is None:
            alasan["nama poligon tak terpetakan ke kode"] += 1
            continue
        updates.append((kode_kec, u["id"]))
        if i % 500 == 0:
            print(f"  ...{i}/{len(usulan)}")

    with db_cursor() as cur:
        cur.executemany("UPDATE usulan_inpres SET kode_kecamatan = %s WHERE id = %s", updates)
        cur.execute("SELECT COUNT(*) n FROM usulan_inpres WHERE kode_kecamatan IS NOT NULL")
        terisi = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) n FROM usulan_inpres")
        total = cur.fetchone()["n"]

    print(f"\nSelesai: {len(updates)} usulan terisi kode_kecamatan pada run ini; "
          f"total terisi {terisi}/{total}.")
    if alasan:
        for k, n in alasan.most_common():
            print(f"  gagal — {k}: {n}")


if __name__ == "__main__":
    main()
