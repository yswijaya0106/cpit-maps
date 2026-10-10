"""Cetak peta (PDF / DOCX) dengan label & tabel atribut.

Dipanggil oleh route `POST /api/peta/cetak` di app.py (route-nya tetap di
app.py, logika di sini -- pola yg sama dgn road_safety.py/urban_darat.py).

Alur:
1. Frontend (static/js/print-map.js) mengirim batas tampilan peta saat ini +
   fitur semua layer overlay aktif yang tampak di layar (geometri GeoJSON,
   atribut, gaya warna persis seperti di peta, dan teks label yg dipilih
   pengguna per layer) + rute/usulan/marker yang sedang tergambar.
2. Basemap dirakit server-side dari tile XYZ (OSM / CARTO terang / citra Esri)
   -- tile Google tidak boleh diambil langsung (ketentuan layanan), jadi
   basemap Google di layar diganti padanan terbukanya di hasil cetak.
3. Vektor digambar dgn Pillow (supersampling 2x supaya garis halus), lalu
   label (poligon: titik representatif; garis: di tengah ruas, diputar
   searah garis; titik: di samping simbol) dgn penghindar tabrakan label
   sederhana. Grid koordinat, panah utara, skala batang & atribusi basemap
   digambar langsung ke gambar peta.
4. Gambar peta ditata ke halaman: PDF via reportlab (vektor, teks bisa
   diseleksi), DOCX via python-docx. Halaman lampiran berisi tabel atribut
   per layer; mode label "nomor" menomori fitur di peta sesuai baris tabel.
"""

import base64
import io
import math
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import requests
import shapely
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field
from shapely.geometry import box, shape

# ---------------------------------------------------------------------------
# Model request
# ---------------------------------------------------------------------------


class CetakGaya(BaseModel):
    fill: Optional[str] = None
    fill_opacity: float = 0.0
    stroke: Optional[str] = None
    stroke_width: float = 1.5
    stroke_opacity: float = 1.0
    point_color: Optional[str] = None
    point_radius: float = 4.0
    # Ikon titik spt di layar (pesawat bandara, jangkar pelabuhan, ...): kunci ke
    # CetakPetaRequest.ikon. Kosong = titik digambar lingkaran point_color.
    point_icon: Optional[str] = None
    point_size: float = 24.0  # lebar ikon di layar (px)


class CetakFitur(BaseModel):
    geometry: Dict[str, Any]
    properties: Dict[str, Any] = Field(default_factory=dict)
    style: CetakGaya = Field(default_factory=CetakGaya)
    label: Optional[str] = None


class CetakLegenda(BaseModel):
    warna: str
    teks: str
    jenis: str = "poligon"  # poligon | garis | titik
    ikon: Optional[str] = None  # kunci CetakPetaRequest.ikon (titik ber-ikon)


class CetakLayer(BaseModel):
    nama: str
    sumber: str = ""
    warna: str = "#4f7cff"
    jenis: str = "poligon"  # jenis geometri dominan, utk simbol legenda
    label_field: Optional[str] = None
    tabel: bool = True
    legend: List[CetakLegenda] = Field(default_factory=list)
    features: List[CetakFitur] = Field(default_factory=list)
    ikon: Optional[str] = None  # ikon titik dominan layer, utk legenda tanpa sub-item


class CetakBatas(BaseModel):
    west: float
    south: float
    east: float
    north: float


class CetakPetaRequest(BaseModel):
    format: str = "pdf"  # pdf | docx
    judul: str = "Peta"
    subjudul: str = ""
    catatan: str = ""
    kertas: str = "A4"  # A4 | A3
    orientasi: str = "landscape"  # landscape | portrait
    basemap: str = "osm"  # osm | terang | satelit | none
    bounds: CetakBatas
    label_mode: str = "atribut"  # atribut | nomor | none
    ukuran_label: str = "sedang"  # kecil | sedang | besar
    sertakan_tabel: bool = True
    grid: bool = True
    maks_baris: int = 300
    layers: List[CetakLayer] = Field(default_factory=list)
    # {kunci: "data:image/png;base64,..."} -- ikon titik yg dirasterisasi
    # browser (print-map.js) dari SVG ikon layer. Dikirim sekali per ikon unik.
    ikon: Dict[str, str] = Field(default_factory=dict)


_IKON_MAKS = 64
_IKON_MAKS_BYTE = 300_000


def _ikon_gambar(req: "CetakPetaRequest", kunci: Optional[str]) -> Optional[Image.Image]:
    """PNG ikon -> PIL RGBA (cache per request). None bila tidak ada/rusak,
    sehingga pemanggil jatuh ke simbol lingkaran lama."""
    if not kunci:
        return None
    cache = req.__dict__.setdefault("_ikon_cache", {})
    if kunci in cache:
        return cache[kunci]
    img = None
    data = req.ikon.get(kunci) if len(req.ikon) <= _IKON_MAKS else None
    if data and data.startswith("data:image/png;base64,"):
        try:
            raw = base64.b64decode(data.split(",", 1)[1], validate=True)
            if len(raw) <= _IKON_MAKS_BYTE:
                img = Image.open(io.BytesIO(raw)).convert("RGBA")
        except Exception:
            img = None
    cache[kunci] = img
    return img


def _ikon_ukuran(img: Image.Image, lebar: float) -> Image.Image:
    lebar = max(4, int(round(lebar)))
    tinggi = max(4, int(round(lebar * img.height / img.width)))
    return img.resize((lebar, tinggi), Image.Resampling.LANCZOS)


# ---------------------------------------------------------------------------
# Font
# ---------------------------------------------------------------------------

_FONT_CANDIDATES = {
    False: [
        r"C:\Windows\Fonts\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/Library/Fonts/Arial.ttf",
    ],
    True: [
        r"C:\Windows\Fonts\arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ],
}


@lru_cache(maxsize=4)
def _font_path(bold: bool) -> Optional[str]:
    for p in _FONT_CANDIDATES[bold]:
        if os.path.exists(p):
            return p
    # fallback terjamin: font Vera bawaan paket reportlab
    try:
        import reportlab

        p = os.path.join(os.path.dirname(reportlab.__file__), "fonts", "VeraBd.ttf" if bold else "Vera.ttf")
        if os.path.exists(p):
            return p
    except ImportError:
        pass
    return None


@lru_cache(maxsize=64)
def _font(px: int, bold: bool = False):
    path = _font_path(bold)
    if path:
        return ImageFont.truetype(path, max(6, int(px)))
    return ImageFont.load_default(size=max(6, int(px)))


# ---------------------------------------------------------------------------
# Warna
# ---------------------------------------------------------------------------

_RGB_RE = re.compile(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)")


def _rgb(c: Optional[str], default=(79, 124, 255)) -> Tuple[int, int, int]:
    if not c:
        return default
    c = str(c).strip()
    if c.startswith("#"):
        h = c[1:]
        if len(h) in (3, 4):
            h = "".join(ch * 2 for ch in h[:3])
        if len(h) >= 6:
            try:
                return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            except ValueError:
                return default
    m = _RGB_RE.match(c)
    if m:
        return tuple(int(float(v)) for v in m.groups())  # type: ignore[return-value]
    return default


def _rgba(c, alpha: float, default=(79, 124, 255)):
    r, g, b = _rgb(c, default)
    return r, g, b, max(0, min(255, int(round(alpha * 255))))


def _darken(rgb, f=0.45):
    return tuple(int(v * f) for v in rgb)


# ---------------------------------------------------------------------------
# Proyeksi Web Mercator (koordinat "dunia" zoom 0, 256 px)
# ---------------------------------------------------------------------------

TILE = 256
_MAX_LAT = 85.05112878
_KELILING_BUMI_M = 40075016.686


def _ke_dunia(lon: float, lat: float) -> Tuple[float, float]:
    lat = max(min(lat, _MAX_LAT), -_MAX_LAT)
    s = math.sin(math.radians(lat))
    return (lon + 180.0) / 360.0 * TILE, (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * TILE


def _dari_dunia(x: float, y: float) -> Tuple[float, float]:
    lon = x / TILE * 360.0 - 180.0
    n = math.pi - 2 * math.pi * y / TILE
    return lon, math.degrees(math.atan(math.sinh(n)))


class Tampilan:
    """Jendela peta: kotak koordinat dunia (x0,y0,x1,y1) -> gambar W x H px."""

    def __init__(self, bounds: CetakBatas, w: int, h: int, pad_frac: float = 0.0):
        x0, y1 = _ke_dunia(bounds.west, bounds.south)
        x1, y0 = _ke_dunia(bounds.east, bounds.north)
        if x1 <= x0:
            x1 = x0 + 1e-6
        if y1 <= y0:
            y1 = y0 + 1e-6
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        bw, bh = (x1 - x0) * (1 + pad_frac), (y1 - y0) * (1 + pad_frac)
        # minimal ~ skala jalan (hindari zoom tak hingga utk batas titik tunggal)
        bw, bh = max(bw, 2e-4), max(bh, 2e-4)
        aspek = w / h
        if bw / bh > aspek:
            bh = bw / aspek
        else:
            bw = bh * aspek
        self.x0, self.y0, self.x1, self.y1 = cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2
        self.W, self.H = int(w), int(h)

    @property
    def batas_lonlat(self):
        west, north = _dari_dunia(self.x0, self.y0)
        east, south = _dari_dunia(self.x1, self.y1)
        return west, south, east, north

    def px(self, lon, lat, ss=1.0):
        x, y = _ke_dunia(lon, lat)
        return (x - self.x0) / (self.x1 - self.x0) * self.W * ss, (y - self.y0) / (self.y1 - self.y0) * self.H * ss

    def meter_per_px(self) -> float:
        _, lat_c = _dari_dunia((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)
        return (self.x1 - self.x0) / self.W / TILE * _KELILING_BUMI_M * math.cos(math.radians(lat_c))

    def fungsi_proyeksi(self, ss: float):
        x0, y0 = self.x0, self.y0
        sx = self.W * ss / (self.x1 - self.x0)
        sy = self.H * ss / (self.y1 - self.y0)

        def f(arr):
            lon = arr[:, 0]
            lat = np.clip(arr[:, 1], -_MAX_LAT, _MAX_LAT)
            s = np.sin(np.radians(lat))
            wx = (lon + 180.0) / 360.0 * TILE
            wy = (0.5 - np.log((1 + s) / (1 - s)) / (4 * np.pi)) * TILE
            return np.column_stack([(wx - x0) * sx, (wy - y0) * sy])

        return f


# ---------------------------------------------------------------------------
# Basemap dari tile XYZ
# ---------------------------------------------------------------------------

BASEMAPS = {
    "osm": {
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "maxz": 19,
        "nama": "OpenStreetMap",
        "atribusi": "© kontributor OpenStreetMap",
    },
    # CARTO Positron sempat dicoba -- server-nya membalas tile placeholder
    # ("redacted") utk request tanpa Referer situs terdaftar, jadi pakai Esri.
    "terang": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        "maxz": 16,
        "nama": "Esri Light Gray Canvas (terang)",
        "atribusi": "Esri, HERE, Garmin, © kontributor OpenStreetMap",
    },
    # "Alami tanpa label" (usulan pengguna 7 Okt 2026: peta dasar polos utk paparan).
    # Satu-satunya sumber berwarna alami TANPA tulisan sama sekali yg bisa diambil
    # server tanpa API key (CARTO *_nolabels butuh key; "terang" masih ada label
    # provinsi samar). Tile asli hanya s.d. zoom 10 -- di atasnya Esri membalas
    # placeholder, jadi maxz=10 (diperbesar utk area sempit).
    "alami": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}",
        "maxz": 10,
        "nama": "Esri World Ocean Base (tanpa label)",
        "atribusi": "Esri, GEBCO, NOAA, Garmin, HERE",
    },
    "satelit": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "maxz": 19,
        "nama": "Citra satelit Esri World Imagery",
        "atribusi": "Citra: Esri, Maxar, Earthstar Geographics",
    },
}

