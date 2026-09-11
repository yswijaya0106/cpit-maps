"""
Cari titik potong (perlintasan sebidang) antara seluruh jaringan jalan
(Nasional/Provinsi/Kabupaten-Kota) dengan jalur rel kereta api, lalu tulis
hasilnya sebagai point shapefile.

Sumber:
- Rel KA: docs/New/.../Kereta Api/Rel KA_2022.shp (garis, atribut KETLAIN =
  jenis jalur, tidak ada nama rute per-segmen di sumber ini).
- Jalan Nasional: Maps/JALAN NASIONAL/Jalan Nasional.shp (kolom LINK_NAME).
- Jalan Provinsi: Maps/JALAN PROVINSI/Jalan Provinsi_up.shp (kolom RUAS).
- Jalan Kabupaten/Kota: Maps/<PROVINSI>/<KABUPATEN>/*.shp, ~234 file dengan
  skema kolom yang TIDAK seragam antar kabupaten (sudah didokumentasikan di
  CLAUDE.md) -> nama ruas diambil best-effort dari daftar kandidat nama
  kolom, provinsi/kabupaten dari nama folder.

Provinsi/kabupaten/kecamatan pada titik hasil TIDAK diambil dari atribut
sumber jalan (tidak konsisten), melainkan dari spatial join titik potong ke
polygon kecamatan resmi Maps/BATAS_ADMINISTRASI.gdb (layer
ADMINISTRASI_KECAMATAN_AR, WADMPR/WADMKK/WADMKC) -- sama seperti yang
dipakai import_batas_administrasi_kecamatan.py.

Usage: python scripts/build_jalan_rel_intersection.py [--out PATH.shp]
"""

import argparse
import glob
import os
import sys
import warnings

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import Point
from shapely.strtree import STRtree

warnings.filterwarnings("ignore")

MAPS_DIR = os.path.join(os.path.dirname(__file__), "..", "Maps")
REL_KA_SHP = os.path.join(
    os.path.dirname(__file__), "..",
    "docs", "New", "0. DATA SHP-20260820T015255Z-1-001", "0. DATA SHP",
    "Kereta Api", "Rel KA_2022.shp",
)
BATAS_GDB = os.path.join(MAPS_DIR, "BATAS_ADMINISTRASI.gdb")

# Folder-folder di Maps/ yang BUKAN provinsi berisi jalan kabupaten/kota
NON_PROVINSI_DIRS = {
    "BANDARA", "BATAS KECAMATAN", "BATAS_ADMINISTRASI.gdb", "IP2019-2024",
    "JALAN (mentah, belum diproses)", "JALAN NASIONAL", "JALAN PROVINSI",
    "JALAN TOL", "KONEKTIVITAS SIMPUL TRANSPORTASI", "PELABUHAN",
    "PELABUHAN LAUT", "PELABUHAN PENYEBRANGAN", "PETA KORIDOR",
}

# Kandidat nama kolom nama-ruas di shapefile jalan kabupaten/kota, berbagai
# skema yang ditemukan di sumber (lihat CLAUDE.md "234 per-kabupaten road
# SHPs" varying schema note) -- diurutkan dari yang paling sering dipakai
# (dicek langsung: "Nm_Ruas" muncul di 227/234 file, jauh di atas varian
# lain) supaya kolom nama yang benar-benar deskriptif diprioritaskan di atas
# kode/nomor ruas polos. "Tk_Ruas_Aw/Ak" (titik ruas awal/akhir, bukan nama
# ruas) sengaja TIDAK dimasukkan meski namanya mengandung "Ruas".
NAMA_RUAS_CANDIDATES = [
    "Nm_Ruas", "NM_RUAS", "Nama_Ruas", "NAMA_RUAS", "nama_ruas",
    "Nm_Ruas_1", "Nm_Ruas1", "NM_Ruas",
    "NAMA_JALAN", "Nama_Jalan", "NamaJalan", "namajalan",
    "RUAS_JALAN", "Ruas", "RUAS",
    "PKL_RUAS", "No_Ruas", "NO_RUAS", "No_Ruas1",
    "PENGENAL", "NAMOBJ",
]


def _find_name_column(columns):
    for c in NAMA_RUAS_CANDIDATES:
        if c in columns:
            return c
    return None


def load_rel_ka():
    gdf = gpd.read_file(REL_KA_SHP, engine="pyogrio")
    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)
    gdf = gdf[gdf.geometry.notna() & gdf.geometry.is_valid]
    return gdf[["KETLAIN", "geometry"]].rename(columns={"KETLAIN": "jenis_rel"})


