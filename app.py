import io
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Optional

import anthropic
import openpyxl
import pymysql
import requests
from dotenv import load_dotenv
import os

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import geopandas as gpd
from pyproj import Geod
import shapely.wkt
from shapely.geometry import LineString, Point, mapping
from shapely.strtree import STRtree

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# Logika import/export xlsx usulan Inpres (COLUMN_MAP, upsert, export) tinggal
# satu di scripts/import_usulan_inpres.py — dipakai bersama oleh CLI dan
# endpoint /api/usulan-inpres/import|export di bawah.
sys.path.insert(0, str(BASE_DIR / "scripts"))
import import_usulan_inpres as usulan_xlsx  # noqa: E402
import import_penduduk_kecamatan as penduduk_xlsx  # noqa: E402
import import_bappenas_lokus_a as bappenas_lokus_xlsx  # noqa: E402

from db import db_cursor  # noqa: E402
import chat_providers  # noqa: E402
# _llm_plain/_plain_* (penilaian Bappenas AI) masih tinggal di app.py dan
# butuh konstanta model/URL yang ikut pindah ke chat_providers saat refactor
# Fase 2 — tanpa import ini semua fitur AI Bappenas NameError.
from chat_providers import (  # noqa: E402
    GROQ_MODEL, GROQ_API_URL, GROK_MODEL, GROK_API_URL,
    OPENAI_MODEL, CLAUDE_MODEL, GEMINI_MODEL,
)

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


@app.post("/api/usulan-inpres/import")
def usulan_inpres_import(file: UploadFile = File(...)):
    """Upsert xlsx usulan (format SITIA) ke database: ID yang sudah ada
    di-update, yang belum ada di-insert. Kolom geometri hasil fetch KML
    tidak disentuh."""
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(400, "File harus berformat .xlsx")
    conn = usulan_xlsx.connect()
    try:
        usulan_xlsx.run_schema(conn)
        try:
            stats = usulan_xlsx.upsert_xlsx(file.file, conn)
        except ValueError as exc:  # kolom wajib tidak ada
            raise HTTPException(400, str(exc))
    finally:
        conn.close()
    return {"filename": file.filename, **stats}


@app.get("/api/usulan-inpres/export/xlsx")
def usulan_inpres_export():
    """Unduh seluruh isi usulan_inpres sebagai xlsx dengan tata letak kolom
    yang sama dengan file sumber SITIA (bisa di-import balik)."""
    buf = io.BytesIO()
    usulan_xlsx.export_xlsx(buf)
    buf.seek(0)
    fname = f"usulan_inpres_export_{datetime.now():%Y%m%d%H%M%S}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


@app.post("/api/penduduk-kecamatan/import")
def penduduk_kecamatan_import(file: UploadFile = File(...)):
    """Upsert xlsx master ID wilayah + jumlah penduduk per kecamatan (format
    "3_ID dan Jumlah Penduduk Indonesia") ke tabel penduduk_kecamatan."""
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(400, "File harus berformat .xlsx")
    conn = penduduk_xlsx.connect()
    try:
        penduduk_xlsx.run_schema(conn)
        try:
            stats = penduduk_xlsx.upsert_xlsx(file.file, conn)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    finally:
        conn.close()
    return {"filename": file.filename, **stats}


# --- Penampil data tabel database (topbar "Data") ---
# Whitelist nama tabel -> label tampilan; menghindari akses tabel arbitrer.
DATA_TABLES = {
    "usulan_inpres": "Usulan Inpres (SITIA)",
    "usulan_dokumen": "Dokumen Usulan",
    "penduduk_kecamatan": "Penduduk per Kecamatan (Nasional 2025)",
    "bps_kecamatan_demografi": "Demografi Kecamatan (Dalam Angka)",
    "bps_kabupaten_padi": "Padi per Kab/Kota (Dalam Angka)",
    "bps_kabupaten_kendaraan": "Kendaraan per Kab/Kota (Dalam Angka)",
    "bps_kecamatan_potensi_tematik": "Potensi Tematik Kecamatan (Dalam Angka)",
    "si_panjang_jalan_provinsi": "Panjang Jalan per Provinsi (SI 2026)",
    "si_kendaraan_provinsi": "Kendaraan per Provinsi (SI 2026)",
    "si_lahan_sawah_provinsi": "Lahan Baku Sawah per Provinsi (SI 2026)",
    "ijd_scoring_rules": "Kaidah Skoring IJD",
    "dpp_ijd_2025": "DPP IJD TA 2025 (BA + DPP)",
    "wilayah_mapping": "Pemetaan Wilayah SITIA ↔ Kode BPS",
    "kecamatan_data_turunan": "Data Turunan Kecamatan (C.A1/C.A3)",
    "penilaian_bappenas_ai": "Draf Penilaian Bappenas (AI)",
    "bappenas_lokus_a": "Lokus Aspek A Bappenas (Prioritas & Nilai Strategis)",
}
# kolom yang tidak ditampilkan (payload besar)
DATA_TABLE_SKIP_COLS = {"geom_geojson"}

# Tabel yang bisa difilter provinsi/kabupaten di viewer "Data" -> (ekspresi SQL
# kode provinsi, ekspresi SQL kode kabupaten), keduanya disetarakan ke kode BPS
# numerik (kode_provinsi 2 digit, kode_kabupaten 4 digit) supaya nilai filter dari
# dropdown (diisi dari penduduk_kecamatan, master nasional) selalu cocok — walau
# sebagian tabel BPS Dalam Angka menyimpan kode_kab sbg CHAR(4), bukan kolom
# kode_provinsi terpisah. usulan_inpres/dpp_ijd_2025/dll TIDAK di sini karena
# wilayahnya teks bebas SITIA (sudah ada filter provinsi sendiri di panel
# "Jelajahi Usulan Inpres"), bukan kode BPS langsung.
DATA_TABLE_GEO = {
    "penduduk_kecamatan": ("kode_provinsi", "kode_kabupaten"),
    "kecamatan_data_turunan": ("(kode_kabupaten DIV 100)", "kode_kabupaten"),
    "wilayah_mapping": ("kode_provinsi", "kode_kabupaten"),
    "bps_kecamatan_demografi": ("CAST(LEFT(kode_kab, 2) AS UNSIGNED)", "CAST(kode_kab AS UNSIGNED)"),
    "bps_kabupaten_padi": ("CAST(LEFT(kode_kab, 2) AS UNSIGNED)", "CAST(kode_kab AS UNSIGNED)"),
    "bps_kabupaten_kendaraan": ("CAST(LEFT(kode_kab, 2) AS UNSIGNED)", "CAST(kode_kab AS UNSIGNED)"),
    "bps_kecamatan_potensi_tematik": ("CAST(LEFT(kode_kab, 2) AS UNSIGNED)", "CAST(kode_kab AS UNSIGNED)"),
    "bappenas_lokus_a": ("kode_provinsi", "kode_kabupaten"),
}


@app.get("/api/data/tables")
def data_tables():
    out = []
    with db_cursor() as cur:
        for name, label in DATA_TABLES.items():
            try:
                cur.execute(f"SELECT COUNT(*) AS n FROM `{name}`")
                total = cur.fetchone()["n"]
            except pymysql.err.ProgrammingError:
                continue  # tabel belum dibuat — sembunyikan dari daftar
            out.append({"name": name, "label": label, "total": total, "geo": name in DATA_TABLE_GEO})
    return out


@app.get("/api/data/geo/provinces")
def data_geo_provinces():
    """Master provinsi (dari penduduk_kecamatan, cakupan nasional) — dipakai
    dropdown filter provinsi di viewer "Data" untuk semua tabel di DATA_TABLE_GEO."""
    with db_cursor() as cur:
        cur.execute("SELECT DISTINCT kode_provinsi, provinsi FROM penduduk_kecamatan ORDER BY provinsi")
        return cur.fetchall()


@app.get("/api/data/geo/kabupaten")
def data_geo_kabupaten(provinsi: int):
    with db_cursor() as cur:
        cur.execute(
            "SELECT DISTINCT kode_kabupaten, kabupaten_kota FROM penduduk_kecamatan "
            "WHERE kode_provinsi = %s ORDER BY kabupaten_kota",
            (provinsi,),
        )
        return cur.fetchall()


# --- Import/export lokus Aspek A Bappenas (docs/spec/Draf Penilaian Bappenas.md)
# -- upload xlsx per kriteria dari browser, dipetakan ke fungsi ekstraksi yang
# sudah ada di scripts/import_bappenas_lokus_a.py (KRITERIA_SOURCES) supaya
# CLI dan endpoint ini pakai logika parsing yang SAMA persis, bukan duplikat.
# Export cukup lewat viewer "Data" generik (bappenas_lokus_a sudah masuk
# DATA_TABLES di atas) — tidak perlu endpoint export terpisah. ---

@app.get("/api/bappenas-lokus-a/kriteria")
def bappenas_lokus_a_kriteria():
    """Daftar 8 kriteria yang bisa di-upload ulang + jumlah baris saat ini
    (utk dropdown UI upload)."""
    with db_cursor() as cur:
        cur.execute(
            "SELECT kriteria, COUNT(*) n FROM bappenas_lokus_a WHERE kriteria IN %s GROUP BY kriteria",
            (tuple(bappenas_lokus_xlsx.KRITERIA_SOURCES.keys()),),
        )
        counts = {r["kriteria"]: r["n"] for r in cur.fetchall()}
    return [
        {"kriteria": k, "label": spec["label"], "default_file": spec["file"], "total": counts.get(k, 0)}
        for k, spec in bappenas_lokus_xlsx.KRITERIA_SOURCES.items()
    ]


@app.post("/api/bappenas-lokus-a/import")
def bappenas_lokus_a_import(kriteria: str, file: UploadFile = File(...)):
    """Upload ulang xlsx sumber utk satu kriteria (update/tambah data) --
    baris lama utk kriteria itu diganti (DELETE + INSERT), kriteria lain
    tidak tersentuh."""
    if kriteria not in bappenas_lokus_xlsx.KRITERIA_SOURCES:
        raise HTTPException(400, f"Kriteria tidak dikenal: {kriteria}")
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(400, "File harus berformat .xlsx")

    conn = bappenas_lokus_xlsx.connect()
    try:
        bappenas_lokus_xlsx.run_schema(conn)
        ctx = bappenas_lokus_xlsx.build_master_index(conn)
        try:
            wb = openpyxl.load_workbook(file.file, read_only=True, data_only=True)
            rows = bappenas_lokus_xlsx.import_kriteria(kriteria, wb, ctx)
        except KeyError as exc:
            raise HTTPException(400, f"Sheet tidak ditemukan di file ini: {exc}")
        if not rows:
            raise HTTPException(400, "Tidak ada baris yang bisa diekstrak dari file ini — cek formatnya sesuai sheet aslinya.")
        n_match = sum(1 for r in rows if r[6] is not None)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM bappenas_lokus_a WHERE kriteria = %s", (kriteria,))
            cur.executemany(
                "INSERT INTO bappenas_lokus_a (kriteria, level, provinsi_asli, kabupaten_asli, "
                "kecamatan_asli, kode_provinsi, kode_kabupaten, kode_kecamatan, keterangan, "
                "sumber_file, sumber_sheet) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                rows,
            )
        conn.commit()
    finally:
        conn.close()
    _ijd_bulk_cache.clear()  # lokus Aspek A baru -> skor bulk kadaluarsa
    return {"kriteria": kriteria, "filename": file.filename, "total": len(rows), "match_kabupaten": n_match}


def _data_table_geo_where(table: str, provinsi: int, kabupaten: int, kriteria: str = ""):
    """WHERE + params dari filter provinsi/kabupaten, kalau tabelnya kebagian
    kode geo (DATA_TABLE_GEO) dan filter diisi. Kabupaten menang kalau
    keduanya diisi (provinsinya sudah tersirat). "kriteria" -- khusus
    bappenas_lokus_a (dialog "Lokus Bappenas" navbar) -- filter tambahan
    ANDed di atas geo, supaya dropdown kriteria bisa memfilter preview
    grid, bukan cuma menentukan target upload xlsx."""
    clauses, params = [], []
    geo = DATA_TABLE_GEO.get(table)
    if geo:
        prov_expr, kab_expr = geo
        if kabupaten:
            clauses.append(f"{kab_expr} = %s")
            params.append(kabupaten)
        elif provinsi:
            clauses.append(f"{prov_expr} = %s")
            params.append(provinsi)
    if kriteria and table == "bappenas_lokus_a":
        clauses.append("kriteria = %s")
        params.append(kriteria)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


@app.get("/api/data/{table}/export/xlsx")
def data_table_export(table: str, provinsi: int = 0, kabupaten: int = 0, kriteria: str = ""):
    if table not in DATA_TABLES:
        raise HTTPException(404, "Tabel tidak dikenal")
    where, params = _data_table_geo_where(table, provinsi, kabupaten, kriteria)
    with db_cursor() as cur:
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        columns = [c["Field"] for c in cur.fetchall()
                   if c["Field"] not in DATA_TABLE_SKIP_COLS]
        col_sql = ", ".join(f"`{c}`" for c in columns)
        cur.execute(f"SELECT {col_sql} FROM `{table}` {where} ORDER BY 1", params)
        rows = cur.fetchall()

    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet(table[:31])
    ws.append(columns)
    for r in rows:
        ws.append([r[c] for c in columns])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"{table}_export_{datetime.now():%Y%m%d%H%M%S}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


@app.get("/api/data/{table}")
def data_table_rows(table: str, limit: int = 50, offset: int = 0, provinsi: int = 0, kabupaten: int = 0, kriteria: str = ""):
    if table not in DATA_TABLES:
        raise HTTPException(404, "Tabel tidak dikenal")
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    where, params = _data_table_geo_where(table, provinsi, kabupaten, kriteria)
    with db_cursor() as cur:
        cur.execute(f"SHOW COLUMNS FROM `{table}`")
        columns = [c["Field"] for c in cur.fetchall()
                   if c["Field"] not in DATA_TABLE_SKIP_COLS]
        col_sql = ", ".join(f"`{c}`" for c in columns)
        cur.execute(f"SELECT COUNT(*) AS n FROM `{table}` {where}", params)
        total = cur.fetchone()["n"]
        cur.execute(
            f"SELECT {col_sql} FROM `{table}` {where} ORDER BY 1 LIMIT %s OFFSET %s",
            params + [limit, offset],
        )
        rows = []
        for r in cur.fetchall():
            row = []
            for c in columns:
                v = r[c]
                if isinstance(v, str) and len(v) > 200:
                    v = v[:200] + "…"
                row.append(v)
            rows.append(row)
    return jsonable_encoder({
        "table": table, "label": DATA_TABLES[table], "columns": columns,
        "rows": rows, "total": total, "limit": limit, "offset": offset,
    })


@app.get("/api/penduduk-kecamatan/export/xlsx")
def penduduk_kecamatan_export():
    """Unduh master penduduk per kecamatan sebagai xlsx (bisa di-import balik)."""
    buf = io.BytesIO()
    penduduk_xlsx.export_xlsx(buf)
    buf.seek(0)
    fname = f"penduduk_kecamatan_export_{datetime.now():%Y%m%d%H%M%S}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


# --- Skoring "Prioritisasi Teknokratik" IJD (Inpres Jalan Daerah No. 11/2025) ---
# Kaidah nilai/bobot per parameter (Tabel 1, 3, 6, A1/A2) disimpan di tabel
# ijd_scoring_rules (lihat scripts/schema_ijd_scoring.sql) supaya bisa
# disesuaikan tanpa redeploy saat kebijakan IJD berubah tiap tahun anggaran.
# Hanya parameter A (tematik, sub A1/A2 saja), B (kemantapan), D (koridor,
# pendekatan), dan F (kelengkapan RC; hanya kaidah 2025 — dihapus dari
# penilaian 2026) yang punya sumber data di tabel usulan_inpres — C
# (Kemanfaatan) dan E (Penuntasan IJD sebelumnya) dilaporkan "belum tersedia"
# karena sumber datanya (BPS/LHR untuk C, pencocokan DPP IJD 2025 untuk E)
# belum diimpor ke aplikasi ini. Bobot maksimal parameter pending berbeda per
# tahun kaidah (Tabel 1 dokumen 14072026: C naik 20 -> 25).
IJD_PENDING_PARAMETERS = {
    "C": {
        "parameter_label": "Kemanfaatan (kepadatan penduduk, produktivitas lahan, LHR)",
        "bobot_maks_per_tahun": {2025: 20, 2026: 25},
        "alasan": "Belum ada sumber data kepadatan penduduk per kecamatan, produktivitas lahan, dan volume lalu lintas (LHR) di aplikasi ini.",
    },
    "E": {
        # Terpakai hanya untuk tahun kaidah tanpa rules E di DB (2025) —
        # kaidah 2026 menilai E lewat _ijd_score_penuntasan().
        "parameter_label": "Kegiatan IJD Sebelumnya (Penuntasan)",
        "bobot_maks_per_tahun": {2025: 10, 2026: 10},
        "alasan": "Skoring penuntasan hanya diimplementasikan pada kaidah 2026 (pencocokan DPP IJD TA 2025).",
    },
}

# (label komponen, kolom deklarasi Pemda, kolom hasil verifikasi Balai)
_RC_FIELD_MAP = [
    ("DED", "rc_ded_pemda", "rc_ded_balai"),
    ("RAB", "rab_pemda", "rab_balai"),
    ("DOKLING", "rc_dokling_pemda", "rc_dokling_balai"),
    ("LAHAN", "rc_lahan_pemda", "rc_lahan_balai"),
]


