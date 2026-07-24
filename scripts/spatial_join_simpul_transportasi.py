# -*- coding: utf-8 -*-
"""Lengkapi/perbaiki simpul_transportasi utk SEMUA 4 layer SHP di
Maps/BANDARA + Maps/KONEKTIVITAS SIMPUL TRANSPORTASI/ (bandara, pelabuhan
nasional, pelabuhan penyeberangan, pelabuhan laut) dengan spatial join
titik->poligon kecamatan (Maps/BATAS KECAMATAN) sbg METODE UTAMA utk 2
layer yang belum py resolusi teks sama sekali, dan sbg FALLBACK utk 2 layer
yang sudah diimpor scripts/import_simpul_transportasi.py (text-matching)
tapi masih py baris tak-match (Pelabuhan Nasional 101/359, Pelabuhan
Penyeberangan 19/254 -- dicek 21 Jul 2026). Lihat
docs/kajian_overlay_kecamatan_simpul_jalan.md §2.1.

Reuse: norm/norm_prov/_match_kabupaten/build_master_index dari
import_simpul_transportasi.py (SAMA persis, bukan ditulis ulang) utk jalur
text-matching; STRtree poligon Maps/BATAS KECAMATAN (pola SAMA dgn
spatial_join_kecamatan.py, arah kebalik) utk jalur spatial join.

Per layer:
  - Bandara.shp        : cuma atribut provinsi -- SPATIAL JOIN SATU-SATUNYA
                          metode (scoped ke provinsi kalau diketahui, fallback
                          nama kecamatan unik nasional).
  - PELABUHAN_PT.shp    : NOL atribut teks -- SPATIAL JOIN SATU-SATUNYA metode
                          (cuma nama kecamatan unik nasional, tanpa scoping
                          provinsi krn tak ada info provinsi sama sekali).
  - Pelabuhan Nasional.shp : text-match (kolom KABUPATEN) DULU spt skrip asal;
                              spatial join HANYA utk baris yg gagal text-match.
  - PP.shp (Penyeberangan) : text-match (KD_KABKOT) DULU spt skrip asal;
                              spatial join HANYA utk baris yg gagal text-match.

Usage (venv aktif):
    python scripts/spatial_join_simpul_transportasi.py
"""

import io
import re
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

from app import _batas_kec_shp, db_cursor  # noqa: E402
import import_simpul_transportasi as ist  # noqa: E402 -- reuse norm/_match_kabupaten/build_master_index

RADIUS_KM_DEFAULT = 30

BASE_DIR = Path(__file__).resolve().parent.parent
BANDARA_SHP = BASE_DIR / "Maps" / "BANDARA" / "Bandara.shp"
SIMPUL_DIR = BASE_DIR / "Maps" / "KONEKTIVITAS SIMPUL TRANSPORTASI"
PELABUHAN_NASIONAL_SHP = SIMPUL_DIR / "pelabuhan" / "Pelabuhan Nasional.shp"
PP_SHP = SIMPUL_DIR / "Pelabuhan Penyeberangan" / "SHP PP" / "PP.shp"
PELABUHAN_PT_SHP = SIMPUL_DIR / "Pelabuhan Laut" / "PELABUHAN_PT.shp"

# Bandara.shp masih pakai pembagian provinsi Papua LAMA (2 provinsi) +
# singkatan gaya non-BPS -- pola sama persis dgn import_simpul_transportasi.py,
# daftar alias diperluas utk singkatan yg muncul spesifik di Bandara.shp.
_PROV_ALIAS = {
    "DIY": "DI YOGYAKARTA", "NTB": "NUSA TENGGARA BARAT", "NTT": "NUSA TENGGARA TIMUR",
    "KEP RIAU": "KEPULAUAN RIAU", "KEP BABEL": "KEPULAUAN BANGKA BELITUNG",
}
_PAPUA_LAMA = {"PAPUA", "PAPUA BARAT"}


def norm_prov_bandara(s):
    base = ist.norm(s)
    return _PROV_ALIAS.get(base, base)


def load_kecamatan_tree():
    """Return (tree_4326, tree_3857, poly_names) -- dua STRtree geometri SAMA
    dari 2 CRS: 4326 utk point-in-polygon persis (spatial_lookup, sudah ada),
    3857 (metrik) utk query radius jarak dlm km yang akurat (radius_kecamatan,
    baru) -- reproyeksi SEKALI di awal drpd per-titik supaya murah."""
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
    gdf_m = gdf.to_crs(3857)
    tree_m = STRtree(list(gdf_m.geometry))
    print(f"  {len(poly_names)} poligon siap di-query")
    return tree, tree_m, poly_names


