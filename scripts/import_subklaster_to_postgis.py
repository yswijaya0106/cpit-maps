# -*- coding: utf-8 -*-
"""Impor SHP Klaster/Subklaster (docs/250820206/SHP Subklaster/, versi
17-09-2026) ke map_layers sebagai overlay peta umum.

Cakupan: Kabupaten Merauke dsk. (Papua Selatan, bbox ~138,2-141,0 BT /
6,3-8,7 LS) -- rencana klaster Tanaman Pangan, Perkebunan Tebu, Perkebunan
Sawit, dan Peternakan periode 2026-2029.

Dua sumber, dua jenis layer (bucket nasional flat "KLASTER SUBKLASTER",
kabupaten=""):

- Klaster_subklaster_170926_dissolve.shp (32 poligon) -> layer "SUBKLASTER":
  satu poligon per (Klaster, Subklaster), ringan, untuk gambaran umum.
- Klaster_subklaster_170926.shp (10.328 poligon, dipecah per pola ruang /
  fungsi kawasan / tutupan lahan) -> satu layer "SUBKLASTER DETAIL - <klaster>"
  per klaster, karena gabungannya ~20 MB GeoJSON (Tanaman Pangan sendiri
  ~7.400 poligon) -- dipecah supaya user bisa menyalakan klaster yang
  dibutuhkan saja.

Proyeksi sumber World Cylindrical Equal Area (ESRI:54034) -> EPSG:4326.
Geometri disederhanakan saat impor (SIMPLIFY_DERAJAT, ~10 m) -- sumbernya
sangat rapat verteksnya; layer detail >3000 fitur masih disederhanakan lagi
oleh maps_layer() di app.py saat dibaca.

Warna poligon per klaster dikirim lewat properti `_warna` (dibaca
applyLayerStyle di maps-overlay.js; atribut berawalan `_` disembunyikan dari
popup identify). Nilai warna harus sama dgn KLASTER_LEGEND di maps-overlay.js.

Luas diambil dari kolom `Luas_hacea` (ha); kolom `Luas` di sumber tidak
konsisten dengan geometri per-baris sehingga tidak dipakai.

TIDAK terkait usulan_inpres/IJD.

Idempotent: DELETE + reinsert seluruh bucket tiap run.

Usage (venv aktif):
    python scripts/import_subklaster_to_postgis.py
"""
import io
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import geopandas as gpd
import shapely
from psycopg.types.json import Json

from db import db_cursor as pg_cursor  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE_DIR = REPO_ROOT / "docs" / "250820206" / "SHP Subklaster"
SHP_DISSOLVE = BASE_DIR / "Klaster_subklaster_170926_dissolve.shp"
SHP_DETAIL = BASE_DIR / "Klaster_subklaster_170926.shp"

PROVINSI = "KLASTER SUBKLASTER"
KABUPATEN = ""
LAYER_RINGKAS = "SUBKLASTER"
LAYER_DETAIL_PREFIX = "SUBKLASTER DETAIL - "
SIMPLIFY_DERAJAT = 0.0001

KLASTER_WARNA = {
    "Klaster Tanaman Pangan": "#E6B800",
    "Klaster Perkebunan Tebu": "#009E73",
    "Klaster Perkebunan Sawit": "#D55E00",
    "Klaster Peternakan": "#CC79A7",
}
WARNA_LAIN = "#8a94a6"


def _bersih(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, str):
        v = " ".join(v.split())
        return v or None
    return v


def _baca(path):
    gdf = gpd.read_file(path, engine="pyogrio")
    gdf = gdf.to_crs(epsg=4326)
    gdf["geometry"] = gdf.geometry.simplify(SIMPLIFY_DERAJAT, preserve_topology=True)
    return gdf


def _geom_hex(geom):
    if geom is None or geom.is_empty:
        return None
    if geom.has_z:
        geom = shapely.force_2d(geom)
    if not geom.is_valid:
        geom = shapely.make_valid(geom)
        if geom.is_empty:
            return None
    return geom.wkb_hex