def _load_ijd_rules(tahun: int) -> dict:
    with db_cursor() as cur:
        cur.execute(
            "SELECT parameter_kode, parameter_label, bobot_maks, sub_kode, kondisi_label, nilai "
            "FROM ijd_scoring_rules WHERE tahun_berlaku = %s",
            (tahun,),
        )
        rows = cur.fetchall()
    rules: dict = {}
    for r in rows:
        p = rules.setdefault(r["parameter_kode"], {"label": r["parameter_label"], "bobot_maks": float(r["bobot_maks"]), "subs": {}})
        p["subs"][r["sub_kode"]] = {"label": r["kondisi_label"], "nilai": float(r["nilai"])}
    return rules


def _ijd_score_tematik(row: dict, rules: dict, ctx: dict = None) -> dict:
    rule = rules.get("A")
    if not rule:
        return {"tersedia": False, "keterangan": "Kaidah tematik belum diset di database."}
    # A1 di dokumen 14072026 berjudul "Tematik SITIA (Kompetensi)" — pakai
    # hasil verifikasi kompetensi bila ada, fallback verifikasi Balai, baru
    # deklarasi Pemda (pola sama dengan RC balai->pemda).
    tematik, sumber = "", "deklarasi Pemda"
    for col, label_sumber in (
        ("tematik_kawasan_kompetensi", "verifikasi kompetensi"),
        ("tematik_kawasan_balai", "verifikasi Balai"),
        ("tematik_kawasan_pemda", "deklarasi Pemda"),
    ):
        tematik = (row.get(col) or "").strip()
        if tematik:
            sumber = label_sumber
            break
    sub = rule["subs"].get(tematik)
    if not sub:
        keterangan = (
            f"Kategori tematik '{tematik}' ({sumber}) tidak dikenali kaidah." if tematik
            else "Usulan tidak mencantumkan tematik kawasan."
        )
        return {"tersedia": False, "keterangan": keterangan}

    nilai = sub["nilai"]
    detail = [f"{sub['label']} — sumber: {sumber}"]
    # A4 data dukung tematik (kaidah 2026: rules ber-sub_kode "A4_<STATUS>",
    # nilai sudah tertimbang x10%) dari kolom hasil verifikasi kompetensi.
    # Kaidah tanpa sub A4 (2025) memakai pesan lama apa adanya.
    if any(k.startswith("A4_") for k in rule["subs"]):
        status_a4 = (row.get("jenis_data_dukung_tematik_kompetensi") or "").strip().upper()
        sub_a4 = rule["subs"].get(f"A4_{status_a4}") if status_a4 else None
        if sub_a4:
            nilai += sub_a4["nilai"]
            detail.append(sub_a4["label"])
        elif status_a4:
            detail.append(f"A4: status data dukung '{status_a4}' tidak dikenali kaidah")
        else:
            detail.append("A4: data dukung belum dinilai verifikasi kompetensi")
        # A3 tematik tambahan: DUA sumber independen digabung, nilai tertinggi
        # dipakai bila cocok >1 kategori dan/atau >1 sumber —
        #  (a) tabel kawasan_tematik (data lokus Bappenas) by kabupaten/kecamatan
        #  (b) kecamatan_data_turunan.potensi_* (BPS Dalam Angka, parsial) by
        #      kecamatan — lihat scripts/extract_dalam_angka.py POTENSI_TABLES
        if any(k.startswith("A3_") for k in rule["subs"]):
            kategori_cocok = []
            kode_kab = (row["kode_kecamatan"] // 1000) if row.get("kode_kecamatan") else None
            if not kode_kab:
                if ctx and "kab_by_wilayah" in ctx:
                    kode_kab = ctx["kab_by_wilayah"].get((row.get("provinsi"), row.get("kabupaten_kota")))
                else:
                    with db_cursor() as cur:
                        cur.execute(
                            "SELECT kode_kabupaten FROM wilayah_mapping "
                            "WHERE provinsi_sitia = %s AND kabupaten_kota_sitia = %s",
                            (row.get("provinsi"), row.get("kabupaten_kota")),
                        )
                        r = cur.fetchone()
                    kode_kab = r["kode_kabupaten"] if r else None
            if kode_kab:
                if ctx and "kawasan_by_kab" in ctx:
                    kategori_cocok += [f"A3_{r['kategori']}" for r in ctx["kawasan_by_kab"].get(kode_kab, [])
                                        if r["kode_kecamatan"] is None or r["kode_kecamatan"] == row.get("kode_kecamatan")]
                else:
                    with db_cursor() as cur:
                        cur.execute(
                            "SELECT DISTINCT kategori FROM kawasan_tematik WHERE kode_kabupaten = %s "
                            "AND (kode_kecamatan IS NULL OR kode_kecamatan = %s)",
                            (kode_kab, row.get("kode_kecamatan")),
                        )
                        kategori_cocok += [f"A3_{r['kategori']}" for r in cur.fetchall()]

            kode_kec = row.get("kode_kecamatan")
            potensi = None
            if kode_kec:
                if ctx and "potensi_by_kec" in ctx:
                    potensi = ctx["potensi_by_kec"].get(kode_kec)
                else:
                    with db_cursor() as cur:
                        cur.execute(
                            "SELECT potensi_pertanian, potensi_perkebunan, potensi_peternakan, "
                            "potensi_perikanan FROM kecamatan_data_turunan WHERE kode_kecamatan = %s "
                            "ORDER BY tahun DESC LIMIT 1",
                            (kode_kec,),
                        )
                        potensi = cur.fetchone()
            if potensi:
                # potensi_pertanian SENGAJA tidak dicocokkan ke A3 -- Tabel 2
                # dokumen 14072026 tidak punya kategori Pertanian di A3 (mulai
                # dari Perkebunan), beda dengan A1 yang punya Pertanian.
                for field, kategori in (("potensi_perkebunan", "PERKEBUNAN"),
                                         ("potensi_peternakan", "PETERNAKAN"),
                                         ("potensi_perikanan", "PERIKANAN")):
                    if potensi.get(field):
                        kategori_cocok.append(f"A3_{kategori}")

            kandidat = [rule["subs"][k] for k in kategori_cocok if k in rule["subs"]]
            sub_a3 = max(kandidat, key=lambda s: s["nilai"]) if kandidat else None
            if sub_a3:
                nilai += sub_a3["nilai"]
                detail.append(sub_a3["label"])
            else:
                detail.append(
                    "A3: tidak ada kawasan tematik tambahan yang cocok (Perkebunan/Peternakan/"
                    "Perikanan/Transmigrasi/Kawasan Industri Prioritas/PKPN)"
                )
        else:
            detail.append("A3 (tematik tambahan) belum tersedia — menunggu data lokus gdrive")
        keterangan = "; ".join(detail) + "."
    else:
        keterangan = (
            f"{sub['label']} (sumber: {sumber}) — hanya mencakup sub-parameter tematik "
            "utama (A1/A2); tematik tambahan & data dukung (A3/A4) belum tersedia."
        )
    return {"tersedia": True, "nilai": nilai, "keterangan": keterangan}


def _ijd_score_kemantapan(row: dict, rules: dict, ctx: dict = None) -> dict:
    rule = rules.get("B")
    if not rule:
        return {"tersedia": False, "keterangan": "Kaidah kemantapan belum diset di database."}
    if "pembangunan" in (row.get("jenis_penanganan") or "").lower():
        sub = rule["subs"]["PEMBANGUNAN"]
        return {"tersedia": True, "nilai": sub["nilai"], "keterangan": sub["label"]}

    baik = float(row.get("kondisi_baik_km") or 0)
    sedang = float(row.get("kondisi_sedang_km") or 0)
    ringan = float(row.get("kondisi_ringan_km") or 0)
    berat = float(row.get("kondisi_berat_km") or 0)
    total = baik + sedang + ringan + berat
    if total <= 0:
        return {"tersedia": False, "keterangan": "Data kondisi ruas (baik/sedang/ringan/berat) belum diisi."}

    pct_mantap = (baik + sedang) / total * 100
    sub = rule["subs"]["TIDAK_MANTAP" if pct_mantap < 60 else "MANTAP"]
    return {
        "tersedia": True,
        "nilai": sub["nilai"],
        "keterangan": f"{sub['label']} (kemantapan eksisting {pct_mantap:.1f}%)",
    }


def _ijd_score_koridor(row: dict, rules: dict, ctx: dict = None) -> dict:
    rule = rules.get("D")
    if not rule:
        return {"tersedia": False, "keterangan": "Kaidah koridor belum diset di database."}
    # Hasil verifikasi Balai (kolom Status Koridor Prioritas Balai, terisi
    # mulai tarikan 15 Juli) diprioritaskan; usulan yang belum dinilai Balai
    # jatuh ke proksi kode_koridor terisi/kosong.
    status_balai = (row.get("status_koridor_balai") or "").strip().upper()
    if status_balai == "SESUAI":
        sub, sumber = rule["subs"]["TERIDENTIFIKASI"], "verifikasi Balai"
    elif status_balai:
        sub = rule["subs"].get("LAINNYA_BALAI") or rule["subs"]["LAINNYA"]
        sumber = "verifikasi Balai"
    elif (row.get("kode_koridor") or "").strip():
        sub, sumber = rule["subs"]["TERIDENTIFIKASI"], "perkiraan dari kode koridor"
    else:
        sub, sumber = rule["subs"]["LAINNYA"], "perkiraan dari kode koridor"
    return {
        "tersedia": True,
        "nilai": sub["nilai"],
        "keterangan": f"{sub['label']} ({sumber}).",
    }


def _ijd_score_rc(row: dict, rules: dict, ctx: dict = None) -> dict:
    rule = rules.get("F")
    if not rule:
        return {"tersedia": False, "keterangan": "Kaidah RC belum diset di database."}

    nilai_list, detail = [], []
    for label, pemda_col, balai_col in _RC_FIELD_MAP:
        status = row.get(balai_col) or row.get(pemda_col)
        if not status:
            detail.append(f"{label}: belum diisi")
            continue
        sumber = "Balai" if row.get(balai_col) else "Pemda"
        sub_key = f"{label}_{status.strip().upper().replace(' ', '_')}"
        sub = rule["subs"].get(sub_key)
        if not sub:
            detail.append(f"{label}: status '{status}' tidak dikenali kaidah")
            continue
        nilai_list.append(sub["nilai"])
        detail.append(f"{label}: {status} ({sumber}) → {sub['nilai']:.0f}")

    if not nilai_list:
        return {"tersedia": False, "keterangan": "Belum ada status RC (DED/RAB/Dokling/Lahan) yang terisi."}

    nilai = sum(nilai_list) / len(nilai_list)
    return {
        "tersedia": True,
        "nilai": round(nilai, 1),
        "keterangan": "; ".join(detail) + f" — rata-rata dari {len(nilai_list)}/4 komponen RC yang terisi.",
    }


def _ijd_score_kemanfaatan(row: dict, rules: dict, ctx: dict = None) -> dict:
    """Parameter C kaidah 2026 — sub A1 (kepadatan penduduk kecamatan, bobot
    35%) + A2 produktivitas padi kabupaten (proksi "Produktivitas Ton/Ha",
    bobot 12% dari 35% A2 -- Indeks Penanaman 11% & Luas Lahan 12% masih
    menunggu data). Nilai rules sudah tertimbang. Butuh relasi
    usulan_inpres.kode_kecamatan (interim manual, menunggu SHP batas
    kecamatan); A1 dari kecamatan_data_turunan, A2 dari bps_kabupaten_padi
    (dalam_angka/) -- lihat scripts/schema_ijd_scoring_2026.sql. Sub A3
    lalu lintas menunggu data."""
    rule = rules.get("C")
    if not rule:
        return {"tersedia": False, "keterangan": "Kaidah kemanfaatan belum diset di database."}
    kode_kec = row.get("kode_kecamatan")
    if not kode_kec:
        return {
            "tersedia": False,
            "keterangan": (
                "Usulan belum dihubungkan ke kecamatan (kolom kode_kecamatan — "
                "interim manual, spatial-join menunggu SHP batas kecamatan)."
            ),
        }
    if ctx and "kepadatan_by_kec" in ctx:
        kec = ctx["kepadatan_by_kec"].get(kode_kec)
    else:
        with db_cursor() as cur:
            cur.execute(
                "SELECT kecamatan, kepadatan_per_km2 FROM kecamatan_data_turunan "
                "WHERE kode_kecamatan = %s ORDER BY tahun DESC LIMIT 1",
                (kode_kec,),
            )
            kec = cur.fetchone()
    if not kec:
        return {"tersedia": False, "keterangan": f"Kode kecamatan {kode_kec} tidak dikenal di master."}
    if kec["kepadatan_per_km2"] is None:
        return {
            "tersedia": False,
            "keterangan": (
                f"Kepadatan penduduk Kec. {kec['kecamatan']} belum tersedia — "
                "buku Dalam Angka provinsi ybs. belum diimpor (folder dalam_angka/)."
            ),
        }
    kepadatan = float(kec["kepadatan_per_km2"])
    if kepadatan > 1000:
        sub_kode = "A1_GT1000"
    elif kepadatan >= 500:
        sub_kode = "A1_500_1000"
    elif kepadatan >= 100:
        sub_kode = "A1_100_500"
    else:
        sub_kode = "A1_LT100"
    sub = rule["subs"][sub_kode]
    nilai = sub["nilai"]
    detail = [f"Kec. {kec['kecamatan']}: {sub['label']} (kepadatan {kepadatan:,.0f} jiwa/km2)"]

    if any(k.startswith("A2_") for k in rule["subs"]):
        kode_kab = kode_kec // 1000
        padi = (ctx["produktivitas_padi_by_kab"].get(kode_kab) if ctx and "produktivitas_padi_by_kab" in ctx
                else None)
        if padi is None and not (ctx and "produktivitas_padi_by_kab" in ctx):
            with db_cursor() as cur:
                cur.execute(
                    "SELECT nama_kab, produktivitas_ku_ha FROM bps_kabupaten_padi "
                    "WHERE kode_kab = %s ORDER BY tahun DESC LIMIT 1",
                    (f"{kode_kab:04d}",),
                )
                padi = cur.fetchone()
        if padi and padi.get("produktivitas_ku_ha") is not None:
            ku_ha = float(padi["produktivitas_ku_ha"])
            if ku_ha > 60:
                sub_a2 = rule["subs"]["A2_GT6"]
            elif ku_ha >= 50:
                sub_a2 = rule["subs"]["A2_5_6"]
            elif ku_ha >= 40:
                sub_a2 = rule["subs"]["A2_4_5"]
            elif ku_ha >= 30:
                sub_a2 = rule["subs"]["A2_3_4"]
            else:
                sub_a2 = rule["subs"]["A2_LT3"]
            nilai += sub_a2["nilai"]
            detail.append(f"{sub_a2['label']} (produktivitas padi kab. {ku_ha/10:.1f} ton/ha, proksi kabupaten)")
        else:
            detail.append("A2: produktivitas padi kabupaten belum tersedia (buku Dalam Angka belum diimpor)")
        detail.append("Indeks Penanaman & Luas Lahan (sub A2) dan Lalu Lintas (A3) belum tersedia.")
    else:
        detail.append("hanya sub A1 kepadatan; produktivitas (A2) & lalu lintas (A3) belum tersedia.")

    return {"tersedia": True, "nilai": nilai, "keterangan": "; ".join(detail) + "."}


def _ijd_score_penuntasan(row: dict, rules: dict, ctx: dict = None) -> dict:
    """Parameter E kaidah 2026: lanjutan/penuntasan IJD TA 2025 vs usulan baru.
    Flag usulan_inpres.lanjutan_ijd_2025 diisi scripts/import_dpp_ijd_2025.py
    (pencocokan nama ruas + wilayah terhadap tabel dpp_ijd_2025); NULL berarti
    pencocokan belum pernah dijalankan."""
    rule = rules.get("E")
    if not rule:
        return {"tersedia": False, "keterangan": "Kaidah penuntasan belum diset di database."}
    # Flag resmi hasil verifikasi kompetensi (kolom Penuntasan IJD Sebelumnya,
    # terisi mulai tarikan 15 Juli) diprioritaskan di atas hasil pencocokan
    # nama ruas kita sendiri.
    if (row.get("penuntasan_ijd_kompetensi") or "").strip().upper() == "YA":
        sub = rule["subs"]["LANJUTAN"]
        return {
            "tersedia": True,
            "nilai": sub["nilai"],
            "keterangan": sub["label"] + " (flag resmi verifikasi kompetensi SITIA).",
        }
    flag = row.get("lanjutan_ijd_2025")
    if flag is None:
        return {
            "tersedia": False,
            "keterangan": "Pencocokan DPP IJD 2025 belum dijalankan (scripts/import_dpp_ijd_2025.py).",
        }
    sub = rule["subs"]["LANJUTAN" if flag else "BARU"]
    return {
        "tersedia": True,
        "nilai": sub["nilai"],
        "keterangan": sub["label"] + " (pencocokan nama ruas + wilayah terhadap DPP IJD TA 2025, bukan penetapan resmi).",
    }


_IJD_SCORERS = {
    "A": _ijd_score_tematik, "B": _ijd_score_kemantapan, "C": _ijd_score_kemanfaatan,
    "D": _ijd_score_koridor, "E": _ijd_score_penuntasan, "F": _ijd_score_rc,
}


def _compute_ijd_score(row: dict, tahun: int = 2026, rules: dict = None, ctx: dict = None) -> dict:
    if rules is None:
        rules = _load_ijd_rules(tahun)

    komponen = []
    skor_tertimbang = 0.0
    bobot_tersedia = 0.0

    # Daftar parameter mengikuti kaidah tahun terpilih: gabungan kode yang
    # punya rules di DB dan yang masih pending — F ada di kaidah 2025 tapi
    # dihapus dari penilaian 2026, jadi tidak boleh muncul (bahkan sebagai
    # "belum tersedia") saat tahun=2026.
    for kode in sorted(set(rules) | set(IJD_PENDING_PARAMETERS)):
        if kode in rules and kode in _IJD_SCORERS:
            rule = rules.get(kode, {})
            hasil = _IJD_SCORERS[kode](row, rules, ctx)
            bobot_maks = rule.get("bobot_maks", 0)
            entry = {
                "kode": kode,
                "label": rule.get("label", kode),
                "bobot_maks": bobot_maks,
                "tersedia": hasil["tersedia"],
                "keterangan": hasil["keterangan"],
            }
            if hasil["tersedia"]:
                kontribusi = hasil["nilai"] / 100 * bobot_maks
                entry["nilai"] = hasil["nilai"]
                entry["kontribusi"] = round(kontribusi, 2)
                skor_tertimbang += kontribusi
                bobot_tersedia += bobot_maks
            komponen.append(entry)
        else:
            pending = IJD_PENDING_PARAMETERS.get(kode, {})
            bobot_maks = rules.get(kode, {}).get("bobot_maks") or \
                pending.get("bobot_maks_per_tahun", {}).get(tahun, 0)
            komponen.append({
                "kode": kode,
                "label": pending.get("parameter_label") or rules.get(kode, {}).get("label", kode),
                "bobot_maks": bobot_maks,
                "tersedia": False,
                "keterangan": pending.get("alasan", "Parameter belum diimplementasikan."),
            })

    skor_ternormalisasi = round(skor_tertimbang / bobot_tersedia * 100, 1) if bobot_tersedia else None

    return {
        "tahun_berlaku": tahun,
        "komponen": komponen,
        "skor_tertimbang": round(skor_tertimbang, 2),
        "bobot_tersedia": bobot_tersedia,
        "skor_ternormalisasi_100": skor_ternormalisasi,
        "catatan": (
            "Skor 'Prioritisasi Teknokratik' perkiraan berdasarkan Tabel 1 dokumen Penentuan Parameter "
            f"Penilaian IJD No. 11/2025 (kaidah tahun {tahun}). skor_tertimbang dihitung hanya dari parameter yang datanya "
            f"tersedia (total bobot tersedia: {bobot_tersedia:.0f} dari 100); skor_ternormalisasi_100 "
            "menyetarakannya ke skala 0-100 seolah hanya parameter tersedia yang dinilai. Bukan skor "
            "resmi Bina Marga/Bappenas."
        ),
    }


@app.get("/api/usulan-inpres/{usulan_id}/ijd-score")
def usulan_inpres_ijd_score(usulan_id: int, tahun: int = 2026):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM usulan_inpres WHERE id = %s", (usulan_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Usulan tidak ditemukan")
    return _compute_ijd_score(row, tahun)