def build_kode_kec_index_kecamatan():
    """SAMA pola dgn build_kode_kec_index() tapi target kode_KECAMATAN
    (bukan kode_kabupaten) -- dipakai radius_kecamatan() krn radius 30km
    butuh presisi kecamatan, bukan cuma kabupaten penaung titik simpul."""
    with db_cursor() as cur:
        cur.execute("SELECT DISTINCT kode_provinsi, provinsi, kode_kecamatan, kecamatan FROM penduduk_kecamatan")
        rows = cur.fetchall()
    by_prov_nama = defaultdict(set)
    by_nama = defaultdict(set)
    for r in rows:
        n = ist.norm(r["kecamatan"])
        by_prov_nama[(r["kode_provinsi"], n)].add(r["kode_kecamatan"])
        by_nama[n].add(r["kode_kecamatan"])
    return by_prov_nama, by_nama


def radius_kecamatan(pt_4326, to_3857, tree_m, poly_names, kode_provinsi,
                      by_prov_nama_kec, by_nama_kec, radius_km=RADIUS_KM_DEFAULT):
    """Semua kecamatan yg poligonnya berjarak <= radius_km dari titik.
    Return list [(kode_kecamatan, jarak_km, metode), ...] -- nama poligon yg
    ambigu (tak bisa diresolusi tunggal ke 1 kode_kecamatan, dgn/tanpa
    provinsi hint) DILEWATI (dilaporkan lewat penjumlahan, bukan ditebak),
    konsisten dgn spatial_lookup()."""
    if pt_4326 is None or pt_4326.is_empty:
        return [], Counter({"geometri_kosong": 1})
    pt = shapely.force_2d(pt_4326) if pt_4326.has_z else pt_4326
    x, y = to_3857.transform(pt.x, pt.y)
    pt_m = shapely.Point(x, y)
    radius_m = radius_km * 1000
    idxs = tree_m.query(pt_m.buffer(radius_m))
    hasil, stat = [], Counter()
    for idx in idxs:
        jarak_m = pt_m.distance(tree_m.geometries[idx])
        if jarak_m > radius_m:
            continue
        nama = poly_names[idx]
        n = ist.norm(nama)
        kode_kec = None
        if kode_provinsi is not None:
            cand = by_prov_nama_kec.get((kode_provinsi, n))
            if cand and len(cand) == 1:
                kode_kec = next(iter(cand))
        if kode_kec is None:
            cand = by_nama_kec.get(n)
            if cand and len(cand) == 1:
                kode_kec = next(iter(cand))
        if kode_kec is None:
            stat["nama_ambigu"] += 1
            continue
        hasil.append((kode_kec, round(jarak_m / 1000, 2)))
        stat["ok"] += 1
    return hasil, stat


def build_kode_kec_index():
    """(kode_provinsi, norm_nama_kecamatan) -> {kode_kabupaten,...} dan
    norm_nama_kecamatan -> {kode_kabupaten,...} nasional (fallback tanpa
    provinsi diketahui). Dipisah dari ist.build_master_index() krn itu
    keyed by nama kabupaten (utk text-matching), ini keyed by nama
    KECAMATAN (utk hasil spatial join)."""
    with db_cursor() as cur:
        cur.execute("SELECT DISTINCT kode_provinsi, provinsi, kode_kabupaten, kecamatan FROM penduduk_kecamatan")
        rows = cur.fetchall()
    by_prov_nama = defaultdict(set)
    by_nama = defaultdict(set)
    prov_nama_to_kode = {}
    for r in rows:
        n = ist.norm(r["kecamatan"])
        by_prov_nama[(r["kode_provinsi"], n)].add(r["kode_kabupaten"])
        by_nama[n].add(r["kode_kabupaten"])
        prov_nama_to_kode[ist.norm_prov(r["provinsi"])] = r["kode_provinsi"]
    return by_prov_nama, by_nama, prov_nama_to_kode


