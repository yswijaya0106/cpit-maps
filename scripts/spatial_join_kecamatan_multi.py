# -*- coding: utf-8 -*-
"""Overlay MULTI-kecamatan per usulan -- pelengkap spatial_join_kecamatan.py
(yang cuma simpan SATU kecamatan dominan ke usulan_inpres.kode_kecamatan).
Rute usulan yang panjang lazim melintasi >1 kecamatan; skrip ini mendaftar
SEMUA kecamatan yang dilalui ke tabel baru usulan_kecamatan_dilalui, tanpa
mengubah usulan_inpres.kode_kecamatan (tetap dipakai skor C.A1 & tempat lain
apa adanya). Lihat docs/kajian_overlay_kecamatan_simpul_jalan.md §2.3.

Sumber & metode SAMA PERSIS dgn spatial_join_kecamatan.py (norm/sample_points
di-reuse dari situ, bukan ditulis ulang) -- bedanya cuma pada titik sampel,
SEMUA poligon yg menaungi (bukan cuma pemenang terbanyak) diresolusi dan
disimpan, dengan jumlah titik sampel jauh lebih padat (default 1 per ~1,5 km,
minimal 20) supaya kecamatan pendek yang cuma dilintasi sekilas di ujung rute
tetap tertangkap.

Usage (venv aktif):
    python scripts/spatial_join_kecamatan_multi.py
    python scripts/spatial_join_kecamatan_multi.py --min-titik 40
"""

import argparse
import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import geopandas as gpd
import shapely
from pyproj import Transformer
from shapely.strtree import STRtree

from app import _batas_kec_shp, _geojson_line_to_shapely, db_cursor  # noqa: E402
from spatial_join_kecamatan import norm, sample_points  # noqa: E402 -- reuse, bukan tulis ulang