IJD_EXPORT_IDENTITAS_COLS = [
    ("Nama Pengusul", "nama_pengusul"), ("Provinsi", "provinsi"),
    ("Kabupaten/Kota", "kabupaten_kota"), ("Nama Kegiatan", "nama_kegiatan"),
    ("Kode Koridor", "kode_koridor"), ("Nama Koridor", "nama_koridor"),
    ("Panjang Koridor", "panjang_koridor_km"), ("Kode Ruas", "kode_ruas"),
    ("Nama Ruas", "nama_ruas"), ("Panjang Ruas (KM)", "panjang_ruas_km"),
    ("Status Ruas", "status_ruas"), ("No. Jembatan", "no_jembatan"),
    ("Nama Jembatan", "nama_jembatan"), ("Panjang Jembatan (M)", "panjang_jembatan_m"),
    ("Komponen (Kompetensi)", "komponen_kompetensi"),
    ("Panjang Penanganan (Kompetensi)", "panjang_penanganan_kompetensi"),
    ("Satuan", "satuan"), ("Alokasi Usulan (Kompetensi)", "alokasi_usulan_kompetensi"),
    ("Tematik Kawasan (Kompetensi)", "tematik_kawasan_kompetensi"),
    ("Keterangan", "keterangan"), ("Seleksi Sistem (dipake yang lulus)", "seleksi_sistem"),
    ("Verifikasi Kompetensi", "verifikasi_kompetensi"),
    ("Catatan Pembahasan Kompetensi", "catatan_pembahasan_kompetensi"),
    ("Lebar Jalan (M)", "lebar_jalan_m"),
    ("Kondisi Ruas Jalan Baik (KM)", "kondisi_baik_km"),
    ("Kondisi Ruas Jalan Sedang (KM)", "kondisi_sedang_km"),
    ("Kondisi Ruas Jalan Ringan (KM)", "kondisi_ringan_km"),
    ("Kondisi Ruas Jalan Berat (KM)", "kondisi_berat_km"),
    ("Kondisi Jembatan", "kondisi_jembatan"), ("Kapasitas Fiskal", "kapasitas_fiskal"),
]
# Header lengkap (multi-baris, dipakai xlsx -- ikuti persis wording template
# Bappenas) vs pendek (satu baris, dipakai preview JSON di UI -- tabel data-
# viewer generik tidak dirancang utk header berparagraf).
IJD_EXPORT_BAPPENAS_HEADERS = [
    "ASPEK PRIORITAS DAN NILAI STRATEGIS\n"
    "(Menilai sejauh mana usulan berada di lokasi yang menjadi prioritas nasional "
    "dan membutuhkan afirmasi khusus dari pemerintah pusat.)\n\n"
    "Data referensi penilaian adalah di sheet Kumpulan Data, Row Penilaian Lokpri.",
    "DAYA UNGKIT EKONOMI & KINERJA SEKTORAL\n"
    "(Menilai kontribusi ruas terhadap ketahanan pangan nasional, kelancaran logistik, "
    "dan stimulasi pertumbuhan ekonomi lokal).\n\n"
    "Data referensi penilaian adalah di sheet Kumpulan Data, Row Penilaian Ruas.",
    "DAYA UNGKIT EKONOMI & KINERJA SEKTORAL - NARASI AI\n"
    "(Pelengkap kolom sebelumnya, narasi naratif hasil AI. Kosong bila usulan belum pernah "
    "digenerate lewat tombol \"Proses Narasi AI\" (bulk per provinsi) di preview atau fitur "
    "\"Draf Penilaian Bappenas (AI)\" per-usulan.)",
    "RANGKING DALAM PROVINSI\n"
    "(Urutan prioritas ruas dalam masing-masing provinsi merupakan kesimpulan integratif "
    "dari 2 aspek yaitu nilai strategis dan dampak ekonomi dan sektoral)",
    "KESIMPULAN PENILAIAN BAPPENAS",
    "TOTAL",
]
IJD_EXPORT_BAPPENAS_HEADERS_SHORT = [
    "Aspek A: Prioritas & Nilai Strategis",
    "Aspek B: Daya Ungkit Ekonomi & Sektoral",
    "Aspek B: Narasi AI",
    "Ranking Bappenas (per Provinsi)",
    "Kesimpulan Penilaian Bappenas",
    "Total (Bappenas)",
]
IJD_EXPORT_TEKNOKRATIS_KODE = ["A", "B", "C", "D", "E"]
IJD_EXPORT_TEKNOKRATIS_HEADERS = {
    "A": "TEMATIK & DATA DUKUNG (A)", "B": "KONDISI KEMANTAPAN EKSISTING RUAS (B)",
    "C": "KEMANFAATAN (C)", "D": "KORIDOR (D)", "E": "KEBERLANJUTAN KEGIATAN INPRES SEBELUMNYA (E)",
}
IJD_EXPORT_RANKING_LABEL = "PENILAIAN PRIORITASI USULAN PER PROVINSI"

# Cache hasil komputasi bulk (kunci: provinsi+tahun) -- skoring ±3.000 usulan
# makan waktu beberapa detik (query batch + loop scorer), jadi TIDAK dihitung
# ulang tiap kali user membuka/navigasi halaman preview. Di-invalidasi manual
# di titik-titik yang mengubah datanya (draf AI Bappenas baru, import lokus
# Aspek A) -- restart server juga membersihkannya (sama pola dgn cache Maps
# overlay di _map_layer_geojson_cache).
_ijd_bulk_cache: dict = {}