def resolve_kode_kabupaten_spasial(poly_names_hit, kode_provinsi, by_prov_nama, by_nama):
    """poly_names_hit: Counter nama poligon KECAMATAN yg menaungi titik
    (bisa >1 kalau titik pas di perbatasan). Coba tiap kandidat (mulai dari
    yg paling sering menaungi) sampai satu berhasil diresolusi TUNGGAL --
    ambigu (nama kecamatan sama di >1 kabupaten tanpa provinsi diketahui
    utk membedakan) dilaporkan gagal, bukan ditebak."""
    for nama, _n in poly_names_hit.most_common():
        n = ist.norm(nama)
        if kode_provinsi is not None:
            cand = by_prov_nama.get((kode_provinsi, n))
            if cand and len(cand) == 1:
                return next(iter(cand)), "spasial_provinsi"
        cand = by_nama.get(n)
        if cand and len(cand) == 1:
            return next(iter(cand)), "spasial_unik_nasional"
    return None, None


# Ambang jarak fallback utk titik yg jatuh di LUAR semua poligon (umum utk
# simpul pelabuhan -- posisinya persis di garis pantai/dermaga, seringkali
# sedikit meleset dari tepi poligon darat krn beda sumber & skala digitasi).
# ~0.02 derajat ≈ 2 km di ekuator (lebih longgar dari ambang 100m jalan
# krn ini fallback "kecamatan terdekat", bukan validasi "benar-benar
# berdekatan" spt spatial_konektivitas_jalan.py).
_AMBANG_TERDEKAT_DERAJAT = 0.02


def spatial_lookup(geom, tree, poly_names, kode_provinsi, by_prov_nama, by_nama):
    if geom is None or geom.is_empty:
        return None, "geometri_kosong"
    pt = shapely.force_2d(geom) if geom.has_z else geom
    votes = Counter()
    for idx in tree.query(pt, predicate="intersects"):
        votes[poly_names[idx]] += 1
    if votes:
        kode_kab, metode = resolve_kode_kabupaten_spasial(votes, kode_provinsi, by_prov_nama, by_nama)
        if kode_kab is not None:
            return kode_kab, metode
        return None, "nama_ambigu"
    # Tidak ada poligon yg menaungi langsung -- fallback poligon TERDEKAT
    # (umum utk titik pelabuhan persis di garis pantai), asal masih dalam
    # ambang wajar.
    idx = tree.nearest(pt)
    if idx is None:
        return None, "di_luar_poligon"
    jarak = pt.distance(tree.geometries[idx])
    if jarak > _AMBANG_TERDEKAT_DERAJAT:
        return None, "di_luar_poligon"
    kode_kab, metode = resolve_kode_kabupaten_spasial(Counter({poly_names[idx]: 1}), kode_provinsi, by_prov_nama, by_nama)
    if kode_kab is None:
        return None, "nama_ambigu"
    return kode_kab, f"{metode}_terdekat"


