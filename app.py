import io
import json
import re
import zipfile
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Optional

import anthropic
import pymysql
import requests
from dotenv import load_dotenv
import os

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import geopandas as gpd
from pyproj import Geod
import shapely.wkt
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Route to SHP Converter")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Segment(BaseModel):
    segment_id: int
    road_name: Optional[str] = ""
    road_type: Optional[str] = ""
    distance_km: Optional[float] = 0
    duration_min: Optional[float] = 0
    bearing: Optional[float] = None
    start_lat: float
    start_lng: float
    end_lat: float
    end_lng: float


class RoutePayload(BaseModel):
    route_id: str
    route_name: str
    alternative: int
    transport_mode: str
    distance_km: float
    duration_min: float
    coordinates: List[List[float]]  # [[lat, lng], ...]
    segments: Optional[List[Segment]] = []


class ExportRequest(BaseModel):
    format: str
    routes: List[RoutePayload]


class RoadClassRequest(BaseModel):
    coordinates: List[List[float]]  # [[lat, lng], ...]


class RegionQuery(BaseModel):
    provinsi: Optional[str] = None
    kabupaten_kota: Optional[str] = None


class UsulanNearbyRequest(BaseModel):
    regions: List[RegionQuery]


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    text: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    context: Optional[dict] = None


@app.get("/api/config")
def get_config():
    key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    if not key:
        raise HTTPException(500, "GOOGLE_MAPS_API_KEY belum diset di file .env")
    return {"googleMapsApiKey": key}


def _routes_to_geodataframe(routes: List[RoutePayload]) -> gpd.GeoDataFrame:
    records = []
    for r in routes:
        line = LineString([(lng, lat) for lat, lng in r.coordinates])
        records.append({
            "route_id": r.route_id,
            "route_name": r.route_name[:80],
            "distance_km": round(r.distance_km, 3),
            "duration_min": round(r.duration_min, 2),
            "transport_mode": r.transport_mode,
            "alternative": r.alternative,
            "geometry": line,
        })
    return gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")


def _build_geojson(routes: List[RoutePayload]) -> dict:
    gdf = _routes_to_geodataframe(routes)
    return json.loads(gdf.to_json())


def _build_vertex_csv(routes: List[RoutePayload]) -> str:
    lines = ["route_id,route_name,alternative,seq,lat,lng"]
    for r in routes:
        for seq, (lat, lng) in enumerate(r.coordinates):
            lines.append(f'{r.route_id},"{r.route_name}",{r.alternative},{seq},{lat},{lng}')
    return "\n".join(lines)


def _build_gpx(routes: List[RoutePayload]) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="analytic-maps" xmlns="http://www.topografix.com/GPX/1/1">',
    ]
    for r in routes:
        parts.append(f'  <trk><name>{r.route_name}</name><trkseg>')
        for lat, lng in r.coordinates:
            parts.append(f'    <trkpt lat="{lat}" lon="{lng}"></trkpt>')
        parts.append('  </trkseg></trk>')
    parts.append('</gpx>')
    return "\n".join(parts)


def _build_wkt(routes: List[RoutePayload]) -> str:
    lines = ["route_id|route_name|alternative|transport_mode|distance_km|duration_min|wkt"]
    for r in routes:
        line = LineString([(lng, lat) for lat, lng in r.coordinates])
        lines.append(
            f"{r.route_id}|{r.route_name}|{r.alternative}|{r.transport_mode}|"
            f"{r.distance_km}|{r.duration_min}|{line.wkt}"
        )
    return "\n".join(lines)


@app.post("/api/export")
def export_route(payload: ExportRequest):
    if not payload.routes:
        raise HTTPException(400, "Tidak ada rute untuk diekspor")

    fmt = payload.format.lower()

    if fmt == "geojson":
        content = json.dumps(_build_geojson(payload.routes), ensure_ascii=False, indent=2)
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="application/geo+json",
            headers={"Content-Disposition": "attachment; filename=route.geojson"},
        )

    if fmt == "csv":
        content = _build_vertex_csv(payload.routes)
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=route_vertices.csv"},
        )

    if fmt == "gpx":
        content = _build_gpx(payload.routes)
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="application/gpx+xml",
            headers={"Content-Disposition": "attachment; filename=route.gpx"},
        )

    if fmt == "wkt":
        content = _build_wkt(payload.routes)
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=route.wkt"},
        )

    if fmt == "shp":
        gdf = _routes_to_geodataframe(payload.routes)
        with TemporaryDirectory() as tmp:
            shp_path = Path(tmp) / "route.shp"
            gdf.to_file(shp_path, driver="ESRI Shapefile", engine="pyogrio")

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in Path(tmp).glob("route.*"):
                    zf.write(f, arcname=f.name)
            zip_buffer.seek(0)
            return StreamingResponse(
                zip_buffer,
                media_type="application/zip",
                headers={"Content-Disposition": "attachment; filename=route_shp.zip"},
            )

    raise HTTPException(400, f"Format tidak dikenal: {fmt}")


OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Approximate mapping from OSM `highway` tags to Indonesia's legal road
# hierarchy. OSM doesn't carry the official PUPR classification, so this is
# a best-effort estimate, not authoritative data.
HIGHWAY_CLASSIFICATION = {
    "motorway": "Jalan Nasional / Tol (perkiraan)",
    "motorway_link": "Jalan Nasional / Tol (perkiraan)",
    "trunk": "Jalan Nasional (perkiraan)",
    "trunk_link": "Jalan Nasional (perkiraan)",
    "primary": "Jalan Nasional/Provinsi (perkiraan)",
    "primary_link": "Jalan Nasional/Provinsi (perkiraan)",
    "secondary": "Jalan Provinsi (perkiraan)",
    "secondary_link": "Jalan Provinsi (perkiraan)",
    "tertiary": "Jalan Kabupaten/Kota (perkiraan)",
    "tertiary_link": "Jalan Kabupaten/Kota (perkiraan)",
    "unclassified": "Jalan Kabupaten/Kota (perkiraan)",
    "residential": "Jalan Desa/Lingkungan (perkiraan)",
    "living_street": "Jalan Desa/Lingkungan (perkiraan)",
    "service": "Jalan Lingkungan/Service (perkiraan)",
}

_GEOD = Geod(ellps="WGS84")


def _pick_sample_indices(n: int, max_samples: int) -> list:
    if n <= max_samples:
        return list(range(n))
    step = n / max_samples
    return sorted({int(i * step) for i in range(max_samples)} | {n - 1})


def _classify_highway(tag: Optional[str]) -> str:
    return HIGHWAY_CLASSIFICATION.get(tag, "Tidak diketahui")


@app.post("/api/analyze/road-classification")
def analyze_road_classification(payload: RoadClassRequest):
    coords = payload.coordinates
    if len(coords) < 2:
        raise HTTPException(400, "Rute terlalu pendek untuk dianalisis")

    sample_idx = _pick_sample_indices(len(coords), 60)
    samples = [coords[i] for i in sample_idx]
    coord_str = ",".join(f"{lat},{lng}" for lat, lng in samples)

    query = f"""
    [out:json][timeout:25];
    way(around:30,{coord_str})[highway];
    out tags geom;
    """

    data = None
    last_error = None
    for mirror_url in OVERPASS_MIRRORS:
        try:
            resp = requests.post(
                mirror_url,
                data={"data": query},
                headers={
                    "User-Agent": "analytic-maps/1.0 (RouteGIS road classification)",
                    "Accept": "application/json",
                },
                timeout=25,
            )
            resp.raise_for_status()
            data = resp.json()
            break
        except requests.RequestException as e:
            last_error = e
            continue

    if data is None:
        raise HTTPException(
            502,
            f"Semua server Overpass API (OpenStreetMap) sedang tidak dapat diakses/overload: {last_error}",
        )

    way_lines = []
    for way in data.get("elements", []):
        geom = way.get("geometry")
        if not geom or len(geom) < 2:
            continue
        line = LineString([(pt["lon"], pt["lat"]) for pt in geom])
        tags = way.get("tags", {})
        way_lines.append((line, tags.get("highway"), tags.get("ref"), tags.get("name")))

    tree = STRtree([wl[0] for wl in way_lines]) if way_lines else None
    threshold_deg = 0.0007  # ~75m at the equator

    def classify_point(lat, lng):
        if not tree:
            return "Tidak diketahui", None, None
        pt = Point(lng, lat)
        idx = tree.nearest(pt)
        line, highway_tag, ref_tag, name_tag = way_lines[idx]
        if pt.distance(line) > threshold_deg:
            return "Tidak diketahui", None, None
        return _classify_highway(highway_tag), ref_tag, name_tag

    per_vertex = [classify_point(lat, lng) for lat, lng in coords]

    # Aggregate into contiguous runs with real distance (meters) via geodesic calc.
    runs = []
    total_km = 0.0
    for i in range(len(coords) - 1):
        (lat1, lng1), (lat2, lng2) = coords[i], coords[i + 1]
        _, _, dist_m = _GEOD.inv(lng1, lat1, lng2, lat2)
        dist_km = dist_m / 1000
        total_km += dist_km
        label, ref, name = per_vertex[i]
        if runs and runs[-1]["road_type"] == label:
            runs[-1]["distance_km"] += dist_km
            if name and not runs[-1]["road_name"]:
                runs[-1]["road_name"] = name
        else:
            runs.append({"road_type": label, "road_name": name or "", "ref": ref or "", "distance_km": dist_km})

    summary = {}
    for r in runs:
        summary[r["road_type"]] = summary.get(r["road_type"], 0) + r["distance_km"]

    summary_list = [
        {
            "road_type": k,
            "distance_km": round(v, 3),
            "percentage": round((v / total_km * 100) if total_km else 0, 1),
        }
        for k, v in sorted(summary.items(), key=lambda kv: -kv[1])
    ]

    for r in runs:
        r["distance_km"] = round(r["distance_km"], 3)

    return {"total_km": round(total_km, 3), "segments": runs, "summary": summary_list}


MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASS = os.getenv("MYSQL_PASS", "")
MYSQL_DB = os.getenv("MYSQL_DB", "route_gis")