def load_jalan_nasional():
    path = os.path.join(MAPS_DIR, "JALAN NASIONAL", "Jalan Nasional.shp")
    gdf = gpd.read_file(path, engine="pyogrio")
    gdf = gdf.to_crs(4326)
    gdf = gdf[gdf.geometry.notna() & gdf.geometry.is_valid]
    out = gdf[["LINK_NAME", "geometry"]].rename(columns={"LINK_NAME": "nama_jalan"})
    out["jenis_jalan"] = "Nasional"
    return out


def load_jalan_provinsi():
    path = os.path.join(MAPS_DIR, "JALAN PROVINSI", "Jalan Provinsi_up.shp")
    gdf = gpd.read_file(path, engine="pyogrio")
    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)
    gdf = gdf[gdf.geometry.notna() & gdf.geometry.is_valid]
    out = gdf[["RUAS", "geometry"]].rename(columns={"RUAS": "nama_jalan"})
    out["jenis_jalan"] = "Provinsi"
    return out


def load_jalan_kabupaten():
    frames = []
    provinsi_dirs = [
        d for d in sorted(os.listdir(MAPS_DIR))
        if os.path.isdir(os.path.join(MAPS_DIR, d)) and d not in NON_PROVINSI_DIRS
    ]
    for provinsi in provinsi_dirs:
        prov_path = os.path.join(MAPS_DIR, provinsi)
        kab_dirs = [
            d for d in sorted(os.listdir(prov_path))
            if os.path.isdir(os.path.join(prov_path, d))
        ]
        for kabupaten in kab_dirs:
            kab_path = os.path.join(prov_path, kabupaten)
            shps = glob.glob(os.path.join(kab_path, "*.shp"))
            for shp in shps:
                try:
                    gdf = gpd.read_file(shp, engine="pyogrio")
                except Exception as exc:
                    print(f"  [skip] {shp}: {exc}", file=sys.stderr)
                    continue
                if gdf.empty:
                    continue
                try:
                    if gdf.crs is None:
                        continue
                    if gdf.crs.to_epsg() != 4326:
                        gdf = gdf.to_crs(4326)
                except Exception as exc:
                    print(f"  [skip-crs] {shp}: {exc}", file=sys.stderr)
                    continue
                geom_types = set(gdf.geometry.geom_type.dropna())
                if not geom_types & {"LineString", "MultiLineString"}:
                    continue
                gdf = gdf[gdf.geometry.notna() & gdf.geometry.is_valid]
                if gdf.empty:
                    continue
                name_col = _find_name_column(gdf.columns)
                out = gpd.GeoDataFrame(geometry=gdf.geometry, crs=4326)
                out["nama_jalan"] = gdf[name_col].astype(str) if name_col else "-"
                out["jenis_jalan"] = "Kabupaten/Kota"
                out["provinsi_folder"] = provinsi
                out["kabupaten_folder"] = kabupaten
                frames.append(out)
    if not frames:
        return gpd.GeoDataFrame(
            columns=["nama_jalan", "jenis_jalan", "provinsi_folder", "kabupaten_folder", "geometry"],
            geometry="geometry", crs=4326,
        )
    return pd.concat(frames, ignore_index=True)


def compute_intersections(roads, rel_gdf):
    rel_geoms = list(rel_gdf.geometry)
    rel_tree = STRtree(rel_geoms)
    rel_attrs = rel_gdf["jenis_rel"].tolist()

    results = []
    road_geoms = roads.geometry.values
    for i in range(len(roads)):
        rgeom = road_geoms[i]
        if rgeom is None or rgeom.is_empty:
            continue
        idxs = rel_tree.query(rgeom)
        if len(idxs) == 0:
            continue
        row = roads.iloc[i]
        for j in idxs:
            rel_geom = rel_geoms[j]
            if not rgeom.intersects(rel_geom):
                continue
            inter = rgeom.intersection(rel_geom)
            if inter.is_empty:
                continue
            pts = []
            if inter.geom_type == "Point":
                pts = [inter]
            elif inter.geom_type == "MultiPoint":
                pts = list(inter.geoms)
            elif inter.geom_type == "GeometryCollection":
                pts = [g for g in inter.geoms if g.geom_type == "Point"]
            for p in pts:
                results.append({
                    "nama_jalan": row.get("nama_jalan"),
                    "jenis_jalan": row.get("jenis_jalan"),
                    "provinsi_f": row.get("provinsi_folder"),
                    "kabupaten_f": row.get("kabupaten_folder"),
                    "jenis_rel": rel_attrs[j],
                    "geometry": Point(p.x, p.y),
                })
    return results


