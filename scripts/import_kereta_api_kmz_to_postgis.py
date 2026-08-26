# -*- coding: utf-8 -*-
"""Impor layer perkeretaapian (Peta Jalur Kereta Api.kmz, diekspor dari Google
My Maps) ke PostGIS, sebagai overlay `map_layers` baru -- pola yang sama
dengan `import_peta_koridor_to_postgis.py`/`import_maps_to_postgis.py`
(provinsi/kabupaten/layer/attrs JSONB/geom), bukan tabel khusus, karena
sumbernya cuma satu file nasional tanpa pembagian provinsi/kabupaten sendiri.

Sumber: docs/New/5. DARAT-20260820T015302Z-1-001/Peta Jalur Kereta Api.kmz
(KMZ = zip berisi doc.kml + images/ icon). Setiap <Folder> di KML jadi satu
layer (provinsi="KERETA API" tetap, kabupaten="", layer=nama folder --
"Stasiun Kereta Api", "Rel Jawa", "Rel Sumatera", "Rel Sulawesi Selatan",
"Jembatan KA", "Jalur KA Perkotaan", "Batas BTP", "Gudang Prasarana
Perkeretaapian"), sama seperti JALAN NASIONAL/JALAN TOL yang juga dipetakan
sebagai provinsi tanpa kabupaten. `map_layer_label()` sudah fallback ke
`stem.replace("_", " ").title()` untuk nama yang bukan kode RBI, jadi nama
folder KML (sudah dalam Bahasa Indonesia yang layak tampil) tidak perlu
entri baru di `map_layer_labels.py`.

Atribut per Placemark diambil dari <ExtendedData><Data name=..><value>,
ditambah <name>/<description> milik Placemark itu sendiri (disimpan sebagai
key "name"/"deskripsi_placemark" di `attrs` supaya tidak bentrok dengan
field ExtendedData yang kadang juga bernama "deskripsi").

Resumable per layer (skip kalau sudah ada di map_layer_meta, kecuali
--force) -- sama seperti script import lain.

Usage (venv aktif):
    python scripts/import_kereta_api_kmz_to_postgis.py
    python scripts/import_kereta_api_kmz_to_postgis.py --force
"""
import argparse
import io
import sys
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import shapely
import shapely.wkt
from psycopg.types.json import Json

from db import db_cursor as pg_cursor  # noqa: E402
from map_layer_labels import map_layer_label  # noqa: E402

KMZ_PATH = (Path(__file__).resolve().parent.parent / "docs" / "New" /
            "5. DARAT-20260820T015302Z-1-001" / "Peta Jalur Kereta Api.kmz")
PROVINSI = "KERETA API"
KABUPATEN = ""
KML_NS = "http://www.opengis.net/kml/2.2"
NS = {"kml": KML_NS}
INSERT_BATCH = 2000


def _tag(el):
    return el.tag.split("}")[-1]


def _parse_coords(text):
    """'lon,lat,alt lon,lat,alt ...' (whitespace/newline separated) -> [(lon, lat), ...]."""
    pts = []
    for chunk in text.split():
        parts = chunk.split(",")
        if len(parts) < 2:
            continue
        lon, lat = float(parts[0]), float(parts[1])
        pts.append((lon, lat))
    return pts


def _geom_from_element(el):
    tag = _tag(el)
    if tag == "Point":
        coords_el = el.find("kml:coordinates", NS)
        if coords_el is None or not coords_el.text:
            return None
        pts = _parse_coords(coords_el.text)
        if not pts:
            return None
        return shapely.Point(pts[0])
    if tag == "LineString":
        coords_el = el.find("kml:coordinates", NS)
        if coords_el is None or not coords_el.text:
            return None
        pts = _parse_coords(coords_el.text)
        if len(pts) < 2:
            return None
        return shapely.LineString(pts)
    if tag == "Polygon":
        ring_el = el.find("kml:outerBoundaryIs/kml:LinearRing/kml:coordinates", NS)
        if ring_el is None or not ring_el.text:
            return None
        pts = _parse_coords(ring_el.text)
        if len(pts) < 4:
            return None
        return shapely.Polygon(pts)
    if tag == "MultiGeometry":
        parts = [g for g in (_geom_from_element(child) for child in el) if g is not None]
        if not parts:
            return None
        if len(parts) == 1:
            return parts[0]
        types = {p.geom_type for p in parts}
        # Dibangun lewat WKT, bukan shapely.MultiLineString(list)/MultiPoint(list)
        # langsung -- konstruktor itu kena bug numpy 2.x/shapely 2.0.4
        # "TypeError: ufunc 'create_collection' not supported" saat menerima
        # list objek Python (sama dgn bug create_collection yg sudah
        # didokumentasikan di spatial_konektivitas_jalan.py/
        # spatial_join_kecamatan_multi.py utk kasus reproject serupa).
        if types == {"Point"}:
            coords = ", ".join(f"{p.x} {p.y}" for p in parts)
            return shapely.wkt.loads(f"MULTIPOINT ({coords})")
        if types == {"LineString"}:
            lines = ", ".join("(" + ", ".join(f"{x} {y}" for x, y in ls.coords) + ")" for ls in parts)
            return shapely.wkt.loads(f"MULTILINESTRING ({lines})")
        if types == {"Polygon"}:
            return shapely.wkt.loads(
                "MULTIPOLYGON (" + ", ".join(p.wkt.replace("POLYGON ", "") for p in parts) + ")")
        return shapely.wkt.loads("GEOMETRYCOLLECTION (" + ", ".join(p.wkt for p in parts) + ")")
    return None