def _attrs_ringkas(row):
    return {
        "Klaster": _bersih(row["Klaster"]),
        "Subklaster": _bersih(row["Subklaster"]),
        "Keterangan AOI": _bersih(row["Ket_AOI"]),
        "Luas (ha)": round(float(row["Luas_hacea"]), 2),
        "_warna": KLASTER_WARNA.get(row["Klaster"], WARNA_LAIN),
    }


def _attrs_detail(row):
    kode = _bersih(row["Kode"])
    return {
        "Klaster": _bersih(row["Klaster"]),
        "Subklaster": _bersih(row["Subklaster"]),
        "Sektor": _bersih(row["Sektor"]),
        "Periode": _bersih(row["Periode"]),
        "Tahun": _bersih(row["Tahun"]),
        "Perusahaan Tebu": _bersih(row["TAN_TEBU"]),
        "Keterangan AOI": _bersih(row["Ket_AOI"]),
        "Pola Ruang": _bersih(row["NAMOBJ"]),
        "Fungsi Kawasan": _bersih(row["F_update"]),
        "Tutupan Lahan": _bersih(row["Keterang_2"]),
        "Kode Tutupan Lahan": f"{_bersih(row['Toponimi'])} ({int(kode)})" if kode is not None else _bersih(row["Toponimi"]),
        "Status Cagar Budaya": _bersih(row["S_Cagbud"]),
        "Cagar Budaya (Wilayah Adat)": _bersih(row["CAGBUD"]),
        "Status Preservasi": _bersih(row["S_Preserva"]),
        "Lokus Preservasi": _bersih(row["Nama_Lokus"]),
        "Nilai Penting (Fauna)": _bersih(row["NP"]),
        "Luas (ha)": round(float(row["Luas_hacea"]), 2),
        "_warna": KLASTER_WARNA.get(row["Klaster"], WARNA_LAIN),
    }


def _simpan_layer(cur, layer, label, gdf, attrs_fn, source):
    records = []
    for _, row in gdf.iterrows():
        gh = _geom_hex(row.geometry)
        if gh is None:
            continue
        attrs = {k: v for k, v in attrs_fn(row).items() if v is not None}
        records.append((PROVINSI, KABUPATEN, layer, Json(attrs), gh))
    cur.executemany(
        "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
        "VALUES (%s, %s, %s, %s, ST_GeomFromWKB(decode(%s, 'hex'), 4326))",
        records,
    )
    size_mb = round(sum(len(r[4]) / 2 for r in records) / 1_048_576, 2)
    cur.execute(
        """INSERT INTO map_layer_meta
               (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (PROVINSI, KABUPATEN, layer, label, len(records), size_mb, str(source.relative_to(REPO_ROOT))),
    )
    print(f"  {label}: {len(records)} poligon (~{size_mb} MB WKB)")


def main():
    for p in (SHP_DISSOLVE, SHP_DETAIL):
        if not p.exists():
            print(f"GAGAL: tidak ditemukan {p}")
            sys.exit(1)

    print(f"Membaca {SHP_DISSOLVE.name}...")
    ringkas = _baca(SHP_DISSOLVE)
    print(f"Membaca {SHP_DETAIL.name}...")
    detail = _baca(SHP_DETAIL)

    with pg_cursor() as cur:
        cur.execute("DELETE FROM map_layers WHERE provinsi=%s", (PROVINSI,))
        cur.execute("DELETE FROM map_layer_meta WHERE provinsi=%s", (PROVINSI,))
        _simpan_layer(cur, LAYER_RINGKAS, "Subklaster (ringkas, per subklaster)",
                      ringkas, _attrs_ringkas, SHP_DISSOLVE)
        for klaster in sorted(detail["Klaster"].dropna().unique()):
            nama = klaster.removeprefix("Klaster ").upper()
            _simpan_layer(cur, LAYER_DETAIL_PREFIX + nama, f"Detail {klaster} (per pola ruang/tutupan lahan)",
                          detail[detail["Klaster"] == klaster], _attrs_detail, SHP_DETAIL)

    print(f"Selesai: bucket '{PROVINSI}' diimpor. Restart server bila layer ini sudah pernah dibuka "
          "(cache _map_layer_geojson_cache).")


if __name__ == "__main__":
    main()