def spatial_join_admin(points_gdf):
    try:
        kec = gpd.read_file(BATAS_GDB, layer="ADMINISTRASI_KECAMATAN_AR", engine="pyogrio")
    except Exception as exc:
        print(f"[warn] gagal baca BATAS_ADMINISTRASI.gdb: {exc}", file=sys.stderr)
        points_gdf["provinsi"] = None
        points_gdf["kabupaten"] = None
        points_gdf["kecamatan"] = None
        return points_gdf
    kec = kec[["WADMPR", "WADMKK", "WADMKC", "geometry"]]
    # Sumber CRS COMPD_CS (WGS84 horizontal + EGM2008 height) -- horizontal
    # part-nya sudah EPSG:4326, cukup buang Z (force_2d) lalu set ulang CRS
    # datar; to_crs() penuh di sini mencoba transform tinggi/Z dan meledak
    # memori pada geometri sepadat ini.
    kec["geometry"] = shapely.force_2d(kec.geometry.values)
    kec = kec.set_crs(4326, allow_override=True)
    joined = gpd.sjoin(points_gdf, kec, how="left", predicate="within")
    joined = joined.drop(columns=["index_right"], errors="ignore")
    joined = joined.rename(columns={"WADMPR": "provinsi", "WADMKK": "kabupaten", "WADMKC": "kecamatan"})
    joined = joined.loc[~joined.index.duplicated(keep="first")]
    return joined


def dedupe(points_gdf):
    points_gdf["_rx"] = points_gdf.geometry.x.round(5)
    points_gdf["_ry"] = points_gdf.geometry.y.round(5)
    points_gdf = points_gdf.drop_duplicates(subset=["_rx", "_ry", "nama_jalan", "jenis_rel"])
    return points_gdf.drop(columns=["_rx", "_ry"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(__file__), "..", "docs", "New",
        "titik_potong_jalan_rel_ka.shp",
    ))
    ap.add_argument("--skip-kabupaten", action="store_true",
                     help="hanya proses Jalan Nasional + Provinsi (lebih cepat, untuk uji coba)")
    args = ap.parse_args()

    print("Load rel KA...")
    rel_gdf = load_rel_ka()
    print(f"  {len(rel_gdf)} ruas rel")

    print("Load jalan nasional...")
    nasional = load_jalan_nasional()
    print(f"  {len(nasional)} ruas")

    print("Load jalan provinsi...")
    provinsi = load_jalan_provinsi()
    print(f"  {len(provinsi)} ruas")

    frames = [nasional, provinsi]

    if not args.skip_kabupaten:
        print("Load jalan kabupaten/kota (bisa beberapa menit, ~234 file)...")
        kabupaten = load_jalan_kabupaten()
        print(f"  {len(kabupaten)} ruas")
        frames.append(kabupaten)

    roads = pd.concat(frames, ignore_index=True)
    roads = gpd.GeoDataFrame(roads, geometry="geometry", crs=4326)
    print(f"Total ruas jalan: {len(roads)}")

    print("Hitung titik potong jalan x rel...")
    results = compute_intersections(roads, rel_gdf)
    print(f"  {len(results)} titik potong mentah")

    if not results:
        print("Tidak ada titik potong ditemukan.")
        return

    points_gdf = gpd.GeoDataFrame(results, geometry="geometry", crs=4326)
    points_gdf = dedupe(points_gdf)
    print(f"  {len(points_gdf)} titik setelah dedupe")

    print("Spatial join ke polygon kecamatan (provinsi/kabupaten/kecamatan)...")
    points_gdf = spatial_join_admin(points_gdf)

    points_gdf["lon"] = points_gdf.geometry.x.round(6)
    points_gdf["lat"] = points_gdf.geometry.y.round(6)

    out_cols = [
        "nama_jalan", "jenis_jalan", "jenis_rel",
        "provinsi", "kabupaten", "kecamatan", "lon", "lat", "geometry",
    ]
    points_gdf = points_gdf[out_cols]

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    points_gdf.to_file(args.out, engine="pyogrio")
    print(f"Selesai. Ditulis {len(points_gdf)} titik ke {args.out}")


if __name__ == "__main__":
    main()