def _placemark_geom(pm):
    for child in pm:
        geom = _geom_from_element(child)
        if geom is not None:
            return geom
    return None


def _placemark_attrs(pm):
    attrs = {}
    name_el = pm.find("kml:name", NS)
    if name_el is not None and name_el.text:
        attrs["name"] = name_el.text.strip()
    desc_el = pm.find("kml:description", NS)
    if desc_el is not None and desc_el.text and desc_el.text.strip():
        attrs["deskripsi_placemark"] = desc_el.text.strip()
    for data_el in pm.findall("kml:ExtendedData/kml:Data", NS):
        key = data_el.get("name")
        if not key:
            continue
        value_el = data_el.find("kml:value", NS)
        value = value_el.text.strip() if value_el is not None and value_el.text else None
        attrs[key] = value if value else None
    return attrs


def _iter_folders(root):
    for folder in root.findall(".//kml:Folder", NS):
        name_el = folder.find("kml:name", NS)
        name = name_el.text.strip() if name_el is not None and name_el.text else None
        placemarks = folder.findall("kml:Placemark", NS)
        if not name or not placemarks:
            continue
        yield name, placemarks


def _already_imported(cur, layer):
    cur.execute(
        "SELECT 1 FROM map_layer_meta WHERE provinsi=%s AND kabupaten=%s AND layer=%s",
        (PROVINSI, KABUPATEN, layer),
    )
    return cur.fetchone() is not None


def _delete_layer(cur, layer):
    cur.execute(
        "DELETE FROM map_layers WHERE provinsi=%s AND kabupaten=%s AND layer=%s",
        (PROVINSI, KABUPATEN, layer),
    )
    cur.execute(
        "DELETE FROM map_layer_meta WHERE provinsi=%s AND kabupaten=%s AND layer=%s",
        (PROVINSI, KABUPATEN, layer),
    )


def import_folder(cur, layer, placemarks, kmz_path):
    rows = []
    n_bad = 0
    for pm in placemarks:
        geom = _placemark_geom(pm)
        if geom is None or geom.is_empty:
            n_bad += 1
            continue
        attrs = _placemark_attrs(pm)
        rows.append((PROVINSI, KABUPATEN, layer, Json(attrs), geom.wkb_hex))
    if n_bad:
        print(f"    ({n_bad} placemark tanpa geometri valid dilewati)")

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
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (provinsi, kabupaten, layer) DO UPDATE SET
               label=EXCLUDED.label, feature_count=EXCLUDED.feature_count,
               size_mb=EXCLUDED.size_mb, source_shp=EXCLUDED.source_shp,
               imported_at=now()""",
        (PROVINSI, KABUPATEN, layer, map_layer_label(layer), len(rows),
         round(kmz_path.stat().st_size / 1_048_576, 2),
         str(kmz_path.name)),
    )
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kmz", default=str(KMZ_PATH), help="path ke Peta Jalur Kereta Api.kmz")
    ap.add_argument("--force", action="store_true", help="impor ulang layer yang sudah ada di map_layer_meta")
    args = ap.parse_args()

    kmz_path = Path(args.kmz)
    if not kmz_path.exists():
        print(f"File tidak ditemukan: {kmz_path}")
        sys.exit(1)

    with zipfile.ZipFile(kmz_path) as z:
        kml_data = z.read("doc.kml")
    root = ET.fromstring(kml_data)

    t0 = time.time()
    total_layers = total_features = total_skipped = 0
    for layer, placemarks in _iter_folders(root):
        with pg_cursor() as cur:
            if not args.force and _already_imported(cur, layer):
                total_skipped += 1
                print(f"  (lewati, sudah ada) {layer}")
                continue
            if args.force:
                _delete_layer(cur, layer)
            try:
                n = import_folder(cur, layer, placemarks, kmz_path)
            except Exception as e:
                print(f"  GAGAL {layer}: {e}")
                continue
        total_layers += 1
        total_features += n
        print(f"  [{total_layers}] {layer} -> {n} fitur")

    dt = time.time() - t0
    print(f"\nSelesai: {total_layers} layer diimpor ({total_features} fitur total), "
          f"{total_skipped} layer dilewati (sudah ada), {dt:.1f}s")


if __name__ == "__main__":
    main()