def _ijd_score_bulk_rows(provinsi: str, tahun: int):
    """Skoring IJD massal (opsional difilter per provinsi): identitas usulan +
    penilaian Bappenas (Aspek A/B rule-based) + penilaian Teknokratis (A-E) +
    ranking, satu baris per usulan. Dipakai bareng oleh endpoint preview JSON
    (paged) dan export xlsx supaya logikanya cuma ditulis sekali.

    _ijd_score_tematik (A3) dan _ijd_score_kemanfaatan (C) biasanya query DB
    per-usulan — untuk cakupan nasional (±3.000 usulan) itu berarti ribuan
    koneksi kecil. Di sini semua lookup dibatch di muka (kepadatan per
    kecamatan, kawasan tematik per kabupaten, fallback kode kabupaten dari
    wilayah_mapping) lalu dioper lewat `ctx` supaya scorer tidak query per baris.

    Return (header_row_full, header_row_short, data_rows) — data_rows berupa
    list of list, urutan kolom SAMA dgn header_row_*.
    """
    key = (provinsi, tahun)
    if key in _ijd_bulk_cache:
        return _ijd_bulk_cache[key]

    with db_cursor() as cur:
        if provinsi:
            cur.execute("SELECT * FROM usulan_inpres WHERE provinsi = %s", (provinsi,))
        else:
            cur.execute("SELECT * FROM usulan_inpres")
        rows = cur.fetchall()
    if not rows:
        raise HTTPException(404, "Tidak ada usulan yang cocok filter provinsi tsb.")

    rules = _load_ijd_rules(tahun)

    with db_cursor() as cur:
        cur.execute("SELECT provinsi_sitia, kabupaten_kota_sitia, kode_kabupaten FROM wilayah_mapping")
        kab_by_wilayah = {(r["provinsi_sitia"], r["kabupaten_kota_sitia"]): r["kode_kabupaten"]
                           for r in cur.fetchall()}

    kode_kab_set = set()
    for r in rows:
        if r.get("kode_kecamatan"):
            kode_kab_set.add(r["kode_kecamatan"] // 1000)
        else:
            kab = kab_by_wilayah.get((r.get("provinsi"), r.get("kabupaten_kota")))
            if kab:
                kode_kab_set.add(kab)
    kawasan_by_kab = {}
    if kode_kab_set:
        with db_cursor() as cur:
            cur.execute(
                "SELECT kode_kabupaten, kode_kecamatan, kategori FROM kawasan_tematik "
                "WHERE kode_kabupaten IN %s", (tuple(kode_kab_set),),
            )
            for r in cur.fetchall():
                kawasan_by_kab.setdefault(r["kode_kabupaten"], []).append(r)

    kode_kec_set = {r["kode_kecamatan"] for r in rows if r.get("kode_kecamatan")}
    kepadatan_by_kec = {}
    if kode_kec_set:
        with db_cursor() as cur:
            cur.execute(
                "SELECT kode_kecamatan, kecamatan, kepadatan_per_km2, jumlah_penduduk, "
                "kendaraan_total, potensi_pertanian, potensi_perkebunan, potensi_peternakan, "
                "potensi_perikanan FROM kecamatan_data_turunan WHERE kode_kecamatan IN %s ORDER BY tahun DESC",
                (tuple(kode_kec_set),),
            )
            for r in cur.fetchall():
                kepadatan_by_kec.setdefault(r["kode_kecamatan"], r)  # tahun terbaru menang (ORDER BY di atas)

    # Angka produksi riil (bukan sekadar flag ada/tidak) utk narasi Aspek B --
    # sumbernya bps_kecamatan_potensi_tematik (kolom *_produksi_*), BEDA dari
    # kepadatan_by_kec di atas (yang cuma simpan boolean potensi_* dari
    # kecamatan_data_turunan). Lihat _bappenas_aspek_b_ekonomi.
    potensi_produksi_by_kec = {}
    if kode_kec_set:
        with db_cursor() as cur:
            cur.execute(
                "SELECT kode_kecamatan, pertanian_produksi_ton, perkebunan_produksi_ton, "
                "peternakan_produksi_daging_kg, peternakan_produksi_telur_kg, perikanan_produksi_ton "
                "FROM bps_kecamatan_potensi_tematik WHERE kode_kecamatan IN %s ORDER BY tahun DESC",
                (tuple(kode_kec_set),),
            )
            for r in cur.fetchall():
                potensi_produksi_by_kec.setdefault(r["kode_kecamatan"], r)  # tahun terbaru menang

    # Batch utk Aspek A/B Bappenas (rule-based, lihat _bappenas_aspek_a_lokus/
    # _bappenas_aspek_b_ekonomi) — sama alasan: hindari query per baris.
    bappenas_lokus_by_kab, bappenas_lokus_by_prov = {}, {}
    kode_prov_set = {k // 100 for k in kode_kab_set}
    if kode_kab_set or kode_prov_set:
        with db_cursor() as cur:
            cur.execute(
                "SELECT kriteria, level, kode_provinsi, kode_kabupaten, kode_kecamatan "
                "FROM bappenas_lokus_a WHERE kode_kabupaten IN %s OR kode_provinsi IN %s",
                (tuple(kode_kab_set) or (0,), tuple(kode_prov_set) or (0,)),
            )
            for r in cur.fetchall():
                if r["level"] == "PROVINSI" and r["kode_provinsi"]:
                    bappenas_lokus_by_prov.setdefault(r["kode_provinsi"], []).append(r["kriteria"])
                elif r["kode_kabupaten"]:
                    bappenas_lokus_by_kab.setdefault(r["kode_kabupaten"], []).append(r)
    kemantapan_kab_set = set()
    if kode_kab_set:
        with db_cursor() as cur:
            cur.execute(
                "SELECT DISTINCT kode_wilayah FROM kemantapan_ijd_2026 WHERE kode_wilayah IN %s "
                "AND jenis_adm IN ('Kab.','Kota')",
                (tuple(kode_kab_set),),
            )
            kemantapan_kab_set = {r["kode_wilayah"] for r in cur.fetchall()}

    # Produktivitas padi kabupaten (C.A2, proksi "Produktivitas Ton/Ha" Tabel 4
    # — hanya komoditas padi & level kabupaten, lihat _ijd_score_kemanfaatan).
    produktivitas_padi_by_kab = {}
    if kode_kab_set:
        with db_cursor() as cur:
            cur.execute(
                "SELECT kode_kab, nama_kab, produktivitas_ku_ha FROM bps_kabupaten_padi "
                "WHERE kode_kab IN %s ORDER BY tahun DESC",
                (tuple(kode_kab_set),),
            )
            for r in cur.fetchall():
                produktivitas_padi_by_kab.setdefault(int(r["kode_kab"]), r)  # tahun terbaru menang

    # kepadatan_by_kec juga menyimpan kolom potensi_* (satu query, satu tabel
    # sumber) — dipakai ulang sebagai ctx["potensi_by_kec"] utk A3.
    ctx = {"kab_by_wilayah": kab_by_wilayah, "kawasan_by_kab": kawasan_by_kab,
           "kepadatan_by_kec": kepadatan_by_kec, "potensi_by_kec": kepadatan_by_kec,
           "potensi_produksi_by_kec": potensi_produksi_by_kec,
           "bappenas_lokus_by_kab": bappenas_lokus_by_kab, "bappenas_lokus_by_prov": bappenas_lokus_by_prov,
           "kemantapan_kab_set": kemantapan_kab_set,
           "produktivitas_padi_by_kab": produktivitas_padi_by_kab}
    hasil = [(row, _compute_ijd_score(row, tahun, rules, ctx)) for row in rows]
    # Skor tertinggi dulu; usulan tanpa skor (semua parameter belum tersedia) di akhir.
    hasil.sort(key=lambda x: (x[1]["skor_ternormalisasi_100"] is None,
                               -(x[1]["skor_ternormalisasi_100"] or 0)))

    # Peringkat per provinsi (kolom 43 template) dihitung terpisah dari urutan
    # baris utama (yang dalam cakupan filter, bisa nasional) supaya tetap
    # benar walau ekspor mencakup >1 provinsi sekaligus.
    by_provinsi: dict = {}
    for row, skor in hasil:
        by_provinsi.setdefault(row.get("provinsi"), []).append((row, skor))
    rank_in_provinsi = {}
    for items in by_provinsi.values():
        items_sorted = sorted(items, key=lambda x: (x[1]["skor_ternormalisasi_100"] is None,
                                                      -(x[1]["skor_ternormalisasi_100"] or 0)))
        for i, (row, _) in enumerate(items_sorted, start=1):
            rank_in_provinsi[row["id"]] = i

    # Aspek A/B Bappenas (rule-based, lihat _bappenas_aspek_a_lokus/
    # _bappenas_aspek_b_ekonomi) — dihitung skr karena ctx sudah dibatch di
    # atas, jadi murah (tanpa query per baris). "Kesimpulan" TETAP kosong
    # kecuali usulan itu sudah pernah digenerate satu-per-satu lewat
    # POST /api/usulan-inpres/{id}/penilaian-bappenas (AI, di-cache) — bulk
    # export tidak memanggil LLM ribuan kali.
    usulan_ids = [row["id"] for row in rows]
    kesimpulan_cache = {}
    aspek_b_narasi_ai_cache = {}
    if usulan_ids:
        with db_cursor() as cur:
            cur.execute(
                "SELECT usulan_id, kesimpulan, aspek_b_narasi_ai FROM penilaian_bappenas_ai "
                "WHERE usulan_id IN %s",
                (tuple(usulan_ids),),
            )
            for r in cur.fetchall():
                kesimpulan_cache[r["usulan_id"]] = r["kesimpulan"]
                aspek_b_narasi_ai_cache[r["usulan_id"]] = r["aspek_b_narasi_ai"]

    bappenas_hasil = {}
    for row in rows:
        aspek_a = _bappenas_aspek_a_lokus(row, ctx)
        aspek_b = _bappenas_aspek_b_ekonomi(row, ctx)
        poin_a = _bappenas_poin_from_total(aspek_a["total_kriteria"])
        poin_b = _bappenas_poin_from_total(aspek_b["total_indikator"])
        bappenas_hasil[row["id"]] = {"aspek_a": aspek_a, "aspek_b": aspek_b,
                                      "poin_a": poin_a, "poin_b": poin_b, "total": poin_a + poin_b}

    # Peringkat Bappenas per provinsi (kolom "RANGKING DALAM PROVINSI
    # (Bappenas)") — total poin A+B, terpisah dari peringkat teknokratis.
    rank_bappenas_in_provinsi = {}
    for items in by_provinsi.values():
        items_sorted = sorted(items, key=lambda x: -bappenas_hasil[x[0]["id"]]["total"])
        for i, (row, _) in enumerate(items_sorted, start=1):
            rank_bappenas_in_provinsi[row["id"]] = i

    # Struktur & label kolom mengikuti sheet "Output Penilaian" di
    # docs/docs/2_Analisis Prioritas untuk Bappenas dan Teknokratis
    # 15.7.2026.xlsx (template kosong dari Bappenas) — kolom 1-32 identitas/
    # administratif dari usulan_inpres, 33-38 penilaian Bappenas (Aspek A/B
    # rule-based + narasi AI Aspek B + ranking + total; kesimpulan cuma
    # terisi kalau sudah pernah digenerate AI per-usulan), 39-44 penilaian
    # Teknokratis (A-E dari _compute_ijd_score + peringkat per provinsi).
    header_row = (["No.", "ID"] + [label for label, _ in IJD_EXPORT_IDENTITAS_COLS]
                  + IJD_EXPORT_BAPPENAS_HEADERS
                  + [IJD_EXPORT_TEKNOKRATIS_HEADERS[k] for k in IJD_EXPORT_TEKNOKRATIS_KODE]
                  + [IJD_EXPORT_RANKING_LABEL])
    header_row_short = (["No.", "ID"] + [label for label, _ in IJD_EXPORT_IDENTITAS_COLS]
                         + IJD_EXPORT_BAPPENAS_HEADERS_SHORT
                         + [IJD_EXPORT_TEKNOKRATIS_HEADERS[k] for k in IJD_EXPORT_TEKNOKRATIS_KODE]
                         + [IJD_EXPORT_RANKING_LABEL])

    data_rows = []
    for i, (row, skor) in enumerate(hasil, start=1):
        komponen_by_kode = {k["kode"]: k for k in skor["komponen"]}
        bh = bappenas_hasil[row["id"]]
        data_row = [i, row["id"]] + [row.get(field) for _, field in IJD_EXPORT_IDENTITAS_COLS]
        data_row += [
            f"[Poin {bh['poin_a']}] {bh['aspek_a']['narasi']}",
            f"[Poin {bh['poin_b']}] {bh['aspek_b']['narasi']}",
            aspek_b_narasi_ai_cache.get(row["id"]),
            rank_bappenas_in_provinsi[row["id"]],
            kesimpulan_cache.get(row["id"]),
            bh["total"],
        ]
        data_row += [komponen_by_kode.get(k, {}).get("kontribusi") for k in IJD_EXPORT_TEKNOKRATIS_KODE]
        data_row += [rank_in_provinsi[row["id"]]]
        data_rows.append(data_row)

    result = (header_row, header_row_short, data_rows)
    _ijd_bulk_cache[key] = result
    return result


@app.get("/api/usulan-inpres/ijd-score/preview")
def usulan_inpres_ijd_score_preview(provinsi: str = "", tahun: int = 2026, limit: int = 50, offset: int = 0):
    """Versi JSON, dipaging, dari _ijd_score_bulk_rows — dipakai modal preview
    di UI (tabel gaya "Data") supaya user bisa cek isi sebelum benar-benar
    unduh xlsx. Kontrak responsnya sengaja mengikuti GET /api/data/{table}
    supaya bisa pakai styling/komponen tabel yang sama di frontend."""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    _header_full, header_short, data_rows = _ijd_score_bulk_rows(provinsi, tahun)
    page = data_rows[offset:offset + limit]
    # Kolom prosa AI: kirim utuh (batas longgar) — frontend menampilkannya
    # terpotong tapi memberi tooltip berisi teks lengkap saat hover.
    prose_cols = {i for i, h in enumerate(header_short)
                  if h in ("Aspek B: Narasi AI", "Kesimpulan Penilaian Bappenas")}

    def _trim(v, i):
        if not isinstance(v, str):
            return v
        # Sel checklist Aspek A/B: JANGAN potong di 200 char — butir tercentang
        # ([v]) sering di urutan bawah daftar (mis. Kemantapan baris 39) dan
        # ikut terpotong, membuat poinnya tampak tidak cocok dgn centangnya.
        # Tinggi sel dikendalikan CSS (.checklist-cell), bukan pemotongan.
        limit_chars = 1500 if (i in prose_cols or "[v]" in v or "[ ]" in v) else 200
        return (v[:limit_chars] + "…") if len(v) > limit_chars else v

    trimmed = [[_trim(v, i) for i, v in enumerate(r)] for r in page]
    scope = provinsi or "Nasional"
    return jsonable_encoder({
        "table": "ijd_skor_preview", "label": f"Preview Export Skor IJD — {scope} ({tahun})",
        "columns": header_short, "rows": trimmed, "total": len(data_rows),
        "limit": limit, "offset": offset,
    })


@app.get("/api/usulan-inpres/ijd-score/export/xlsx")
def usulan_inpres_ijd_score_bulk_export(provinsi: str = "", tahun: int = 2026):
    header_row, _header_short, data_rows = _ijd_score_bulk_rows(provinsi, tahun)

    wb = openpyxl.Workbook(write_only=True)
    ws = wb.create_sheet("Output Penilaian")
    group_row = [None] * (2 + len(IJD_EXPORT_IDENTITAS_COLS))
    group_row += ["FORMAT PENILAIAN BAPPENAS"] + [None] * (len(IJD_EXPORT_BAPPENAS_HEADERS) - 1)
    group_row += ["FORMAT PENILAIAN TEKNOKRATIS"] + [None] * len(IJD_EXPORT_TEKNOKRATIS_KODE)
    ws.append(group_row)
    ws.append(header_row)
    for data_row in data_rows:
        ws.append(data_row)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    scope = re.sub(r"[^\w]+", "_", provinsi) if provinsi else "Nasional"
    fname = f"ijd_skor_{scope}_{tahun}_{datetime.now():%Y%m%d%H%M%S}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


# --- Skor Prioritas Nasional (dokumen 14072026 bagian C: 70% teknokratis +
# 10% Kementerian PU + 10% Bappenas + 10% Kemenko Infra) ---

_SPN_FIELDS = (
    "id, nama_kegiatan, nama_ruas, provinsi, kabupaten_kota, "
    "prioritas_kompetensi, prioritas_balai, indikasi_prioritas_bappenas, "
    "indikasi_prioritas_kemenko, alokasi_usulan_kompetensi, alokasi_usulan_pemda"
)


def _skor_prioritas_nasional(row: dict) -> dict:
    """Skor kuantitatif per usulan. Hanya usulan yang sudah punya urutan
    prioritas kompetensi (lolos verifikasi) yang bisa dihitung — komponen
    teknokratis 70% adalah basisnya."""
    pk = row.get("prioritas_kompetensi")
    pb = row.get("prioritas_balai")
    bappenas = (row.get("indikasi_prioritas_bappenas") or "").strip().upper() == "YA"
    kemenko = (row.get("indikasi_prioritas_kemenko") or "").strip().upper() == "YA"

    skor_kompetensi = max(101 - int(pk), 1) if pk is not None else None
    skor_pu = 100 if pb == 1 else (50 if pb is not None else 0)

    komponen = [
        {
            "kode": "A", "label": "Prioritisasi Teknokratis", "bobot_pct": 70,
            "nilai": skor_kompetensi,
            "keterangan": (
                f"101 − urutan prioritas kompetensi ({pk}), minimal 1." if pk is not None
                else "Belum ada urutan prioritas kompetensi (usulan belum selesai dinilai)."
            ),
        },
        {
            "kode": "B", "label": "Prioritisasi Kementerian PU", "bobot_pct": 10,
            "nilai": skor_pu,
            "keterangan": (
                f"Prioritas Balai {pb} ({'peringkat 1 = 100' if pb == 1 else 'peringkat 2+ = 50'})."
                if pb is not None else "Belum ada urutan prioritas Balai — dinilai 0."
            ),
        },
        {
            "kode": "C", "label": "Indikasi Prioritas Bappenas", "bobot_pct": 10,
            "nilai": 100 if bappenas else 0,
            "keterangan": (
                "Ditandai prioritas Bappenas." if bappenas else
                "Belum/tidak ditandai prioritas Bappenas (kolom indikasi SITIA masih kosong per tarikan 15 Juli)."
            ),
        },
        {
            "kode": "D", "label": "Indikasi Prioritas Kemenko Infra", "bobot_pct": 10,
            "nilai": 100 if kemenko else 0,
            "keterangan": (
                "Ditandai prioritas Kemenko Infra." if kemenko else
                "Belum/tidak ditandai prioritas Kemenko Infra (kolom indikasi SITIA masih kosong per tarikan 15 Juli)."
            ),
        },
    ]
    total = None
    if skor_kompetensi is not None:
        total = round(sum(k["nilai"] * k["bobot_pct"] / 100 for k in komponen), 2)
    for k in komponen:
        k["kontribusi"] = round((k["nilai"] or 0) * k["bobot_pct"] / 100, 2)

    return {
        "skor_total": total,
        "komponen": komponen,
        "catatan": (
            "Skor Prioritas Nasional perkiraan per dokumen Penentuan Parameter Penilaian IJD "
            "14 Juli 2026 (70% teknokratis + 10% PU + 10% Bappenas + 10% Kemenko Infra). "
            "Bukan penetapan resmi."
        ),
    }


@app.get("/api/usulan-inpres/{usulan_id}/skor-prioritas-nasional")
def usulan_inpres_skor_prioritas(usulan_id: int):
    with db_cursor() as cur:
        cur.execute(f"SELECT {_SPN_FIELDS} FROM usulan_inpres WHERE id = %s", (usulan_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Usulan tidak ditemukan")
    hasil = _skor_prioritas_nasional(row)
    if hasil["skor_total"] is not None:
        # peringkat nasional = posisi skor usulan ini di antara semua yang ternilai
        with db_cursor() as cur:
            cur.execute(
                f"SELECT {_SPN_FIELDS} FROM usulan_inpres WHERE prioritas_kompetensi IS NOT NULL"
            )
            semua = sorted((_skor_prioritas_nasional(r)["skor_total"] for r in cur.fetchall()),
                           reverse=True)
        hasil["peringkat_nasional"] = semua.index(hasil["skor_total"]) + 1
        hasil["jumlah_ternilai"] = len(semua)
    return hasil


@app.get("/api/prioritas-nasional")
def prioritas_nasional_list(provinsi: str = "", limit: int = 50, offset: int = 0):
    """Peringkat Prioritas Nasional: semua usulan yang punya urutan prioritas
    kompetensi, diurutkan skor tertinggi -> terendah (basis alokasi 2 lapis)."""
    limit = max(1, min(limit, 200))
    with db_cursor() as cur:
        cur.execute(f"SELECT {_SPN_FIELDS} FROM usulan_inpres WHERE prioritas_kompetensi IS NOT NULL")
        rows = cur.fetchall()
    dinilai = []
    for r in rows:
        hasil = _skor_prioritas_nasional(r)
        dinilai.append({
            "id": r["id"], "nama_kegiatan": r["nama_kegiatan"], "nama_ruas": r["nama_ruas"],
            "provinsi": r["provinsi"], "kabupaten_kota": r["kabupaten_kota"],
            "prioritas_kompetensi": r["prioritas_kompetensi"], "prioritas_balai": r["prioritas_balai"],
            "alokasi": r["alokasi_usulan_kompetensi"] or r["alokasi_usulan_pemda"],
            "skor_total": hasil["skor_total"],
        })
    dinilai.sort(key=lambda x: (-x["skor_total"], x["id"]))
    for i, d in enumerate(dinilai, start=1):
        d["peringkat_nasional"] = i
    if provinsi:
        dinilai = [d for d in dinilai if d["provinsi"] == provinsi]
    total = len(dinilai)
    return {"total": total, "usulan": dinilai[offset:offset + limit]}


# --- Pagu Indikatif Provinsi (dokumen 14072026 bagian B) + Alokasi 2 Lapis
# (bagian C akhir). Komponen pagu yang datanya ada baru A1 (panjang jalan
# daerah, SI 2026 Tabel 10.1.1) dan A4 (kapasitas fiskal, kolom SITIA usulan
# gubernur) — A2 kemantapan (PUPR), A3 kawasan pangan (KP2B), dan A5 IKK
# (publikasi BPS terpisah) belum ada sumbernya. Tiap komponen dinyatakan
# sebagai pangsa nasional (jumlah antar provinsi = 100%) supaya total pagu
# tepat mendistribusikan alokasi nasional; skor akhir dinormalisasi ulang ke
# bobot komponen yang tersedia (20 + 15 dari 100).

_FISKAL_SKOR = {"SANGAT TINGGI": 10, "TINGGI": 15, "SEDANG": 20, "RENDAH": 25, "SANGAT RENDAH": 30}
_PAGU_KOMPONEN_PENDING = {
    "A3": "Kawasan pangan strategis (bobot 20) — data KP2B/kawasan pangan belum diimpor.",
    "A5": "Indeks Kemahalan Konstruksi (bobot 15) — publikasi IKK BPS belum diimpor.",
}


def _skor_indeks_ketidakmantapan(pct: float) -> float:
    """Tabel 7 dokumen 14072026: skor indeks ketidakmantapan jalan daerah."""
    if pct > 65:
        return 100
    if pct >= 40:
        return 75
    if pct >= 25:
        return 50
    return 25


def _norm_prov_nama(s: str) -> str:
    toks = [t for t in re.split(r"[^A-Z0-9]+", str(s).upper()) if t]
    toks = ["DI" if t in ("DI", "D", "DAERAH") else t for t in toks]
    return " ".join(t for t in toks if t not in ("I", "ISTIMEWA"))


def _pagu_provinsi(alokasi_nasional: Optional[float] = None) -> dict:
    with db_cursor() as cur:
        cur.execute(
            "SELECT provinsi, NULLIF(COALESCE(provinsi_km, 0) + COALESCE(kabkota_km, 0), 0) AS daerah_km "
            "FROM si_panjang_jalan_provinsi WHERE kode_provinsi > 0 "
            "AND tahun = (SELECT MAX(tahun) FROM si_panjang_jalan_provinsi)"
        )
        jalan = {_norm_prov_nama(r["provinsi"]): float(r["daerah_km"])
                 for r in cur.fetchall() if r["daerah_km"] is not None}
        cur.execute(
            "SELECT provinsi, MAX(kapasitas_fiskal) AS fiskal FROM usulan_inpres "
            "WHERE nama_pengusul LIKE 'Gubernur%%' AND kapasitas_fiskal IS NOT NULL "
            "GROUP BY provinsi"
        )
        fiskal = {_norm_prov_nama(r["provinsi"]): r["fiskal"] for r in cur.fetchall()}
        cur.execute(
            "SELECT provinsi, SUM(panjang_km) AS total_km, SUM(tidak_mantap_km) AS total_tm "
            "FROM kemantapan_ijd_2026 GROUP BY provinsi"
        )
        kemantapan_raw = {_norm_prov_nama(r["provinsi"]): r for r in cur.fetchall()
                          if r["total_km"]}
        cur.execute("SELECT DISTINCT provinsi FROM usulan_inpres ORDER BY provinsi")
        frame = [r["provinsi"] for r in cur.fetchall()]

    # A2: pct ketidakmantapan per provinsi -> skor indeks Tabel 7 -> pangsa nasional
    indeks_ketidakmantapan = {}
    for key, r in kemantapan_raw.items():
        pct = float(r["total_tm"] or 0) / float(r["total_km"]) * 100
        indeks_ketidakmantapan[key] = _skor_indeks_ketidakmantapan(pct)

    total_jalan = sum(jalan.get(_norm_prov_nama(p), 0) for p in frame)
    total_fiskal = sum(_FISKAL_SKOR.get((fiskal.get(_norm_prov_nama(p)) or "").upper(), 0) for p in frame)
    total_indeks = sum(indeks_ketidakmantapan.get(_norm_prov_nama(p), 0) for p in frame)

    provinsi_rows, total_skor = [], 0.0
    for p in frame:
        key = _norm_prov_nama(p)
        km = jalan.get(key)
        f_label = fiskal.get(key)
        f_skor = _FISKAL_SKOR.get((f_label or "").upper())
        idx = indeks_ketidakmantapan.get(key)
        a1 = km / total_jalan * 100 if km and total_jalan else None
        a2 = idx / total_indeks * 100 if idx and total_indeks else None
        a4 = f_skor / total_fiskal * 100 if f_skor and total_fiskal else None
        bobot, nilai = 0.0, 0.0
        if a1 is not None:
            bobot += 20
            nilai += a1 * 20
        if a2 is not None:
            bobot += 30
            nilai += a2 * 30
        if a4 is not None:
            bobot += 15
            nilai += a4 * 15
        skor = nilai / bobot if bobot else None
        pct_tm = (float(kemantapan_raw[key]["total_tm"] or 0) / float(kemantapan_raw[key]["total_km"]) * 100
                  if key in kemantapan_raw else None)
        provinsi_rows.append({
            "provinsi": p,
            "jalan_daerah_km": km,
            "a1_pangsa_pct": round(a1, 3) if a1 is not None else None,
            "tidak_mantap_pct": round(pct_tm, 2) if pct_tm is not None else None,
            "a2_pangsa_pct": round(a2, 3) if a2 is not None else None,
            "kapasitas_fiskal": f_label,
            "a4_pangsa_pct": round(a4, 3) if a4 is not None else None,
            "bobot_tersedia": bobot,
            "skor_pct": round(skor, 3) if skor is not None else None,
        })
        total_skor += skor or 0

    # normalisasi ulang supaya jumlah pangsa = 100% (provinsi tanpa data salah
    # satu komponen tetap proporsional terhadap yang lain)
    for r in provinsi_rows:
        if r["skor_pct"] is not None and total_skor:
            r["pangsa_final_pct"] = round(r["skor_pct"] / total_skor * 100, 3)
            if alokasi_nasional:
                r["pagu_rp"] = round(alokasi_nasional * r["pangsa_final_pct"] / 100)
        else:
            r["pangsa_final_pct"] = None
            if alokasi_nasional:
                r["pagu_rp"] = 0

    provinsi_rows.sort(key=lambda r: -(r["pangsa_final_pct"] or 0))
    return {
        "tahun_data_jalan": "SI 2026 (tahun terbaru di tabel)",
        "alokasi_nasional_rp": alokasi_nasional,
        "provinsi": provinsi_rows,
        "komponen_belum_tersedia": _PAGU_KOMPONEN_PENDING,
        "catatan": (
            "Skor pagu provinsi PARSIAL: komponen A1 panjang jalan daerah (bobot 20), A2 panjang "
            "jalan tidak mantap (bobot 30, dari docs/docs/5_IJD 2026 - DATA.xlsx) dan A4 kapasitas "
            "fiskal (bobot 15) dari 5 komponen dokumen 14072026 — A3 kawasan pangan & A5 IKK masih "
            "kosong; pangsa dinormalisasi ulang ke bobot yang tersedia. Bukan penetapan resmi."
        ),
    }


@app.get("/api/pagu-provinsi")
def pagu_provinsi(alokasi_nasional: Optional[float] = None):
    return _pagu_provinsi(alokasi_nasional)


@app.get("/api/alokasi-2-lapis")
def alokasi_2_lapis(alokasi_nasional: float):
    """Simulasi Metode Alokasi 2 Lapis (dokumen 14072026): Lapis 1 = usulan
    peringkat 1-2 per pemda mengikuti Peringkat Nasional, kumulatif <= pagu
    provinsi; Lapis 2 = sisa pagu untuk pemda yang belum kebagian, lalu
    pengisi celah."""
    pagu = {r["provinsi"]: r.get("pagu_rp") or 0 for r in _pagu_provinsi(alokasi_nasional)["provinsi"]}

    with db_cursor() as cur:
        cur.execute(f"SELECT {_SPN_FIELDS} FROM usulan_inpres WHERE prioritas_kompetensi IS NOT NULL")
        rows = cur.fetchall()
    usulan = []
    for r in rows:
        skor = _skor_prioritas_nasional(r)["skor_total"]
        nilai = r["alokasi_usulan_kompetensi"] or r["alokasi_usulan_pemda"] or 0
        usulan.append({
            "id": r["id"], "provinsi": r["provinsi"], "pemda": r["kabupaten_kota"],
            "nama_ruas": r["nama_ruas"], "skor_total": skor, "nilai_rp": int(nilai),
        })
    usulan.sort(key=lambda x: (-x["skor_total"], x["id"]))
    for i, u in enumerate(usulan, start=1):
        u["peringkat_nasional"] = i

    # peringkat dalam pemda (kunci aturan kualifikasi Lapis 1)
    rank_pemda: dict = {}
    for u in usulan:
        key = (u["provinsi"], u["pemda"])
        rank_pemda[key] = rank_pemda.get(key, 0) + 1
        u["peringkat_pemda"] = rank_pemda[key]

    terpakai = {p: 0 for p in pagu}
    pemda_dapat = set()
    hasil = []

    # Lapis 1
    for u in usulan:
        if u["peringkat_pemda"] > 2 or not u["nilai_rp"]:
            continue
        prov = u["provinsi"]
        if terpakai.get(prov, 0) + u["nilai_rp"] <= pagu.get(prov, 0):
            terpakai[prov] = terpakai.get(prov, 0) + u["nilai_rp"]
            pemda_dapat.add((prov, u["pemda"]))
            u["lapis"] = 1
            hasil.append(u)

    # Lapis 2
    teralokasi_ids = {u["id"] for u in hasil}
    for prov in pagu:
        while True:
            sisa = pagu[prov] - terpakai.get(prov, 0)
            if sisa <= 0:
                break
            kandidat = [u for u in usulan
                        if u["provinsi"] == prov and u["id"] not in teralokasi_ids
                        and 0 < u["nilai_rp"] <= sisa]
            if not kandidat:
                break
            # prioritas pemerataan: pemda yang belum dapat alokasi dulu
            belum = [u for u in kandidat if (prov, u["pemda"]) not in pemda_dapat]
            pilih = min(belum or kandidat, key=lambda x: x["peringkat_nasional"])
            terpakai[prov] += pilih["nilai_rp"]
            pemda_dapat.add((prov, pilih["pemda"]))
            teralokasi_ids.add(pilih["id"])
            pilih["lapis"] = 2
            hasil.append(pilih)

    rekap = []
    for prov in sorted(pagu, key=lambda p: -pagu[p]):
        alloc = [u for u in hasil if u["provinsi"] == prov]
        rekap.append({
            "provinsi": prov,
            "pagu_rp": pagu[prov],
            "terpakai_rp": terpakai.get(prov, 0),
            "sisa_rp": pagu[prov] - terpakai.get(prov, 0),
            "jumlah_usulan": len(alloc),
            "lapis1": sum(1 for u in alloc if u["lapis"] == 1),
            "lapis2": sum(1 for u in alloc if u["lapis"] == 2),
        })

    return {
        "alokasi_nasional_rp": alokasi_nasional,
        "total_teralokasi_rp": sum(terpakai.values()),
        "jumlah_usulan_teralokasi": len(hasil),
        "rekap_provinsi": rekap,
        "alokasi": sorted(hasil, key=lambda x: x["peringkat_nasional"]),
        "catatan": (
            "Simulasi alokasi 2 lapis di atas pagu provinsi PARSIAL (komponen A1+A4 saja) dan "
            "Skor Prioritas Nasional perkiraan — hasil berubah saat komponen pagu/flag prioritas "
            "lain terisi. Bukan penetapan resmi."
        ),
    }


# --- Draf narasi "Output Penilaian" Bappenas per usulan, dihasilkan AI (gap
# G11). Format mengikuti sheet Output Penilaian file 2 (aspek A Prioritas-
# Strategis + aspek B Daya Ungkit, poin 0/1/2 + narasi + kesimpulan); hasil
# di-cache di tabel penilaian_bappenas_ai. SELALU berlabel draf AI. ---

# --- Aspek A "Prioritas & Nilai Strategis" (Bappenas) -- RULE-BASED, bukan
# AI lagi (docs/spec/Draf Penilaian Bappenas.md). Cocokkan usulan ke 11
# kriteria lokus yg sudah punya sumber data: 8 dari bappenas_lokus_a
# (scripts/import_bappenas_lokus_a.py) + 3 dari kawasan_tematik (PKPN/
# TRANSMIGRASI/KI_PRIORITAS, sudah diimpor utk IJD A3 — dipakai ulang di
# sini krn sheet "Kumpulan Data" baris 4/7/14-17 memang bagian Aspek A).
# BBM_1_HARGA belum ada sumber data bersih (lihat catatan di
# import_bappenas_lokus_a.py), tidak dicek. ---

BAPPENAS_KRITERIA_LABEL = {
    "LOKPRI_RPJMN": "Lokasi Prioritas (Lokpri) RPJMN 2025-2029",
    "PKPN": "Kawasan Mendukung PKPN (3T/Tertinggal)",
    "PKSN": "Pusat Kegiatan Strategis Nasional (PKSN) Perbatasan",
    "PERBATASAN": "Kecamatan Perbatasan Prioritas",
    "TRANSMIGRASI": "Kawasan Transmigrasi Prioritas",
    "SR": "Lokasi Sekolah Rakyat (SR)",
    "SEKOLAH_GARUDA": "Lokasi Sekolah Unggul Garuda (SUGB)",
    "KNMP": "Kampung Nelayan Merah Putih (KNMP)",
    "KDMP": "Koperasi Desa Merah Putih (KDMP)",
    "KI_PRIORITAS": "Kawasan Industri Prioritas (PSN/Hilirisasi/RPJMN/Dirgantara)",
    "SWASEMBADA_PANGAN_RPJMN": "Kawasan Komoditas Unggulan Swasembada Pangan RPJMN",
}
_BAPPENAS_KAWASAN_TEMATIK_KATEGORI = ("PKPN", "TRANSMIGRASI", "KI_PRIORITAS")


def _bappenas_kode_kab(row: dict, ctx: dict = None) -> int:
    """kode_kabupaten usulan (kode_kecamatan//1000, fallback wilayah_mapping)
    -- dipakai Aspek A & B. ctx["kab_by_wilayah"] (sama dgn ctx IJD) dipakai
    kalau ada, supaya bulk export tidak query per baris."""
    kode_kec = row.get("kode_kecamatan")
    if kode_kec:
        return kode_kec // 1000
    if ctx and "kab_by_wilayah" in ctx:
        return ctx["kab_by_wilayah"].get((row.get("provinsi"), row.get("kabupaten_kota")))
    with db_cursor() as cur:
        cur.execute(
            "SELECT kode_kabupaten FROM wilayah_mapping "
            "WHERE provinsi_sitia = %s AND kabupaten_kota_sitia = %s",
            (row.get("provinsi"), row.get("kabupaten_kota")),
        )
        r = cur.fetchone()
    return r["kode_kabupaten"] if r else None


def _bappenas_aspek_a_lokus(row: dict, ctx: dict = None) -> dict:
    """Cocokkan usulan ke kriteria lokus Aspek A. Return {"checklist": bool,
    "total_kriteria": int, "kriteria_cocok": [kode,...], "narasi": str}.
    ctx (opsional, dipakai bulk export) — "bappenas_lokus_by_kab"/
    "_by_prov": dict hasil batch dari bappenas_lokus_a; "kawasan_by_kab":
    dict hasil batch dari kawasan_tematik (sama dgn ctx IJD A3)."""
    kode_kec = row.get("kode_kecamatan")
    kode_kab = _bappenas_kode_kab(row, ctx)
    kode_prov = kode_kab // 100 if kode_kab else None

    kriteria_cocok = []
    if ctx and "bappenas_lokus_by_kab" in ctx:
        if kode_kab:
            for r in ctx["bappenas_lokus_by_kab"].get(kode_kab, []):
                if r["level"] == "KABUPATEN" or (r["level"] == "KECAMATAN" and
                                                   (r["kode_kecamatan"] is None or r["kode_kecamatan"] == kode_kec)):
                    kriteria_cocok.append(r["kriteria"])
        if kode_prov:
            kriteria_cocok += ctx["bappenas_lokus_by_prov"].get(kode_prov, [])
    elif kode_kab or kode_prov:
        with db_cursor() as cur:
            cur.execute(
                "SELECT DISTINCT kriteria FROM bappenas_lokus_a WHERE "
                "(level='KABUPATEN' AND kode_kabupaten=%s) OR "
                "(level='KECAMATAN' AND kode_kabupaten=%s AND (kode_kecamatan IS NULL OR kode_kecamatan=%s)) OR "
                "(level='PROVINSI' AND kode_provinsi=%s)",
                (kode_kab, kode_kab, kode_kec, kode_prov),
            )
            kriteria_cocok += [r["kriteria"] for r in cur.fetchall()]

    if kode_kab:
        if ctx and "kawasan_by_kab" in ctx:
            kriteria_cocok += [r["kategori"] for r in ctx["kawasan_by_kab"].get(kode_kab, [])
                                if r["kategori"] in _BAPPENAS_KAWASAN_TEMATIK_KATEGORI
                                and (r["kode_kecamatan"] is None or r["kode_kecamatan"] == kode_kec)]
        else:
            with db_cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT kategori FROM kawasan_tematik WHERE kategori IN %s "
                    "AND kode_kabupaten=%s AND (kode_kecamatan IS NULL OR kode_kecamatan=%s)",
                    (_BAPPENAS_KAWASAN_TEMATIK_KATEGORI, kode_kab, kode_kec),
                )
                kriteria_cocok += [r["kategori"] for r in cur.fetchall()]
    kriteria_cocok = sorted(set(kriteria_cocok))

    # Narasi Aspek A HANYA soal keanggotaan lokus prioritas nasional --
    # potensi produksi (bps_kecamatan_potensi_tematik) itu indikator EKONOMI,
    # sengaja cuma dipakai di Aspek B (_bappenas_aspek_b_ekonomi), bukan di sini.
    kriteria_label = [BAPPENAS_KRITERIA_LABEL.get(k, k) for k in kriteria_cocok]
    # Checklist eksplisit atas SELURUH 11 kriteria (bukan cuma yang cocok) --
    # "kolom AG jika salah satu ada maka check list" (docs/spec/Draf Penilaian
    # Bappenas.md) diminta ditampilkan sebagai daftar centang/silang, plus
    # keterangan naratif terpisah di bawahnya.
    checklist_lines = [
        f"{'[v]' if kode in kriteria_cocok else '[ ]'} {label}"
        for kode, label in BAPPENAS_KRITERIA_LABEL.items()
    ]
    if kriteria_label:
        keterangan = (
            f"Usulan berada di lokasi yang termasuk {len(kriteria_label)} kriteria prioritas nasional: "
            + "; ".join(kriteria_label) + "."
        )
    else:
        keterangan = "Usulan tidak terindikasi berada di lokasi kriteria prioritas nasional manapun dari data yang tersedia."
    narasi = "\n".join(checklist_lines) + "\n\nKeterangan: " + keterangan

    return {
        "checklist": len(kriteria_cocok) > 0,
        "total_kriteria": len(kriteria_cocok),
        "kriteria_cocok": kriteria_cocok,
        "checklist_lines": checklist_lines,
        "keterangan": keterangan,
        "narasi": narasi,
    }


# --- Aspek B "Daya Ungkit Ekonomi & Kinerja Sektoral" (Bappenas) -- RULE-BASED
# juga, sama seperti Aspek A (docs/spec/Draf Penilaian Bappenas.md, minta baca
# baris 20-43 sheet Kumpulan Data, bagian "PENILAIAN RUAS"). 9 indikator yang
# sudah punya sumber data di aplikasi ini dicek; sisanya (Tata Guna Lahan,
# Indeks Penanaman, SHP Jaringan Jalan/Simpul Transportasi, KP2B/LP2B,
# Penuntasan Koridor OneDrive) belum ada sumber bersih -- tidak dicek. ---

BAPPENAS_ASPEK_B_INDIKATOR_LABEL = {
    "PENDUDUK": "Jumlah penduduk kecamatan (baris 20)",
    "SWASEMBADA_PANGAN_LOKUS": "Lokus Swasembada Pangan (baris 23)",
    "PERKEBUNAN": "Kawasan Perkebunan (baris 24)",
    "PERIKANAN": "Kawasan Kelautan & Perikanan (baris 22)",
    "PRODUKSI_PERTANIAN": "Produksi Padi/Jagung (baris 25)",
    "PRODUKSI_PERKEBUNAN": "Produksi Kelapa Sawit/Kelapa/Tebu/Karet (baris 26)",
    "PRODUKSI_PETERNAKAN": "Produktivitas Peternakan (baris 27)",
    "PRODUKSI_PERIKANAN": "Produktivitas Perikanan tangkap (baris 28)",
    "KI_PRIORITAS": "Konektivitas Kawasan Industri/KEK (baris 33-36)",
    "KEMANTAPAN_JALAN": "Kemantapan Jalan IJD (baris 39)",
    "KENDARAAN": "Jumlah Kendaraan kecamatan (baris 40)",
    "KEBERLANJUTAN_IJD": "Keberlanjutan Kegiatan IJD (baris 42)",
}


def _bappenas_aspek_b_ekonomi(row: dict, ctx: dict = None) -> dict:
    """12 indikator Daya Ungkit Ekonomi & Kinerja Sektoral yg sudah punya
    sumber data. Return {"checklist": bool, "total_indikator": int,
    "indikator_ada": [kode,...], "narasi": str}. ctx (opsional, bulk export)
    — reuse "kawasan_by_kab"/"bappenas_lokus_by_kab" dari Aspek A,
    "kepadatan_by_kec" (sama dgn ctx IJD C/A3 — kalau sudah di-extend
    dgn jumlah_penduduk/kendaraan_total/kolom bps_* di caller),
    "potensi_produksi_by_kec" (angka produksi riil dari
    bps_kecamatan_potensi_tematik, dipakai memperkonkret keterangan --
    checklist indikator PRODUKSI_* tetap dari flag ada/tidak di
    kepadatan_by_kec, bukan dari sini) dan "kemantapan_kab_set" (set
    kode_kab yg punya baris Kab./Kota)."""
    kode_kec = row.get("kode_kecamatan")
    kode_kab = _bappenas_kode_kab(row, ctx)

    indikator = []
    penduduk_n = kendaraan_n = None

    # baris 22/24/33-36: kawasan_tematik
    if kode_kab:
        if ctx and "kawasan_by_kab" in ctx:
            indikator += [r["kategori"] for r in ctx["kawasan_by_kab"].get(kode_kab, [])
                          if r["kategori"] in ("PERKEBUNAN", "PERIKANAN", "KI_PRIORITAS")
                          and (r["kode_kecamatan"] is None or r["kode_kecamatan"] == kode_kec)]
        else:
            with db_cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT kategori FROM kawasan_tematik WHERE kategori IN "
                    "('PERKEBUNAN','PERIKANAN','KI_PRIORITAS') AND kode_kabupaten=%s "
                    "AND (kode_kecamatan IS NULL OR kode_kecamatan=%s)",
                    (kode_kab, kode_kec),
                )
                indikator += [r["kategori"] for r in cur.fetchall()]

    # baris 23: bappenas_lokus_a SWASEMBADA_PANGAN_LOKUS
    if kode_kab:
        if ctx and "bappenas_lokus_by_kab" in ctx:
            if any(r["kriteria"] == "SWASEMBADA_PANGAN_LOKUS" for r in ctx["bappenas_lokus_by_kab"].get(kode_kab, [])):
                indikator.append("SWASEMBADA_PANGAN_LOKUS")
        else:
            with db_cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM bappenas_lokus_a WHERE kriteria='SWASEMBADA_PANGAN_LOKUS' "
                    "AND kode_kabupaten=%s LIMIT 1",
                    (kode_kab,),
                )
                if cur.fetchone():
                    indikator.append("SWASEMBADA_PANGAN_LOKUS")

    # baris 20/25-28/40: kecamatan_data_turunan + bps_kecamatan_potensi_tematik
    if kode_kec:
        if ctx and "kepadatan_by_kec" in ctx:
            kdt = ctx["kepadatan_by_kec"].get(kode_kec)
        else:
            with db_cursor() as cur:
                cur.execute(
                    "SELECT jumlah_penduduk, kendaraan_total, potensi_pertanian, potensi_perkebunan, "
                    "potensi_peternakan, potensi_perikanan FROM kecamatan_data_turunan "
                    "WHERE kode_kecamatan=%s ORDER BY tahun DESC LIMIT 1",
                    (kode_kec,),
                )
                kdt = cur.fetchone()
        if kdt:
            penduduk_n = kdt.get("jumlah_penduduk")
            kendaraan_n = kdt.get("kendaraan_total")
            if penduduk_n:
                indikator.append("PENDUDUK")
            if kendaraan_n:
                indikator.append("KENDARAAN")
            if kdt.get("potensi_pertanian"):
                indikator.append("PRODUKSI_PERTANIAN")
            if kdt.get("potensi_perkebunan"):
                indikator.append("PRODUKSI_PERKEBUNAN")
            if kdt.get("potensi_peternakan"):
                indikator.append("PRODUKSI_PETERNAKAN")
            if kdt.get("potensi_perikanan"):
                indikator.append("PRODUKSI_PERIKANAN")

    # Angka produksi riil (bukan sekadar flag ada/tidak di atas) --
    # bps_kecamatan_potensi_tematik, dipakai utk memperkonkret keterangan di
    # bawah (bukan komponen checklist tambahan; checklist tetap dari flag
    # potensi_* kecamatan_data_turunan supaya tidak dobel-hitung).
    produksi = None
    if kode_kec:
        if ctx and "potensi_produksi_by_kec" in ctx:
            produksi = ctx["potensi_produksi_by_kec"].get(kode_kec)
        else:
            with db_cursor() as cur:
                cur.execute(
                    "SELECT pertanian_produksi_ton, perkebunan_produksi_ton, "
                    "peternakan_produksi_daging_kg, peternakan_produksi_telur_kg, "
                    "perikanan_produksi_ton FROM bps_kecamatan_potensi_tematik "
                    "WHERE kode_kecamatan=%s ORDER BY tahun DESC LIMIT 1",
                    (kode_kec,),
                )
                produksi = cur.fetchone()

    # baris 39: kemantapan_ijd_2026 (level kab/kota)
    if kode_kab:
        if ctx and "kemantapan_kab_set" in ctx:
            if kode_kab in ctx["kemantapan_kab_set"]:
                indikator.append("KEMANTAPAN_JALAN")
        else:
            with db_cursor() as cur:
                cur.execute(
                    "SELECT mantap_pct FROM kemantapan_ijd_2026 WHERE kode_wilayah=%s "
                    "AND jenis_adm IN ('Kab.','Kota') LIMIT 1",
                    (kode_kab,),
                )
                if cur.fetchone():
                    indikator.append("KEMANTAPAN_JALAN")

    # baris 42: keberlanjutan IJD (flag resmi kompetensi atau pencocokan DPP 2025)
    if (row.get("penuntasan_ijd_kompetensi") or "").strip().upper() == "YA" or row.get("lanjutan_ijd_2025"):
        indikator.append("KEBERLANJUTAN_IJD")

    indikator = sorted(set(indikator))
    indikator_label = [BAPPENAS_ASPEK_B_INDIKATOR_LABEL.get(k, k) for k in indikator]
    # Checklist eksplisit atas SELURUH 12 indikator (bukan cuma yang ada),
    # sama pola dengan Aspek A -- lihat _bappenas_aspek_a_lokus.
    checklist_lines = [
        f"{'[v]' if kode in indikator else '[ ]'} {label}"
        for kode, label in BAPPENAS_ASPEK_B_INDIKATOR_LABEL.items()
    ]

    keterangan_parts = []
    if indikator_label:
        keterangan_parts.append(
            f"Ditemukan {len(indikator_label)} indikator daya ungkit ekonomi/sektoral yang didukung data: "
            + "; ".join(indikator_label) + "."
        )
    else:
        keterangan_parts.append("Belum ada indikator daya ungkit ekonomi/sektoral yang didukung data untuk lokasi usulan ini.")
    if penduduk_n:
        keterangan_parts.append(f"Jumlah penduduk kecamatan: {penduduk_n:,} jiwa.".replace(",", "."))
    if kendaraan_n:
        keterangan_parts.append(f"Jumlah kendaraan kecamatan: {kendaraan_n:,} unit.".replace(",", "."))
    if produksi:
        def _fmt(n):
            return f"{n:,.0f}".replace(",", ".")
        if produksi.get("pertanian_produksi_ton"):
            keterangan_parts.append(f"Produksi padi & jagung kecamatan: {_fmt(produksi['pertanian_produksi_ton'])} ton.")
        if produksi.get("perkebunan_produksi_ton"):
            keterangan_parts.append(
                f"Produksi perkebunan (kelapa sawit/kelapa/karet/tebu) kecamatan: "
                f"{_fmt(produksi['perkebunan_produksi_ton'])} ton."
            )
        if produksi.get("peternakan_produksi_daging_kg"):
            keterangan_parts.append(f"Produksi daging ternak kecamatan: {_fmt(produksi['peternakan_produksi_daging_kg'])} kg.")
        if produksi.get("peternakan_produksi_telur_kg"):
            keterangan_parts.append(f"Produksi telur kecamatan: {_fmt(produksi['peternakan_produksi_telur_kg'])} kg.")
        if produksi.get("perikanan_produksi_ton"):
            keterangan_parts.append(f"Produksi perikanan tangkap kecamatan: {_fmt(produksi['perikanan_produksi_ton'])} ton.")
    keterangan = " ".join(keterangan_parts)
    narasi = "\n".join(checklist_lines) + "\n\nKeterangan: " + keterangan

    return {
        "checklist": len(indikator) > 0,
        "total_indikator": len(indikator),
        "indikator_ada": indikator,
        "checklist_lines": checklist_lines,
        "keterangan": keterangan,
        "narasi": narasi,
    }


PENILAIAN_SYSTEM_PROMPT = """Anda membantu analis Bappenas menyusun DRAF penilaian kualitatif usulan \
Inpres Jalan Daerah. Aspek A (Prioritas & Nilai Strategis) dan Aspek B (Daya Ungkit Ekonomi & Kinerja \
Sektoral) SUDAH DIHITUNG SISTEM (rule-based, bukan tugas Anda menilai ulang) — masing-masing berupa daftar \
kriteria/indikator yang cocok/ada berdasarkan data lokasi usulan. Field "aspek_a_hasil" dan "aspek_b_hasil" \
pada data yang diberikan berisi hasil itu.

Tugas Anda menyusun DUA teks:
1. "kesimpulan": integrasi naratif 2-3 kalimat dari aspek_a_hasil DAN aspek_b_hasil APA ADANYA.
2. "aspek_b_narasi_ai": narasi PELENGKAP khusus Aspek B (Daya Ungkit Ekonomi & Kinerja Sektoral) saja —
   gaya laporan kebijakan yang mengalir dan meyakinkan, BUKAN daftar/enumerasi kaku bergaya "Ditemukan N
   indikator: ...; ...". WAJIB menyinggung SETIAP indikator di aspek_b_hasil["indikator_ada"] — jangan
   diam-diam melewati sebagian demi keringkasan; kalau indikatornya banyak (>4), gunakan lebih banyak
   kalimat (boleh sampai 8-10) supaya semua kebagian tempat, dikelompokkan per tema (mis. produksi pangan
   dijadikan satu kalimat, konektivitas/lalu lintas kalimat lain) alih-alih satu kalimat generik per
   indikator. Rangkai jadi cerita dampak ekonomi/sektoral ruas ini (ketahanan pangan, kelancaran logistik,
   pertumbuhan ekonomi lokal — sesuai definisi Aspek B), sertakan angka konkret dari data bila ada. Bila
   indikator_ada kosong, nyatakan dengan jujur belum ada indikator yang didukung data, jangan dibuat seolah ada.

Kedua teks WAJIB berbasis fakta di aspek_a_hasil/aspek_b_hasil APA ADANYA — jangan mengarang fakta di luar \
itu, jangan menilai ulang atau mengubah checklist/poin yang sudah diberikan. Sebut secara ringkas kriteria/\
indikator utama yang mendukung (atau ketiadaannya bila kosong).

Balas HANYA JSON valid tanpa teks lain, format:
{"kesimpulan": "...", "aspek_b_narasi_ai": "..."}
Bahasa Indonesia formal, sebut angka/kriteria dari data bila relevan."""


def _plain_openai_compatible(url: str, key: str, model: str, system: str, user: str, max_tokens: int = 2048) -> str:
    resp = requests.post(
        url, headers={"Authorization": f"Bearer {key}"},
        json={"model": model, "temperature": 0.4, "max_tokens": max_tokens,
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user}]},
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _plain_claude(key: str, system: str, user: str, max_tokens: int = 2048) -> str:
    client = anthropic.Anthropic(api_key=key)
    resp = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def _plain_gemini(key: str, system: str, user: str, max_tokens: int = 2048) -> str:
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={key}",
        json={"system_instruction": {"parts": [{"text": system}]},
              "contents": [{"parts": [{"text": user}]}],
              "generationConfig": {"maxOutputTokens": max_tokens}},
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def _llm_plain(system: str, user: str, max_tokens: int = 2048) -> tuple:
    """Satu completion polos (tanpa tools) lewat provider pertama yang
    tersedia — urutan sama dengan _chat_providers. Return (provider, model, teks).
    max_tokens dinaikkan oleh pemanggil yang outputnya panjang (narasi bulk)."""
    attempts = []
    if os.getenv("GROQ_API_KEY"):
        attempts.append(("Groq", GROQ_MODEL, lambda: _plain_openai_compatible(GROQ_API_URL, os.getenv("GROQ_API_KEY"), GROQ_MODEL, system, user, max_tokens)))
    if os.getenv("GROK_API_KEY"):
        attempts.append(("Grok", GROK_MODEL, lambda: _plain_openai_compatible(GROK_API_URL, os.getenv("GROK_API_KEY"), GROK_MODEL, system, user, max_tokens)))
    if os.getenv("OPEN_AI_API_KEY"):
        attempts.append(("OpenAI", OPENAI_MODEL, lambda: _plain_openai_compatible("https://api.openai.com/v1/chat/completions", os.getenv("OPEN_AI_API_KEY"), OPENAI_MODEL, system, user, max_tokens)))
    if os.getenv("CLOUDE_API_KEY"):
        attempts.append(("Claude", CLAUDE_MODEL, lambda: _plain_claude(os.getenv("CLOUDE_API_KEY"), system, user, max_tokens)))
    if os.getenv("GEMINI_API_KEY"):
        attempts.append(("Gemini", GEMINI_MODEL, lambda: _plain_gemini(os.getenv("GEMINI_API_KEY"), system, user, max_tokens)))
    if not attempts:
        raise HTTPException(500, "Tidak ada API key LLM di .env (GROQ/GROK/OPEN_AI/CLOUDE/GEMINI_API_KEY).")
    errors = []
    for provider, model, fn in attempts:
        try:
            return provider, model, fn()
        except Exception as e:  # coba provider berikutnya
            errors.append(f"{provider}: {e}")
    raise HTTPException(502, "Semua provider LLM gagal — " + "; ".join(errors))