_HTTP = requests.Session()
_HTTP.headers.update({"User-Agent": "TheNext-SiJalan-CetakPeta/1.0 (aplikasi internal)"})
_tile_cache: Dict[str, bytes] = {}
_tile_lock = threading.Lock()
_TILE_CACHE_MAKS = 1500
_MAKS_TILE = 160


def _ambil_tile(conf, z, x, y) -> Optional[Image.Image]:
    sub = conf.get("sub")
    url = conf["url"].format(z=z, x=x, y=y, s=sub[(x + y) % len(sub)] if sub else "")
    with _tile_lock:
        data = _tile_cache.get(url)
    if data is None:
        try:
            r = _HTTP.get(url, timeout=10)
            if r.status_code != 200 or not r.content:
                return None
            data = r.content
        except requests.RequestException:
            return None
        with _tile_lock:
            _tile_cache[url] = data
            while len(_tile_cache) > _TILE_CACHE_MAKS:
                _tile_cache.pop(next(iter(_tile_cache)))
    try:
        return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return None


def render_basemap(view: Tampilan, basemap: str, dpi_out: float) -> Tuple[Image.Image, int]:
    """Gambar basemap W x H (RGB) + jumlah tile yg gagal dimuat."""
    conf = BASEMAPS.get(basemap)
    if not conf:
        return Image.new("RGB", (view.W, view.H), (246, 247, 249)), 0
    bw = view.x1 - view.x0
    # Tile dipakai pd ~144 dpi efektif (bukan 1:1 dgn dpi cetak) supaya teks
    # jalan/kota di basemap tidak tercetak separuh ukuran layar.
    z = int(round(math.log2(max(view.W * 144.0 / dpi_out / bw, 1e-9))))
    z = max(1, min(conf["maxz"], z))
    while True:
        n = 1 << z
        tx0, tx1 = int(math.floor(view.x0 * n / TILE)), int(math.floor((view.x1 * n - 1e-9) / TILE))
        ty0 = max(0, int(math.floor(view.y0 * n / TILE)))
        ty1 = min(n - 1, int(math.floor((view.y1 * n - 1e-9) / TILE)))
        if (tx1 - tx0 + 1) * (ty1 - ty0 + 1) <= _MAKS_TILE or z <= 1:
            break
        z -= 1
    kanvas = Image.new("RGB", ((tx1 - tx0 + 1) * TILE, (ty1 - ty0 + 1) * TILE), (238, 238, 232))
    tugas = [(tx, ty) for tx in range(tx0, tx1 + 1) for ty in range(ty0, ty1 + 1)]
    gagal = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        hasil = list(ex.map(lambda t: _ambil_tile(conf, z, t[0] % n, t[1]), tugas))
    for (tx, ty), im in zip(tugas, hasil):
        if im is None:
            gagal += 1
            continue
        kanvas.paste(im, ((tx - tx0) * TILE, (ty - ty0) * TILE))
    skala = n / 1.0
    kiri = view.x0 * skala - tx0 * TILE
    atas = view.y0 * skala - ty0 * TILE
    kanan = view.x1 * skala - tx0 * TILE
    bawah = view.y1 * skala - ty0 * TILE
    img = kanvas.transform((view.W, view.H), Image.Transform.EXTENT, (kiri, atas, kanan, bawah),
                           resample=Image.Resampling.BICUBIC)
    return img, gagal


# ---------------------------------------------------------------------------
# Vektor + label
# ---------------------------------------------------------------------------


def _bagian(g):
    """Pecah geometri (Multi*/GeometryCollection) jadi bagian sederhana."""
    if g is None or g.is_empty:
        return []
    return [p for p in shapely.get_parts(g) if not p.is_empty] if g.geom_type.startswith(("Multi", "Geometry")) else [g]


def _tipe_dominan(g) -> str:
    tipe = {p.geom_type for p in _bagian(g)}
    if tipe & {"Polygon"}:
        return "Polygon"
    if tipe & {"LineString", "LinearRing"}:
        return "LineString"
    return "Point"


def _saring(g, tipe):
    bagian = [p for p in _bagian(g) if p.geom_type == tipe or (tipe == "LineString" and p.geom_type == "LinearRing")]
    if not bagian:
        return None
    return bagian[0] if len(bagian) == 1 else shapely.GeometryCollection(bagian)


def _koord(line) -> List[Tuple[float, float]]:
    return [(float(x), float(y)) for x, y in np.asarray(line.coords)[:, :2]]


class _Fitur:
    __slots__ = ("geom", "gaya", "label", "props", "nomor")

    def __init__(self, geom, gaya, label, props):
        self.geom, self.gaya, self.label, self.props, self.nomor = geom, gaya, label, props, None


def siapkan_fitur(req: CetakPetaRequest, view: Tampilan, ss: float):
    """Proyeksikan + potong fitur ke bingkai. Hasil per layer: list _Fitur
    (koordinat piksel pada skala ss), urut sesuai kiriman frontend."""
    proyeksi = view.fungsi_proyeksi(ss)
    pad = 40 * ss
    klip = box(-pad, -pad, view.W * ss + pad, view.H * ss + pad)
    tampak = box(0, 0, view.W * ss, view.H * ss)
    hasil = []
    for layer in req.layers:
        daftar = []
        for f in layer.features:
            try:
                g = shape(f.geometry)
                if g.is_empty:
                    continue
                g = shapely.transform(g, proyeksi)
                if not g.intersects(tampak):
                    continue
                tipe = _tipe_dominan(g)
                if tipe == "Polygon":
                    g = g.simplify(0.5 * ss, preserve_topology=True)
                    if not g.is_valid:
                        g = g.buffer(0)
                    g = g.intersection(klip)
                elif tipe == "LineString":
                    g = g.simplify(0.5 * ss).intersection(klip)
                # potong poligon bisa menyisakan garis/titik singgung -> buang
                g = _saring(g, tipe)
                if g is None:
                    continue
            except Exception:
                continue
            props = {k: v for k, v in (f.properties or {}).items() if not str(k).startswith("_")}
            daftar.append(_Fitur(g, f.style, (f.label or "").strip(), props))
        hasil.append(daftar)
    return hasil


def _lebar_garis(w_layar: float, faktor: float) -> int:
    return max(1, int(round(w_layar * faktor)))


