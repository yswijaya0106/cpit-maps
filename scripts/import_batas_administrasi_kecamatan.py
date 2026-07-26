# -*- coding: utf-8 -*-
"""Impor layer ADMINISTRASI_KECAMATAN_AR dari Maps/BATAS_ADMINISTRASI.gdb (BIG,
poligon kecamatan nasional dgn kolom provinsi/kabupaten/kecamatan lengkap) ke
PostgreSQL/PostGIS, MENGGANTIKAN layer overlay peta "BATAS KECAMATAN" yang
sebelumnya bersumber dari Maps/BATAS KECAMATAN/ (SHP Dukcapil Des 2019, tanpa
kolom provinsi/kabupaten -- hierarki provinsi->kabupaten->kecamatan di app.py
sebelumnya harus menebak lewat nama, termasuk heuristik ketetanggaan utk
kecamatan homonim lintas daerah).

Sumber baru ini punya kolom WADMPR/WADMKK/WADMKC (provinsi/kabupaten/
kecamatan) per poligon -- disimpan LANGSUNG sbg kolom kabupaten/layer di
map_layers (bukan flat+attrs kayak dulu), supaya endpoint /api/maps/* yang
generik (maps_provinces/kabupaten/layers/layer di app.py) bisa melayani
hierarki provinsi Indonesia -> kabupaten/kota -> poligon kecamatan TANPA
pencocokan nama sama sekali di runtime. Provinsi bucket teratas tetap
dipatok konstan "BATAS KECAMATAN" (BATAS_KEC_DIRNAME di app.py) supaya
topbar picker tidak berubah bentuk, cuma isinya yang diganti.

kode_kecamatan (dipakai popup identify utk join ke kecamatan_data_turunan
dkk, lihat app.py::kecamatan_join_data) TETAP dicocokkan lewat nama ke
penduduk_kecamatan -- kolom KDCPUM sumber ini memakai kode Kemendagri, BUKAN
kode BPS (terverifikasi: 0 dari 7.283 kode Kemendagri cocok langsung dgn
kode_kecamatan BPS di penduduk_kecamatan, mis. Aceh Selatan = kab 03 di BPS
tapi 01 di Kemendagri). Pola pencocokan sama dgn build_wilayah_mapping.py
(provinsi persis, kabupaten via prefiks KOTA/KOTA ADMINISTRASI/KABUPATEN,
kecamatan via kunci longgar tanpa spasi) -- tapi jauh lebih akurat drpd versi
lama krn provinsi+kabupaten sumber ini sudah eksplisit per poligon (bukan
satu SHP nasional flat tanpa kolom wilayah).

Geometri disederhanakan (shapely .simplify, toleransi sama dgn threshold
simplifikasi maps_layer() di app.py, ~15m) SAAT IMPOR, bukan saat baca:
sumber BIG ini jauh lebih detail (vertex lebih padat) drpd SHP Dukcapil lama
walau jumlah fitur mirip (7.283 vs 6.810 nasional), sedangkan andalan lama
"simplify kalau feature_count>3000" di maps_layer() tidak akan pernah kena
di sini (hitungannya per-kabupaten, cuma puluhan fitur) padahal payload per
kabupaten tetap bisa berat kalau tidak disederhanakan lebih dulu di sini.

TIPADM==3 = poligon kecamatan definitif (7.283 baris); baris TIPADM==999
(60 baris) adalah agregat multi-kabupaten/kawasan belum definitif (WADMKC
kosong, KDPKAB kadang gabungan spt "71.05/71.10") -- dilewati.

Mengganti SELURUH data lama tiap dijalankan (DELETE lalu INSERT ulang utk
provinsi='BATAS KECAMATAN'), bukan upsert per-baris -- aman dijalankan
berkali-kali, sumbernya satu file gdb utuh, bukan tarikan bertahap.

Usage (venv aktif):
    python scripts/import_batas_administrasi_kecamatan.py
"""
import io
import os
import re
import sys
import time
from pathlib import Path

os.environ.setdefault("SHAPE_RESTORE_SHX", "YES")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import geopandas as gpd
import shapely
from psycopg.types.json import Json

from db import db_cursor as pg_cursor  # noqa: E402

