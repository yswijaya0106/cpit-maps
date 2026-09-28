# -*- coding: utf-8 -*-
"""Impor Jaringan Transportasi RTRW Provinsi Papua Selatan (Perda Prov.
Papua Selatan No. 3/2025, RTRW 2025-2045; docs/250820206/SHP Jaringan Jalan/
Jaringan Jalan.shp, 115 garis) ke map_layers.

Isi sumber (kolom NAMOBJ) dipecah jadi 2 kelompok:
- Jalan (Arteri Primer, Kolektor Primer, Jalan Khusus; 64 garis) -> layer
  "JARINGAN JALAN RTRW" di bucket provinsi ASLI + kabupaten ASLI (kategori
  "Jalan" di tree overlay, sejajar layer jalan RBI per kabupaten). Tiap garis
  dipotong (intersection) dgn poligon BATAS KABUPATEN -- sumber tidak punya
  kolom kabupaten, dan beberapa ruas (mis. KENYAM - DEKAI) sebenarnya masuk
  Papua Pegunungan walau WADMPR-nya "Papua Selatan", jadi provinsi/kabupaten
  diambil dari poligon, bukan dari WADMPR. Potongan di luar semua poligon
  (garis pantai/laut) dibuang.
- Alur pelayaran (umum & perlintasan, sungai/danau, masuk pelabuhan; 51
  garis) -> layer "Alur Pelayaran (RTRW Struktur Ruang)" di bucket
  provinsi="RTRW", kabupaten="Papua Selatan" (pola sama dgn
  import_rtrw_kalbar_transportasi_to_postgis.py).

STSJRN dibaca menurut konvensi KUGI ATR/BPN: 1 = Rencana, 2 = Eksisting
(konsisten dgn datanya: satu-satunya Jalan Khusus, Wanam - Muting sumber
"KSPP Tahun 2025", ber-STSJRN 1). Ruas rencana diberi warna lebih muda.

"Jalan Wanam - Muting/Jalan Wanam - Muting.shp" (subfolder) SENGAJA tidak
diimpor: ruas yang sama dgn baris "Wanam - Muting" di Jaringan Jalan.shp
(selisih Hausdorff ~1 km), tetapi hanya 4 verteks vs 91 -- versi utama lebih
detail.

Warna/ketebalan garis dikirim lewat properti `_warna`/`_lebar` (generik di
applyLayerStyle, maps-overlay.js); nilainya harus sama dgn
RTRW_PAPSEL_LEGEND di maps-overlay.js.

TIDAK terkait usulan_inpres/IJD. Idempotent: DELETE + reinsert per layer
(layer jalan dihapus di SEMUA bucket provinsi lebih dulu).

Usage (venv aktif):
    python scripts/import_rtrw_papua_selatan_jaringan_to_postgis.py
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
SHP = REPO_ROOT / "docs" / "250820206" / "SHP Jaringan Jalan" / "Jaringan Jalan.shp"

RTRW_PROVINSI = "RTRW"
RTRW_KABUPATEN = "Papua Selatan"
LAYER_JALAN = "JARINGAN JALAN RTRW"
LABEL_JALAN = "Jaringan Jalan (RTRW Prov. Papua Selatan)"
LAYER_ALUR = "Alur Pelayaran (RTRW Struktur Ruang)"
LAYER_JALAN_LAMA = "Jaringan Jalan (RTRW Struktur Ruang)"  # impor versi awal, dihapus
MIN_PANJANG_POTONGAN = 0.0005  # derajat (~50 m): serpihan di tepi batas kabupaten dibuang

STATUS_JARINGAN = {1: "Rencana", 2: "Eksisting"}
# (warna eksisting, warna rencana, lebar px) per NAMOBJ
GAYA = {
    "Jalan Arteri Primer": ("#C62828", "#EF9A9A", 4),
    "Jalan Kolektor Primer": ("#EF6C00", "#FFB74D", 3),
    "Jalan Khusus": ("#6A1B9A", "#B39DDB", 3),
    "Alur-Pelayaran Umum dan Perlintasan": ("#1565C0", "#90CAF9", 2),
    "Alur-Pelayaran Sungai dan Alur-Pelayaran Danau": ("#00ACC1", "#80DEEA", 2),
    "Alur-Pelayaran Masuk Pelabuhan": ("#0D47A1", "#64B5F6", 3),
}
GAYA_LAIN = ("#8a94a6", "#cfd4dc", 2)


def _attrs(row):
    status = STATUS_JARINGAN.get(int(row["STSJRN"])) if row["STSJRN"] is not None else None
    warna_eks, warna_ren, lebar = GAYA.get(row["NAMOBJ"], GAYA_LAIN)
    attrs = {
        "Name": row["REMARK"],
        "Jenis": row["NAMOBJ"],
        "Status Jaringan": status,
        "Sumber Data": row["SBDATA"],
        "Provinsi (RTRW)": row["WADMPR"],
        "Dasar Hukum RTRW": row["NOTHPR"],
        "_warna": warna_ren if status == "Rencana" else warna_eks,
        "_lebar": lebar,
    }
    return {k: v for k, v in attrs.items() if v}


def _garis_saja(geom):
    """Ambil bagian garis dari hasil intersection (bisa GeometryCollection berisi titik)."""
    if geom.is_empty:
        return None
    if geom.geom_type in ("LineString", "MultiLineString"):
        return geom
    parts = [g for g in getattr(geom, "geoms", []) if g.geom_type in ("LineString", "MultiLineString")]
    return shapely.line_merge(shapely.union_all(parts)) if parts else None


def _poligon_kabupaten(cur, bbox):
    """Poligon BATAS KABUPATEN (import_batas_administrasi_kabupaten_provinsi.py) yg bersinggungan bbox."""
    cur.execute(
        """SELECT attrs->>'PROVINSI' AS provinsi, attrs->>'KABUPATEN_KOTA' AS kabupaten,
                  ST_AsBinary(geom) AS wkb
           FROM map_layers
           WHERE provinsi='BATAS KABUPATEN' AND geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)""",
        tuple(bbox),
    )
    return [(r["provinsi"].upper(), r["kabupaten"], shapely.from_wkb(bytes(r["wkb"]))) for r in cur.fetchall()]


def _simpan_meta(cur, provinsi, kabupaten, layer, label, records):
    cur.execute(
        """INSERT INTO map_layer_meta
               (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (provinsi, kabupaten, layer) DO UPDATE SET
               label=EXCLUDED.label, feature_count=EXCLUDED.feature_count,
               size_mb=EXCLUDED.size_mb, source_shp=EXCLUDED.source_shp,
               imported_at=now()""",
        (provinsi, kabupaten, layer, label, len(records),
         round(sum(len(r[4]) / 2 for r in records) / 1_048_576, 2),
         str(SHP.relative_to(REPO_ROOT))),
    )


def _insert(cur, records):
    cur.executemany(
        "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
        "VALUES (%s, %s, %s, %s, ST_GeomFromWKB(decode(%s, 'hex'), 4326))",
        records,
    )


def main():
    if not SHP.exists():
        print(f"GAGAL: tidak ditemukan {SHP}")
        sys.exit(1)

    gdf = gpd.read_file(SHP, engine="pyogrio")
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    gdf["geometry"] = [shapely.force_2d(g) if g is not None and g.has_z else g for g in gdf.geometry]
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    is_alur = gdf["NAMOBJ"].astype(str).str.startswith("Alur")
    alur, jalan = gdf[is_alur], gdf[~is_alur]

    with pg_cursor() as cur:
        # --- alur pelayaran: bucket RTRW / Papua Selatan ---
        for layer in (LAYER_ALUR, LAYER_JALAN_LAMA):
            cur.execute("DELETE FROM map_layers WHERE provinsi=%s AND kabupaten=%s AND layer=%s",
                        (RTRW_PROVINSI, RTRW_KABUPATEN, layer))
            cur.execute("DELETE FROM map_layer_meta WHERE provinsi=%s AND kabupaten=%s AND layer=%s",
                        (RTRW_PROVINSI, RTRW_KABUPATEN, layer))
        records = [(RTRW_PROVINSI, RTRW_KABUPATEN, LAYER_ALUR, Json(_attrs(r)), r.geometry.wkb_hex)
                   for _, r in alur.iterrows()]
        _insert(cur, records)
        _simpan_meta(cur, RTRW_PROVINSI, RTRW_KABUPATEN, LAYER_ALUR, LAYER_ALUR, records)
        print(f"{LAYER_ALUR}: {len(records)} garis (RTRW / {RTRW_KABUPATEN}).")

        # --- jalan: dipotong per kabupaten, bucket provinsi/kabupaten asli ---
        polys = _poligon_kabupaten(cur, jalan.total_bounds)
        per_kab, panjang_luar = {}, 0.0
        for _, r in jalan.iterrows():
            attrs, sisa = _attrs(r), r.geometry
            for prov, kab, poly in polys:
                if not r.geometry.intersects(poly):
                    continue
                bagian = _garis_saja(r.geometry.intersection(poly))
                if bagian is None or bagian.length < MIN_PANJANG_POTONGAN:
                    continue
                per_kab.setdefault((prov, kab), []).append(
                    (prov, kab, LAYER_JALAN, Json(attrs), bagian.wkb_hex))
                sisa = sisa.difference(poly)
            panjang_luar += 0 if sisa.is_empty else sisa.length

        cur.execute("DELETE FROM map_layers WHERE layer=%s", (LAYER_JALAN,))
        cur.execute("DELETE FROM map_layer_meta WHERE layer=%s", (LAYER_JALAN,))
        for (prov, kab), records in sorted(per_kab.items()):
            _insert(cur, records)
            _simpan_meta(cur, prov, kab, LAYER_JALAN, LABEL_JALAN, records)
            print(f"{LAYER_JALAN}: {len(records)} potongan ruas -> {prov} / {kab}")
        print(f"  panjang di luar semua poligon kabupaten (dibuang): ~{panjang_luar * 111:.1f} km")
    print("Selesai. Restart server bila layer ini sudah pernah dibuka (cache _map_layer_geojson_cache).")


if __name__ == "__main__":
    main()