_PENILAIAN_SCHEMA_PATH = BASE_DIR / "scripts" / "schema_penilaian_bappenas.sql"
_penilaian_table_ready = False


def _ensure_penilaian_table():
    global _penilaian_table_ready
    if _penilaian_table_ready:
        return
    sql_text = _PENILAIAN_SCHEMA_PATH.read_text(encoding="utf-8")
    code = "\n".join(l for l in sql_text.splitlines() if not l.strip().startswith("--"))
    with db_cursor() as cur:
        for stmt in [s.strip() for s in code.split(";") if s.strip()]:
            cur.execute(stmt)
        # kolom aspek_a_checklist/aspek_a_total_kriteria ditambahkan belakangan
        # (aspek A jadi rule-based) -- CREATE TABLE IF NOT EXISTS di atas tidak
        # menambah kolom ke tabel yang sudah ada.
        cur.execute(
            "SELECT COUNT(*) n FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'penilaian_bappenas_ai' "
            "AND column_name = 'aspek_a_checklist'"
        )
        if cur.fetchone()["n"] == 0:
            cur.execute(
                "ALTER TABLE penilaian_bappenas_ai "
                "ADD COLUMN aspek_a_checklist TINYINT(1) NULL, "
                "ADD COLUMN aspek_a_total_kriteria TINYINT UNSIGNED NULL"
            )
        # kolom aspek_b_checklist/aspek_b_total_indikator ditambahkan belakangan
        # (aspek B jadi rule-based juga) -- sama alasan seperti di atas.
        cur.execute(
            "SELECT COUNT(*) n FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'penilaian_bappenas_ai' "
            "AND column_name = 'aspek_b_checklist'"
        )
        if cur.fetchone()["n"] == 0:
            cur.execute(
                "ALTER TABLE penilaian_bappenas_ai "
                "ADD COLUMN aspek_b_checklist TINYINT(1) NULL, "
                "ADD COLUMN aspek_b_total_indikator TINYINT UNSIGNED NULL"
            )
        # aspek_b_narasi_ai: narasi naratif/persuasif hasil AI, PELENGKAP
        # aspek_b_narasi (checklist rule-based) -- bukan pengganti. Digenerate
        # bareng kesimpulan lewat POST .../penilaian-bappenas, di-cache di sini
        # supaya bulk export bisa reuse tanpa panggil LLM ribuan kali.
        cur.execute(
            "SELECT COUNT(*) n FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'penilaian_bappenas_ai' "
            "AND column_name = 'aspek_b_narasi_ai'"
        )
        if cur.fetchone()["n"] == 0:
            cur.execute(
                "ALTER TABLE penilaian_bappenas_ai ADD COLUMN aspek_b_narasi_ai TEXT NULL"
            )
    _penilaian_table_ready = True