@contextmanager
def db_cursor():
    conn = pymysql.connect(
        host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASS,
        database=MYSQL_DB, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    finally:
        conn.close()


USULAN_LIST_FIELDS = """
    id, provinsi, kabupaten_kota, nama_ruas, nama_kegiatan, kode_ruas,
    jenis_penanganan, status_ruas, panjang_ruas_km, alokasi_usulan_pemda,
    prioritas, seleksi_sistem, verifikasi_balai, kapasitas_fiskal,
    tematik_kawasan_pemda, kondisi_baik_km, kondisi_sedang_km,
    kondisi_ringan_km, kondisi_berat_km, kondisi_jembatan,
    (kml_original_url IS NOT NULL) AS has_geometry
"""


@app.post("/api/usulan-inpres/nearby")
def usulan_inpres_nearby(payload: UsulanNearbyRequest):
    """Cari usulan Inpres Jalan/Jembatan (SITIA Bina Marga) yang berada di
    provinsi/kabupaten-kota yang dilalui rute. Pencocokan berbasis wilayah
    administratif (bukan geometri presisi), karena hanya sebagian usulan yang
    punya data KML dan rute jalan raya bisa melintasi banyak ruas sekaligus."""
    seen_regions = []
    for r in payload.regions:
        if not r.provinsi and not r.kabupaten_kota:
            continue
        key = (r.provinsi or "", r.kabupaten_kota or "")
        if key not in seen_regions:
            seen_regions.append(key)

    if not seen_regions:
        return {"regions_matched": 0, "usulan": []}

    results = []
    seen_ids = set()
    with db_cursor() as cur:
        for provinsi, kabupaten_kota in seen_regions:
            conditions = []
            params = []
            if provinsi:
                conditions.append("provinsi LIKE %s")
                params.append(f"%{provinsi}%")
            if kabupaten_kota:
                conditions.append("kabupaten_kota LIKE %s")
                params.append(f"%{kabupaten_kota}%")
            where_clause = " AND ".join(conditions)
            cur.execute(
                f"""
                SELECT {USULAN_LIST_FIELDS}
                FROM usulan_inpres
                WHERE {where_clause}
                ORDER BY (seleksi_sistem = 'LULUS') DESC, prioritas ASC, alokasi_usulan_pemda DESC
                LIMIT 15
                """,
                params,
            )
            for row in cur.fetchall():
                if row["id"] in seen_ids:
                    continue
                seen_ids.add(row["id"])
                results.append(row)

    return {"regions_matched": len(seen_regions), "usulan": results}


@app.get("/api/usulan-inpres/provinsi")
def usulan_inpres_provinsi_list():
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT provinsi, COUNT(*) AS jumlah
            FROM usulan_inpres
            WHERE provinsi IS NOT NULL
            GROUP BY provinsi
            ORDER BY provinsi ASC
            """
        )
        return cur.fetchall()


@app.get("/api/usulan-inpres")
def usulan_inpres_list(
    provinsi: Optional[str] = None,
    kabupaten_kota: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    conditions = []
    params: list = []
    if provinsi:
        conditions.append("provinsi = %s")
        params.append(provinsi)
    if kabupaten_kota:
        conditions.append("kabupaten_kota LIKE %s")
        params.append(f"%{kabupaten_kota}%")
    if q:
        like = f"%{q}%"
        conditions.append("(nama_ruas LIKE %s OR nama_kegiatan LIKE %s OR kode_ruas LIKE %s)")
        params.extend([like, like, like])
    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with db_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS total FROM usulan_inpres {where_clause}", params)
        total = cur.fetchone()["total"]
        cur.execute(
            f"""
            SELECT {USULAN_LIST_FIELDS}
            FROM usulan_inpres
            {where_clause}
            ORDER BY (seleksi_sistem = 'LULUS') DESC, prioritas ASC, alokasi_usulan_pemda DESC
            LIMIT %s OFFSET %s
            """,
            params + [limit, offset],
        )
        rows = cur.fetchall()

    return {"total": total, "limit": limit, "offset": offset, "usulan": rows}


@app.get("/api/usulan-inpres/{usulan_id}")
def usulan_inpres_detail(usulan_id: int):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM usulan_inpres WHERE id = %s", (usulan_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Usulan tidak ditemukan")
        cur.execute(
            "SELECT jenis_dokumen, url FROM usulan_dokumen WHERE usulan_id = %s",
            (usulan_id,),
        )
        row["dokumen"] = cur.fetchall()
    return row


_KML_COORD_RE = re.compile(
    r"<(?:LineString|Point)\b[^>]*>.*?<coordinates>\s*([^<]+?)\s*</coordinates>",
    re.DOTALL,
)


def _parse_kml_linestrings(kml_text: str) -> Optional[dict]:
    lines = []
    for match in _KML_COORD_RE.finditer(kml_text):
        raw = match.group(1).strip()
        pts = []
        for token in raw.split():
            parts = token.split(",")
            if len(parts) < 2:
                continue
            lng, lat = float(parts[0]), float(parts[1])
            pts.append([lng, lat])
        if len(pts) >= 2:
            lines.append(pts)

    if not lines:
        return None
    if len(lines) == 1:
        return {"type": "LineString", "coordinates": lines[0]}
    return {"type": "MultiLineString", "coordinates": lines}


MAPS_DIR = BASE_DIR / "Maps"

# Best-effort Indonesian labels for RBI (Rupa Bumi Indonesia) shapefile layer
# codes, keyed by the name with its trailing _AR_25K/_LN_25K/_PT_25K stripped.
MAP_LAYER_LABELS = {
    "ADMINISTRASIDESA": "Batas Desa",
    "ADMINISTRASI": "Batas Administrasi",
    "AGRIKEBUN": "Kebun",
    "AGRILADANG": "Ladang",
    "AGRISAWAH": "Sawah",
    "AGRITANAMCAMPUR": "Tanaman Campuran",
    "AIRTERJUN": "Air Terjun",
    "BANGUNAN": "Bangunan",
    "CAGARBUDAYA": "Cagar Budaya",
    "DANAU": "Danau",
    "DEPOMINYAK": "Depo Minyak",
    "GENLISTRIK": "Pembangkit Listrik",
    "INDUSTRI": "Kawasan Industri",
    "JALAN": "Jalan",
    "JEMBATAN": "Jembatan",
    "KABELLISTRIK": "Kabel Listrik",
    "KANTORPOS": "Kantor Pos",
    "KESEHATAN": "Fasilitas Kesehatan",
    "KONTUR": "Kontur",
    "MENARATELPON": "Menara Telekomunikasi",
    "NIAGA": "Kawasan Niaga",
    "NONAGRIALANG": "Alang-alang",
    "NONAGRIHUTANKERING": "Hutan Kering",
    "NONAGRISEMAKBELUKAR": "Semak Belukar",
    "PASIR": "Pasir",
    "PEMERINTAHAN": "Kantor Pemerintahan",
    "PEMUKIMAN": "Permukiman",
    "PENDIDIKAN": "Fasilitas Pendidikan",
    "PESISIR": "Pesisir",
    "PILARBATAS": "Pilar Batas",
    "PIPAMINYAK": "Pipa Minyak",
    "PUNGGUNGBUKIT": "Punggung Bukit",
    "SARANAIBADAH": "Sarana Ibadah",
    "SPOTHEIGHT": "Titik Tinggi",
    "STASIUNKA": "Stasiun Kereta Api",
    "SUNGAI": "Sungai",
    "TERMINALBUS": "Terminal Bus",
    "TEROWONG": "Terowongan",
    "TONGGAKKM": "Tonggak KM",
    "TOPONIMI": "Toponimi (Nama Tempat)",
}

_MAP_LAYER_SUFFIX_RE = re.compile(r"_(AR|LN|PT)_\d+K$", re.IGNORECASE)
_SAFE_NAME_RE = re.compile(r"^[^/\\]+$")
_map_layer_geojson_cache: dict = {}


def _map_layer_label(stem: str) -> str:
    code = _MAP_LAYER_SUFFIX_RE.sub("", stem).upper()
    return MAP_LAYER_LABELS.get(code, stem.replace("_", " ").title())


def _resolve_map_dir(*parts: str) -> Path:
    d = MAPS_DIR
    for part in parts:
        if not part or not _SAFE_NAME_RE.match(part) or part in (".", ".."):
            raise HTTPException(400, "Nama folder peta tidak valid")
        d = d / part
    if not d.is_dir():
        raise HTTPException(404, "Folder peta tidak ditemukan")
    return d


def _resolve_map_layer(kabupaten_dir: Path, layer: str) -> Path:
    if not layer or not _SAFE_NAME_RE.match(layer) or layer in (".", ".."):
        raise HTTPException(400, "Layer tidak valid")
    shp_path = kabupaten_dir / f"{layer}.shp"
    if not shp_path.exists():
        raise HTTPException(404, "Layer tidak ditemukan")
    return shp_path


@app.get("/api/maps/provinces")
def maps_provinces():
    if not MAPS_DIR.is_dir():
        return []
    provinces = []
    for d in sorted(MAPS_DIR.iterdir()):
        if d.is_dir():
            count = sum(1 for sub in d.iterdir() if sub.is_dir())
            provinces.append({"provinsi": d.name, "kabupaten_count": count})
    return provinces


@app.get("/api/maps/kabupaten")
def maps_kabupaten(provinsi: str):
    provinsi_dir = _resolve_map_dir(provinsi)
    kabupaten = []
    for d in sorted(provinsi_dir.iterdir()):
        if d.is_dir():
            count = sum(1 for _ in d.glob("*.shp"))
            kabupaten.append({"kabupaten": d.name, "layer_count": count})
    return kabupaten


@app.get("/api/maps/layers")
def maps_layers(provinsi: str, kabupaten: str):
    kabupaten_dir = _resolve_map_dir(provinsi, kabupaten)
    layers = []
    for shp in sorted(kabupaten_dir.glob("*.shp")):
        layers.append({
            "layer": shp.stem,
            "label": _map_layer_label(shp.stem),
            "size_mb": round(shp.stat().st_size / 1_048_576, 2),
        })
    return layers


@app.get("/api/maps/layer")
def maps_layer(provinsi: str, kabupaten: str, layer: str):
    key = (provinsi, kabupaten, layer)
    if key in _map_layer_geojson_cache:
        return _map_layer_geojson_cache[key]

    kabupaten_dir = _resolve_map_dir(provinsi, kabupaten)
    shp_path = _resolve_map_layer(kabupaten_dir, layer)

    gdf = gpd.read_file(shp_path, engine="pyogrio")
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]

    # Heavy layers (e.g. KONTUR, tens of MB of contour lines) are simplified
    # so the browser doesn't choke on rendering; tolerance is in degrees
    # (~0.00015 deg ~ 15-17m at this latitude), fine for on-screen display.
    if len(gdf) > 3000:
        gdf["geometry"] = gdf.geometry.simplify(0.00015, preserve_topology=True)

    geojson = json.loads(gdf.to_json())
    geojson["label"] = _map_layer_label(layer)
    _map_layer_geojson_cache[key] = geojson
    return geojson


def _fetch_usulan_geometry(usulan_id: int) -> dict:
    with db_cursor() as cur:
        cur.execute(
            "SELECT kml_original_url, geom_geojson FROM usulan_inpres WHERE id = %s",
            (usulan_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Usulan tidak ditemukan")

        if row["geom_geojson"]:
            return json.loads(row["geom_geojson"])

        if not row["kml_original_url"]:
            raise HTTPException(404, "Usulan ini tidak memiliki data geometri (KML)")

        try:
            resp = requests.get(row["kml_original_url"], timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise HTTPException(502, f"Gagal mengambil KML dari SITIA Bina Marga: {e}")

        geojson = _parse_kml_linestrings(resp.text)
        if not geojson:
            raise HTTPException(404, "KML tidak berisi geometri jalur yang dapat dibaca")

        cur.execute(
            "UPDATE usulan_inpres SET geom_geojson = %s, geom_fetched_at = NOW() WHERE id = %s",
            (json.dumps(geojson), usulan_id),
        )

    return geojson


@app.get("/api/usulan-inpres/{usulan_id}/geometry")
def usulan_inpres_geometry(usulan_id: int):
    return _fetch_usulan_geometry(usulan_id)


@app.get("/api/usulan-inpres/{usulan_id}/export/shp")
def usulan_inpres_export_shp(usulan_id: int):
    geojson = _fetch_usulan_geometry(usulan_id)

    with db_cursor() as cur:
        cur.execute(
            "SELECT nama_kegiatan, nama_ruas, kode_ruas, kabupaten_kota, provinsi, "
            "jenis_penanganan, panjang_ruas_km FROM usulan_inpres WHERE id = %s",
            (usulan_id,),
        )
        u = cur.fetchone()
    if not u:
        raise HTTPException(404, "Usulan tidak ditemukan")

    if geojson["type"] == "MultiLineString":
        # MultiLineString(list_of_linestrings) segfaults-into-TypeError on this
        # shapely/numpy combo (shapely.creation.multilinestrings chokes on the
        # object array) — round-tripping through WKT avoids that code path.
        lines = [LineString(coords) for coords in geojson["coordinates"]]
        wkt = "MULTILINESTRING (" + ", ".join(
            "(" + ", ".join(f"{x} {y}" for x, y in ls.coords) + ")" for ls in lines
        ) + ")"
        geometry = shapely.wkt.loads(wkt)
    else:
        geometry = LineString(geojson["coordinates"])

    gdf = gpd.GeoDataFrame(
        [{
            "nama": (u["nama_kegiatan"] or u["nama_ruas"] or "")[:80],
            "kode_ruas": u["kode_ruas"],
            "kab_kota": u["kabupaten_kota"],
            "provinsi": u["provinsi"],
            "penanganan": u["jenis_penanganan"],
            "panjang_km": u["panjang_ruas_km"],
            "geometry": geometry,
        }],
        geometry="geometry",
        crs="EPSG:4326",
    )

    with TemporaryDirectory() as tmp:
        shp_path = Path(tmp) / "usulan_inpres.shp"
        gdf.to_file(shp_path, driver="ESRI Shapefile", engine="pyogrio")

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in Path(tmp).glob("usulan_inpres.*"):
                zf.write(f, arcname=f.name)
        zip_buffer.seek(0)
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename=usulan_inpres_{usulan_id}_shp.zip"},
        )


# Beberapa provider LLM opsional untuk chat assistant — semua dicek dari .env
# dan dicoba berurutan (lihat _call_chat) sampai salah satu berhasil, supaya
# tidak bergantung pada satu provider yang bisa kehabisan kuota harian.
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

GROK_MODEL = os.getenv("GROK_MODEL", "grok-3-mini")
GROK_API_URL = "https://api.x.ai/v1/chat/completions"

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-4-8")

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")

CHAT_SYSTEM_PROMPT = """Anda adalah asisten analisis rute di aplikasi RouteGIS, sebuah alat perencanaan rute \
dan analisis GIS untuk jalan di Indonesia. Jawab dalam Bahasa Indonesia, singkat dan langsung ke inti.
Anda diberi data ringkas tentang rute yang sedang dilihat pengguna (jarak, durasi, wilayah administratif yang \
dilalui, perkiraan klasifikasi jalan dari OpenStreetMap, dan usulan Inpres Jalan/Jembatan di sekitar rute). \
Gunakan data ini untuk menjawab. Bila pengguna bertanya tentang usulan Inpres di luar rute yang sedang dilihat \
(wilayah lain, pencarian umum, atau detail satu usulan tertentu), gunakan fungsi cari_usulan_inpres atau \
detail_usulan_inpres untuk mengambil data terbaru dari database — jangan mengarang data. Bila pengguna bertanya \
soal geometri KML riil suatu usulan (panjang aktual, jumlah segmen, apakah cocok dengan data atribut \
panjang_ruas_km), gunakan fungsi analisa_geometri_kml_usulan. \
Klasifikasi jalan OSM adalah perkiraan, bukan data resmi PUPR."""

CHAT_SEARCH_AVAILABLE_NOTE = (
    " Anda memiliki akses pencarian web untuk pertanyaan di luar data aplikasi (jumlah penduduk, kondisi "
    "ekonomi, konteks wilayah lain di sekitar lokasi jalan, dsb.) — gunakan pencarian web untuk itu, dan "
    "sebutkan bahwa jawabannya berasal dari hasil pencarian internet, bukan data resmi aplikasi ini."
)
CHAT_SEARCH_UNAVAILABLE_NOTE = (
    " Anda TIDAK punya akses pencarian internet saat ini — bila pengguna bertanya hal di luar data aplikasi "
    "(jumlah penduduk, kondisi ekonomi, konteks wilayah lain, dsb.), katakan terus terang bahwa data itu "
    "tidak tersedia di aplikasi ini, jangan mengarang jawaban."
)

# Fungsi yang boleh dipanggil model (tool calling gaya OpenAI, dipakai Groq) —
# dibatasi ke query baca-saja lewat helper yang sudah ada (parameterized query,
# tidak ada SQL bebas dari model) supaya tidak ada risiko injeksi atau akses
# tulis ke database.
CHAT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "cari_usulan_inpres",
            "description": (
                "Mencari usulan Inpres Jalan/Jembatan di database berdasarkan provinsi, "
                "kabupaten/kota, dan/atau kata kunci nama ruas/kegiatan/kode ruas. Gunakan "
                "ini untuk pertanyaan di luar rute yang sedang dilihat pengguna."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "provinsi": {"type": "string", "description": "Nama provinsi persis, contoh: JAWA BARAT"},
                    "kabupaten_kota": {"type": "string", "description": "Nama kabupaten/kota (pencocokan sebagian)"},
                    "q": {"type": "string", "description": "Kata kunci nama ruas, nama kegiatan, atau kode ruas"},
                    "limit": {"type": "integer", "description": "Jumlah maksimum hasil, default 10, maksimum 20"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detail_usulan_inpres",
            "description": "Mengambil detail lengkap satu usulan Inpres Jalan/Jembatan berdasarkan id-nya.",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "integer", "description": "ID usulan"}},
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analisa_geometri_kml_usulan",
            "description": (
                "Menghitung statistik geometri KML riil suatu usulan: panjang aktual hasil "
                "ukur geodesik (bisa berbeda dari field atribut panjang_ruas_km yang diinput "
                "manual), jumlah segmen garis, bounding box, serta titik awal/akhir jalur."
            ),
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "integer", "description": "ID usulan"}},
                "required": ["id"],
            },
        },
    },
]

_USULAN_TOOL_FIELDS = (
    "id", "nama_kegiatan", "nama_ruas", "kabupaten_kota", "provinsi", "jenis_penanganan",
    "panjang_ruas_km", "prioritas", "seleksi_sistem", "alokasi_usulan_pemda", "has_geometry",
)


def _tool_cari_usulan_inpres(provinsi=None, kabupaten_kota=None, q=None, limit=10) -> dict:
    limit = max(1, min(int(limit or 10), 20))
    result = usulan_inpres_list(provinsi=provinsi, kabupaten_kota=kabupaten_kota, q=q, limit=limit, offset=0)
    return {
        "total_ditemukan": result["total"],
        "usulan": [{k: u.get(k) for k in _USULAN_TOOL_FIELDS} for u in result["usulan"]],
    }


def _tool_detail_usulan_inpres(id=None) -> dict:
    if id is None:
        return {"error": "id usulan diperlukan"}
    try:
        return usulan_inpres_detail(int(id))
    except HTTPException as e:
        return {"error": e.detail}


def _tool_analisa_geometri_kml_usulan(id=None) -> dict:
    if id is None:
        return {"error": "id usulan diperlukan"}
    try:
        geojson = _fetch_usulan_geometry(int(id))
    except HTTPException as e:
        return {"error": e.detail}

    segments = geojson["coordinates"] if geojson["type"] == "MultiLineString" else [geojson["coordinates"]]

    total_m = 0.0
    all_lngs, all_lats = [], []
    for seg in segments:
        lngs = [pt[0] for pt in seg]
        lats = [pt[1] for pt in seg]
        total_m += _GEOD.line_length(lngs, lats)
        all_lngs.extend(lngs)
        all_lats.extend(lats)

    start, end = segments[0][0], segments[-1][-1]
    return {
        "jumlah_segmen": len(segments),
        "panjang_kml_km": round(total_m / 1000, 3),
        "bounding_box": {
            "min_lat": min(all_lats), "max_lat": max(all_lats),
            "min_lng": min(all_lngs), "max_lng": max(all_lngs),
        },
        "titik_awal": {"lat": start[1], "lng": start[0]},
        "titik_akhir": {"lat": end[1], "lng": end[0]},
    }


CHAT_TOOL_DISPATCH = {
    "cari_usulan_inpres": _tool_cari_usulan_inpres,
    "detail_usulan_inpres": _tool_detail_usulan_inpres,
    "analisa_geometri_kml_usulan": _tool_analisa_geometri_kml_usulan,
}


def _chat_system_text(context: Optional[dict], has_search: bool = False) -> str:
    system_text = CHAT_SYSTEM_PROMPT + (CHAT_SEARCH_AVAILABLE_NOTE if has_search else CHAT_SEARCH_UNAVAILABLE_NOTE)
    if context:
        system_text += "\n\nData rute saat ini (JSON):\n" + json.dumps(context, ensure_ascii=False)
    return system_text


def _run_tool_call(name: str, args: dict) -> dict:
    fn = CHAT_TOOL_DISPATCH.get(name)
    return fn(**args) if fn else {"error": "fungsi tidak dikenal"}


def _call_openai_compatible(provider: str, api_url: str, api_key: str, model: str, messages: List[ChatMessage], context: Optional[dict]) -> str:
    """Chat Completions-compatible provider tanpa pencarian web (Groq, Grok/xAI)."""
    chat_messages = [{"role": "system", "content": _chat_system_text(context)}]
    chat_messages += [{"role": m.role, "content": m.text} for m in messages]

    for _ in range(4):  # batas jumlah putaran pemanggilan fungsi, cegah loop tak berujung
        try:
            resp = requests.post(
                api_url,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                json={"model": model, "messages": chat_messages, "tools": CHAT_TOOLS, "tool_choice": "auto"},
                timeout=30,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            detail = e.response.text if getattr(e, "response", None) is not None else str(e)
            raise RuntimeError(f"{provider}: {detail}")

        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"{provider}: tidak mengembalikan jawaban")
        message = choices[0]["message"]

        tool_calls = message.get("tool_calls")
        if not tool_calls:
            text = message.get("content") or ""
            if not text:
                raise RuntimeError(f"{provider}: jawaban kosong")
            return text

        chat_messages.append(message)
        for tc in tool_calls:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result = _run_tool_call(tc["function"]["name"], args)
            chat_messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(jsonable_encoder(result), ensure_ascii=False),
            })

    raise RuntimeError(f"{provider}: terlalu banyak pemanggilan fungsi")


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
# Format tool Responses API berbeda dari Chat Completions: rata (flat), bukan
# dibungkus {"function": {...}}. web_search_preview adalah tool bawaan OpenAI
# yang berjalan di sisi mereka — tidak perlu didaftarkan di CHAT_TOOL_DISPATCH.
OPENAI_RESPONSES_TOOLS = [{"type": "web_search_preview"}] + [
    {"type": "function", "name": t["function"]["name"], "description": t["function"]["description"], "parameters": t["function"]["parameters"]}
    for t in CHAT_TOOLS
]


def _call_openai_responses(api_key: str, model: str, messages: List[ChatMessage], context: Optional[dict]) -> str:
    """OpenAI Responses API — satu-satunya provider yang benar-benar mendukung
    pencarian internet (web_search_preview) digabung dengan tool database/KML kita."""
    input_items = [{"role": m.role, "content": m.text} for m in messages]

    for _ in range(4):  # batas jumlah putaran pemanggilan fungsi, cegah loop tak berujung
        try:
            resp = requests.post(
                OPENAI_RESPONSES_URL,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "instructions": _chat_system_text(context, has_search=True),
                    "input": input_items,
                    "tools": OPENAI_RESPONSES_TOOLS,
                },
                timeout=30,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            detail = e.response.text if getattr(e, "response", None) is not None else str(e)
            raise RuntimeError(f"OpenAI: {detail}")

        data = resp.json()
        output = data.get("output") or []

        function_calls = [item for item in output if item.get("type") == "function_call"]
        if not function_calls:
            text = "".join(
                c.get("text", "")
                for item in output if item.get("type") == "message"
                for c in item.get("content", []) if c.get("type") == "output_text"
            )
            if not text:
                raise RuntimeError("OpenAI: jawaban kosong")
            return text

        # Balas semua output turn ini (termasuk pemanggilan web_search_preview,
        # bila ada) lalu tambahkan function_call_output untuk tiap function_call.
        input_items.extend(output)
        for fc in function_calls:
            try:
                args = json.loads(fc.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result = _run_tool_call(fc["name"], args)
            input_items.append({
                "type": "function_call_output",
                "call_id": fc["call_id"],
                "output": json.dumps(jsonable_encoder(result), ensure_ascii=False),
            })

    raise RuntimeError("OpenAI: terlalu banyak pemanggilan fungsi")


def _openai_tools_to_gemini(tools: list) -> list:
    def upcase_types(schema):
        if not isinstance(schema, dict):
            return schema
        out = {}
        for k, v in schema.items():
            if k == "type" and isinstance(v, str):
                out[k] = v.upper()
            elif k == "properties":
                out[k] = {pk: upcase_types(pv) for pk, pv in v.items()}
            else:
                out[k] = v
        return out

    return [{
        "function_declarations": [
            {"name": t["function"]["name"], "description": t["function"]["description"], "parameters": upcase_types(t["function"]["parameters"])}
            for t in tools
        ],
    }]


GEMINI_CHAT_TOOLS = _openai_tools_to_gemini(CHAT_TOOLS)


def _call_gemini(api_key: str, model: str, messages: List[ChatMessage], context: Optional[dict]) -> str:
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    contents = [{"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.text}]} for m in messages]

    for _ in range(4):  # batas jumlah putaran pemanggilan fungsi, cegah loop tak berujung
        try:
            resp = requests.post(
                api_url,
                headers={"Content-Type": "application/json", "X-goog-api-key": api_key},
                json={
                    "system_instruction": {"parts": [{"text": _chat_system_text(context)}]},
                    "tools": GEMINI_CHAT_TOOLS,
                    "contents": contents,
                },
                timeout=30,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            detail = e.response.text if getattr(e, "response", None) is not None else str(e)
            raise RuntimeError(f"Gemini: {detail}")

        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError("Gemini: tidak mengembalikan jawaban")
        parts = candidates[0].get("content", {}).get("parts", [])

        function_calls = [p["functionCall"] for p in parts if "functionCall" in p]
        if not function_calls:
            text = "".join(p.get("text", "") for p in parts)
            if not text:
                raise RuntimeError("Gemini: jawaban kosong")
            return text

        # Model bisa memanggil beberapa fungsi sekaligus dalam satu giliran — semua
        # harus dibalas dalam satu content "function", atau giliran berikutnya
        # kembali kosong karena Gemini masih menunggu jawaban yang belum terkirim.
        response_parts = [
            {"functionResponse": {"name": fc["name"], "response": jsonable_encoder(_run_tool_call(fc["name"], fc.get("args") or {}))}}
            for fc in function_calls
        ]
        contents.append({"role": "model", "parts": parts})
        contents.append({"role": "function", "parts": response_parts})

    raise RuntimeError("Gemini: terlalu banyak pemanggilan fungsi")


CLAUDE_TOOLS = [
    {"name": t["function"]["name"], "description": t["function"]["description"], "input_schema": t["function"]["parameters"]}
    for t in CHAT_TOOLS
]


def _call_claude(api_key: str, model: str, messages: List[ChatMessage], context: Optional[dict]) -> str:
    client = anthropic.Anthropic(api_key=api_key)
    claude_messages = [{"role": m.role, "content": m.text} for m in messages]

    for _ in range(4):  # batas jumlah putaran pemanggilan fungsi, cegah loop tak berujung
        try:
            response = client.messages.create(
                model=model,
                max_tokens=4096,
                system=_chat_system_text(context),
                tools=CLAUDE_TOOLS,
                messages=claude_messages,
            )
        except anthropic.APIError as e:
            raise RuntimeError(f"Claude: {e.message}")

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        if not tool_use_blocks:
            text = "".join(b.text for b in response.content if b.type == "text")
            if not text:
                raise RuntimeError("Claude: jawaban kosong")
            return text

        claude_messages.append({"role": "assistant", "content": response.content})
        tool_results = [
            {
                "type": "tool_result",
                "tool_use_id": tb.id,
                "content": json.dumps(jsonable_encoder(_run_tool_call(tb.name, tb.input or {})), ensure_ascii=False),
            }
            for tb in tool_use_blocks
        ]
        claude_messages.append({"role": "user", "content": tool_results})

    raise RuntimeError("Claude: terlalu banyak pemanggilan fungsi")


def _chat_providers() -> list:
    """Provider yang API key-nya diisi di .env, urut prioritas (yang free-tier-nya
    paling longgar duluan) — dicoba satu per satu di _call_chat sampai ada yang
    berhasil, supaya chat tidak macet total hanya karena satu provider kehabisan
    kuota harian."""
    providers = []
    if os.getenv("GROQ_API_KEY"):
        providers.append(("Groq", lambda msgs, ctx: _call_openai_compatible("Groq", GROQ_API_URL, os.getenv("GROQ_API_KEY"), GROQ_MODEL, msgs, ctx)))
    if os.getenv("GROK_API_KEY"):
        providers.append(("Grok", lambda msgs, ctx: _call_openai_compatible("Grok", GROK_API_URL, os.getenv("GROK_API_KEY"), GROK_MODEL, msgs, ctx)))
    if os.getenv("OPEN_AI_API_KEY"):
        providers.append(("OpenAI", lambda msgs, ctx: _call_openai_responses(os.getenv("OPEN_AI_API_KEY"), OPENAI_MODEL, msgs, ctx)))
    if os.getenv("CLOUDE_API_KEY"):
        providers.append(("Claude", lambda msgs, ctx: _call_claude(os.getenv("CLOUDE_API_KEY"), CLAUDE_MODEL, msgs, ctx)))
    if os.getenv("GEMINI_API_KEY"):
        providers.append(("Gemini", lambda msgs, ctx: _call_gemini(os.getenv("GEMINI_API_KEY"), GEMINI_MODEL, msgs, ctx)))
    return providers


def _call_chat(messages: List[ChatMessage], context: Optional[dict]) -> str:
    providers = _chat_providers()
    if not providers:
        raise HTTPException(
            500,
            "Tidak ada API key LLM yang diset di .env (GROQ_API_KEY / GROK_API_KEY / OPEN_AI_API_KEY / CLOUDE_API_KEY / GEMINI_API_KEY)",
        )

    errors = []
    for name, call in providers:
        try:
            return call(messages, context)
        except Exception as e:
            errors.append(f"{name}: {e}")

    raise HTTPException(502, "Semua provider LLM gagal — " + " | ".join(errors))


@app.post("/api/chat")
def chat(payload: ChatRequest):
    if not payload.messages:
        raise HTTPException(400, "Tidak ada pesan")
    reply = _call_chat(payload.messages, payload.context)
    return {"reply": reply}


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", 8000)),
        reload=True,
    )
