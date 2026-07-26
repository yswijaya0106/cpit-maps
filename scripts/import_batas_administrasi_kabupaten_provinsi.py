# -*- coding: utf-8 -*-
"""Impor layer Area_Batas_Wilayah_Administrasi dari Maps/BATAS_ADMINISTRASI.gdb
(BIG) ke PostgreSQL/PostGIS sbg DUA overlay peta baru: "BATAS KABUPATEN" dan
"BATAS PROVINSI" -- pelengkap "BATAS KECAMATAN" yang sudah diimpor lewat
scripts/import_batas_administrasi_kecamatan.py (lihat catatan di sana utk
alasan sumber ini dipilih drpd Maps/BATAS KECAMATAN/ SHP Dukcapil lama).

Sumber gdb ini TIDAK punya layer poligon provinsi bersih (satu baris per
provinsi) -- yang ada cuma Area_Batas_Wilayah_Administrasi berisi poligon
kabupaten/kota (TIPADM 4=kabupaten, 5=kota, ~518 baris nasional, kolom
WADMKK terisi) PLUS sisa pecahan pulau tanpa kabupaten (TIPADM=6, WADMKK
kosong -- mis. beberapa pulau lepas Maluku/Sumatera Barat yg tak masuk
potongan kabupaten manapun di sumber ini). Poligon provinsi dibangun sendiri
di sini lewat geopandas dissolve() atas SELURUH baris (TIPADM 4/5/6)
dikelompokkan per WADMPR -- kalau TIPADM=6 dilewatkan, sebagian pulau kecil
akan hilang dari poligon provinsi hasil dissolve.

Struktur map_layers (provinsi/kabupaten/layer) reuse pola yg sama dgn
kecamatan:
  - "BATAS KABUPATEN": provinsi=BATAS_KAB_DIRNAME (konstan), kabupaten=nama
    provinsi asli, layer="Kabupaten/Kota" (SATU layer per provinsi berisi
    SEMUA poligon kabupaten/kota provinsi itu -- sama pola dgn "BATAS
    KECAMATAN" yg satu layer per kabupaten berisi semua poligon kecamatan).
    Endpoint /api/maps/* generik otomatis melayani hierarki provinsi ->
    kabupaten/kota TANPA kode tambahan di app.py, identik dgn kecamatan.
  - "BATAS PROVINSI": provinsi=BATAS_PROV_DIRNAME (konstan), kabupaten=""
    (flat nasional, sama pola dgn JALAN NASIONAL/JALAN TOL), layer="Provinsi"
    -- SATU layer nasional berisi 34 poligon provinsi hasil dissolve.

KODE_KABUPATEN/KODE_PROVINSI dicocokkan best-effort ke penduduk_kecamatan
(reuse matcher dari import_batas_administrasi_kecamatan) utk konsistensi/
potensi join di masa depan -- TIDAK ada endpoint yg butuh ini sekarang
(kecamatan_join_data di app.py cuma terima kode_kecamatan), jadi kegagalan
match di sini tidak mempengaruhi fungsi apa pun saat ini.

Usage (venv aktif):
    python scripts/import_batas_administrasi_kabupaten_provinsi.py
"""
import io
import os
import sys
import time
from functools import reduce
from pathlib import Path

os.environ.setdefault("SHAPE_RESTORE_SHX", "YES")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import geopandas as gpd
import shapely
from psycopg.types.json import Json

from db import db_cursor as pg_cursor  # noqa: E402
from import_batas_administrasi_kecamatan import (  # noqa: E402 -- reuse, bukan tulis ulang
    norm, norm_compact, build_master_index, match_kode_kabupaten, kabupaten_label,
)

GDB_PATH = Path(__file__).resolve().parent.parent / "Maps" / "BATAS_ADMINISTRASI.gdb"
LAYER_NAME = "Area_Batas_Wilayah_Administrasi"
BATAS_KAB_DIRNAME = "BATAS KABUPATEN"
BATAS_PROV_DIRNAME = "BATAS PROVINSI"
KAB_LAYER_NAME = "Kabupaten/Kota"
PROV_LAYER_NAME = "Provinsi"
SIMPLIFY_TOLERANCE = 0.00015  # ~15-17m, sama dgn maps_layer() di app.py & import kecamatan
INSERT_BATCH = 2000


