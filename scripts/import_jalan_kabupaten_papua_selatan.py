# -*- coding: utf-8 -*-
"""Impor jaringan jalan kabupaten Papua Selatan (data Pemda) sbg layer overlay.

Sumber: Google Drive "Jalan Kabupaten Papua Selatan" (deck "20261007
PENAMBAHAN PENYEMPURNAAN SIJALAN" slide 1), diunduh ke
docs/07102026/Jalan Kabupaten Papua Selatan/<94xx Kab. X>/ (kode folder = kode
LAMA sebelum pemekaran; kode BPS sekarang 9501-9504). Tiap kabupaten format &
atributnya berbeda, jadi dipetakan satu per satu ke atribut baku:

- Merauke : JARINGAN_JALAN KAB_MERAUKE.shp (1.643 ruas, status, kondisi, perkerasan)
- Boven Digoel : SHP GIS/Administrasi/Jalan Eksisting.shp (950 garis; garis
  "Landas Pacu ..." DIBUANG -- itu landasan bandara, bukan jalan; NAMA_UNSUR
  RBI disimpan sbg "Fungsi" supaya Jalan Lain/Setapak terbaca kelas desa).
  Folder GPS1/GPS2 (jejak survei lapangan) & "Rencana Jalan" (tanpa .dbf) dilewati.
- Mappi : Jalan.shp (374 ruas; nama berisi "Rencana" ditandai rencana)
- Asmat : Jalan_Kabupaten_Asmat.shp (Pemda 2021) + Jalan_Asmat_RBI.shp (RBI/DJJ 2018) sbg layer kedua

Hasil: map_layers bucket provinsi "PAPUA SELATAN", kabupaten "Kabupaten X",
layer "JALAN KABUPATEN (PEMDA)" (+ "JALAN KABUPATEN (RBI DJJ 2018)" utk Asmat).
Nama layer berawalan JALAN -> otomatis diwarnai hierarki jalan di peta
(maps-overlay.js JALAN_KELAS). DELETE + INSERT per layer; layer lain di bucket
yang sama (PETA KORIDOR, JARINGAN JALAN RTRW) tidak disentuh.

Usage (venv aktif, PG_* di .env): python scripts/import_jalan_kabupaten_papua_selatan.py
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import geopandas as gpd  # noqa: E402
import shapely  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from psycopg.types.json import Json  # noqa: E402
from pyproj import Geod  # noqa: E402

load_dotenv(REPO_ROOT / ".env")
from db import db_cursor  # noqa: E402

BASE = REPO_ROOT / "docs" / "07102026" / "Jalan Kabupaten Papua Selatan"
PROVINSI = "PAPUA SELATAN"
LAYER_PEMDA = "JALAN KABUPATEN (PEMDA)"
LAYER_RBI = "JALAN KABUPATEN (RBI DJJ 2018)"
GEOD = Geod(ellps="WGS84")


def teks(v):
    if v is None or (isinstance(v, float) and v != v):
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s or None


def kondisi(v):
    s = (teks(v) or "").lower()
    if s.startswith("sedan"):
        return "Sedang"
    return s.title() or None


def attrs_merauke(r):
    return {"Nama Ruas": teks(r.get("Nm_Ruas")), "No. Ruas": teks(r.get("No_Ruas")),
            "Status": teks(r.get("Status")), "Kondisi": kondisi(r.get("Kondisi")),
            "Perkerasan": teks(r.get("Perkerasan")), "Lebar (m)": r.get("Lebar"),
            "Kecamatan": teks(r.get("Kecamatan")),
            "Klasifikasi (kode sumber)": teks(r.get("Klasi"))}


def attrs_boven(r):
    unsur = teks(r.get("NAMA_UNSUR"))
    if unsur and unsur.lower().startswith("landas pacu"):
        return None  # landasan bandara, bukan jalan
    # Sumber tidak punya kolom status -> TIDAK diisi (status didahulukan dlm
    # klasifikasi warna; mengisinya akan membuat Jalan Lain/Setapak terbaca kab/kota).
    return {"Fungsi": unsur or "Tidak tercatat"}


def attrs_mappi(r):
    nama = teks(r.get("Nama"))
    a = {"Nama Ruas": nama, "Panjang sumber (km)": r.get("Panjang_Km")}  # sumber tanpa kolom status
    if nama and "rencana" in nama.lower():
        a["Keterangan"] = "Ruas rencana (menurut nama di sumber)"
    return a


def attrs_asmat(r):
    return {"Nama Ruas": teks(r.get("Nm_Ruas")), "No. Ruas": teks(r.get("No_Ruas")),
            "Status": teks(r.get("Status")), "Fungsi": teks(r.get("Fungsi")),
            "Distrik": teks(r.get("Distrik") or r.get("Kecamatan")), "Tahun Data": teks(r.get("Thn_Data"))}


SUMBER = [  # (kabupaten bucket, layer, file relatif BASE, fungsi atribut, keterangan sumber)
    ("Kabupaten Merauke", LAYER_PEMDA, "9401 Kab. Merauke/JARINGAN_JALAN KAB_MERAUKE.shp", attrs_merauke,
     "Pemda Kab. Merauke (Jaringan Jalan Kabupaten)"),
    ("Kabupaten Boven Digoel", LAYER_PEMDA, "9413 Kab. Boven Digoel/Jalan Eksisting.shp", attrs_boven,
     "Pemda Kab. Boven Digoel (SHP GIS - Jalan Eksisting)"),
    ("Kabupaten Mappi", LAYER_PEMDA, "9414 Kab. Mappi/Jalan.shp", attrs_mappi, "Pemda Kab. Mappi"),
    ("Kabupaten Asmat", LAYER_PEMDA, "9415 Kab. Asmat/Jalan_Kabupaten_Asmat.shp", attrs_asmat,
     "Pemda Kab. Asmat (2021)"),
    ("Kabupaten Asmat", LAYER_RBI, "9415 Kab. Asmat/Jalan_Asmat_RBI.shp", attrs_asmat, "RBI / DJJ 2018"),
]


def main():
    with db_cursor() as cur:
        for kab, layer, rel, fn, ket in SUMBER:
            path = BASE / rel
            gdf = gpd.read_file(path, engine="pyogrio")
            if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs(4326)
            fitur, dibuang = [], 0
            km_total = 0.0
            for _, r in gdf.iterrows():
                g = r.geometry
                a = fn(r) if g is not None and not g.is_empty else None
                if a is None:
                    dibuang += 1
                    continue
                g = shapely.force_2d(g)
                if not g.is_valid:
                    g = shapely.make_valid(g)
                # garis rusak (mis. 1 titik berulang) bisa berubah jadi Point/koleksi -> ambil garisnya saja
                garis = [x for x in getattr(g, "geoms", [g]) if x.geom_type in ("LineString", "MultiLineString")]
                if not garis:
                    dibuang += 1
                    continue
                g = garis[0] if len(garis) == 1 else shapely.MultiLineString(
                    [ls for x in garis for ls in getattr(x, "geoms", [x])])
                km = GEOD.geometry_length(g) / 1000
                km_total += km
                a = {k: v for k, v in a.items() if v not in (None, "")}
                a["Panjang geometri (km)"] = round(km, 3)
                a["Sumber"] = ket
                fitur.append((Json(a), g.wkb_hex))
            cur.execute("DELETE FROM map_layers WHERE provinsi=%s AND kabupaten=%s AND layer=%s", (PROVINSI, kab, layer))
            cur.executemany(
                "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
                "VALUES (%s, %s, %s, %s, ST_SetSRID(ST_GeomFromWKB(decode(%s, 'hex')), 4326))",
                [(PROVINSI, kab, layer, a, w) for a, w in fitur])
            cur.execute(
                """INSERT INTO map_layer_meta (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (provinsi, kabupaten, layer) DO UPDATE SET
                       label=EXCLUDED.label, feature_count=EXCLUDED.feature_count,
                       size_mb=EXCLUDED.size_mb, source_shp=EXCLUDED.source_shp, imported_at=now()""",
                (PROVINSI, kab, layer, layer, len(fitur), round(sum(len(w) for _, w in fitur) / 2 / 1_048_576, 2),
                 str(path.relative_to(REPO_ROOT))))
            print(f"{kab:24s} {layer:32s} {len(fitur):5d} ruas  {km_total:8,.0f} km  (dibuang {dibuang})")


if __name__ == "__main__":
    main()
