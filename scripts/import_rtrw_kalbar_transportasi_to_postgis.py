# -*- coding: utf-8 -*-
"""Impor 2 layer Rencana Struktur Ruang RTRW Provinsi Kalimantan Barat
(Perda No. 8/2024, docs/New/11092026/.../RTRW KALBAR/RENCAN POLA RUANG DAN
STRUKTUR RUANG_Shp/) yang relevan Udara/Laut/Darat/Jalan ke map_layers --
lihat docs/kajian_data_baru_11092026.md §2:

- Sistem_Infrastruktur_Transportasit.shp (314 titik) -- simpul transportasi
  RTRW dgn HIERARKI RESMI (Bandar Udara Pengumpul/Pengumpan/Khusus,
  Pelabuhan Utama/Pengumpul/Pengumpan/Penyeberangan/Sungai dan Danau,
  Terminal Tipe A/B, Jembatan Timbang, dst) -- atribut yang TIDAK ada di
  sumber manapun yang sudah diimpor (bps_data_bandara/bandara_kemenhub/
  pelabuhan_daerah/bps_kinerja_pelabuhan tidak punya kolom hierarki RTRW).
- Sistem_Jaringan_Transportasi.shp (326 garis) -- jaringan jalan per fungsi
  (Arteri/Kolektor/Lokal Primer, Tol) + alur pelayaran sungai/danau (jalur
  pelayaran yang juga belum ada layer-nya di aplikasi).

Layer lain di folder yang sama (Rencana_Pola_Ruang, Penetapan_Kawasan_
Strategis, Sistem_Infrastruktur_Energi/Prasarana_Lainnya/Sumber_Daya_Air/
Telekomunikasi, Sistem_Jaringan_Energi/Sumber_Daya_Air/Telekomunikasi,
Sistem_Pusat_Permukiman) SENGAJA tidak diimpor di sini -- di luar cakupan
Udara/Laut/Darat/Jalan (zonasi lahan & sektor lain), lihat kajian di atas.

**Cakupan cuma 1 provinsi** (Kalimantan Barat) -- bukan sumber nasional,
lihat catatan di kajian. Bucket provinsi="RTRW", kabupaten="Kalimantan
Barat" (bukan bucket nasional flat spt JALAN NASIONAL) supaya kalau nanti
ada dump RTRW provinsi lain, tinggal ditambah kabupaten baru dgn pola yang
sama -- bukan revisi struktur bucket.

TIDAK terkait usulan_inpres/IJD.

Idempotent: DELETE + reinsert penuh per layer.

Usage (venv aktif):
    python scripts/import_rtrw_kalbar_transportasi_to_postgis.py
"""
import io
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
BASE_DIR = (
    REPO_ROOT / "docs" / "New" / "11092026" / "drive-download-20260911T021054Z-1-001"
    / "RTRW KALBAR (1)" / "RTRW KALBAR" / "RENCAN POLA RUANG DAN STRUKTUR RUANG_Shp"
)

PROVINSI = "RTRW"
KABUPATEN = "Kalimantan Barat"

DATASETS = [
    ("Sistem_Infrastruktur_Transportasit.shp", "Simpul Transportasi (RTRW Struktur Ruang)"),
    ("Sistem_Jaringan_Transportasi.shp", "Jaringan Transportasi (RTRW Struktur Ruang)"),
]

ATTR_COLS = ["NAMOBJ", "REMARK", "WADMPR"]


def import_dataset(cur, filename: str, layer: str):
    gdf = gpd.read_file(BASE_DIR / filename, engine="pyogrio")
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    records = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty or not geom.is_valid:
            continue
        if geom.has_z:
            geom = shapely.force_2d(geom)
        attrs = {
            "Name": row.get("REMARK") or row.get("NAMOBJ"),
            "Jenis": row.get("NAMOBJ"),
            "Provinsi (RTRW)": row.get("WADMPR"),
        }
        attrs = {k: v for k, v in attrs.items() if v}
        records.append((PROVINSI, KABUPATEN, layer, Json(attrs), geom.wkb_hex))

    cur.execute("DELETE FROM map_layers WHERE provinsi=%s AND kabupaten=%s AND layer=%s", (PROVINSI, KABUPATEN, layer))
    cur.executemany(
        "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
        "VALUES (%s, %s, %s, %s, ST_GeomFromWKB(decode(%s, 'hex'), 4326))",
        records,
    )
    cur.execute(
        """INSERT INTO map_layer_meta
               (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (provinsi, kabupaten, layer) DO UPDATE SET
               label=EXCLUDED.label, feature_count=EXCLUDED.feature_count,
               size_mb=EXCLUDED.size_mb, source_shp=EXCLUDED.source_shp,
               imported_at=now()""",
        (PROVINSI, KABUPATEN, layer, layer, len(records), 0, str((BASE_DIR / filename).relative_to(REPO_ROOT))),
    )
    return len(records)


def main():
    with pg_cursor() as cur:
        for filename, layer in DATASETS:
            n = import_dataset(cur, filename, layer)
            print(f"{layer}: {n} fitur diimpor.")
    print(f"Selesai: RTRW Kalbar (provinsi='{PROVINSI}', kabupaten='{KABUPATEN}') diimpor.")


if __name__ == "__main__":
    main()