def process_bandara(tree, poly_names, by_prov_nama, by_nama, prov_nama_to_kode):
    if not BANDARA_SHP.exists():
        print(f"  SKIP Bandara: {BANDARA_SHP} tidak ditemukan")
        return []
    gdf = gpd.read_file(BANDARA_SHP)
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    out, stat = [], Counter()
    for _, row in gdf.iterrows():
        provinsi = ist.clean(row.get("provinsi"))
        kode_prov = None
        if provinsi:
            pk = norm_prov_bandara(provinsi)
            if pk not in _PAPUA_LAMA:
                kode_prov = prov_nama_to_kode.get(pk)
        kode_kab, metode = spatial_lookup(row.geometry, tree, poly_names, kode_prov, by_prov_nama, by_nama)
        stat[metode] += 1
        out.append((("BANDARA", ist.clean(row.get("Name")), provinsi, None,
                      kode_kab // 100 if kode_kab else None, kode_kab, "Bandara.shp"), row.geometry))
    print(f"  Bandara: {len(out)} titik, {stat}")
    return out


def process_pelabuhan_laut_pt(tree, poly_names, by_prov_nama, by_nama):
    if not PELABUHAN_PT_SHP.exists():
        print(f"  SKIP Pelabuhan Laut (PT): {PELABUHAN_PT_SHP} tidak ditemukan")
        return []
    gdf = gpd.read_file(PELABUHAN_PT_SHP)
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    out, stat = [], Counter()
    for _, row in gdf.iterrows():
        kode_kab, metode = spatial_lookup(row.geometry, tree, poly_names, None, by_prov_nama, by_nama)
        stat[metode] += 1
        out.append((("PELABUHAN_LAUT", None, None, None,
                      kode_kab // 100 if kode_kab else None, kode_kab, "PELABUHAN_PT.shp"), row.geometry))
    print(f"  Pelabuhan Laut (PT, nol atribut): {len(out)} titik, {stat}")
    return out


def process_pelabuhan_nasional(master_idx, tree, poly_names, by_prov_nama, by_nama):
    if not PELABUHAN_NASIONAL_SHP.exists():
        print(f"  SKIP Pelabuhan Nasional: {PELABUHAN_NASIONAL_SHP} tidak ditemukan")
        return []
    kab_idx, kab_compact, kab_name_list_by_prov, kab_name_all_prov = master_idx
    gdf = gpd.read_file(PELABUHAN_NASIONAL_SHP)
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    out, stat = [], Counter()
    for _, row in gdf.iterrows():
        nama = ist.clean(row.get("Name"))
        provinsi = ist.clean(row.get("Provinsi"))
        kabupaten = ist.clean(row.get("KABUPATEN"))
        m, method = (None, None)
        if provinsi and kabupaten:
            m, method = ist._match_kabupaten(provinsi, kabupaten, kab_idx, kab_compact,
                                              kab_name_list_by_prov, kab_name_all_prov)
        if m:
            kode_prov, kode_kab = m["kode_provinsi"], m["kode_kabupaten"]
            stat[f"teks_{method}"] += 1
        else:
            kode_prov_hint = None
            if provinsi:
                pk = ist.norm_prov(provinsi)
                cands = kab_name_list_by_prov.get(pk)
                if cands:
                    kode_prov_hint = cands[0][1]["kode_provinsi"]
            kode_kab, metode = spatial_lookup(row.geometry, tree, poly_names, kode_prov_hint, by_prov_nama, by_nama)
            kode_prov = kode_kab // 100 if kode_kab else None
            stat[metode] += 1
        out.append((("PELABUHAN_NASIONAL", nama, provinsi, kabupaten, kode_prov, kode_kab, "Pelabuhan Nasional.shp"), row.geometry))
    print(f"  Pelabuhan Nasional: {len(out)} titik, {stat}")
    return out


def process_pelabuhan_penyeberangan(valid_kab_codes, tree, poly_names, by_prov_nama, by_nama):
    if not PP_SHP.exists():
        print(f"  SKIP Pelabuhan Penyeberangan: {PP_SHP} tidak ditemukan")
        return []
    gdf = gpd.read_file(PP_SHP)
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    out, stat = [], Counter()
    for _, row in gdf.iterrows():
        nama = ist.clean(row.get("NAMOBJ"))
        provinsi = ist.clean(row.get("PROV"))
        kabupaten = ist.clean(row.get("KABKOT"))
        kd = ist.clean(row.get("KD_KABKOT"))
        kode_kab = None
        if kd:
            digits = kd.replace(".", "")
            if digits.isdigit():
                cand = int(digits)
                if cand in valid_kab_codes:
                    kode_kab = cand
        if kode_kab:
            stat["teks_kd_kabkot"] += 1
        else:
            kode_prov_hint = None
            if provinsi:
                kd_prov = ist.clean(row.get("KD_PROV"))
                if kd_prov and str(kd_prov).replace(".0", "").isdigit():
                    kode_prov_hint = int(float(kd_prov))
            kode_kab, metode = spatial_lookup(row.geometry, tree, poly_names, kode_prov_hint, by_prov_nama, by_nama)
            stat[metode] += 1
        out.append((("PELABUHAN_PENYEBERANGAN", nama, provinsi, kabupaten,
                      kode_kab // 100 if kode_kab else None, kode_kab, "PP.shp"), row.geometry))
    print(f"  Pelabuhan Penyeberangan: {len(out)} titik, {stat}")
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--radius", type=float, default=RADIUS_KM_DEFAULT,
                     help=f"radius pencarian kecamatan sekitar simpul, km (default {RADIUS_KM_DEFAULT})")
    args = ap.parse_args()

    tree, tree_m, poly_names = load_kecamatan_tree()
    by_prov_nama, by_nama, prov_nama_to_kode = build_kode_kec_index()
    by_prov_nama_kec, by_nama_kec = build_kode_kec_index_kecamatan()
    to_3857 = Transformer.from_crs(4326, 3857, always_xy=True)

    ist_conn = ist.connect()
    try:
        master_idx = ist.build_master_index(ist_conn)  # (kab_idx, kab_compact, kab_name_list_by_prov, kab_name_all_prov, valid_kab_codes)
    finally:
        ist_conn.close()
    kab_idx, kab_compact, kab_name_list_by_prov, kab_name_all_prov, valid_kab_codes = master_idx

    all_rows_geom = []
    all_rows_geom += process_bandara(tree, poly_names, by_prov_nama, by_nama, prov_nama_to_kode)
    all_rows_geom += process_pelabuhan_laut_pt(tree, poly_names, by_prov_nama, by_nama)
    all_rows_geom += process_pelabuhan_nasional(
        (kab_idx, kab_compact, kab_name_list_by_prov, kab_name_all_prov), tree, poly_names, by_prov_nama, by_nama)
    all_rows_geom += process_pelabuhan_penyeberangan(valid_kab_codes, tree, poly_names, by_prov_nama, by_nama)
    all_rows = [r for r, _g in all_rows_geom]

    with db_cursor() as cur:
        cur.execute(
            "DELETE FROM simpul_transportasi WHERE jenis IN "
            "('BANDARA','PELABUHAN_LAUT','PELABUHAN_NASIONAL','PELABUHAN_PENYEBERANGAN')"
        )
        cur.executemany(
            "INSERT INTO simpul_transportasi (jenis, nama, provinsi_asli, kabupaten_asli, "
            "kode_provinsi, kode_kabupaten, sumber_file) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            all_rows,
        )
        # Ambil balik id auto_increment yg baru saja disisipkan, URUTAN SAMA
        # dgn all_rows (INSERT tunggal dlm 1 koneksi/transaksi -- MySQL
        # menjamin id berurutan sesuai urutan baris utk kasus ini). Dipakai
        # sbg simpul_id di tabel radius di bawah (bukan re-match by nama,
        # yang rawan tabrakan drpd andalkan urutan insert yg deterministik).
        cur.execute(
            "SELECT id FROM simpul_transportasi WHERE jenis IN "
            "('BANDARA','PELABUHAN_LAUT','PELABUHAN_NASIONAL','PELABUHAN_PENYEBERANGAN') ORDER BY id"
        )
        ids = [r["id"] for r in cur.fetchall()]
    if len(ids) != len(all_rows):
        sys.exit(f"FATAL: jumlah id hasil INSERT ({len(ids)}) != jumlah baris ({len(all_rows)}) -- "
                  f"urutan tak bisa dipercaya, batal lanjut ke radius kecamatan.")
    n_match = sum(1 for r in all_rows if r[5] is not None)
    print(f"\nTotal: {len(all_rows)} baris dimuat ke simpul_transportasi, {n_match} match kode_kabupaten "
          f"({len(all_rows) - n_match} tidak match)")

    print(f"\nMencari kecamatan dlm radius {args.radius:.0f} km dari tiap simpul...")
    radius_rows = []
    stat_total = Counter()
    for i, (simpul_id, (row, geom)) in enumerate(zip(ids, all_rows_geom), start=1):
        jenis, nama = row[0], row[1]
        kode_prov_hint = row[4]  # kode_provinsi hasil resolusi sblmnya (bisa None)
        hasil, stat = radius_kecamatan(geom, to_3857, tree_m, poly_names, kode_prov_hint,
                                        by_prov_nama_kec, by_nama_kec, args.radius)
        stat_total.update(stat)
        for kode_kec, jarak_km in hasil:
            radius_rows.append((simpul_id, jenis, nama, kode_kec, kode_kec // 1000, jarak_km, int(args.radius)))
        if i % 250 == 0:
            print(f"  ...{i}/{len(ids)}")
    print(f"  Ringkasan resolusi kecamatan dlm radius: {dict(stat_total)}")

    with db_cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='simpul_transportasi_kecamatan_radius'"
        )
        if not cur.fetchone():
            sys.exit(
                "Tabel simpul_transportasi_kecamatan_radius belum ada di PostgreSQL -- "
                "jalankan scripts/migrate_pg_01_schema.py dulu."
            )
        simpul_ids_diproses = list(ids)
        cur.execute(
            "DELETE FROM simpul_transportasi_kecamatan_radius WHERE simpul_id = ANY(%s)",
            (simpul_ids_diproses,),
        )
        cur.executemany(
            "INSERT INTO simpul_transportasi_kecamatan_radius "
            "(simpul_id, jenis_simpul, nama_simpul, kode_kecamatan, kode_kabupaten, jarak_km, radius_km) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            radius_rows,
        )
    n_simpul_ada_kecamatan = len({r[0] for r in radius_rows})
    print(f"\nTotal: {len(radius_rows)} pasangan simpul-kecamatan dlm radius {args.radius:.0f} km "
          f"({n_simpul_ada_kecamatan}/{len(ids)} simpul py minimal 1 kecamatan teresolusi)")


if __name__ == "__main__":
    main()
