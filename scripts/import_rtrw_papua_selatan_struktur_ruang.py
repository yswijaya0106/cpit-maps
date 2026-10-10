"""Struktur ruang RTRW Provinsi Papua Selatan (Perda 3/2025) dari paket "SHP KSPEAN Klaster
Subklaster 2026-2029" -> layer bucket RTRW / kabupaten "Papua Selatan".

Sumber: docs/10102026/SHP KSPEAN Klaster Subklaster 2026 - 2029-...zip (Drive Konektivitas
"9. DATA LAINNYA", 27 Sep 2026), diekstrak ke Maps/_sumber_kspean_2026/. Subklaster dan
Jaringan Jalan di paket ini IDENTIK (hash sama) dgn yang sudah diimpor
(import_subklaster_to_postgis.py, import_rtrw_papua_selatan_jaringan_to_postgis.py) -> dilewati.

Layer (semua atribut KUGI: NAMOBJ = jenis, REMARK = nama, STSJRN 1 = Rencana / 2 = Eksisting,
konvensi yang sama dgn import_rtrw_papua_selatan_jaringan_to_postgis.py):
  Simpul Transportasi & Logistik (RTRW Papua Selatan)   278 titik (jembatan, pelabuhan, bandara, terminal khusus)
  Infrastruktur Energi (RTRW Papua Selatan)               48 titik (pembangkit, migas, gardu)
  Jaringan Transmisi Listrik (RTRW Papua Selatan)          1 garis (transmisi KEK Merauke)
  Sistem Pusat Permukiman (RTRW Papua Selatan)            18 titik (PKN/PKSN/PKW/PKL)
  Jaringan Telekomunikasi (RTRW Papua Selatan)             5 titik
  Jaringan Irigasi (RTRW Papua Selatan)                 2168 garis (D.I. Kurik, Tanah Miring, ...)
  Rencana Irigasi Demplot Wanam (KSPEAN)                 saluran/tanggul/petak rencana dari gambar CAD
                                                         (UTM 54S, diproyeksikan ke WGS84), komponen = nama folder
Sengaja TIDAK dipakai: kolom KUGI PP/BA/CT/BT/MD (kode administrasi data, tanpa arti utk peta).

Hapus per (bucket, kabupaten, layer) -- tidak menyentuh layer RTRW lain. Jumlah fitur harus sama
dgn sumber. Aman di-rerun.

Usage (venv aktif):
    python scripts/import_rtrw_papua_selatan_struktur_ruang.py --cek
    python scripts/import_rtrw_papua_selatan_struktur_ruang.py
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import geopandas as gpd  # noqa: E402
import pandas as pd  # noqa: E402
import shapely  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from psycopg.types.json import Json  # noqa: E402

load_dotenv(REPO_ROOT / ".env")
from db import db_cursor  # noqa: E402

SUMBER = REPO_ROOT / "Maps" / "_sumber_kspean_2026" / "SHP KSPEAN Klaster Subklaster 2026 - 2029"
BUCKET, KAB = "RTRW", "Papua Selatan"
STATUS = {1: "Rencana", 2: "Eksisting"}
# warna HARUS sama dgn LEGENDA_PER_LAYER di static/js/maps-overlay.js
WARNA_STATUS = {"Eksisting": "#0F766E", "Rencana": "#F59E0B"}
WARNA_DEMPLOT = {"Saluran Primer Pemberi": "#1D4ED8", "Saluran Sekunder Pemberi": "#3B82F6",
                 "Saluran Tersier": "#93C5FD", "Saluran Primer Pembuang": "#B91C1C",
                 "Saluran Sekunder Pembuang": "#F87171", "Saluran Gendong": "#7C3AED",
                 "Tanggul Luar": "#78350F", "Tanggul Dalam": "#A16207", "Tanggul Lahan": "#D97706",
                 "Lahan": "#9CA3AF", "Area Demplot": "#16A34A"}
KUGI = [
    ("SHP Konektivitas dan Logistik/Infrastruktur Konektivitas dan Logistik.shp",
     "Simpul Transportasi & Logistik (RTRW Papua Selatan)", 278),
    ("SHP Pembangkit Listrik/Infrastruktur Pembangkit Listrik.shp", "Infrastruktur Energi (RTRW Papua Selatan)", 48),
    ("SHP Jaringan Transmisi Listrik/Jaringan Transmisi Listrik.shp", "Jaringan Transmisi Listrik (RTRW Papua Selatan)", 1),
    ("Sistem Pusat Permukiman/Sistem Pusat Permukiman.shp", "Sistem Pusat Permukiman (RTRW Papua Selatan)", 18),
    ("SHP Jaringan Telekomunikasi/Jaringan Telekomunikasi.shp", "Jaringan Telekomunikasi (RTRW Papua Selatan)", 5),
    ("SHP Jaringan Irigasi/Irigasi Eksisting/Jaringan Irigasi.shp", "Jaringan Irigasi (RTRW Papua Selatan)", 2168),
]
DEMPLOT = "Rencana Irigasi Demplot Wanam (KSPEAN)"


def baca(path):
    g = gpd.read_file(path, engine="pyogrio", on_invalid="ignore")
    if g.crs is None:
        raise SystemExit(f"DITOLAK: {path} tanpa CRS")
    return g.to_crs(4326) if g.crs.to_epsg() != 4326 else g


def geom_bersih(geom):
    if geom is None or geom.is_empty:
        return None
    if geom.has_z:
        geom = shapely.force_2d(geom)
    return geom if geom.is_valid else shapely.make_valid(geom)


def teks(v):
    return None if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() in ("", "-") else str(v).strip()


def siapkan():
    hasil = []
    for rel, layer, n_harus in KUGI:
        g = baca(SUMBER / rel)
        rows = []
        for _, r in g.iterrows():
            geom = geom_bersih(r.geometry)
            if geom is None:
                continue
            status = STATUS.get(int(r["STSJRN"])) if pd.notna(r.get("STSJRN")) else None
            a = {"Nama": teks(r.get("REMARK")), "Jenis": teks(r.get("NAMOBJ")), "Status": status,
                 "Sumber data": teks(r.get("SBDATA")), "Dasar hukum": teks(r.get("NOTHPR")),
                 "Provinsi": teks(r.get("WADMPR")),
                 "_warna": WARNA_STATUS.get(status, "#6B7280")}
            rows.append(({k: v for k, v in a.items() if v is not None}, geom.wkb_hex))
        if len(rows) != len(g) or len(g) != n_harus:
            raise SystemExit(f"DITOLAK {layer}: sumber {len(g)} (harus {n_harus}), siap {len(rows)}")
        hasil.append((layer, rows, rel))
    rows = []
    n_sumber = 0
    for shp in sorted((SUMBER / "SHP Jaringan Irigasi" / "Irigasi Rencana").glob("*/*.shp")):
        komponen = shp.parent.name
        g = baca(shp)
        n_sumber += len(g)
        for _, r in g.iterrows():
            geom = geom_bersih(r.geometry)
            if geom is None:
                continue
            rows.append(({"Komponen": komponen, "Jenis": "Rencana irigasi demplot (gambar CAD)",
                          "Status": "Rencana", "Lokasi": "Wanam, Kab. Merauke (KSPEAN)",
                          "_warna": WARNA_DEMPLOT.get(komponen, "#6B7280"), "_lebar": 1.5}, geom.wkb_hex))
    if len(rows) != n_sumber:
        raise SystemExit(f"DITOLAK {DEMPLOT}: sumber {n_sumber}, siap {len(rows)}")
    hasil.append((DEMPLOT, rows, "SHP Jaringan Irigasi/Irigasi Rencana/*"))
    return hasil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cek", action="store_true")
    a = ap.parse_args()
    if not SUMBER.exists():
        sys.exit(f"Folder sumber {SUMBER} tidak ada -- ekstrak dulu zip di docs/10102026/ ke Maps/_sumber_kspean_2026/")
    hasil = siapkan()
    for layer, rows, _ in hasil:
        print(f"OK {layer}: {len(rows)} fitur")
    if a.cek:
        print("Mode --cek: tidak menulis ke database.")
        return
    with db_cursor() as cur:
        for layer, rows, rel in hasil:
            cur.execute("DELETE FROM map_layers WHERE provinsi=%s AND kabupaten=%s AND layer=%s", (BUCKET, KAB, layer))
            cur.executemany(
                "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
                "VALUES (%s, %s, %s, %s, ST_GeomFromWKB(decode(%s, 'hex'), 4326))",
                [(BUCKET, KAB, layer, Json(attrs), wkb) for attrs, wkb in rows])
            cur.execute("""
                INSERT INTO map_layer_meta (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp)
                SELECT %s, %s, %s, %s, COUNT(*),
                       ROUND((SUM(pg_column_size(geom) + pg_column_size(attrs)) / 1048576.0)::numeric, 2), %s
                FROM map_layers WHERE provinsi = %s AND kabupaten = %s AND layer = %s
                ON CONFLICT (provinsi, kabupaten, layer) DO UPDATE SET label = EXCLUDED.label,
                    feature_count = EXCLUDED.feature_count, size_mb = EXCLUDED.size_mb,
                    source_shp = EXCLUDED.source_shp, imported_at = now()""",
                (BUCKET, KAB, layer, layer, "_sumber_kspean_2026/" + rel, BUCKET, KAB, layer))
        cur.execute("SELECT layer, feature_count, size_mb FROM map_layer_meta WHERE provinsi=%s AND kabupaten=%s "
                    "ORDER BY layer", (BUCKET, KAB))
        for r in cur.fetchall():
            print(f"DB {BUCKET}/{KAB}/{r['layer']}: {r['feature_count']} fitur, {r['size_mb']} MB")


if __name__ == "__main__":
    main()