GDB_PATH = Path(__file__).resolve().parent.parent / "Maps" / "BATAS_ADMINISTRASI.gdb"
LAYER_NAME = "ADMINISTRASI_KECAMATAN_AR"
BATAS_KEC_DIRNAME = "BATAS KECAMATAN"  # sama dgn konstanta app.py, lihat catatan di sana
SIMPLIFY_TOLERANCE = 0.00015  # ~15-17m, sama dgn maps_layer() di app.py
INSERT_BATCH = 2000


def norm(s):
    return " ".join(t for t in re.split(r"[^A-Z0-9]+", str(s).upper()) if t)


def norm_compact(s):
    return norm(s).replace(" ", "")


# Penyeteraan bilangan pada nama kecamatan (ILIR BARAT SATU vs ILIR BARAT I),
# plus varian Minang ANAM=ENAM -- sama dgn pola lama app.py::_batas_kec_index.
_ANGKA = {
    "SATU": "I", "DUA": "II", "TIGA": "III", "EMPAT": "IV", "LIMA": "V",
    "ENAM": "VI", "ANAM": "VI", "TUJUH": "VII", "DELAPAN": "VIII",
    "SEMBILAN": "IX", "SEPULUH": "X", "1": "I", "2": "II", "3": "III",
    "4": "IV", "5": "V", "6": "VI", "7": "VII", "8": "VIII", "9": "IX", "10": "X",
}


def norm_angka(s):
    return "".join(_ANGKA.get(t, t) for t in norm(s).split())


def is_kota(kode_kabupaten):
    return kode_kabupaten % 100 >= 71


def kabupaten_label(wadmkk: str) -> str:
    """Label tampilan konsisten dgn konvensi folder Maps/<prov>/Kabupaten X
    yang sudah ada -- sumber gdb ini kadang sudah berprefiks 'Kota '/'Kota
    Administrasi ' (kota), sisanya polos tanpa prefiks (kabupaten)."""
    s = str(wadmkk).strip()
    if s.upper().startswith("KOTA"):
        return s
    return f"Kabupaten {s}"


def build_master_index(cur):
    """(kab_idx, kab_idx2, kec_by_kab): kab_idx/kab_idx2 = (prov_norm, jenis)
    -> {kab_norm: kode_kabupaten} (persis / tanpa-spasi); kec_by_kab =
    kode_kabupaten -> {kec_norm|kec_compact|kec_angka: kode_kecamatan}."""
    cur.execute("SELECT provinsi, kabupaten_kota, kode_kabupaten, kecamatan, kode_kecamatan "
                "FROM penduduk_kecamatan")
    master = cur.fetchall()
    kab_idx, kab_idx2, kec_by_kab = {}, {}, {}
    for m in master:
        jenis = "KOTA" if is_kota(m["kode_kabupaten"]) else "KABUPATEN"
        prov_n = norm(m["provinsi"])
        kab_n = norm(m["kabupaten_kota"])
        kab_idx.setdefault((prov_n, jenis), {})[kab_n] = m["kode_kabupaten"]
        kab_idx2.setdefault((prov_n, jenis), {})[norm_compact(kab_n)] = m["kode_kabupaten"]
        d = kec_by_kab.setdefault(m["kode_kabupaten"], {})
        kec_n = norm(m["kecamatan"])
        d.setdefault(kec_n, m["kode_kecamatan"])
        d.setdefault(norm_compact(kec_n), m["kode_kecamatan"])
        d.setdefault(norm_angka(kec_n), m["kode_kecamatan"])
    return kab_idx, kab_idx2, kec_by_kab


def match_kode_kabupaten(kab_idx, kab_idx2, provinsi, wadmkk):
    prov_n = norm(provinsi)
    kab_n = norm(wadmkk)
    jenis = "KABUPATEN"
    for prefix in ("KOTA ADMINISTRASI ", "KABUPATEN ADMINISTRATIF ", "KOTA ", "KABUPATEN "):
        if kab_n.startswith(prefix):
            jenis = "KOTA" if prefix.startswith("KOTA") else "KABUPATEN"
            kab_n = kab_n[len(prefix):]
            break
    kode = kab_idx.get((prov_n, jenis), {}).get(kab_n)
    if kode is None:
        kode = kab_idx2.get((prov_n, jenis), {}).get(norm_compact(kab_n))
    return kode


def match_kode_kecamatan(kec_by_kab, kode_kabupaten, kecamatan):
    if kode_kabupaten is None:
        return None
    d = kec_by_kab.get(kode_kabupaten, {})
    kec_n = norm(kecamatan)
    return d.get(kec_n) or d.get(norm_compact(kec_n)) or d.get(norm_angka(kec_n))