RADIUS_SCHEMA = """
CREATE TABLE IF NOT EXISTS usulan_kecamatan_dilalui (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  usulan_id       INT NOT NULL,
  kode_kecamatan  INT UNSIGNED NOT NULL,
  kode_kabupaten  MEDIUMINT UNSIGNED NOT NULL,
  n_titik_sampel  SMALLINT UNSIGNED NOT NULL,
  n_titik_total   SMALLINT UNSIGNED NOT NULL,
  UNIQUE KEY uq_usulan_kec (usulan_id, kode_kecamatan),
  KEY idx_kode_kecamatan (kode_kecamatan),
  KEY idx_usulan_id (usulan_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

# ~1 titik tiap 1,5 km rute (dihitung dari panjang METRIK, bukan derajat --
# beda dgn sample_points() yg unitnya derajat utk pembagian PROPORSIONAL
# antar segmen MultiLineString, di sini dipakai cuma utk menentukan TOTAL n).
_METER_PER_TITIK = 1500
_MIN_TITIK = 20
_MAX_TITIK = 400


def panjang_meter(geom, to_3857):
    """Panjang total rute dlm meter -- reproyeksi ringan (cuma utk hitung
    panjang, bukan geometri yg dipakai query final) lewat WKT spt pola
    reproject() di spatial_konektivitas_jalan.py (transform() shapely
    langsung kena bug create_collection numpy)."""
    def _line_wkt(coords):
        xs, ys = to_3857.transform([c[0] for c in coords], [c[1] for c in coords])
        return "(" + ", ".join(f"{x} {y}" for x, y in zip(xs, ys)) + ")"
    lines = [geom] if geom.geom_type == "LineString" else list(geom.geoms)
    total = 0.0
    for l in lines:
        wkt = "LINESTRING " + _line_wkt(l.coords)
        total += shapely.from_wkt(wkt).length
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-titik", type=int, default=_MIN_TITIK, help=f"titik sampel minimum per usulan (default {_MIN_TITIK})")
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

    to_3857 = Transformer.from_crs(4326, 3857, always_xy=True)

    with db_cursor() as cur:
        cur.execute(
            "SELECT provinsi_sitia, kabupaten_kota_sitia, kode_kabupaten FROM wilayah_mapping "
            "WHERE kode_kabupaten IS NOT NULL"
        )
        kab_map = {(r["provinsi_sitia"], r["kabupaten_kota_sitia"]): r["kode_kabupaten"] for r in cur.fetchall()}
        cur.execute("SELECT kode_kabupaten, kecamatan, kode_kecamatan FROM penduduk_kecamatan")
        master = cur.fetchall()
        cur.execute(
            "SELECT id, provinsi, kabupaten_kota, geom_geojson FROM usulan_inpres WHERE geom_geojson IS NOT NULL"
        )
        usulan = cur.fetchall()

    by_kab_nama = {}   # (kode_kab, norm_nama) -> kode_kecamatan
    by_nama = defaultdict(set)  # norm_nama -> {kode_kecamatan}
    for m in master:
        by_kab_nama[(m["kode_kabupaten"], norm(m["kecamatan"]))] = m["kode_kecamatan"]
        by_nama[norm(m["kecamatan"])].add(m["kode_kecamatan"])

    print(f"Antrian overlay multi-kecamatan: {len(usulan)} usulan bergeometri")
    rows_out = []
    alasan = Counter()
    n_ambigu_total = 0
    for i, u in enumerate(usulan, start=1):
        try:
            geom = _geojson_line_to_shapely(json.loads(u["geom_geojson"]))
        except Exception:
            alasan["geometri tidak valid"] += 1
            continue
        if geom is None or geom.is_empty:
            alasan["geometri kosong"] += 1
            continue
        n_koord = len(geom.coords) if geom.geom_type == "LineString" else sum(len(ls.coords) for ls in geom.geoms)
        if n_koord > 10000:
            # Geometri KML korup (self-intersecting, ratusan ribu titik) --
            # SAMA kasus persis yg didokumentasikan di
            # spatial_konektivitas_jalan.py (usulan 239705/239723 dkk.,
            # >280rb titik) & payload 20MB yg baru ditemukan di
            # fetch_kml_massal.py (poison utk max_allowed_packet). "Tidak
            # bisa divalidasi", bukan dipaksa proses (risiko hang/lambat).
            alasan["geometri korup (>10rb titik)"] += 1
            continue

        try:
            panjang_m = panjang_meter(geom, to_3857)
        except Exception:
            panjang_m = 0
        # Geometri KML degradasi (koordinat NaN/inf dari parsing buruk, sama
        # kelas masalah dgn komentar reproject()/GEOS di
        # spatial_konektivitas_jalan.py) bikin panjang_m NaN -- round(NaN)
        # crash ValueError, bukan exception yg ketangkep try/except di atas
        # (perhitungannya SENDIRI sukses, cuma hasilnya NaN). Fallback ke
        # min_titik drpd skip usulan sepenuhnya -- sample_points() jalan
        # normal pakai geometri asli, cuma jumlah TITIK-nya yg tak bisa
        # diskalakan dari panjang.
        if panjang_m != panjang_m:  # NaN != NaN, cara cek tanpa import math
            panjang_m = 0
        n_titik = min(_MAX_TITIK, max(args.min_titik, round(panjang_m / _METER_PER_TITIK)))

        votes = Counter()
        for pt in sample_points(geom, n_titik):
            for idx in tree.query(pt, predicate="intersects"):
                votes[poly_names[idx]] += 1
        if not votes:
            alasan["di luar cakupan poligon"] += 1
            continue

        kode_kab_usulan = kab_map.get((u["provinsi"], u["kabupaten_kota"]))
        kecamatan_ditemukan = {}  # kode_kecamatan -> n_titik (vote count)
        for nama, n_vote in votes.items():
            n = norm(nama)
            kode_kec = by_kab_nama.get((kode_kab_usulan, n))
            if kode_kec is None and len(by_nama.get(n, ())) == 1:
                kode_kec = next(iter(by_nama[n]))
            if kode_kec is None:
                n_ambigu_total += 1
                continue
            kecamatan_ditemukan[kode_kec] = kecamatan_ditemukan.get(kode_kec, 0) + n_vote

        if not kecamatan_ditemukan:
            alasan["semua poligon ambigu, tak satu pun teresolusi"] += 1
            continue
        for kode_kec, n_vote in kecamatan_ditemukan.items():
            rows_out.append((u["id"], kode_kec, kode_kec // 1000, n_vote, n_titik))

        if i % 500 == 0:
            print(f"  ...{i}/{len(usulan)}")

    with db_cursor() as cur:
        for stmt in RADIUS_SCHEMA.split(";"):
            if stmt.strip():
                cur.execute(stmt)
        cur.execute("DELETE FROM usulan_kecamatan_dilalui")
        cur.executemany(
            "INSERT INTO usulan_kecamatan_dilalui "
            "(usulan_id, kode_kecamatan, kode_kabupaten, n_titik_sampel, n_titik_total) "
            "VALUES (%s,%s,%s,%s,%s)",
            rows_out,
        )
    n_usulan_terisi = len({r[0] for r in rows_out})
    rata_kec = len(rows_out) / n_usulan_terisi if n_usulan_terisi else 0
    print(f"\nTotal: {len(rows_out)} pasangan usulan-kecamatan ({n_usulan_terisi}/{len(usulan)} usulan "
          f"teresolusi minimal 1 kecamatan, rata-rata {rata_kec:.1f} kecamatan/usulan), "
          f"{n_ambigu_total} poligon ambigu dilewati")
    if alasan:
        for k, n in alasan.most_common():
            print(f"  gagal — {k}: {n}")


if __name__ == "__main__":
    main()
