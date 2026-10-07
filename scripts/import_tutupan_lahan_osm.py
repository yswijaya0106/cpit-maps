# -*- coding: utf-8 -*-
"""Tutupan lahan pertanian/perkebunan dari OpenStreetMap -> bucket overlay
"TUTUPAN LAHAN OSM" di map_layers.

Latar (5 Okt 2026, permintaan pengguna): kawasan spt kebun kelapa sawit sudah
tampak di basemap OSM, tapi hanya sbg gambar tile -- tidak bisa diklik, tidak
masuk legenda, tidak ikut cetak/ekspor. Skrip ini menarik poligonnya sbg layer
overlay biasa. Pelengkap (bukan pengganti) build_kawasan_tematik_layer.py, yg
memetakan daftar resmi Bappenas.

Sifat data -- tampilkan apa adanya, jangan diperlakukan sbg data resmi:
- Cakupan OSM sangat tidak merata (uji 5 Okt 2026: Kalimantan Selatan hanya 77
  poligon sawit, Jawa Barat 59). Tidak ada poligon != tidak ada kebun.
- Tidak dipakai skoring IJD mana pun.
- Lisensi ODbL: atribut "Sumber" tiap fitur memuat atribusi wajib.

Sumber: ekstrak OSM Indonesia (.osm.pbf, ~2 GB) dari
https://download.openstreetmap.fr/extracts/asia/indonesia-latest.osm.pbf, disimpan
di Maps/OSM/ (Maps/ di-gitignore). Dua tahap:
1. --ekstrak: GDAL (driver OSM, merakit multipolygon/relasi) membaca layer
   multipolygons PBF dgn filter tag -> Maps/OSM/tutupan_lahan_osm.gpkg (kecil).
   Lama (puluhan menit) & butuh beberapa GB berkas temp -- jalankan di laptop,
   bukan di staging (disk staging sempit).
2. (default) GeoPackage itu -> map_layers. Untuk staging cukup salin .gpkg-nya.
Overpass API sempat dicoba (5 Okt 2026) tapi semua mirror publik 504/timeout
untuk kueri per provinsi; Geofabrik terlalu lambat dari jaringan kantor.

Klasifikasi (urutan prioritas, satu kategori per poligon) ada di klasifikasi().

DELETE + INSERT seluruh bucket, lalu wilayah_provinsi dihitung di sini (logika
sama dgn build_map_layer_wilayah.py) supaya pemecahan per provinsi di tree
Overlay Peta langsung aktif. Restart server tidak perlu: imported_at baru ->
cache layer basi otomatis.

Usage (venv aktif, .env berisi PG_*):
    python scripts/import_tutupan_lahan_osm.py --ekstrak      # PBF -> gpkg, lalu impor
    python scripts/import_tutupan_lahan_osm.py                # impor gpkg yg sudah ada
"""
import argparse
import io
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
import pyogrio  # noqa: E402
from psycopg.types.json import Json  # noqa: E402
from shapely import make_valid  # noqa: E402

from db import db_cursor  # noqa: E402

BUCKET = "TUTUPAN LAHAN OSM"
DIR_OSM = ROOT / "Maps" / "OSM"
PBF = DIR_OSM / "indonesia-latest.osm.pbf"
GPKG = DIR_OSM / "tutupan_lahan_osm.gpkg"
ATRIBUSI = "© OpenStreetMap contributors (ODbL)"
CATATAN = "Indikatif: dipetakan sukarelawan OSM, cakupan tidak merata; bukan data resmi"
# filter kasar di GDAL; klasifikasi() yg memutuskan (mis. tag "rubber" lain -> dibuang)
FILTER_TAG = ("landuse IN ('orchard','plantation','farmland','paddy','aquaculture','salt_pond') "
              "OR other_tags LIKE '%oil_palm%' OR other_tags LIKE '%palm_oil%' "
              "OR other_tags LIKE '%rubber%' OR other_tags LIKE '%coconut%'")
KOLOM = ["osm_id", "osm_way_id", "name", "landuse", "other_tags"]