def _penilaian_context(row: dict, aspek_a_hasil: dict, aspek_b_hasil: dict) -> str:
    """Ringkasan data usulan (JSON) yang jadi satu-satunya bahan penilaian AI
    (skr cuma "kesimpulan" — aspek_a & aspek_b dihitung rule-based, lihat
    _bappenas_aspek_a_lokus/_bappenas_aspek_b_ekonomi, disisipkan APA ADANYA
    sbg fakta given)."""
    ijd = _compute_ijd_score(row, 2026)
    spn = _skor_prioritas_nasional(row)
    data = {
        "aspek_a_hasil": aspek_a_hasil,
        "aspek_b_hasil": aspek_b_hasil,
        "usulan": {k: row.get(k) for k in (
            "id", "nama_kegiatan", "nama_ruas", "provinsi", "kabupaten_kota",
            "jenis_penanganan", "status_ruas", "panjang_ruas_km", "panjang_penanganan_pemda",
            "alokasi_usulan_pemda", "alokasi_usulan_kompetensi", "kapasitas_fiskal",
            "tematik_kawasan_pemda", "kondisi_baik_km", "kondisi_sedang_km",
            "kondisi_ringan_km", "kondisi_berat_km", "verifikasi_balai",
            "verifikasi_kompetensi", "prioritas_balai", "prioritas_kompetensi",
            "status_koridor_balai", "penuntasan_ijd_kompetensi", "lanjutan_ijd_2025",
            "jenis_data_dukung_tematik_kompetensi", "indikasi_prioritas_pu",
        )},
        "skor_teknokratik_ijd_2026": {
            "skor_ternormalisasi_100": ijd["skor_ternormalisasi_100"],
            "komponen": [{k: c.get(k) for k in ("kode", "label", "tersedia", "nilai", "keterangan")}
                         for c in ijd["komponen"]],
        },
        "skor_prioritas_nasional": {
            "total": spn["skor_total"],
            "komponen": [{k: c.get(k) for k in ("kode", "label", "nilai", "keterangan")}
                         for c in spn["komponen"]],
        },
    }
    return json.dumps(jsonable_encoder(data), ensure_ascii=False)