def _clean_geom(geom):
    """force_2d + simplify, atau None kalau geometri rusak/kosong -- pola sama
    dgn import_batas_administrasi_kecamatan.py, DITAMBAH validasi ulang
    setelah simplify: simplify(preserve_topology=True) terbukti (27 Jul 2026,
    Aceh/Gorontalo/NTB/NTT/4 provinsi Sulawesi -- semua padat kepulauan)
    kadang menghasilkan poligon SELF-INTERSECT walau input union-nya valid,
    walau preserve_topology semestinya mencegah ini. Tanpa cek ulang di sini,
    8/38 provinsi tersenyapkan hilang total dari peta. buffer(0) adalah
    perbaikan standar shapely utk self-intersection minor; kalau itu pun
    masih invalid, pakai geometri UTUH (belum disederhanakan) drpd membuang
    seluruh provinsi -- payload lebih besar tapi provinsinya tetap tampil."""
    if geom is None or geom.is_empty or not geom.is_valid:
        return None
    if geom.has_z:
        geom = shapely.force_2d(geom)
    try:
        simplified = geom.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)
        if simplified.is_valid and not simplified.is_empty:
            return simplified
        repaired = simplified.buffer(0)
        if repaired.is_valid and not repaired.is_empty:
            return repaired
    except Exception:
        pass
    return geom


def build_provinsi_index(cur):
    """provinsi_norm -> kode_provinsi, dari penduduk_kecamatan."""
    cur.execute("SELECT DISTINCT kode_provinsi, provinsi FROM penduduk_kecamatan")
    return {norm(r["provinsi"]): r["kode_provinsi"] for r in cur.fetchall()}


def import_kabupaten(cur, gdf, kab_idx, kab_idx2):
    sub = gdf[gdf["TIPADM"].isin([4, 5])].copy()
    print(f"  {len(sub)} poligon kabupaten/kota definitif")

    cur.execute("DELETE FROM map_layers WHERE provinsi=%s", (BATAS_KAB_DIRNAME,))
    cur.execute("DELETE FROM map_layer_meta WHERE provinsi=%s", (BATAS_KAB_DIRNAME,))

    rows = []
    meta_counts = {}
    n_bad = n_miss = 0
    for _, r in sub.iterrows():
        geom = _clean_geom(r["geometry"])
        if geom is None:
            n_bad += 1
            continue
        provinsi = str(r["WADMPR"]).strip()
        wadmkk = str(r["WADMKK"]).strip()
        kab_label = kabupaten_label(wadmkk)
        kode_kab = match_kode_kabupaten(kab_idx, kab_idx2, provinsi, wadmkk)
        if kode_kab is None:
            n_miss += 1
        attrs = {
            "KABUPATEN_KOTA": kab_label,
            "PROVINSI": provinsi,
            "KODE_KABUPATEN": kode_kab,
        }
        rows.append((BATAS_KAB_DIRNAME, provinsi, KAB_LAYER_NAME, Json(attrs), geom.wkb_hex))
        meta_counts[provinsi] = meta_counts.get(provinsi, 0) + 1

    if n_bad:
        print(f"    ({n_bad} fitur geometri rusak/kosong dilewati)")
    print(f"    kode_kabupaten tidak match ke penduduk_kecamatan: {n_miss}/{len(sub)}")

    for i in range(0, len(rows), INSERT_BATCH):
        chunk = rows[i:i + INSERT_BATCH]
        cur.executemany(
            "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
            "VALUES (%s, %s, %s, %s, ST_GeomFromWKB(decode(%s, 'hex'), 4326))",
            chunk,
        )
    for provinsi, n in meta_counts.items():
        cur.execute(
            """INSERT INTO map_layer_meta
                   (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp)
               VALUES (%s, %s, %s, %s, %s, NULL, %s)
               ON CONFLICT (provinsi, kabupaten, layer) DO UPDATE SET
                   label=EXCLUDED.label, feature_count=EXCLUDED.feature_count, imported_at=now()""",
            (BATAS_KAB_DIRNAME, provinsi, KAB_LAYER_NAME, f"{KAB_LAYER_NAME} ({n} kab/kota)", n,
             "BATAS_ADMINISTRASI.gdb::Area_Batas_Wilayah_Administrasi"),
        )
    print(f"  -> {len(rows)} poligon kabupaten/kota diimpor ke {len(meta_counts)} provinsi")