LAYER_SAWIT = "Kelapa Sawit (OSM)"
LAYER_KARET = "Karet (OSM)"
LAYER_KELAPA = "Kelapa (OSM)"
LAYER_KEBUN = "Kebun & Perkebunan Lainnya (OSM)"
LAYER_SAWAH = "Sawah (OSM)"
LAYER_TANI = "Lahan Pertanian Lainnya (OSM)"
LAYER_TAMBAK = "Tambak & Tambak Garam (OSM)"

_TAG = re.compile(r'"((?:[^"\\]|\\.)*)"=>"((?:[^"\\]|\\.)*)"')


def tag_lain(s):
    return {k: v for k, v in _TAG.findall(s or "")}


def klasifikasi(landuse, tags, nama):
    """-> nama layer, atau None (mis. landuse lain yg ikut terambil lewat trees=)."""
    teks = " ".join(str(tags.get(k, "")) for k in ("trees", "crop", "produce")).lower()
    nm = (nama or "").lower()
    if "oil_palm" in teks or "palm_oil" in teks or "palm oil" in teks or "sawit" in nm or "sawit" in teks:
        return LAYER_SAWIT
    if "rubber" in teks or "karet" in nm:
        return LAYER_KARET
    if "coconut" in teks or re.search(r"\bkelapa\b", nm):
        return LAYER_KELAPA
    if landuse in ("orchard", "plantation"):
        return LAYER_KEBUN
    if landuse == "paddy" or re.search(r"rice|paddy", teks) or "sawah" in nm:
        return LAYER_SAWAH
    if landuse == "farmland":
        return LAYER_TANI
    if landuse in ("aquaculture", "salt_pond"):
        return LAYER_TAMBAK
    return None


def ekstrak():
    """PBF -> GPKG berisi poligon kandidat saja (layer multipolygons, filter FILTER_TAG)."""
    if not PBF.exists():
        raise SystemExit(f"{PBF} tidak ada -- unduh dulu (lihat docstring)")
    tmp = DIR_OSM / "tmp_gdal"
    tmp.mkdir(exist_ok=True)
    os.environ["CPL_TMPDIR"] = str(tmp)        # indeks node sementara GDAL (beberapa GB)
    os.environ["OSM_MAX_TMPFILE_SIZE"] = "4000"  # MB di RAM sebelum tumpah ke disk
    t = time.time()
    gdf = pyogrio.read_dataframe(PBF, layer="multipolygons", columns=KOLOM, where=FILTER_TAG)
    print(f"  {len(gdf)} poligon kandidat dari PBF ({time.time() - t:.0f}s)", flush=True)
    pyogrio.write_dataframe(gdf, GPKG, layer="tutupan_lahan", driver="GPKG")
    print(f"  -> {GPKG} ({GPKG.stat().st_size / 1048576:.1f} MB)")