@app.get("/api/usulan-inpres/{usulan_id}/penilaian-bappenas")
def penilaian_bappenas_get(usulan_id: int):
    _ensure_penilaian_table()
    with db_cursor() as cur:
        cur.execute("SELECT * FROM penilaian_bappenas_ai WHERE usulan_id = %s", (usulan_id,))
        row = cur.fetchone()
    if not row:
        return {"tersedia": False}
    row["tersedia"] = True
    return jsonable_encoder(row)


def _bappenas_poin_from_total(total: int) -> int:
    """0/1/2 dari jumlah kriteria/indikator yang cocok/ada -- 0=tidak ada,
    1=1-2 cocok, 2=>=3 cocok. Dipakai Aspek A & B (sama-sama rule-based)."""
    if total <= 0:
        return 0
    return 2 if total >= 3 else 1


@app.post("/api/usulan-inpres/{usulan_id}/penilaian-bappenas")
def penilaian_bappenas_generate(usulan_id: int):
    _ensure_penilaian_table()
    with db_cursor() as cur:
        cur.execute("SELECT * FROM usulan_inpres WHERE id = %s", (usulan_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Usulan tidak ditemukan")

    aspek_a_hasil = _bappenas_aspek_a_lokus(row)
    aspek_b_hasil = _bappenas_aspek_b_ekonomi(row)
    poin_a = _bappenas_poin_from_total(aspek_a_hasil["total_kriteria"])
    poin_b = _bappenas_poin_from_total(aspek_b_hasil["total_indikator"])

    provider, model, teks = _llm_plain(
        PENILAIAN_SYSTEM_PROMPT, _penilaian_context(row, aspek_a_hasil, aspek_b_hasil)
    )
    teks = re.sub(r"^```(?:json)?\s*|\s*```$", "", teks.strip())
    try:
        hasil = json.loads(teks)
        kesimpulan = hasil["kesimpulan"]
        aspek_b_narasi_ai = hasil.get("aspek_b_narasi_ai")
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(502, f"Jawaban {provider} tidak sesuai format JSON penilaian: {e}")

    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO penilaian_bappenas_ai (usulan_id, aspek_a_poin, aspek_a_checklist, "
            "aspek_a_total_kriteria, aspek_a_narasi, aspek_b_poin, aspek_b_checklist, "
            "aspek_b_total_indikator, aspek_b_narasi, aspek_b_narasi_ai, total_poin, kesimpulan, "
            "provider, model) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE aspek_a_poin=VALUES(aspek_a_poin), "
            "aspek_a_checklist=VALUES(aspek_a_checklist), aspek_a_total_kriteria=VALUES(aspek_a_total_kriteria), "
            "aspek_a_narasi=VALUES(aspek_a_narasi), aspek_b_poin=VALUES(aspek_b_poin), "
            "aspek_b_checklist=VALUES(aspek_b_checklist), aspek_b_total_indikator=VALUES(aspek_b_total_indikator), "
            "aspek_b_narasi=VALUES(aspek_b_narasi), aspek_b_narasi_ai=VALUES(aspek_b_narasi_ai), "
            "total_poin=VALUES(total_poin), "
            "kesimpulan=VALUES(kesimpulan), provider=VALUES(provider), model=VALUES(model)",
            (usulan_id, poin_a, aspek_a_hasil["checklist"], aspek_a_hasil["total_kriteria"],
             aspek_a_hasil["narasi"], poin_b, aspek_b_hasil["checklist"], aspek_b_hasil["total_indikator"],
             aspek_b_hasil["narasi"], aspek_b_narasi_ai, poin_a + poin_b, kesimpulan, provider, model),
        )
    _ijd_bulk_cache.clear()  # kesimpulan/narasi AI baru -> preview & export xlsx kadaluarsa
    return penilaian_bappenas_get(usulan_id)


PENILAIAN_BULK_SYSTEM_PROMPT = """Anda membantu analis Bappenas menyusun DRAF narasi Aspek B (Daya Ungkit \
Ekonomi & Kinerja Sektoral) untuk BEBERAPA usulan Inpres Jalan Daerah sekaligus. Untuk SETIAP usulan pada \
data JSON yang diberikan, susun narasi gaya laporan kebijakan yang mengalir dan meyakinkan — BUKAN \
enumerasi kaku bergaya "Ditemukan N indikator: ...; ...". Narasi WAJIB menyinggung SETIAP indikator di \
"indikator_ada" — jangan diam-diam melewati sebagian demi keringkasan; kalau indikatornya banyak (>4), \
pakai lebih banyak kalimat (boleh sampai 8-10) supaya semua kebagian tempat, dikelompokkan per tema (mis. \
produksi pangan jadi satu kalimat, konektivitas/lalu lintas kalimat lain) alih-alih satu kalimat generik \
per indikator. Rangkai indikator beserta angka konkret pada "fakta" menjadi cerita dampak ekonomi/sektoral \
ruas tersebut (ketahanan pangan, kelancaran logistik, pertumbuhan ekonomi lokal). "fakta" berisi \
"ringkasan_indikator" plus data BPS pendukung: "demografi_kecamatan_bps" (level kecamatan) serta \
"padi_kabupaten_bps" dan "kendaraan_kabupaten_bps" (level KABUPATEN/KOTA — bila disebut, WAJIB \
diatribusikan ke kabupaten/kota, jangan ditulis seolah angka kecamatan atau ruas). Sebut nama kegiatan/\
koridor, wilayah, dan angka dari data bila relevan.

WAJIB berbasis fakta yang diberikan APA ADANYA — jangan mengarang angka atau fakta di luar data. Bila \
"indikator_ada" sebuah usulan kosong, nyatakan jujur belum ada indikator daya ungkit yang didukung data \
untuk lokasi itu, jangan dibuat seolah ada.

Balas HANYA JSON valid tanpa teks lain, format:
[{"id": <id usulan>, "narasi": "..."}, ...]
— satu objek per usulan, "id" disalin apa adanya dari data. Bahasa Indonesia formal."""

# Usulan per panggilan LLM — model diminta membalas array JSON satu objek per
# usulan, lalu di-upsert per baris. Narasi kini wajib menyinggung SEMUA
# indikator_ada (bisa sampai 8-10 kalimat utk usulan dgn banyak indikator,
# bukan 3-5 lagi) -- batch diperkecil dari 30 ke 20 supaya total token
# output per panggilan LLM tetap wajar di bawah max_tokens (lihat
# _PENILAIAN_BULK_MAX_TOKENS) tanpa mengubah max_tokens setinggi mungkin
# risiko melewati batas keras sebagian provider.
_PENILAIAN_BULK_BATCH = 20
_PENILAIAN_BULK_MAX_TOKENS = 8192


def _bappenas_fakta_pendukung(row: dict, aspek_b: dict) -> dict:
    """Data pendukung BPS untuk narasi AI Aspek B (bulk) — melengkapi
    aspek_b["keterangan"] (yang sudah memuat angka kecamatan_data_turunan +
    bps_kecamatan_potensi_tematik) dengan angka level kecamatan
    (penduduk_kecamatan, bps_kecamatan_demografi) dan level kabupaten
    (bps_kabupaten_padi, bps_kabupaten_kendaraan). Nilai yang tidak tersedia
    dihilangkan dari dict supaya prompt tetap ringkas. Cakupan bps_* mengikuti
    isi dalam_angka/ (parsial per provinsi) — tidak apa-apa kosong."""
    kode_kec = row.get("kode_kecamatan")
    kode_kab = _bappenas_kode_kab(row)
    fakta = {"ringkasan_indikator": aspek_b["keterangan"]}

    nama_kec = None
    if kode_kec:
        with db_cursor() as cur:
            cur.execute(
                "SELECT kecamatan FROM penduduk_kecamatan "
                "WHERE kode_kecamatan=%s ORDER BY tahun DESC LIMIT 1",
                (kode_kec,),
            )
            pk = cur.fetchone()
        if pk:
            nama_kec = pk["kecamatan"]
            fakta["kecamatan"] = nama_kec
    # bps_kecamatan_demografi tidak punya kode_kecamatan — dicocokkan lewat
    # kode_kab + nama kecamatan master; gagal cocok = lewati saja (best-effort).
    if kode_kab and nama_kec:
        with db_cursor() as cur:
            cur.execute(
                "SELECT tahun, jumlah_penduduk, laju_pertumbuhan_pct, kepadatan_per_km2, "
                "rasio_jenis_kelamin FROM bps_kecamatan_demografi "
                "WHERE kode_kab=%s AND UPPER(kecamatan)=UPPER(%s) ORDER BY tahun DESC LIMIT 1",
                (str(kode_kab), nama_kec),
            )
            demo = cur.fetchone()
        if demo:
            fakta["demografi_kecamatan_bps"] = {k: v for k, v in demo.items() if v is not None}
    if kode_kab:
        with db_cursor() as cur:
            cur.execute(
                "SELECT tahun, luas_panen_ha, produktivitas_ku_ha, produksi_ton "
                "FROM bps_kabupaten_padi WHERE kode_kab=%s ORDER BY tahun DESC LIMIT 1",
                (str(kode_kab),),
            )
            padi = cur.fetchone()
            cur.execute(
                "SELECT tahun, mobil_penumpang, bus, mobil_barang, sepeda_motor, jumlah "
                "FROM bps_kabupaten_kendaraan WHERE kode_kab=%s ORDER BY tahun DESC LIMIT 1",
                (str(kode_kab),),
            )
            kendaraan = cur.fetchone()
        if padi:
            fakta["padi_kabupaten_bps"] = {k: v for k, v in padi.items() if v is not None}
        if kendaraan:
            fakta["kendaraan_kabupaten_bps"] = {k: v for k, v in kendaraan.items() if v is not None}
    return fakta


@app.post("/api/usulan-inpres/penilaian-bappenas/bulk")
def penilaian_bappenas_bulk(provinsi: str = ""):
    """Generate narasi AI Aspek B massal — SATU batch (<= _PENILAIAN_BULK_BATCH
    usulan, satu panggilan LLM) per request; frontend memanggil berulang sampai
    sisa=0 supaya ada progres dan request tidak kena timeout. SENGAJA hanya
    per provinsi (bukan nasional) supaya pemakaian kuota LLM terkendali.
    Usulan yang sudah punya aspek_b_narasi_ai dilewati (resume-able, tidak
    menimpa). Aspek A/B rule-based ikut di-upsert supaya panel detail tetap
    utuh; "kesimpulan" TETAP hanya digenerate per-usulan lewat
    POST /api/usulan-inpres/{id}/penilaian-bappenas."""
    provinsi = (provinsi or "").strip()
    if not provinsi:
        raise HTTPException(400, "Proses bulk narasi AI hanya bisa per provinsi — pilih filter provinsi dulu.")
    _ensure_penilaian_table()
    with db_cursor() as cur:
        cur.execute(
            "SELECT u.* FROM usulan_inpres u "
            "LEFT JOIN penilaian_bappenas_ai p ON p.usulan_id = u.id "
            "WHERE u.provinsi = %s AND (p.aspek_b_narasi_ai IS NULL OR p.aspek_b_narasi_ai = '') "
            "ORDER BY u.id",
            (provinsi,),
        )
        pending = cur.fetchall()
    if not pending:
        return {"diproses": 0, "sisa": 0, "provinsi": provinsi}

    rows = pending[:_PENILAIAN_BULK_BATCH]
    hasil = {}
    payload = []
    for row in rows:
        aspek_a = _bappenas_aspek_a_lokus(row)
        aspek_b = _bappenas_aspek_b_ekonomi(row)
        hasil[row["id"]] = (aspek_a, aspek_b)
        payload.append({
            "id": row["id"],
            "nama_kegiatan": row.get("nama_kegiatan"),
            "nama_koridor": row.get("nama_koridor"),
            "provinsi": row.get("provinsi"),
            "kabupaten_kota": row.get("kabupaten_kota"),
            "jenis_penanganan": row.get("jenis_penanganan"),
            "panjang_penanganan_km": row.get("panjang_penanganan_pemda"),
            "indikator_ada": [BAPPENAS_ASPEK_B_INDIKATOR_LABEL.get(k, k) for k in aspek_b["indikator_ada"]],
            "fakta": _bappenas_fakta_pendukung(row, aspek_b),
        })

    provider, model, teks = _llm_plain(
        PENILAIAN_BULK_SYSTEM_PROMPT, json.dumps(jsonable_encoder(payload), ensure_ascii=False),
        max_tokens=_PENILAIAN_BULK_MAX_TOKENS,
    )
    teks = re.sub(r"^```(?:json)?\s*|\s*```$", "", teks.strip())
    try:
        narasi_by_id = {int(item["id"]): (item.get("narasi") or "").strip()
                        for item in json.loads(teks)}
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(502, f"Jawaban {provider} tidak sesuai format JSON narasi bulk: {e}")

    diproses = 0
    with db_cursor() as cur:
        for row in rows:
            narasi = narasi_by_id.get(row["id"])
            if not narasi:
                continue  # id tidak dijawab model — dicoba ulang di batch berikutnya
            aspek_a, aspek_b = hasil[row["id"]]
            poin_a = _bappenas_poin_from_total(aspek_a["total_kriteria"])
            poin_b = _bappenas_poin_from_total(aspek_b["total_indikator"])
            # kesimpulan sengaja TIDAK disentuh (kolom per-usulan, lihat docstring)
            cur.execute(
                "INSERT INTO penilaian_bappenas_ai (usulan_id, aspek_a_poin, aspek_a_checklist, "
                "aspek_a_total_kriteria, aspek_a_narasi, aspek_b_poin, aspek_b_checklist, "
                "aspek_b_total_indikator, aspek_b_narasi, aspek_b_narasi_ai, total_poin, provider, model) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE aspek_a_poin=VALUES(aspek_a_poin), "
                "aspek_a_checklist=VALUES(aspek_a_checklist), aspek_a_total_kriteria=VALUES(aspek_a_total_kriteria), "
                "aspek_a_narasi=VALUES(aspek_a_narasi), aspek_b_poin=VALUES(aspek_b_poin), "
                "aspek_b_checklist=VALUES(aspek_b_checklist), aspek_b_total_indikator=VALUES(aspek_b_total_indikator), "
                "aspek_b_narasi=VALUES(aspek_b_narasi), aspek_b_narasi_ai=VALUES(aspek_b_narasi_ai), "
                "total_poin=VALUES(total_poin), provider=VALUES(provider), model=VALUES(model)",
                (row["id"], poin_a, aspek_a["checklist"], aspek_a["total_kriteria"], aspek_a["narasi"],
                 poin_b, aspek_b["checklist"], aspek_b["total_indikator"], aspek_b["narasi"],
                 narasi, poin_a + poin_b, provider, model),
            )
            diproses += 1
    if diproses == 0:
        # lindungi frontend dari loop tak berujung kalau model menjawab tapi id-nya salah semua
        raise HTTPException(502, f"{provider} menjawab, tetapi tidak ada narasi valid untuk batch ini.")
    _ijd_bulk_cache.clear()  # narasi AI baru -> preview & export xlsx kadaluarsa
    return {"diproses": diproses, "sisa": len(pending) - diproses,
            "provider": provider, "model": model, "provinsi": provinsi}


_KML_COORD_RE = re.compile(
    r"<(?:LineString|Point|Polygon)\b[^>]*>.*?<coordinates>\s*([^<]+?)\s*</coordinates>",
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


def _geojson_line_to_shapely(geojson: dict):
    """GeoJSON LineString/MultiLineString -> geometri shapely.
    MultiLineString(list_of_linestrings) segfaults-into-TypeError pada kombinasi
    shapely/numpy ini (shapely.creation.multilinestrings tersedak object array)
    — lewat WKT untuk menghindari jalur kode itu."""
    if geojson["type"] == "MultiLineString":
        lines = [LineString(coords) for coords in geojson["coordinates"] if len(coords) >= 2]
        wkt = "MULTILINESTRING (" + ", ".join(
            "(" + ", ".join(f"{c[0]} {c[1]}" for c in ls.coords) + ")" for ls in lines
        ) + ")"
        return shapely.wkt.loads(wkt)
    return LineString(geojson["coordinates"])


def _parse_usulan_geometry(content: bytes) -> Optional[dict]:
    """Parse unggahan geometri SITIA apa adanya: sebagian 'KML' ternyata
    KMZ (zip berisi doc.kml) atau bahkan shapefile ter-zip — deteksi dari
    header PK lalu tangani ketiganya. Return geojson LineString/
    MultiLineString atau None."""
    if content[:2] != b"PK":
        return _parse_kml_linestrings(content.decode("utf-8", "replace"))
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        return None
    names = zf.namelist()

    kml = next((n for n in names if n.lower().endswith(".kml")), None)
    if kml:
        return _parse_kml_linestrings(zf.read(kml).decode("utf-8", "replace"))

    kmz = next((n for n in names if n.lower().endswith(".kmz")), None)
    if kmz:
        # zip berisi .kmz (arsip di dalam arsip) — rekursi sekali
        return _parse_usulan_geometry(zf.read(kmz))

    shp = next((n for n in names if n.lower().endswith(".shp")), None)
    if shp:
        with TemporaryDirectory() as tmp:
            # ekstraksi rata (basename saja) — hindari path traversal dari
            # nama entri arsip
            for n in names:
                base = Path(n).name
                if not base:
                    continue
                (Path(tmp) / base).write_bytes(zf.read(n))
            try:
                gdf = gpd.read_file(Path(tmp) / Path(shp).name)
                if gdf.crs and gdf.crs.to_epsg() != 4326:
                    gdf = gdf.to_crs(epsg=4326)
            except Exception:
                return None
        lines = []
        for geom in gdf.geometry:
            if geom is None:
                continue
            if geom.geom_type == "LineString":
                lines.append([[c[0], c[1]] for c in geom.coords])
            elif geom.geom_type == "MultiLineString":
                lines.extend([[c[0], c[1]] for c in g.coords] for g in geom.geoms)
        lines = [l for l in lines if len(l) >= 2]
        if not lines:
            return None
        if len(lines) == 1:
            return {"type": "LineString", "coordinates": lines[0]}
        return {"type": "MultiLineString", "coordinates": lines}
    return None


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


# --- Layer khusus: Maps/BATAS KECAMATAN (SHP batas kecamatan nasional
# Dukcapil Des 2019, 6.810 poligon, 90MB). Atributnya HANYA nama kecamatan —
# tanpa kolom provinsi/kabupaten — jadi hierarki pilih provinsi -> kabupaten
# -> kecamatan dibangun dengan mencocokkan nama ke master penduduk_kecamatan
# (±89% nama match unik; homonim nasional & beda pemekaran 2019/2025 ditandai).
# Folder ini di-treat sebagai hierarki virtual di endpoint maps yang sudah
# ada: dropdown "kabupaten" berisi provinsi Indonesia, daftar layer berisi
# kabupaten (centang = tampilkan seluruh poligon kecamatannya; tiap poligon
# membawa properti nama untuk identify/select).
BATAS_KEC_DIRNAME = "BATAS KECAMATAN"
_batas_kec_index_cache: Optional[dict] = None


def _batas_kec_shp() -> Optional[Path]:
    d = MAPS_DIR / BATAS_KEC_DIRNAME
    if not d.is_dir():
        return None
    return next(iter(sorted(d.glob("*.shp"))), None)


def _norm_nama_wilayah(s) -> str:
    return " ".join(t for t in re.split(r"[^A-Z0-9]+", str(s).upper()) if t)


def _batas_kec_index() -> dict:
    """{provinsi: {kabupaten: [{kecamatan, kode_kecamatan, shp_nama|None,
    homonim}]}} — dibangun sekali per proses (restart untuk file baru)."""
    global _batas_kec_index_cache
    if _batas_kec_index_cache is not None:
        return _batas_kec_index_cache

    shp = _batas_kec_shp()
    if not shp:
        raise HTTPException(404, "SHP batas kecamatan tidak ditemukan di Maps/BATAS KECAMATAN")
    # Penyeteraan bilangan pada nama kecamatan: SHP memakai romawi ("ILIR
    # BARAT I"), master memakai kata ("ILIR BARAT SATU") / angka arab; plus
    # varian Minang ANAM=ENAM.
    _ANGKA = {
        "SATU": "I", "DUA": "II", "TIGA": "III", "EMPAT": "IV", "LIMA": "V",
        "ENAM": "VI", "ANAM": "VI", "TUJUH": "VII", "DELAPAN": "VIII",
        "SEMBILAN": "IX", "SEPULUH": "X", "1": "I", "2": "II", "3": "III",
        "4": "IV", "5": "V", "6": "VI", "7": "VII", "8": "VIII", "9": "IX",
        "10": "X",
    }

    def _kunci_longgar(norm_nama: str) -> str:
        return "".join(_ANGKA.get(t, t) for t in norm_nama.split())

    attrs = gpd.read_file(shp, ignore_geometry=True, engine="pyogrio")
    shp_nama = {}     # norm -> nama asli di shp
    shp_compact = {}  # tanpa spasi -> {nama asli} (GUNUNG KENCANA vs GUNUNGKENCANA)
    shp_angka = {}    # tanpa spasi + bilangan diseragamkan -> {nama asli} (ILIR BARAT SATU vs I)
    for v in attrs["KECAMATAN"].dropna():
        n = _norm_nama_wilayah(v)
        shp_nama.setdefault(n, str(v))
        shp_compact.setdefault(n.replace(" ", ""), set()).add(str(v))
        shp_angka.setdefault(_kunci_longgar(n), set()).add(str(v))

    def _cari_shp_nama(norm_nama: str):
        """Cari nama poligon: persis dulu, lalu dua kunci longgar berurutan
        (tanpa-spasi, lalu bilangan diseragamkan) bila hasilnya tunggal."""
        hit = shp_nama.get(norm_nama)
        if hit:
            return hit
        for idx, key in ((shp_compact, norm_nama.replace(" ", "")),
                         (shp_angka, _kunci_longgar(norm_nama))):
            loose = idx.get(key, set())
            if len(loose) == 1:
                return next(iter(loose))
        return None

    with db_cursor() as cur:
        cur.execute(
            "SELECT provinsi, kabupaten_kota, kode_kabupaten, kecamatan, kode_kecamatan "
            "FROM penduduk_kecamatan ORDER BY provinsi, kabupaten_kota, kecamatan"
        )
        master = cur.fetchall()

    from collections import Counter as _Counter
    nama_count = _Counter(_norm_nama_wilayah(m["kecamatan"]) for m in master)

    index: dict = {}
    entries_flat = []
    for m in master:
        n = _norm_nama_wilayah(m["kecamatan"])
        # nama master polos ("SERANG" bisa kabupaten ATAU kota) — beri prefiks
        # dari konvensi kode BPS supaya keduanya tidak menyatu jadi satu entri
        jenis = "KOTA" if m["kode_kabupaten"] % 100 >= 71 else "KAB."
        kab_label = f"{jenis} {m['kabupaten_kota']}"
        entry = {
            "kecamatan": m["kecamatan"],
            "kode_kecamatan": m["kode_kecamatan"],
            "shp_nama": _cari_shp_nama(n),
            "homonim": nama_count[n] > 1,
        }
        index.setdefault(m["provinsi"], {}).setdefault(kab_label, []).append(entry)
        entries_flat.append(entry)

    # Pass terakhir — fuzzy KONSERVATIF untuk beda ejaan/typo (CIGEMBLONG vs
    # Cigemlong, TERISI vs Trisi, PALABUHANRATU vs Pelabuhanratu): hanya
    # menjodohkan nama master yang belum match dengan poligon "yatim" (tidak
    # diklaim pass manapun), dan hanya bila keduanya saling kandidat terbaik
    # (mutual best, rasio >= 0.85) supaya tidak ada tebakan ganda.
    import difflib
    terpakai = {e["shp_nama"] for e in entries_flat if e["shp_nama"]}
    orphan = {}  # kunci longgar -> nama asli shp
    for n_shp, asli in shp_nama.items():
        if asli not in terpakai:
            orphan.setdefault(_kunci_longgar(n_shp), asli)
    belum = {}   # kunci longgar master -> [entry]
    for e in entries_flat:
        if not e["shp_nama"]:
            belum.setdefault(_kunci_longgar(_norm_nama_wilayah(e["kecamatan"])), []).append(e)

    orphan_keys, belum_keys = list(orphan), list(belum)
    for b in belum_keys:
        best = difflib.get_close_matches(b, orphan_keys, n=1, cutoff=0.85)
        if not best:
            continue
        o = best[0]
        balik = difflib.get_close_matches(o, belum_keys, n=1, cutoff=0.85)
        if balik and balik[0] == b and o in orphan:
            for e in belum[b]:
                e["shp_nama"] = orphan.pop(o)

    _batas_kec_index_cache = index
    return index


def _batas_kec_layer_geojson(prov: str, kab: str) -> dict:
    index = _batas_kec_index()
    entries = index.get(prov, {}).get(kab)
    if entries is None:
        raise HTTPException(404, "Provinsi/kabupaten tidak dikenal di master wilayah")

    by_shp_nama = {e["shp_nama"]: e for e in entries if e["shp_nama"]}
    tanpa_poligon = [e["kecamatan"] for e in entries if not e["shp_nama"]]
    if not by_shp_nama:
        raise HTTPException(404, "Tidak ada poligon kecamatan yang cocok nama untuk kabupaten ini")

    daftar = ", ".join("'" + n.replace("'", "''") + "'" for n in by_shp_nama)
    gdf = gpd.read_file(_batas_kec_shp(), engine="pyogrio", where=f"KECAMATAN IN ({daftar})")
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    # Poligon kecamatan HOMONIM di SHP sumber tergabung jadi satu MultiPolygon
    # lintas daerah (file tanpa kolom wilayah). Kecamatan dalam satu kabupaten
    # saling berbatasan, jadi bagian yang benar dipilih lewat ketetanggaan:
    # bagian yang berjarak > ±1 km dari semua poligon non-homonim kabupaten
    # ini dibuang; bila tak ada yang dekat, ambil bagian terdekat saja.
    # (Sengaja tanpa unary_union/MultiPolygon(list) — kombinasi shapely/numpy
    # di sini gagal membuat koleksi dari list Python, lihat
    # _geojson_line_to_shapely.)
    anchor_geoms = [row.geometry for _, row in gdf.iterrows()
                    if (e := by_shp_nama.get(str(row["KECAMATAN"]))) and not e["homonim"]]

    features = []
    for _, row in gdf.iterrows():
        e = by_shp_nama.get(str(row["KECAMATAN"]))
        geom_json, catatan = mapping(row.geometry), None
        if e and e["homonim"]:
            if anchor_geoms and row.geometry.geom_type == "MultiPolygon":
                parts = [p for p in row.geometry.geoms
                         if any(p.distance(a) < 0.01 for a in anchor_geoms)]
                if not parts:
                    parts = [min(row.geometry.geoms,
                                 key=lambda p: min(p.distance(a) for a in anchor_geoms))]
                if len(parts) == 1:
                    geom_json = mapping(parts[0])
                else:
                    geom_json = {"type": "MultiPolygon",
                                 "coordinates": [mapping(p)["coordinates"] for p in parts]}
                catatan = ("Nama kecamatan homonim nasional — bagian poligon yang jauh dari "
                           "kabupaten ini disembunyikan (heuristik ketetanggaan; SHP Dukcapil "
                           "2019 tanpa kolom wilayah).")
            else:
                catatan = ("Nama kecamatan homonim nasional — poligon bisa mencakup kecamatan "
                           "senama di daerah lain (SHP Dukcapil 2019 tanpa kolom wilayah).")
        features.append({
            "type": "Feature",
            "geometry": geom_json,
            "properties": {
                "KECAMATAN": row["KECAMATAN"],
                "KABUPATEN_KOTA": kab,
                "PROVINSI": prov,
                "KODE_KECAMATAN": e["kode_kecamatan"] if e else None,
                "CATATAN": catatan,
            },
        })
    return {
        "label": f"Batas Kecamatan — {kab} ({prov})",
        "type": "FeatureCollection",
        "features": features,
        "kecamatan_tanpa_poligon": tanpa_poligon,
    }


# Join atribut poligon kecamatan (identify di overlay BATAS KECAMATAN) ke
# tabel database — pengguna memilih tabel mana yang dilihat di popup.
KECAMATAN_JOIN_TABLES = {
    "kecamatan_data_turunan": "Data turunan (kepadatan, kendaraan)",
    "penduduk_kecamatan": "Master penduduk kecamatan",
    "usulan_inpres": "Usulan Inpres di kecamatan ini",
    "bps_kecamatan_potensi_tematik": "Potensi & Produksi Tematik (Dalam Angka)",
}
_USULAN_JOIN_COLS = (
    "id", "nama_ruas", "jenis_penanganan", "panjang_ruas_km",
    "alokasi_usulan_pemda", "prioritas", "verifikasi_balai", "verifikasi_kompetensi",
)


@app.get("/api/kecamatan/{kode_kecamatan}/data")
def kecamatan_join_data(kode_kecamatan: int, tabel: str = "kecamatan_data_turunan"):
    if tabel not in KECAMATAN_JOIN_TABLES:
        raise HTTPException(400, "Tabel tidak dikenal untuk join kecamatan")
    with db_cursor() as cur:
        if tabel == "usulan_inpres":
            cur.execute(
                f"SELECT {', '.join(_USULAN_JOIN_COLS)} FROM usulan_inpres "
                "WHERE kode_kecamatan = %s ORDER BY id LIMIT 50",
                (kode_kecamatan,),
            )
        else:
            cur.execute(
                f"SELECT * FROM `{tabel}` WHERE kode_kecamatan = %s LIMIT 20",
                (kode_kecamatan,),
            )
        rows = cur.fetchall()
    columns = [c for c in (rows[0].keys() if rows else []) if c not in DATA_TABLE_SKIP_COLS]
    return {
        "tabel": tabel,
        "label": KECAMATAN_JOIN_TABLES[tabel],
        "tabel_tersedia": [{"tabel": k, "label": v} for k, v in KECAMATAN_JOIN_TABLES.items()],
        "columns": columns,
        "rows": [[jsonable_encoder(r[c]) for c in columns] for r in rows],
    }


@app.get("/api/maps/provinces")
def maps_provinces():
    if not MAPS_DIR.is_dir():
        return []
    provinces = []
    for d in sorted(MAPS_DIR.iterdir()):
        if d.is_dir():
            count = sum(1 for sub in d.iterdir() if sub.is_dir())
            if count == 0 and any(d.glob("*.shp")):
                # Folder "datar" tanpa sub-folder kabupaten (mis. Maps/KAMPUNG
                # NELAYAN/*.shp langsung) — perlakukan sebagai 1 pseudo-kabupaten
                # supaya tidak terlihat kosong di daftar provinsi.
                count = 1
            provinces.append({"provinsi": d.name, "kabupaten_count": count})
    return provinces


@app.get("/api/maps/kabupaten")
def maps_kabupaten(provinsi: str):
    if provinsi == BATAS_KEC_DIRNAME and _batas_kec_shp():
        # hierarki virtual: "kabupaten" = provinsi Indonesia dari master
        index = _batas_kec_index()
        return [{"kabupaten": p, "label": p, "layer_count": len(kabs)}
                for p, kabs in sorted(index.items())]
    provinsi_dir = _resolve_map_dir(provinsi)
    kabupaten = []
    for d in sorted(provinsi_dir.iterdir()):
        if d.is_dir():
            count = sum(1 for _ in d.glob("*.shp"))
            kabupaten.append({"kabupaten": d.name, "layer_count": count})
    if not kabupaten:
        # Folder provinsi tanpa sub-folder kabupaten tapi berisi .shp langsung
        # (mis. Maps/KAMPUNG NELAYAN/) — pakai folder itu sendiri sebagai satu
        # entri "kabupaten" (kabupaten="" jadi penanda: pakai folder provinsi).
        count = sum(1 for _ in provinsi_dir.glob("*.shp"))
        if count:
            kabupaten.append({"kabupaten": "", "label": provinsi, "layer_count": count})
    return kabupaten


def _resolve_kabupaten_dir(provinsi: str, kabupaten: str) -> Path:
    if kabupaten:
        return _resolve_map_dir(provinsi, kabupaten)
    return _resolve_map_dir(provinsi)


@app.get("/api/maps/layers")
def maps_layers(provinsi: str, kabupaten: str = ""):
    if provinsi == BATAS_KEC_DIRNAME and _batas_kec_shp():
        # hierarki virtual: layer = kabupaten/kota berisi poligon kecamatannya
        index = _batas_kec_index()
        kabs = index.get(kabupaten)
        if kabs is None:
            raise HTTPException(404, "Provinsi tidak dikenal di master wilayah")
        out = []
        for kab, entries in sorted(kabs.items()):
            ada = sum(1 for e in entries if e["shp_nama"])
            out.append({
                "layer": f"BATASKEC__{kabupaten}__{kab}",
                "label": f"{kab} ({ada}/{len(entries)} kecamatan)",
                "size_mb": None,
            })
        return out
    kabupaten_dir = _resolve_kabupaten_dir(provinsi, kabupaten)
    layers = []
    for shp in sorted(kabupaten_dir.glob("*.shp")):
        layers.append({
            "layer": shp.stem,
            "label": _map_layer_label(shp.stem),
            "size_mb": round(shp.stat().st_size / 1_048_576, 2),
        })
    return layers


@app.get("/api/maps/layer")
def maps_layer(provinsi: str, layer: str, kabupaten: str = ""):
    key = (provinsi, kabupaten, layer)
    if key in _map_layer_geojson_cache:
        return _map_layer_geojson_cache[key]

    if provinsi == BATAS_KEC_DIRNAME and layer.startswith("BATASKEC__"):
        try:
            _, prov, kab = layer.split("__", 2)
        except ValueError:
            raise HTTPException(400, "Layer batas kecamatan tidak valid")
        geojson = _batas_kec_layer_geojson(prov, kab)
        _map_layer_geojson_cache[key] = geojson
        return geojson

    kabupaten_dir = _resolve_kabupaten_dir(provinsi, kabupaten)
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

        geojson = _parse_usulan_geometry(resp.content)
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

    geometry = _geojson_line_to_shapely(geojson)

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


@app.post("/api/chat")
def chat(payload: ChatRequest):
    if not payload.messages:
        raise HTTPException(400, "Tidak ada pesan")
    reply = chat_providers._call_chat(payload.messages, payload.context)
    return {"reply": reply}


class NoCacheStaticFiles(StaticFiles):
    """StaticFiles tanpa Cache-Control membuat browser memakai caching
    heuristik: js/css lama bisa terus dipakai setelah file berubah (tanpa
    build step tidak ada cache-busting hash). no-cache = browser tetap
    menyimpan file tapi selalu revalidasi ETag (304 bila tidak berubah)."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app.mount("/", NoCacheStaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", 8000)),
        reload=True,
    )