def render_vektor(req: CetakPetaRequest, view: Tampilan, fitur_per_layer, ss: int, dpi: float) -> Image.Image:
    """Semua layer digambar ke kanvas RGBA (skala ss), lalu diperkecil ke W x H."""
    W, H = view.W * ss, view.H * ss
    kanvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    faktor = ss * dpi / 96.0 * 0.75  # px layar -> px cetak (sedikit lebih tipis dari layar)
    for layer, daftar in zip(req.layers, fitur_per_layer):
        if not daftar:
            continue
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        # Poligon berlubang digambar DULU: lubangnya "dihapus" (diisi
        # transparan) di overlay layer ini, jadi fitur enklave yg digambar
        # sesudahnya tidak ikut terhapus.
        poligon = [f for f in daftar if _tipe_dominan(f.geom) == "Polygon"]
        poligon.sort(key=lambda f: -sum(len(p.interiors) for p in _bagian(f.geom) if p.geom_type == "Polygon"))
        for f in poligon:
            g = f.gaya
            if g.fill and g.fill_opacity > 0:
                isi = _rgba(g.fill, g.fill_opacity, _rgb(layer.warna))
                for p in _bagian(f.geom):
                    if p.geom_type != "Polygon" or len(p.exterior.coords) < 3:
                        continue
                    d.polygon(_koord(p.exterior), fill=isi)
                    for hole in p.interiors:
                        if len(hole.coords) >= 3:
                            d.polygon(_koord(hole), fill=(0, 0, 0, 0))
        for f in poligon:
            g = f.gaya
            if not g.stroke or g.stroke_opacity <= 0:
                continue
            warna = _rgba(g.stroke, g.stroke_opacity, _rgb(layer.warna))
            w = _lebar_garis(g.stroke_width, faktor)
            for p in _bagian(f.geom):
                if p.geom_type != "Polygon":
                    continue
                for ring in [p.exterior, *p.interiors]:
                    c = _koord(ring)
                    if len(c) >= 2:
                        d.line(c, fill=warna, width=w, joint="curve" if w > 2 else None)
        for f in daftar:
            g = f.gaya
            if _tipe_dominan(f.geom) == "Polygon":
                continue
            for p in _bagian(f.geom):
                if p.geom_type in ("LineString", "LinearRing"):
                    c = _koord(p)
                    if len(c) < 2:
                        continue
                    w = _lebar_garis(g.stroke_width, faktor)
                    d.line(c, fill=_rgba(g.stroke or layer.warna, g.stroke_opacity, _rgb(layer.warna)),
                           width=w, joint="curve" if w > 2 else None)
                elif p.geom_type == "Point":
                    x, y = p.x, p.y
                    ikon = _ikon_gambar(req, g.point_icon)
                    if ikon is not None:
                        # ukuran sama dgn di layar (faktor = px layar -> px cetak)
                        im = _ikon_ukuran(ikon, g.point_size * faktor / 0.75 * 0.8)
                        ov.paste(im, (int(round(x - im.width / 2)), int(round(y - im.height / 2))), im)
                        continue
                    r = max(2.0, g.point_radius * faktor)
                    d.ellipse((x - r, y - r, x + r, y + r),
                              fill=_rgba(g.point_color or layer.warna, 0.95, _rgb(layer.warna)),
                              outline=(20, 24, 34, 255), width=max(1, int(round(ss * dpi / 96 * 0.9))))
        kanvas.alpha_composite(ov)
    if ss != 1:
        kanvas = kanvas.resize((view.W, view.H), Image.Resampling.LANCZOS)
    return kanvas


_UKURAN_LABEL_PT = {"kecil": 6.5, "sedang": 8.0, "besar": 10.0}