def baca(berkas):
    gdf = pyogrio.read_dataframe(berkas, layer="tutupan_lahan", columns=KOLOM)
    hasil = []
    for kol in KOLOM:  # NaN -> None
        gdf[kol] = gdf[kol].astype(object).where(gdf[kol].notna(), None)
    for r in gdf.itertuples(index=False):
        if r.geometry is None or r.geometry.is_empty:
            continue
        tags = tag_lain(r.other_tags)
        layer = klasifikasi(r.landuse, tags, r.name)
        if not layer:
            continue
        jenis, oid = ("relation", r.osm_id) if r.osm_id else ("way", r.osm_way_id)
        geom = r.geometry if r.geometry.is_valid else make_valid(r.geometry)
        attrs = {
            "Kategori": layer.replace(" (OSM)", ""),
            "Nama": r.name,
            "landuse (OSM)": r.landuse,
            "trees (OSM)": tags.get("trees"),
            "crop (OSM)": tags.get("crop"),
            "produce (OSM)": tags.get("produce"),
            "Pengelola (OSM)": tags.get("operator") or tags.get("owner"),
            "ID OSM": f"{jenis}/{oid}",
            "Tautan OSM": f"https://www.openstreetmap.org/{jenis}/{oid}",
            "Sumber": ATRIBUSI,
            "Catatan": CATATAN,
        }
        hasil.append((f"{jenis}/{oid}", layer, {k: v for k, v in attrs.items() if v}, geom.wkb))
    return hasil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ekstrak", action="store_true", help="bangun ulang gpkg dari PBF dulu")
    args = ap.parse_args()
    if args.ekstrak or not GPKG.exists():
        ekstrak()

    fitur = {}
    for oid, layer, attrs, wkb in baca(GPKG):
        fitur.setdefault(oid, (layer, attrs, wkb))
    print(f"Poligon unik: {len(fitur)}  {dict(Counter(v[0] for v in fitur.values()))}")

    with db_cursor() as cur:
        cur.execute("DELETE FROM map_layers WHERE provinsi=%s", (BUCKET,))
        cur.execute("DELETE FROM map_layer_meta WHERE provinsi=%s", (BUCKET,))
        cur.executemany(
            "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
            "SELECT %s, '', %s, %s::jsonb || jsonb_build_object('Luas (ha)', round((ST_Area(g::geography) / 1e4)::numeric, 1)), g "
            "FROM (SELECT ST_CollectionExtract(ST_SetSRID(ST_GeomFromWKB(%s), 4326), 3) AS g) s "
            "WHERE NOT ST_IsEmpty(g)",
            [(BUCKET, layer, Json(attrs), wkb) for layer, attrs, wkb in fitur.values()])

        # wilayah_provinsi -- sama dgn build_map_layer_wilayah.py (titik/poligon pesisir <= ~11 km)
        cur.execute("CREATE TEMP TABLE tmp_prov ON COMMIT DROP AS SELECT attrs->>'PROVINSI' AS nama, "
                    "ST_Subdivide(geom, 256) AS geom FROM map_layers WHERE provinsi='BATAS PROVINSI' AND kabupaten=''")
        cur.execute("CREATE INDEX ON tmp_prov USING gist (geom)")
        cur.execute("""UPDATE map_layers m SET wilayah_provinsi = s.arr
            FROM (SELECT m.id, array_agg(DISTINCT p.nama ORDER BY p.nama) arr FROM map_layers m
                  JOIN tmp_prov p ON ST_Intersects(m.geom, p.geom) WHERE m.provinsi=%s GROUP BY m.id) s
            WHERE m.id = s.id""", (BUCKET,))
        cur.execute("""UPDATE map_layers m SET wilayah_provinsi = COALESCE((SELECT ARRAY[p.nama] FROM tmp_prov p
                WHERE ST_DWithin(m.geom, p.geom, 0.1) ORDER BY m.geom <-> p.geom LIMIT 1), '{}')
            WHERE m.provinsi=%s AND m.wilayah_provinsi IS NULL""", (BUCKET,))

        cur.execute("""
            INSERT INTO map_layer_meta (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp)
            SELECT provinsi, kabupaten, layer, layer, COUNT(*),
                   ROUND((SUM(pg_column_size(geom) + pg_column_size(attrs)) / 1048576.0)::numeric, 2),
                   'OpenStreetMap via Overpass API (scripts/import_tutupan_lahan_osm.py)'
            FROM map_layers WHERE provinsi = %s GROUP BY provinsi, kabupaten, layer""", (BUCKET,))
        cur.execute("SELECT layer, feature_count, size_mb FROM map_layer_meta WHERE provinsi=%s ORDER BY layer",
                    (BUCKET,))
        hasil = cur.fetchall()
        cur.execute("SELECT count(*) n FROM map_layers WHERE provinsi=%s AND wilayah_provinsi='{}'", (BUCKET,))
        tanpa_prov = cur.fetchone()["n"]

    print(f"Bucket {BUCKET}:")
    for r in hasil:
        print(f"  {r['layer']}: {r['feature_count']} poligon ({r['size_mb']} MB)")
    print(f"Tanpa provinsi (di luar semua poligon BATAS PROVINSI): {tanpa_prov}")


if __name__ == "__main__":
    main()