def import_provinsi(cur, gdf, prov_idx):
    # SEMUA baris (4/5/6) diikutkan dlm dissolve -- TIPADM=6 = pecahan pulau
    # tanpa kabupaten yg tetap bagian wilayah provinsinya, lihat docstring modul.
    sub = gdf[gdf["WADMPR"].notna() & (gdf["WADMPR"] != "")].copy()
    print(f"  Dissolve {len(sub)} poligon (kabupaten + pecahan tanpa kabupaten) -> per provinsi...")

    # Union berpasangan (bukan geopandas dissolve()/unary_union) -- unary_union
    # HIT bug yg sama persis dgn _geojson_line_to_shapely: shapely/numpy di sini
    # gagal bikin GEOMETRYCOLLECTION dari array geometri hasil groupby (vectorized
    # union_all()); .union() binary tiap panggilan menghindari jalur itu, sama
    # pola dgn import_indeks_penanaman_raster.py::build_kabupaten_polygons().
    groups = {}
    for _, r in sub.iterrows():
        geom = _clean_geom(r["geometry"])
        if geom is None:
            continue
        groups.setdefault(str(r["WADMPR"]).strip(), []).append(geom)
    print(f"  {len(groups)} provinsi hasil dissolve")

    cur.execute("DELETE FROM map_layers WHERE provinsi=%s", (BATAS_PROV_DIRNAME,))
    cur.execute("DELETE FROM map_layer_meta WHERE provinsi=%s", (BATAS_PROV_DIRNAME,))

    rows = []
    n_bad = n_miss = 0
    for provinsi, geoms in groups.items():
        try:
            merged = reduce(lambda a, b: a.union(b), geoms)
            merged = _clean_geom(merged)
        except Exception:
            merged = None
        if merged is None:
            n_bad += 1
            continue
        kode_prov = prov_idx.get(norm(provinsi))
        if kode_prov is None:
            n_miss += 1
        attrs = {"PROVINSI": provinsi, "KODE_PROVINSI": kode_prov}
        rows.append((BATAS_PROV_DIRNAME, "", PROV_LAYER_NAME, Json(attrs), merged.wkb_hex))

    if n_bad:
        print(f"    ({n_bad} fitur geometri rusak/kosong dilewati)")
    print(f"    kode_provinsi tidak match ke penduduk_kecamatan: {n_miss}/{len(groups)}")

    for i in range(0, len(rows), INSERT_BATCH):
        chunk = rows[i:i + INSERT_BATCH]
        cur.executemany(
            "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
            "VALUES (%s, %s, %s, %s, ST_GeomFromWKB(decode(%s, 'hex'), 4326))",
            chunk,
        )
    cur.execute(
        """INSERT INTO map_layer_meta
               (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp)
           VALUES (%s, %s, %s, %s, %s, NULL, %s)
           ON CONFLICT (provinsi, kabupaten, layer) DO UPDATE SET
               label=EXCLUDED.label, feature_count=EXCLUDED.feature_count, imported_at=now()""",
        (BATAS_PROV_DIRNAME, "", PROV_LAYER_NAME, f"{PROV_LAYER_NAME} ({len(rows)} provinsi)",
         len(rows), "BATAS_ADMINISTRASI.gdb::Area_Batas_Wilayah_Administrasi (dissolve)"),
    )
    print(f"  -> {len(rows)} poligon provinsi diimpor")


def main():
    if not GDB_PATH.exists():
        sys.exit(f"Tidak ditemukan: {GDB_PATH}")

    t0 = time.time()
    print("Membaca layer geometri...")
    gdf = gpd.read_file(GDB_PATH, layer=LAYER_NAME, engine="pyogrio")
    print(f"  {len(gdf)} poligon dibaca ({time.time() - t0:.1f}s)")

    with pg_cursor() as cur:
        kab_idx, kab_idx2, _kec_by_kab = build_master_index(cur)
        prov_idx = build_provinsi_index(cur)

        print("\nImpor BATAS KABUPATEN...")
        import_kabupaten(cur, gdf, kab_idx, kab_idx2)

        print("\nImpor BATAS PROVINSI (dissolve dari kabupaten)...")
        import_provinsi(cur, gdf, prov_idx)

    print(f"\nSelesai, {time.time() - t0:.1f}s total")


if __name__ == "__main__":
    main()