def _huruf_layer(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _kotak_bentrok(k, terpakai) -> bool:
    x0, y0, x1, y1 = k
    for a0, b0, a1, b1 in terpakai:
        if x0 < a1 and x1 > a0 and y0 < b1 and y1 > b0:
            return True
    return False


def render_label(img: Image.Image, req: CetakPetaRequest, fitur_per_layer, ss: float, dpi: float):
    """Label ditulis di gambar final (skala 1x) supaya teks tetap tajam."""
    if req.label_mode == "none":
        return
    pt = _UKURAN_LABEL_PT.get(req.ukuran_label, 8.0)
    px = pt / 72.0 * dpi
    font = _font(int(px), bold=req.label_mode == "nomor")
    sw = max(1, int(round(px * 0.14)))
    # ImageDraw pd gambar RGBA MENGGANTI piksel (tidak memadukan alpha) ->
    # tulis ke overlay transparan lalu alpha_composite sekali di akhir.
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    _tulis_label(ov, req, fitur_per_layer, ss, dpi, font, sw)
    img.alpha_composite(ov)


def _tulis_label(img, req, fitur_per_layer, ss, dpi, font, sw):
    d = ImageDraw.Draw(img)
    W, H = img.size
    terpakai: List[Tuple[float, float, float, float]] = []
    halo = (255, 255, 255, 235)
    jumlah = 0
    for li, (layer, daftar) in enumerate(zip(req.layers, fitur_per_layer)):
        warna_layer = _rgb(layer.warna)
        for f in daftar:
            if jumlah >= 3000:
                return
            teks = f.label if req.label_mode == "atribut" else (f.nomor or "")
            if not teks:
                continue
            if len(teks) > 42:
                teks = teks[:40].rstrip() + "…"
            l, t, r, b = font.getbbox(teks, stroke_width=sw)
            tw, th = r - l, b - t
            bagian = _bagian(f.geom)
            tipe = bagian[0].geom_type if bagian else ""
            if tipe == "Polygon":
                p = max((q for q in bagian if q.geom_type == "Polygon"), key=lambda q: q.area, default=None)
                if p is None:
                    continue
                bx0, by0, bx1, by1 = [v / ss for v in p.bounds]
                if req.label_mode == "atribut" and (bx1 - bx0 < tw * 0.5 or by1 - by0 < th * 0.8):
                    continue
                titik = p.representative_point()
                x, y = titik.x / ss, titik.y / ss
                k = (x - tw / 2, y - th / 2, x + tw / 2, y + th / 2)
                if k[0] < 0 or k[1] < 0 or k[2] > W or k[3] > H or _kotak_bentrok(k, terpakai):
                    continue
                d.text((x, y), teks, font=font, fill=(17, 24, 39, 255), anchor="mm", stroke_width=sw, stroke_fill=halo)
                terpakai.append(k)
            elif tipe in ("LineString", "LinearRing"):
                garis = max((q for q in bagian if q.geom_type in ("LineString", "LinearRing")), key=lambda q: q.length)
                panjang = garis.length / ss
                if req.label_mode == "atribut" and panjang < tw * 1.1:
                    continue
                s0 = garis.interpolate(0.5, normalized=True)
                s1 = garis.interpolate(max(0.0, garis.length / 2 - tw * ss / 2))
                s2 = garis.interpolate(min(garis.length, garis.length / 2 + tw * ss / 2))
                sudut = -math.degrees(math.atan2(s2.y - s1.y, s2.x - s1.x))
                if sudut > 90:
                    sudut -= 180
                elif sudut < -90:
                    sudut += 180
                pad = sw + 2
                tmp = Image.new("RGBA", (int(tw + 2 * pad), int(th + 2 * pad)), (0, 0, 0, 0))
                ImageDraw.Draw(tmp).text((tmp.width / 2, tmp.height / 2), teks, font=font, anchor="mm",
                                         fill=(*_darken(warna_layer, 0.4), 255), stroke_width=sw, stroke_fill=halo)
                rot = tmp.rotate(sudut, expand=True, resample=Image.Resampling.BICUBIC)
                x, y = s0.x / ss, s0.y / ss
                k = (x - rot.width / 2, y - rot.height / 2, x + rot.width / 2, y + rot.height / 2)
                # kotak tabrakan sedikit diperkecil: kotak sumbu dari teks miring terlalu boros
                kc = (k[0] + rot.width * 0.15, k[1] + rot.height * 0.15, k[2] - rot.width * 0.15, k[3] - rot.height * 0.15)
                if k[0] < 0 or k[1] < 0 or k[2] > W or k[3] > H or _kotak_bentrok(kc, terpakai):
                    continue
                img.alpha_composite(rot, dest=(int(round(k[0])), int(round(k[1]))))
                terpakai.append(kc)
            elif tipe == "Point":
                p = bagian[0]
                x, y = p.x / ss, p.y / ss
                off = max(3.0, f.gaya.point_radius * dpi / 96 * 0.75) + 3
                if f.gaya.point_icon:
                    off = max(off, f.gaya.point_size * dpi / 96 * 0.8 / 2 + 2)
                calon = [
                    (x + off, y - th / 2, x + off + tw, y + th / 2),
                    (x - off - tw, y - th / 2, x - off, y + th / 2),
                    (x - tw / 2, y - off - th, x + tw / 2, y - off),
                    (x - tw / 2, y + off, x + tw / 2, y + off + th),
                ]
                for k in calon:
                    if k[0] < 0 or k[1] < 0 or k[2] > W or k[3] > H or _kotak_bentrok(k, terpakai):
                        continue
                    d.text(((k[0] + k[2]) / 2, (k[1] + k[3]) / 2), teks, font=font, fill=(17, 24, 39, 255),
                           anchor="mm", stroke_width=sw, stroke_fill=halo)
                    terpakai.append(k)
                    break
            jumlah += 1


# ---------------------------------------------------------------------------
# Perlengkapan peta: grid koordinat, panah utara, skala batang, atribusi
# ---------------------------------------------------------------------------

_LANGKAH_BAGUS = [0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.025, 0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 20]


def _langkah_grid(rentang: float) -> float:
    for s in _LANGKAH_BAGUS:
        if rentang / s <= 5:
            return s
    return 20


def _fmt_derajat(v: float, lat: bool, langkah: float) -> str:
    desimal = max(0, int(math.ceil(-math.log10(langkah))) + (1 if langkah in (0.025, 0.25) else 0))
    arah = ("LU" if v > 0 else "LS" if v < 0 else "") if lat else ("BT" if v >= 0 else "BB")
    angka = f"{abs(v):.{desimal}f}".replace(".", ",")
    return f"{angka}° {arah}".strip()


def _fmt_angka(n: float) -> str:
    return f"{int(round(n)):,}".replace(",", ".")


def _jarak_bagus(maks_m: float) -> float:
    if maks_m <= 0:
        return 1
    e = 10 ** math.floor(math.log10(maks_m))
    for m in (5, 2, 1):
        if m * e <= maks_m:
            return m * e
    return e


def render_perlengkapan(img: Image.Image, view: Tampilan, dpi: float, atribusi: str, grid: bool):
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    _gambar_perlengkapan(ov, view, dpi, atribusi, grid)
    img.alpha_composite(ov)


def _gambar_perlengkapan(img, view, dpi, atribusi, grid):
    d = ImageDraw.Draw(img)
    W, H = img.size
    u = dpi / 25.4  # px per mm
    f_kecil = _font(int(2.3 * u))
    f_kecil_b = _font(int(2.5 * u), bold=True)
    halo = (255, 255, 255, 230)

    if grid:
        west, south, east, north = view.batas_lonlat
        for lat_axis, (a, b) in ((False, (west, east)), (True, (south, north))):
            langkah = _langkah_grid(b - a)
            v = math.ceil(a / langkah) * langkah
            while v < b:
                if lat_axis:
                    _, y = view.px(west, v)
                    d.line([(0, y), (W, y)], fill=(40, 40, 40, 70), width=max(1, int(0.18 * u)))
                    d.text((1.2 * u, y - 0.6 * u), _fmt_derajat(v, True, langkah), font=f_kecil, anchor="ls",
                           fill=(30, 30, 30, 255), stroke_width=max(1, int(0.3 * u)), stroke_fill=halo)
                else:
                    x, _ = view.px(v, south)
                    d.line([(x, 0), (x, H)], fill=(40, 40, 40, 70), width=max(1, int(0.18 * u)))
                    d.text((x + 0.8 * u, H - 1.2 * u), _fmt_derajat(v, False, langkah), font=f_kecil, anchor="ls",
                           fill=(30, 30, 30, 255), stroke_width=max(1, int(0.3 * u)), stroke_fill=halo)
                v += langkah

    # Panah utara (kanan atas)
    ukuran = 11 * u
    x0, y0 = W - ukuran - 3 * u, 3 * u
    d.rounded_rectangle((x0, y0, x0 + ukuran, y0 + ukuran * 1.25), radius=1.5 * u, fill=(255, 255, 255, 225),
                        outline=(60, 70, 90, 255), width=max(1, int(0.25 * u)))
    cx = x0 + ukuran / 2
    atas, bawah, lebar = y0 + ukuran * 0.42, y0 + ukuran * 1.12, ukuran * 0.28
    tengah = bawah - (bawah - atas) * 0.28
    d.polygon([(cx, atas), (cx - lebar, bawah), (cx, tengah)], fill=(31, 41, 55, 255))
    d.polygon([(cx, atas), (cx + lebar, bawah), (cx, tengah)], fill=(255, 255, 255, 255), outline=(31, 41, 55, 255))
    d.text((cx, y0 + ukuran * 0.22), "U", font=_font(int(3.6 * u), bold=True), anchor="mm", fill=(31, 41, 55, 255))

    # Skala batang (kiri bawah) -- di atas label bujur grid
    mpp = view.meter_per_px()
    target_px = min(W * 0.25, 50 * u)
    panjang_m = _jarak_bagus(target_px * mpp)
    bar_px = panjang_m / mpp
    satuan_km = panjang_m >= 1000
    bx, by = 3 * u, H - 13 * u
    d.rounded_rectangle((bx - 2 * u, by - 5.2 * u, bx + bar_px + 9 * u, by + 4.2 * u), radius=1.2 * u,
                        fill=(255, 255, 255, 225), outline=(60, 70, 90, 180), width=max(1, int(0.2 * u)))
    tinggi = 1.4 * u
    for i in range(4):
        sx0 = bx + bar_px * i / 4
        d.rectangle((sx0, by, bx + bar_px * (i + 1) / 4, by + tinggi),
                    fill=(31, 41, 55, 255) if i % 2 == 0 else (255, 255, 255, 255), outline=(31, 41, 55, 255))
    for frac in (0, 0.5, 1):
        nilai = panjang_m * frac / (1000 if satuan_km else 1)
        teks = (f"{nilai:g}".replace(".", ","))
        d.text((bx + bar_px * frac, by - 0.8 * u), teks, font=f_kecil, anchor="ms", fill=(31, 41, 55, 255))
    d.text((bx + bar_px + 1.5 * u, by + tinggi), "km" if satuan_km else "m", font=f_kecil_b, anchor="ls",
           fill=(31, 41, 55, 255))

    # Atribusi basemap (kanan bawah)
    if atribusi:
        l, t, r, b = f_kecil.getbbox(atribusi)
        tx1, ty1 = W - 1.5 * u, H - 1.2 * u
        d.rectangle((tx1 - (r - l) - 1.5 * u, ty1 - (b - t) - 1.2 * u, W, H), fill=(255, 255, 255, 200))
        d.text((tx1, ty1), atribusi, font=f_kecil, anchor="rs", fill=(55, 65, 81, 255))


# ---------------------------------------------------------------------------
# Peta lengkap + peta indeks
# ---------------------------------------------------------------------------

_BATAS_INDONESIA = CetakBatas(west=94.5, south=-11.5, east=141.5, north=6.5)


class HasilPeta:
    def __init__(self, gambar: Image.Image, view: Tampilan, fitur_per_layer, tile_gagal: int, dpi: float):
        self.gambar, self.view, self.fitur_per_layer, self.tile_gagal, self.dpi = gambar, view, fitur_per_layer, tile_gagal, dpi

    def skala(self) -> float:
        return self.view.meter_per_px() / (0.0254 / self.dpi)


def _nomori(req: CetakPetaRequest, fitur_per_layer):
    """Nomor fitur (A1, A2, B1 ...) = urutan baris tabel atribut."""
    satu_layer = len([d for d in fitur_per_layer if d]) <= 1
    for li, daftar in enumerate(fitur_per_layer):
        for i, f in enumerate(daftar[: max(1, req.maks_baris)]):
            f.nomor = str(i + 1) if satu_layer else f"{_huruf_layer(li)}{i + 1}"


def render_peta(req: CetakPetaRequest, lebar_mm: float, tinggi_mm: float, dpi: float) -> HasilPeta:
    W, H = int(lebar_mm / 25.4 * dpi), int(tinggi_mm / 25.4 * dpi)
    view = Tampilan(req.bounds, W, H)
    ss = 2 if W * H <= 7_500_000 else 1
    fitur = siapkan_fitur(req, view, ss)
    _nomori(req, fitur)
    dasar, gagal = render_basemap(view, req.basemap, dpi)
    img = dasar.convert("RGBA")
    img.alpha_composite(render_vektor(req, view, fitur, ss, dpi))
    render_label(img, req, fitur, ss, dpi)
    atribusi = (BASEMAPS.get(req.basemap) or {}).get("atribusi", "")
    render_perlengkapan(img, view, dpi, atribusi, req.grid)
    return HasilPeta(img.convert("RGB"), view, fitur, gagal, dpi)


def render_peta_indeks(req: CetakPetaRequest, view_utama: Tampilan, lebar_mm: float, tinggi_mm: float,
                       dpi: float = 150) -> Image.Image:
    """Peta lokasi kecil (Indonesia) dgn kotak merah area cetak."""
    west, south, east, north = view_utama.batas_lonlat
    b = CetakBatas(west=min(_BATAS_INDONESIA.west, west), south=min(_BATAS_INDONESIA.south, south),
                   east=max(_BATAS_INDONESIA.east, east), north=max(_BATAS_INDONESIA.north, north))
    W, H = int(lebar_mm / 25.4 * dpi), int(tinggi_mm / 25.4 * dpi)
    view = Tampilan(b, W, H)
    img, _ = render_basemap(view, "terang" if req.basemap in ("none", "terang", "osm") else req.basemap, dpi)
    img = img.convert("RGBA")
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    x0, y0 = view.px(west, north)
    x1, y1 = view.px(east, south)
    if x1 - x0 < 6:
        cx = (x0 + x1) / 2
        x0, x1 = cx - 3, cx + 3
    if y1 - y0 < 6:
        cy = (y0 + y1) / 2
        y0, y1 = cy - 3, cy + 3
    d.rectangle((x0, y0, x1, y1), fill=(220, 38, 38, 60), outline=(220, 38, 38, 255), width=max(2, int(dpi / 60)))
    img.alpha_composite(ov)
    return img.convert("RGB")


# ---------------------------------------------------------------------------
# Tabel atribut
# ---------------------------------------------------------------------------


def _teks_nilai(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        if math.isnan(v):
            return ""
        if v.is_integer() and abs(v) < 1e15:
            return _fmt_angka(v)
        return f"{v:,.3f}".rstrip("0").rstrip(".").replace(",", "_").replace(".", ",").replace("_", ".")
    if isinstance(v, bool):
        return "Ya" if v else "Tidak"
    if isinstance(v, int):
        return _fmt_angka(v) if abs(v) >= 10000 else str(v)
    if isinstance(v, (dict, list)):
        return str(v)[:200]
    s = str(v).strip()
    if "<" in s:  # deskripsi placemark KML sering berisi HTML (<br>, <b>, ...)
        s = re.sub(r"\s*<br\s*/?>\s*", "; ", s, flags=re.I)
        s = re.sub(r"<[^>]+>", "", s).strip("; ").strip()
    return s if len(s) <= 160 else s[:157] + "…"


def pilih_kolom(layer: CetakLayer, daftar, maks: int) -> List[str]:
    urut: List[str] = []
    isi: Dict[str, int] = {}
    for f in daftar:
        for k, v in f.props.items():
            if k not in isi:
                urut.append(k)
                isi[k] = 0
            if _teks_nilai(v) != "":
                isi[k] += 1
    calon = [k for k in urut if isi[k] > 0]
    utama = [layer.label_field] if layer.label_field in calon else []
    sisa = sorted((k for k in calon if k not in utama), key=lambda k: (-isi[k], urut.index(k)))
    return (utama + sisa)[:maks]


def _lebar_kolom_mm(kolom: List[str], baris, total_mm: float) -> List[float]:
    """Kolom No 11 mm; sisanya proporsional rata-rata panjang isi (dibatasi)."""
    bobot = []
    for ci, k in enumerate(kolom):
        panjang = [len(r[ci + 1]) for r in baris[:80]] or [0]
        bobot.append(min(max(len(k) * 0.8, sum(panjang) / len(panjang), 6), 38))
    sisa = total_mm - 11
    return [11.0] + [sisa * b / sum(bobot) for b in bobot]


def _maks_kolom(kertas: str, orientasi: str) -> int:
    return {("A4", "landscape"): 9, ("A4", "portrait"): 6, ("A3", "landscape"): 14, ("A3", "portrait"): 9}.get(
        (kertas, orientasi), 8)


def _tabel_layer(req: CetakPetaRequest, hasil: HasilPeta):
    """[(indeks_layer, layer, kolom, baris(list[list[str]]), total)] utk layer yg ber-tabel."""
    out = []
    maks = _maks_kolom(req.kertas, req.orientasi)
    for li, (layer, daftar) in enumerate(zip(req.layers, hasil.fitur_per_layer)):
        if not layer.tabel or not daftar:
            continue
        kolom = pilih_kolom(layer, daftar, maks)
        if not kolom:
            continue
        baris = [[f.nomor or ""] + [_teks_nilai(f.props.get(k)) for k in kolom] for f in daftar[: req.maks_baris]]
        out.append((li, layer, kolom, baris, len(daftar)))
    return out


# ---------------------------------------------------------------------------
# Info bersama PDF/DOCX
# ---------------------------------------------------------------------------

_BULAN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
          "November", "Desember"]


def _tanggal_id(dt: datetime) -> str:
    return f"{dt.day} {_BULAN[dt.month - 1]} {dt.year}, {dt:%H:%M}"


def _info_peta(req: CetakPetaRequest, hasil: HasilPeta) -> List[Tuple[str, str]]:
    west, south, east, north = hasil.view.batas_lonlat
    n_fitur = sum(len(d) for d in hasil.fitur_per_layer)
    basemap = (BASEMAPS.get(req.basemap) or {}).get("nama", "Tanpa basemap")
    if hasil.tile_gagal:
        basemap += f" ({hasil.tile_gagal} tile gagal dimuat)"
    label = {"atribut": "Nama/atribut fitur", "nomor": "Nomor fitur (rujuk tabel atribut)", "none": "Tanpa label"}
    return [
        ("Skala", f"± 1 : {_fmt_angka(_skala_bulat(hasil.skala()))} (kertas {req.kertas})"),
        ("Sistem koordinat", "Geografis WGS 84 (EPSG:4326)"),
        ("Proyeksi tampilan", "Web Mercator (EPSG:3857)"),
        ("Batas area", f"{_fmt_derajat(west, False, 0.001)} – {_fmt_derajat(east, False, 0.001)}; "
                       f"{_fmt_derajat(south, True, 0.001)} – {_fmt_derajat(north, True, 0.001)}"),
        ("Basemap", basemap),
        ("Fitur tergambar", f"{_fmt_angka(n_fitur)} fitur dari {len([d for d in hasil.fitur_per_layer if d])} layer"),
        ("Label", label.get(req.label_mode, "-")),
    ]


def _skala_bulat(s: float) -> float:
    if s <= 0:
        return 0
    e = 10 ** max(0, math.floor(math.log10(s)) - 1)
    return round(s / e) * e


def _legenda(req: CetakPetaRequest, hasil: HasilPeta):
    """[(judul_layer, [(warna, teks, jenis)], huruf)] hanya utk layer yg punya fitur tergambar."""
    out = []
    banyak_layer = len([d for d in hasil.fitur_per_layer if d]) > 1
    for li, (layer, daftar) in enumerate(zip(req.layers, hasil.fitur_per_layer)):
        if not daftar:
            continue
        huruf = _huruf_layer(li) if (banyak_layer and req.label_mode == "nomor") else ""
        sub = [(x.warna, x.teks, x.jenis, _ikon_gambar(req, x.ikon)) for x in layer.legend]
        out.append((layer.nama, sub or [(layer.warna, "", layer.jenis, _ikon_gambar(req, layer.ikon))], huruf, layer))
    return out


def _nama_file(req: CetakPetaRequest, ext: str) -> str:
    dasar = re.sub(r"[^A-Za-z0-9]+", "_", req.judul or "peta").strip("_")[:60] or "peta"
    return f"{dasar}_{datetime.now():%Y%m%d_%H%M}.{ext}"


# ---------------------------------------------------------------------------
# PDF (reportlab)
# ---------------------------------------------------------------------------

_NAVY = (15, 42, 74)
_AKSEN = (34, 211, 165)


def _rl_font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    try:
        pdfmetrics.getFont("PetaSans")
        return "PetaSans", "PetaSans-Bold"
    except KeyError:
        pass
    try:
        pdfmetrics.registerFont(TTFont("PetaSans", _font_path(False)))
        pdfmetrics.registerFont(TTFont("PetaSans-Bold", _font_path(True)))
        return "PetaSans", "PetaSans-Bold"
    except Exception:
        return "Helvetica", "Helvetica-Bold"


def _rl_warna(rgb):
    from reportlab.lib.colors import Color

    return Color(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255)


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _ukuran_halaman(req: CetakPetaRequest) -> Tuple[float, float]:
    w, h = (420.0, 297.0) if req.kertas == "A3" else (297.0, 210.0)
    return (w, h) if req.orientasi == "landscape" else (h, w)


def _gambar_simbol(c, jenis, warna, x, y, w, h, ikon=None):
    """Simbol legenda vektor di kanvas reportlab (x,y = kiri bawah, satuan pt).
    ikon (PIL RGBA) = ikon titik spt di peta; dipusatkan di kotak simbol."""
    if ikon is not None:
        from reportlab.lib.utils import ImageReader

        s = min(w, h) * 1.15
        c.drawImage(ImageReader(ikon), x + (w - s) / 2, y + (h - s) / 2, s, s,
                    preserveAspectRatio=True, anchor="c", mask="auto")
        return
    col = _rl_warna(_rgb(warna))
    if jenis == "garis":
        c.setStrokeColor(col)
        c.setLineWidth(2.2)
        c.setLineCap(1)
        c.line(x + 1, y + h / 2, x + w - 1, y + h / 2)
    elif jenis == "titik":
        c.setFillColor(col)
        c.setStrokeColorRGB(0.08, 0.1, 0.14)
        c.setLineWidth(0.6)
        c.circle(x + w / 2, y + h / 2, min(w, h) / 2.6, stroke=1, fill=1)
    else:
        c.setFillColor(col, alpha=0.4)
        c.setStrokeColor(col)
        c.setLineWidth(0.9)
        c.rect(x, y, w, h, stroke=1, fill=1)
        c.setFillAlpha(1)


def build_pdf(req: CetakPetaRequest, pengguna: Optional[str]) -> bytes:
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader, simpleSplit
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.platypus import (BaseDocTemplate, Frame, NextPageTemplate, PageBreak, PageTemplate, Paragraph,
                                    Spacer, Table, TableStyle)

    fn, fb = _rl_font()
    PW, PH = _ukuran_halaman(req)
    a3 = req.kertas == "A3"
    m = 10.0
    kepala = 20.0 if a3 else 17.0
    kaki = 7.0
    lanskap = req.orientasi == "landscape"
    dpi = 170 if a3 else 200
    if lanskap:
        sb = 86.0 if a3 else 70.0
        peta_w, peta_h = PW - 2 * m - sb - 4, PH - 2 * m - kepala - kaki - 4
        peta_x, peta_y = m, m + kaki
    else:
        panel = 82.0 if a3 else 64.0
        peta_w, peta_h = PW - 2 * m, PH - 2 * m - kepala - kaki - panel - 6
        peta_x, peta_y = m, m + kaki + panel + 3
    hasil = render_peta(req, peta_w, peta_h, dpi)
    info = _info_peta(req, hasil)
    legenda = _legenda(req, hasil)
    tabel = _tabel_layer(req, hasil) if req.sertakan_tabel else []
    sekarang = datetime.now()
    teks_kaki = f"Dicetak dari The Next - SiJalan · {_tanggal_id(sekarang)}" + (f" · oleh {pengguna}" if pengguna else "")

    buf_peta = io.BytesIO()
    hasil.gambar.save(buf_peta, format="JPEG", quality=90, optimize=True)
    buf_peta.seek(0)

    def kepala_halaman(c, judul, sub, kecil=False):
        tinggi = (9.0 if kecil else kepala) * mm
        y = PH * mm - m * mm - tinggi
        c.setFillColor(_rl_warna(_NAVY))
        c.roundRect(m * mm, y, (PW - 2 * m) * mm, tinggi, 2.2 * mm, stroke=0, fill=1)
        c.setFillColor(_rl_warna(_AKSEN))
        c.rect(m * mm, y, 2.2 * mm, tinggi, stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        if kecil:
            c.setFont(fb, 9.5)
            c.drawString((m + 5) * mm, y + 3.2 * mm, judul[:120])
            c.setFont(fn, 8)
            c.drawRightString((PW - m - 4) * mm, y + 3.2 * mm, sub)
            return
        ukuran_judul = 17 if a3 else 14.5
        c.setFont(fb, ukuran_judul)
        judul_baris = simpleSplit(judul, fb, ukuran_judul, (PW - 2 * m - 70) * mm)[:1]
        c.drawString((m + 6) * mm, y + tinggi - 7.2 * mm - (1.5 * mm if a3 else 0), judul_baris[0] if judul_baris else "")
        if sub:
            c.setFont(fn, 9)
            c.setFillColorRGB(0.8, 0.86, 0.95)
            c.drawString((m + 6) * mm, y + 3.6 * mm, simpleSplit(sub, fn, 9, (PW - 2 * m - 70) * mm)[0])
        c.setFillColor(_rl_warna(_AKSEN))
        c.setFont(fb, 9)
        c.drawRightString((PW - m - 5) * mm, y + tinggi - 6.5 * mm, "THE NEXT - SiJalan")
        c.setFillColorRGB(0.8, 0.86, 0.95)
        c.setFont(fn, 7.5)
        c.drawRightString((PW - m - 5) * mm, y + 3.6 * mm, _tanggal_id(sekarang))

    def kaki_halaman(c, doc):
        c.setStrokeColorRGB(0.8, 0.83, 0.89)
        c.setLineWidth(0.4)
        c.line(m * mm, (m + kaki - 2) * mm, (PW - m) * mm, (m + kaki - 2) * mm)
        c.setFillColorRGB(0.4, 0.45, 0.53)
        c.setFont(fn, 6.8)
        c.drawString(m * mm, m * mm + 1.2 * mm, teks_kaki)
        c.drawRightString((PW - m) * mm, m * mm + 1.2 * mm, f"Halaman {doc.page}")

    def judul_bagian(c, x, y, w, teks):
        c.setFillColor(_rl_warna(_NAVY))
        c.setFont(fb, 8.5)
        c.drawString(x, y, teks)
        c.setStrokeColor(_rl_warna(_AKSEN))
        c.setLineWidth(1.1)
        c.line(x, y - 1.6 * mm, x + w, y - 1.6 * mm)
        return y - 5.5 * mm

    def gambar_legenda(c, x, y_atas, w, y_bawah):
        y = judul_bagian(c, x, y_atas, w, "LEGENDA")
        sisa = 0
        for bi, (judul, sub, huruf, layer) in enumerate(legenda):
            if y < y_bawah + 5 * mm:
                sisa = len(legenda) - bi
                break
            kepala_layer = (f"{huruf}. " if huruf else "") + judul
            if len(sub) == 1 and not sub[0][1]:
                _gambar_simbol(c, sub[0][2], sub[0][0], x, y - 1.2 * mm, 7 * mm, 3.6 * mm, sub[0][3])
                c.setFillColorRGB(0.12, 0.16, 0.22)
                c.setFont(fn, 7.3)
                baris = simpleSplit(kepala_layer, fn, 7.3, w - 9 * mm)[:2]
                for i, t in enumerate(baris):
                    c.drawString(x + 9 * mm, y - i * 3.1 * mm, t)
                y -= (len(baris) * 3.1 + 2.2) * mm
                continue
            c.setFillColorRGB(0.12, 0.16, 0.22)
            c.setFont(fb, 7.3)
            for t in simpleSplit(kepala_layer, fb, 7.3, w)[:2]:
                c.drawString(x, y, t)
                y -= 3.3 * mm
            for warna, teks, jenis, ikon in sub:
                if y < y_bawah + 3 * mm:
                    break
                _gambar_simbol(c, jenis, warna, x + 2 * mm, y - 1 * mm, 6 * mm, 3.2 * mm, ikon)
                c.setFillColorRGB(0.2, 0.24, 0.3)
                c.setFont(fn, 6.8)
                baris = simpleSplit(teks, fn, 6.8, w - 10 * mm)[:2] if teks else [""]
                for i, t in enumerate(baris):
                    c.drawString(x + 10 * mm, y - i * 2.9 * mm, t)
                y -= (3.6 + (len(baris) - 1) * 2.9) * mm
            y -= 1.4 * mm
        if sisa:
            c.setFont(fn, 6.5)
            c.setFillColorRGB(0.45, 0.5, 0.58)
            c.drawString(x, y_bawah + 1 * mm, f"… dan {sisa} layer lain (lihat tabel lampiran)")
        return y

    def gambar_info(c, x, y_atas, w, y_bawah):
        y = judul_bagian(c, x, y_atas, w, "INFORMASI PETA")
        # lebar kolom kunci mengikuti kunci terpanjang (dulu tetap 24 mm: "Sistem koordinat"
        # / "Proyeksi tampilan" menabrak nilainya)
        kunci_w = min(max(stringWidth(k, fb, 6.8) for k, _ in info) + 2.5 * mm, w * 0.45)
        for k, v in info:
            baris = simpleSplit(v, fn, 6.8, w - kunci_w)
            if y - len(baris) * 3 * mm < y_bawah:
                break
            c.setFont(fb, 6.8)
            c.setFillColorRGB(0.3, 0.35, 0.43)
            c.drawString(x, y, k)
            c.setFont(fn, 6.8)
            c.setFillColorRGB(0.12, 0.16, 0.22)
            for i, t in enumerate(baris):
                c.drawString(x + kunci_w, y - i * 3 * mm, t)
            y -= (len(baris) * 3 + 1.2) * mm
        if req.catatan and y > y_bawah + 8 * mm:
            y -= 1.5 * mm
            y = judul_bagian(c, x, y, w, "CATATAN")
            c.setFont(fn, 6.8)
            c.setFillColorRGB(0.12, 0.16, 0.22)
            for t in simpleSplit(req.catatan, fn, 6.8, w):
                if y < y_bawah:
                    break
                c.drawString(x, y, t)
                y -= 3 * mm
        return y

    def gambar_indeks(c, x, y, w, h):
        img = render_peta_indeks(req, hasil.view, w / mm, h / mm)
        b = io.BytesIO()
        img.save(b, format="JPEG", quality=88)
        b.seek(0)
        c.drawImage(ImageReader(b), x, y, w, h)
        c.setStrokeColorRGB(0.55, 0.6, 0.68)
        c.setLineWidth(0.5)
        c.rect(x, y, w, h, stroke=1, fill=0)

    def halaman_peta(c, doc):
        kepala_halaman(c, req.judul or "Peta", req.subjudul)
        # bingkai peta
        c.drawImage(ImageReader(buf_peta), peta_x * mm, peta_y * mm, peta_w * mm, peta_h * mm)
        c.setStrokeColor(_rl_warna(_NAVY))
        c.setLineWidth(1.2)
        c.rect(peta_x * mm, peta_y * mm, peta_w * mm, peta_h * mm, stroke=1, fill=0)
        c.setStrokeColorRGB(1, 1, 1)
        c.setLineWidth(0.4)
        c.rect((peta_x + 0.8) * mm, (peta_y + 0.8) * mm, (peta_w - 1.6) * mm, (peta_h - 1.6) * mm, stroke=1, fill=0)
        if lanskap:
            sx, sw_ = (peta_x + peta_w + 4) * mm, sb * mm
            y_atas = peta_y + peta_h
            c.setFillColorRGB(0.965, 0.972, 0.984)
            c.setStrokeColorRGB(0.85, 0.88, 0.93)
            c.roundRect(sx, peta_y * mm, sw_, peta_h * mm, 2 * mm, stroke=1, fill=1)
            dalam_x, dalam_w = sx + 3.5 * mm, sw_ - 7 * mm
            indeks_h = dalam_w * 0.52
            # peta indeks di bawah, info di atasnya, legenda di atas
            gambar_indeks(c, dalam_x, (peta_y + 3.5) * mm, dalam_w, indeks_h)
            c.setFont(fn, 6.3)
            c.setFillColorRGB(0.4, 0.45, 0.53)
            c.drawString(dalam_x, (peta_y + 3.5) * mm + indeks_h + 1.3 * mm, "Peta indeks — kotak merah: area cetak")
            info_tinggi = (len(info) * 5.6 + (16 if req.catatan else 0) + 8) * mm
            info_atas = (peta_y + 3.5) * mm + indeks_h + 6 * mm + info_tinggi
            # info langsung di bawah legenda bila legenda pendek (tidak menyisakan celah kosong)
            y_leg = gambar_legenda(c, dalam_x, (y_atas - 6) * mm, dalam_w, info_atas + 2 * mm)
            gambar_info(c, dalam_x, max(info_atas, y_leg - 3 * mm), dalam_w,
                        (peta_y + 3.5) * mm + indeks_h + 5 * mm)
        else:
            py0, ph = m + kaki, (peta_y - 3 - m - kaki)
            c.setFillColorRGB(0.965, 0.972, 0.984)
            c.setStrokeColorRGB(0.85, 0.88, 0.93)
            c.roundRect(m * mm, py0 * mm, (PW - 2 * m) * mm, ph * mm, 2 * mm, stroke=1, fill=1)
            kolom_w = (PW - 2 * m - 14) / 3
            atas = (py0 + ph - 6) * mm
            gambar_legenda(c, (m + 3.5) * mm, atas, kolom_w * mm, (py0 + 3) * mm)
            gambar_info(c, (m + 7 + kolom_w) * mm, atas, kolom_w * mm, (py0 + 3) * mm)
            ih = min(ph - 12, kolom_w * 0.6)
            gambar_indeks(c, (m + 10.5 + 2 * kolom_w) * mm, (py0 + ph - 8 - ih) * mm, kolom_w * mm, ih * mm)
            c.setFont(fn, 6.3)
            c.setFillColorRGB(0.4, 0.45, 0.53)
            c.drawString((m + 10.5 + 2 * kolom_w) * mm, (py0 + ph - 6) * mm, "Peta indeks — kotak merah: area cetak")
        kaki_halaman(c, doc)

    def halaman_tabel(c, doc):
        kepala_halaman(c, req.judul or "Peta", "Lampiran — Tabel Atribut Fitur", kecil=True)
        kaki_halaman(c, doc)

    out = io.BytesIO()
    doc = BaseDocTemplate(out, pagesize=(PW * mm, PH * mm), leftMargin=m * mm, rightMargin=m * mm,
                          topMargin=m * mm, bottomMargin=m * mm, title=req.judul or "Peta",
                          author=pengguna or "The Next - SiJalan", creator="The Next - SiJalan")
    f_peta = Frame(0, 0, PW * mm, PH * mm, id="peta", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    f_tabel = Frame(m * mm, (m + kaki) * mm, (PW - 2 * m) * mm, (PH - 2 * m - kaki - 13) * mm, id="tabel",
                    leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate("peta", [f_peta], onPage=halaman_peta),
                          PageTemplate("tabel", [f_tabel], onPage=halaman_tabel)])

    story: list = [Spacer(1, 1)]
    if tabel:
        gs_sel = ParagraphStyle("sel", fontName=fn, fontSize=6.8, leading=8.2, textColor=_rl_warna((31, 41, 55)))
        gs_kepala = ParagraphStyle("kp", parent=gs_sel, fontName=fb, textColor=_rl_warna((255, 255, 255)))
        gs_judul = ParagraphStyle("jd", fontName=fb, fontSize=10, leading=13, textColor=_rl_warna(_NAVY),
                                  spaceBefore=2, spaceAfter=1)
        gs_catatan = ParagraphStyle("ct", fontName=fn, fontSize=7.2, leading=9, textColor=_rl_warna((90, 100, 115)),
                                    spaceAfter=4)
        story += [NextPageTemplate("tabel"), PageBreak()]
        lebar_total = (PW - 2 * m) * mm
        for ti, (li, layer, kolom, baris, total) in enumerate(tabel):
            huruf = _huruf_layer(li)
            story.append(Paragraph(f"{huruf}. {_esc(layer.nama)}", gs_judul))
            ket = f"{_fmt_angka(total)} fitur dalam area cetak"
            if total > len(baris):
                ket += f" — ditampilkan {_fmt_angka(len(baris))} pertama"
            if layer.sumber:
                ket += f" · Sumber: {_esc(layer.sumber)}"
            story.append(Paragraph(ket, gs_catatan))
            # lebar kolom proporsional panjang isi
            lebar = [w * mm for w in _lebar_kolom_mm(kolom, baris, lebar_total / mm)]
            data = [[Paragraph("No", gs_kepala)] + [Paragraph(_esc(k), gs_kepala) for k in kolom]]
            data += [[Paragraph(_esc(v), gs_sel) for v in r] for r in baris]
            t = Table(data, colWidths=lebar, repeatRows=1)
            gaya = [
                ("BACKGROUND", (0, 0), (-1, 0), _rl_warna(_NAVY)),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.25, _rl_warna((201, 210, 227))),
                ("LINEBELOW", (0, 0), (-1, 0), 1.2, _rl_warna(_AKSEN)),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("BACKGROUND", (0, 1), (0, -1), _rl_warna((232, 238, 248))),
            ]
            for ri in range(2, len(data), 2):
                gaya.append(("BACKGROUND", (1, ri), (-1, ri), _rl_warna((245, 247, 251))))
            t.setStyle(TableStyle(gaya))
            story.append(t)
            if ti < len(tabel) - 1:
                story.append(Spacer(1, 7 * mm))
    doc.build(story)
    return out.getvalue()


# ---------------------------------------------------------------------------
# DOCX (python-docx)
# ---------------------------------------------------------------------------


def _docx_shading(el, hex_warna: str):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    tcPr = el._tc.get_or_add_tcPr() if hasattr(el, "_tc") else el
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_warna)
    tcPr.append(shd)