def main():
    if not GDB_PATH.exists():
        sys.exit(f"Tidak ditemukan: {GDB_PATH}")

    t0 = time.time()
    print("Membaca layer geometri (bisa beberapa menit -- ~7.300 poligon detail)...")
    gdf = gpd.read_file(GDB_PATH, layer=LAYER_NAME, engine="pyogrio")
    gdf = gdf[gdf["TIPADM"] == 3].copy()
    print(f"  {len(gdf)} poligon kecamatan definitif dibaca ({time.time() - t0:.1f}s)")

    with pg_cursor() as cur:
        kab_idx, kab_idx2, kec_by_kab = build_master_index(cur)

        rows = []
        meta_counts = {}  # (provinsi, kab_label) -> jumlah kecamatan
        n_bad = n_kab_miss = n_kec_miss = 0
        for _, r in gdf.iterrows():
            try:
                geom = r["geometry"]
                if geom is None or geom.is_empty or not geom.is_valid:
                    n_bad += 1
                    continue
                if geom.has_z:
                    geom = shapely.force_2d(geom)
                geom = geom.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)
                if geom.is_empty:
                    n_bad += 1
                    continue
                wkb_hex = geom.wkb_hex
            except Exception:
                n_bad += 1
                continue

            provinsi = str(r["WADMPR"]).strip()
            wadmkk = str(r["WADMKK"]).strip()
            kab_label = kabupaten_label(wadmkk)
            kecamatan = str(r["WADMKC"]).strip()

            kode_kab = match_kode_kabupaten(kab_idx, kab_idx2, provinsi, wadmkk)
            if kode_kab is None:
                n_kab_miss += 1
            kode_kec = match_kode_kecamatan(kec_by_kab, kode_kab, kecamatan)
            if kode_kab is not None and kode_kec is None:
                n_kec_miss += 1

            attrs = {
                "KECAMATAN": kecamatan,
                "KABUPATEN_KOTA": kab_label,
                "PROVINSI": provinsi,
                "KODE_KECAMATAN": kode_kec,
                "KODE_KEMENDAGRI": r.get("KDCPUM"),
            }
            rows.append((BATAS_KEC_DIRNAME, provinsi, kab_label, Json(attrs), wkb_hex))
            key = (provinsi, kab_label)
            meta_counts[key] = meta_counts.get(key, 0) + 1

        if n_bad:
            print(f"  ({n_bad} fitur geometri rusak/kosong dilewati)")
        print(f"  kode_kabupaten tidak match ke penduduk_kecamatan: {n_kab_miss}/{len(gdf)}")
        print(f"  kode_kecamatan tidak match (kabupaten match): {n_kec_miss}/{len(gdf)}")

        print("Mengganti data lama (provinsi='BATAS KECAMATAN')...")
        cur.execute("DELETE FROM map_layers WHERE provinsi=%s", (BATAS_KEC_DIRNAME,))
        cur.execute("DELETE FROM map_layer_meta WHERE provinsi=%s", (BATAS_KEC_DIRNAME,))

        for i in range(0, len(rows), INSERT_BATCH):
            chunk = rows[i:i + INSERT_BATCH]
            cur.executemany(
                "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
                "VALUES (%s, %s, %s, %s, ST_GeomFromWKB(decode(%s, 'hex'), 4326))",
                chunk,
            )

        for (provinsi, kab_label), n in meta_counts.items():
            cur.execute(
                """INSERT INTO map_layer_meta
                       (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp)
                   VALUES (%s, %s, %s, %s, %s, NULL, %s)
                   ON CONFLICT (provinsi, kabupaten, layer) DO UPDATE SET
                       label=EXCLUDED.label, feature_count=EXCLUDED.feature_count,
                       imported_at=now()""",
                (BATAS_KEC_DIRNAME, provinsi, kab_label, f"{kab_label} ({n} kecamatan)", n,
                 "BATAS_ADMINISTRASI.gdb::ADMINISTRASI_KECAMATAN_AR"),
            )

    print(f"\nSelesai: {len(rows)} poligon kecamatan diimpor ke {len(meta_counts)} "
          f"kabupaten/kota, {time.time() - t0:.1f}s total")


if __name__ == "__main__":
    main()