def _docx_cell_margin(table, mm_pad=1.2):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    tblPr = table._tbl.tblPr
    mar = OxmlElement("w:tblCellMar")
    for sisi in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{sisi}")
        el.set(qn("w:w"), str(int(mm_pad * 56.7)))
        el.set(qn("w:type"), "dxa")
        mar.append(el)
    tblPr.append(mar)


def _docx_repeat_header(row):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    trPr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    trPr.append(el)


def _docx_field(run, instr: str):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    for tipe, teks in (("begin", None), (None, instr), ("separate", None), (None, "1"), ("end", None)):
        if tipe:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), tipe)
        elif teks == instr:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = teks
        else:
            el = OxmlElement("w:t")
            el.text = teks
        run._r.append(el)


def _swatch_png(jenis: str, warna: str, ikon=None) -> io.BytesIO:
    img = Image.new("RGBA", (84, 44), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)
    rgb = _rgb(warna)
    if ikon is not None:
        im = _ikon_ukuran(ikon, 40)
        if im.height > 42:
            im = _ikon_ukuran(ikon, 40 * 42 / im.height)
        img.paste(im, ((84 - im.width) // 2, (44 - im.height) // 2), im)
    elif jenis == "garis":
        d.line([(6, 22), (78, 22)], fill=(*rgb, 255), width=8)
    elif jenis == "titik":
        d.ellipse((28, 8, 56, 36), fill=(*rgb, 255), outline=(20, 24, 34, 255), width=3)
    else:
        d.rectangle((4, 6, 80, 38), fill=(*rgb, 110), outline=(*rgb, 255), width=4)
    b = io.BytesIO()
    img.save(b, format="PNG")
    b.seek(0)
    return b


def build_docx(req: CetakPetaRequest, pengguna: Optional[str]) -> bytes:
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.shared import Mm, Pt, RGBColor

    PW, PH = _ukuran_halaman(req)
    margin = 15.0
    isi_w, isi_h = PW - 2 * margin, PH - 2 * margin
    lanskap = req.orientasi == "landscape"
    panel_w = 74.0 if req.kertas == "A3" else 64.0
    # Tinggi peta menyisakan ruang pita judul (~32 mm, judul bisa 2 baris) +
    # caption; baris tabel berisi gambar tidak bisa dipecah Word, jadi kalau
    # kelebihan sedikit saja seluruh peta terdorong ke halaman berikutnya.
    if lanskap:
        peta_w, peta_h = isi_w - panel_w - 4, isi_h - 52
    else:
        peta_w, peta_h = isi_w, min(isi_w * 0.9, isi_h - 150)
    hasil = render_peta(req, peta_w, peta_h, 170 if req.kertas == "A3" else 200)
    info = _info_peta(req, hasil)
    legenda = _legenda(req, hasil)
    tabel = _tabel_layer(req, hasil) if req.sertakan_tabel else []
    sekarang = datetime.now()
    navy = RGBColor(*_NAVY)
    navy_hex = "%02X%02X%02X" % _NAVY

    doc = Document()
    gaya = doc.styles["Normal"]
    gaya.font.name = "Arial"
    gaya.font.size = Pt(9)
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE if lanskap else WD_ORIENT.PORTRAIT
    sec.page_width, sec.page_height = Mm(PW), Mm(PH)
    for attr in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, attr, Mm(margin))
    sec.header_distance = Mm(7)
    sec.footer_distance = Mm(7)

    # Kaki halaman
    pk = sec.footer.paragraphs[0]
    pk.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = pk.add_run(f"Dicetak dari The Next - SiJalan · {_tanggal_id(sekarang)}" + (f" · oleh {pengguna}" if pengguna else "")
                   + "    |    Halaman ")
    r.font.size = Pt(7.5)
    r.font.color.rgb = RGBColor(100, 110, 125)
    r2 = pk.add_run()
    r2.font.size = Pt(7.5)
    _docx_field(r2, "PAGE")

    # Pita judul
    pita = doc.add_table(rows=1, cols=1)
    pita.alignment = WD_TABLE_ALIGNMENT.CENTER
    sel = pita.rows[0].cells[0]
    _docx_shading(sel, navy_hex)
    p = sel.paragraphs[0]
    rj = p.add_run(req.judul or "Peta")
    rj.bold = True
    rj.font.size = Pt(18)
    rj.font.color.rgb = RGBColor(255, 255, 255)
    if req.subjudul:
        ps = sel.add_paragraph()
        rs = ps.add_run(req.subjudul)
        rs.font.size = Pt(10)
        rs.font.color.rgb = RGBColor(205, 220, 242)
    pm = sel.add_paragraph()
    rm = pm.add_run(f"THE NEXT - SiJalan  ·  {_tanggal_id(sekarang)}")
    rm.font.size = Pt(8)
    rm.bold = True
    rm.font.color.rgb = RGBColor(*_AKSEN)
    _docx_cell_margin(pita, 2.5)

    # Gambar peta + panel (legenda, info, peta indeks). Lanskap: panel di
    # samping peta (satu halaman, meniru PDF); potret: panel di bawah peta.
    b = io.BytesIO()
    hasil.gambar.save(b, format="JPEG", quality=90, optimize=True)
    b.seek(0)
    caption = (f"Gambar 1. {req.judul or 'Peta'} — skala ± 1 : {_fmt_angka(_skala_bulat(hasil.skala()))} "
               f"pada kertas {req.kertas}")

    def tulis_peta(par):
        par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        par.paragraph_format.space_before = Pt(6)
        par.paragraph_format.space_after = Pt(2)
        par.add_run().add_picture(b, width=Mm(peta_w))

    def tulis_caption(par):
        par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        rc = par.add_run(caption)
        rc.italic = True
        rc.font.size = Pt(8)
        rc.font.color.rgb = RGBColor(90, 100, 115)

    def judul_panel(par, teks):
        par.paragraph_format.space_before = Pt(4)
        par.paragraph_format.space_after = Pt(3)
        rh = par.add_run(teks)
        rh.bold = True
        rh.font.size = Pt(9.5)
        rh.font.color.rgb = navy

    def tulis_legenda(cell):
        judul_panel(cell.paragraphs[0], "LEGENDA")
        for judul, sub, huruf, layer in legenda:
            kepala_layer = (f"{huruf}. " if huruf else "") + judul
            if len(sub) == 1 and not sub[0][1]:
                pl = cell.add_paragraph()
                pl.paragraph_format.space_after = Pt(2)
                pl.add_run().add_picture(_swatch_png(sub[0][2], sub[0][0], sub[0][3]), width=Mm(7))
                rl = pl.add_run("  " + kepala_layer)
                rl.font.size = Pt(8)
                continue
            pl = cell.add_paragraph()
            pl.paragraph_format.space_after = Pt(1)
            rl = pl.add_run(kepala_layer)
            rl.bold = True
            rl.font.size = Pt(8)
            for warna, teks, jenis, ikon in sub:
                ps_ = cell.add_paragraph()
                ps_.paragraph_format.left_indent = Mm(3)
                ps_.paragraph_format.space_after = Pt(1)
                ps_.add_run().add_picture(_swatch_png(jenis, warna, ikon), width=Mm(6))
                r_ = ps_.add_run("  " + (teks or ""))
                r_.font.size = Pt(7.5)

    def tulis_info(cell, lebar_mm, pertama=False):
        judul_panel(cell.paragraphs[0] if pertama else cell.add_paragraph(), "INFORMASI PETA")
        ti = cell.add_table(rows=0, cols=2)
        ti.autofit = False
        for k, v in info:
            row = ti.add_row().cells
            row[0].width, row[1].width = Mm(24), Mm(lebar_mm - 28)
            for c_, teks, tebal in ((row[0], k, True), (row[1], v, False)):
                c_.paragraphs[0].paragraph_format.space_after = Pt(1)
                r_ = c_.paragraphs[0].add_run(teks)
                r_.bold = tebal
                r_.font.size = Pt(7.5)
                if tebal:
                    r_.font.color.rgb = RGBColor(75, 85, 100)
        if req.catatan:
            pc = cell.add_paragraph()
            pc.paragraph_format.space_before = Pt(4)
            rc_ = pc.add_run("Catatan: ")
            rc_.bold = True
            rc_.font.size = Pt(7.5)
            pc.add_run(req.catatan).font.size = Pt(7.5)

    def tulis_indeks(cell, lebar_mm, rasio=0.52):
        indeks = render_peta_indeks(req, hasil.view, lebar_mm, lebar_mm * rasio)
        bi = io.BytesIO()
        indeks.save(bi, format="JPEG", quality=88)
        bi.seek(0)
        pi = cell.add_paragraph()
        pi.paragraph_format.space_before = Pt(6)
        pi.paragraph_format.space_after = Pt(0)
        # keterangan di paragraf yg sama (line break) -- satu paragraf lebih
        # sedikit supaya panel samping lanskap tidak meluber ke halaman 2
        ri = pi.add_run("Peta indeks — kotak merah: area cetak")
        ri.font.size = Pt(7)
        ri.italic = True
        ri.add_break()
        pi.add_run().add_picture(bi, width=Mm(lebar_mm))

    t = doc.add_table(rows=1, cols=2)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    kiri, kanan = t.rows[0].cells
    if lanskap:
        kiri.width, kanan.width = Mm(peta_w + 2), Mm(panel_w)
        tulis_peta(kiri.paragraphs[0])
        tulis_caption(kiri.add_paragraph())
        _docx_shading(kanan, "F5F7FB")
        tulis_legenda(kanan)
        tulis_info(kanan, panel_w - 4)
        tulis_indeks(kanan, panel_w - 6, rasio=0.45)
        _docx_cell_margin(t, 1.5)
    else:
        # tabel panel harus di bawah peta: pindahkan elemen tabel ke setelah paragraf peta
        pp = doc.add_paragraph()
        tulis_peta(pp)
        pc = doc.add_paragraph()
        tulis_caption(pc)
        pc._p.addnext(t._tbl)
        kiri.width, kanan.width = Mm(isi_w * 0.46), Mm(isi_w * 0.54)
        for c_ in (kiri, kanan):
            _docx_shading(c_, "F5F7FB")
        tulis_legenda(kiri)
        tulis_info(kanan, isi_w * 0.54 - 4, pertama=True)
        tulis_indeks(kanan, min(58, isi_w * 0.54 - 6))
        _docx_cell_margin(t, 2.0)

    # Lampiran tabel atribut
    if tabel:
        doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        h = doc.add_paragraph()
        rh = h.add_run("Lampiran — Tabel Atribut Fitur")
        rh.bold = True
        rh.font.size = Pt(14)
        rh.font.color.rgb = navy
        for li, layer, kolom, baris, total in tabel:
            pj = doc.add_paragraph()
            pj.paragraph_format.space_before = Pt(10)
            pj.paragraph_format.keep_with_next = True
            rj_ = pj.add_run(f"{_huruf_layer(li)}. {layer.nama}")
            rj_.bold = True
            rj_.font.size = Pt(11)
            rj_.font.color.rgb = navy
            ket = f"{_fmt_angka(total)} fitur dalam area cetak"
            if total > len(baris):
                ket += f" — ditampilkan {_fmt_angka(len(baris))} pertama"
            if layer.sumber:
                ket += f" · Sumber: {layer.sumber}"
            pk_ = doc.add_paragraph()
            pk_.paragraph_format.keep_with_next = True
            rk_ = pk_.add_run(ket)
            rk_.font.size = Pt(8)
            rk_.font.color.rgb = RGBColor(90, 100, 115)
            tb = doc.add_table(rows=1, cols=len(kolom) + 1)
            tb.style = "Table Grid"
            tb.alignment = WD_TABLE_ALIGNMENT.CENTER
            tb.autofit = False
            lebar = [Mm(w) for w in _lebar_kolom_mm(kolom, baris, isi_w)]
            _docx_cell_margin(tb, 0.8)
            hdr = tb.rows[0]
            _docx_repeat_header(hdr)
            for ci, teks in enumerate(["No"] + kolom):
                c_ = hdr.cells[ci]
                c_.width = lebar[ci]
                _docx_shading(c_, navy_hex)
                r_ = c_.paragraphs[0].add_run(teks)
                r_.bold = True
                r_.font.size = Pt(7.5)
                r_.font.color.rgb = RGBColor(255, 255, 255)
            for ri_, nilai in enumerate(baris):
                sel_baris = tb.add_row().cells
                for ci, v in enumerate(nilai):
                    sel_baris[ci].width = lebar[ci]
                    r_ = sel_baris[ci].paragraphs[0].add_run(v)
                    r_.font.size = Pt(7)
                    if ci == 0:
                        r_.bold = True
                    if ri_ % 2 == 1:
                        _docx_shading(sel_baris[ci], "F3F6FB")
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def cetak(req: CetakPetaRequest, pengguna: Optional[str] = None) -> Tuple[bytes, str, str]:
    """-> (konten, media_type, nama_file)."""
    if req.kertas not in ("A4", "A3"):
        req.kertas = "A4"
    if req.orientasi not in ("landscape", "portrait"):
        req.orientasi = "landscape"
    req.maks_baris = max(1, min(int(req.maks_baris or 300), 2000))
    if req.format == "docx":
        return (build_docx(req, pengguna),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document", _nama_file(req, "docx"))
    return build_pdf(req, pengguna), "application/pdf", _nama_file(req, "pdf")
