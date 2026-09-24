# -*- coding: utf-8 -*-
"""Peta Kapasitas Lintas (KAPLIN) KA per petak jalan dari
docs/24092026/Data Kapasitas KA.xlsx (sheet "KAPLIN SUMATERA" / "KAPLIN JAWA").

Tiap baris sheet = satu petak jalan (stasiun awal -> akhir, kode stasiun
PT KAI) berikut jarak, jalur tunggal/ganda, Vmax, persinyalan, program KA
(KA/hari) dan kapasitas lintas (KA/hari). Sheet tidak membawa koordinat, jadi:

  * titik stasiun = layer "Stasiun Kereta Api" (kolom KODE PRASARANA) di
    map_layers; kode ganda (mis. ME, MP, KBG, MLI) dipilih yang terdekat ke
    jaringan rel pulau itu; kode yang tidak ada di layer dipetakan lewat
    ALIAS (nama stasiun) di bawah;
  * garis petak = jalur terpendek menyusuri layer rel ("Rel Sumatera"/
    "Rel Jawa") antara proyeksi kedua stasiun (graf rel sendiri, Dijkstra).
    Kalau stasiun >2 km dari rel, tak ada jalur, atau panjang jalur tak wajar
    dibanding JARAK di sheet (rasio di luar 0,5-2,0) -> garis lurus antar
    stasiun, ditandai "Sumber geometri" = garis lurus (perkiraan);
  * stasiun tanpa koordinat di layer (atau koordinat rusak) yang diapit dua
    stasiun bertetangga di lintas yang sama diletakkan secara INTERPOLASI di
    jalur rel antara kedua tetangganya (fraksi = jarak petak sheet), ditandai
    "Koordinat diinterpolasi (perkiraan)";
  * petak yang salah satu stasiunnya tetap tak punya koordinat (mis. stasiun
    ujung lintas) TIDAK digambar; dicetak di akhir run (dan ditulis di KAMUS_KOLOM.txt).

Keluaran: SHP di Maps/KAPASITAS LINTAS KA/ (petak + stasiun per pulau) dan
layer PostGIS (provinsi "KAPASITAS LINTAS KA", kabupaten = pulau, layer
"KAPLIN PETAK JALAN" & "KAPLIN STASIUN"). Warna garis = utilisasi (program KA
/ kapasitas), label stasiun = properti "_label" (frontend: maps-overlay.js).
Idempotent per pulau. Usage (venv aktif):
    python scripts/import_kaplin_ka.py                # Sumatera + Jawa
    python scripts/import_kaplin_ka.py --pulau Sumatera
"""
import argparse
import heapq
import io
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
import openpyxl  # noqa: E402
import shapely  # noqa: E402
from psycopg.types.json import Json  # noqa: E402
from shapely import wkb  # noqa: E402
from shapely.geometry import LineString, Point  # noqa: E402

from db import db_cursor  # noqa: E402

XLSX = ROOT / "docs" / "24092026" / "Data Kapasitas KA.xlsx"
BUCKET = "KAPASITAS LINTAS KA"
OUT_DIR = ROOT / "Maps" / BUCKET
LAYER_PETAK, LAYER_STASIUN = "KAPLIN PETAK JALAN", "KAPLIN STASIUN"
LAYER_UTAMA = "KAPLIN KORIDOR UTAMA"
# warna koridor utama (sheet "KAPLIN jawa koridor utama", kolom LINTAS UTAMA);
# legenda frontend (map-tools.js) memakai nama koridor yang sama persis
WARNA_KORIDOR = {
    "jakarta-cirebon": "#0072B2", "cirebon-semarang": "#009E73", "cirebon-jogjakarta": "#E69F00",
    "semarang-surabaya": "#D55E00", "bandung-kroya": "#CC79A7",
}

PULAU = {
    "Sumatera": {"sheet": "KAPLIN SUMATERA", "rel": "Rel Sumatera", "first_row": 6, "lat0": -3.0},
    "Jawa": {"sheet": "KAPLIN JAWA", "rel": "Rel Jawa", "first_row": 7, "lat0": -7.2,
             "sheet_utama": "KAPLIN jawa koridor utama"},
}

# kode sheet -> nama stasiun di layer (utk kode yang tidak ada di KODE PRASARANA)
ALIAS = {
    "TPP": "TITIPAPAN", "KRG": "KRUENG GEUKUE", "KRM": "KRUENG MANE", "GRK": "GEURUGOK",
    "KBL": "KUTABLANG", "PID": "PIDADA", "PJN": "PANJANG", "PBRX5": "POS BLOK X5",
    "PBRX6": "PRABUMULIH X6", "MRP": "MERAPI",
}
SNAP_MAKS_M = 2000
RASIO_WAJAR = (0.5, 2.0)
# Graf rel utama (layer "Rel Jawa"/"Rel Sumatera") terputus jadi puluhan potongan: celah kecil antar
# ujung garis (digitasi tidak menyambung) disambung bila <= GAP_JEMBATAN_M meter. Celah besar (mis.
# ruas Jatinegara-Bekasi ~3 km yang memang tidak ada di layer itu) TIDAK disambung paksa -- petak
# semacam itu dicoba lewat layer rel cadangan (FALLBACK_REL) dalam koridor sempit di sekitar petak.
GAP_JEMBATAN_M = 150
KORIDOR_PAD_DERAJAT = 0.03  # ~3 km di kiri/kanan/atas/bawah kotak batas kedua stasiun
GARIS_LURUS_DIGAMBAR = False  # True = petak tanpa jalur rel digambar sbg garis lurus (perkiraan)
LURUS_RASIO = (0.3, 1.5)  # rentang wajar panjang garis lurus / jarak petak di sheet
RASIO_FALLBACK = (0.6, 1.7)  # lebih ketat dari RASIO_WAJAR: layer cadangan bisa tumpang tindih/paralel
# urutan percobaan layer cadangan (masing-masing dipakai SENDIRI, tidak digabung -- menggabung semua
# layer sekaligus terbukti memperbanyak garis lurus karena jalur paralel saling tersambung salah)
FALLBACK_REL = [("JALUR KERETA API", "JALUR KERETA API AKTIF (BTP)"), ("JALUR KERETA API", "JALUR KERETA API"),
                ("KERETA API", "Jalur KA Perkotaan")]
WARNA = {"rendah": "#2e9e5b", "sedang": "#e0a800", "tinggi": "#d64545", "na": "#8a94a6"}


def num(v):
    return float(v) if isinstance(v, (int, float)) else None


class Xy:
    """Proyeksi equirectangular lokal (meter) -- cukup utk jarak lokal & snapping."""
    def __init__(self, lat0):
        self.kx = 111320.0 * math.cos(math.radians(lat0))
        self.ky = 110540.0

    def to_m(self, lon, lat):
        return lon * self.kx, lat * self.ky

    def to_ll(self, x, y):
        return x / self.kx, y / self.ky


def build_graph(lines, xy):
    """lines: list[list[(lon,lat)]] -> (nodes{key:(x,y)}, segs[(key_a,key_b)])."""
    nodes, segs = {}, []
    ends = []
    for ci, coords in enumerate(lines):
        keys = []
        for lon, lat in coords:
            k = (round(lon, 5), round(lat, 5))
            nodes.setdefault(k, xy.to_m(lon, lat))
            if not keys or keys[-1] != k:
                keys.append(k)
        for a, b in zip(keys, keys[1:]):
            segs.append((a, b, ci))
        if len(keys) > 1:
            ends += [(keys[0], ci), (keys[-1], ci)]
    return nodes, segs, ends


def proj_on_seg(p, a, b):
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return t, (ax + t * dx, ay + t * dy)


class Rail:
    def __init__(self, lines, xy):
        self.xy = xy
        self.nodes, self.segs, ends = build_graph(lines, xy)
        self.A = np.array([self.nodes[s[0]] for s in self.segs])
        self.B = np.array([self.nodes[s[1]] for s in self.segs])
        self.cid = np.array([s[2] for s in self.segs])
        self.inserts = {}  # idx segmen -> list[(t, key)]
        # sambungkan ujung lintas yg menempel di badan lintas lain (T-junction, <=40 m)
        for key, ci in ends:
            d, i, t, q = self.nearest(self.nodes[key], exclude_cid=ci)
            if d is not None and d <= 40 and 0 < t < 1:
                self.inserts.setdefault(i, []).append((t, key, q))
        self.adj = None
        self.sta_node = {}

    def nearest(self, p, exclude_cid=None):
        A, B = self.A, self.B
        d = B - A
        L2 = (d ** 2).sum(1)
        L2[L2 == 0] = 1e-9
        t = np.clip(((p[0] - A[:, 0]) * d[:, 0] + (p[1] - A[:, 1]) * d[:, 1]) / L2, 0, 1)
        q = A + d * t[:, None]
        dist = np.hypot(q[:, 0] - p[0], q[:, 1] - p[1])
        if exclude_cid is not None:
            dist = np.where(self.cid == exclude_cid, np.inf, dist)
        i = int(dist.argmin())
        if not np.isfinite(dist[i]):
            return None, None, None, None
        return float(dist[i]), i, float(t[i]), (float(q[i, 0]), float(q[i, 1]))

    def add_station(self, name_key, p):
        d, i, t, q = self.nearest(p)
        if d is None or d > SNAP_MAKS_M:
            return d
        node = ("P", name_key)
        self.inserts.setdefault(i, []).append((t, node, q))
        self.sta_node[name_key] = (node, q)
        return d

    def finalize(self):
        pos = dict(self.nodes)
        for lst in self.inserts.values():
            for _, key, q in lst:
                if isinstance(key, tuple) and key and key[0] == "P":
                    pos[key] = q
        adj = {}

        def edge(u, v):
            w = math.hypot(pos[u][0] - pos[v][0], pos[u][1] - pos[v][1])
            adj.setdefault(u, []).append((v, w))
            adj.setdefault(v, []).append((u, w))
        for i, (a, b, _) in enumerate(self.segs):
            chain = [a] + [k for _, k, _ in sorted(self.inserts.get(i, []), key=lambda x: x[0])] + [b]
            for u, v in zip(chain, chain[1:]):
                if u != v:
                    edge(u, v)
        self.adj, self.pos = adj, pos
        self._jembatani_celah(GAP_JEMBATAN_M)

    def _jembatani_celah(self, gap_m):
        """Sambung ujung buntu (node berderajat 1) ke node terdekat di KOMPONEN LAIN bila jaraknya
        <= gap_m. Hanya celah kecil akibat digitasi; celah besar dibiarkan (lihat GAP_JEMBATAN_M)."""
        adj, pos = self.adj, self.pos
        komp, cid = {}, 0
        for n in adj:
            if n in komp:
                continue
            st = [n]
            komp[n] = cid
            while st:
                u = st.pop()
                for v, _ in adj[u]:
                    if v not in komp:
                        komp[v] = cid
                        st.append(v)
            cid += 1
        if cid < 2:
            return
        keys = list(adj)
        P = np.array([pos[k] for k in keys])
        C = np.array([komp[k] for k in keys])
        for i, k in enumerate(keys):
            if len(adj[k]) != 1:
                continue
            d = np.hypot(P[:, 0] - P[i, 0], P[:, 1] - P[i, 1])
            d[C == C[i]] = np.inf
            j = int(d.argmin())
            if np.isfinite(d[j]) and d[j] <= gap_m:
                adj[k].append((keys[j], float(d[j])))
                adj[keys[j]].append((k, float(d[j])))

    def path(self, s, t):
        dist, prev, pq, n = {s: 0.0}, {}, [(0.0, 0, s)], 0
        while pq:
            d, _, u = heapq.heappop(pq)
            if u == t:
                break
            if d > dist.get(u, 1e18):
                continue
            for v, w in self.adj.get(u, ()):
                nd = d + w
                if nd < dist.get(v, 1e18):
                    dist[v], prev[v] = nd, u
                    n += 1
                    heapq.heappush(pq, (nd, n, v))
        if t not in dist:
            return None, None
        out, u = [t], t
        while u != s:
            u = prev[u]
            out.append(u)
        return [self.pos[k] for k in reversed(out)], dist[t]


def load_stasiun(cur):
    cur.execute(
        "SELECT attrs, ST_AsBinary(geom) AS g FROM map_layers WHERE layer='Stasiun Kereta Api'")
    res = []
    for r in cur.fetchall():
        pt = wkb.loads(bytes(r["g"]))
        a = r["attrs"]
        res.append({"kode": (a.get("KODE PRASARANA") or "").strip(), "nama": (a.get("name") or "").strip(),
                    "lon": pt.x, "lat": pt.y, "attrs": a})
    return res


def baca_petak(cfg):
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    lintas, out = "", []
    for r in wb[cfg["sheet"]].iter_rows(min_row=cfg["first_row"], values_only=True):
        if r[2]:
            lintas = str(r[2]).strip()
        if not (r[3] and r[4]):
            continue
        out.append({
            "no": r[0], "divre": r[1], "lintas": lintas, "awal": str(r[3]).strip(), "akhir": str(r[4]).strip(),
            "jarak_m": num(r[5]), "jalur": r[6], "vmax": num(r[7]), "sinyal": r[8], "program": num(r[9]),
            "kapasitas": num(r[10]), "produktivitas": num(r[11]) if len(r) > 11 else None,
            "kondisi": r[12] if len(r) > 12 and r[12] not in (None, "") else None,
        })
    return out


def baca_utama(cfg):
    """(awal, akhir) -> (koridor utama, jenis lintas elektrik/mekanik/parsial) dari sheet koridor utama."""
    if not cfg.get("sheet_utama"):
        return {}
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    out = {}
    for r in wb[cfg["sheet_utama"]].iter_rows(min_row=7, values_only=True):
        if r[5] and r[6]:
            out.setdefault((str(r[5]).strip(), str(r[6]).strip()), (
                str(r[3]).strip() if r[3] else None, str(r[4]).strip().lower() if r[4] else None))
    return out


def nama_tampil(s):
    """Nama stasiun utk label/atribut; stasiun interpolasi hanya punya kode -> tampil apa adanya."""
    return s["nama"] if s.get("interp") else s["nama"].replace("STASIUN ", "").title()


def kategori(u):
    if u is None:
        return "Tidak tersedia", WARNA["na"]
    if u < 60:
        return "Rendah (< 60%)", WARNA["rendah"]
    if u < 85:
        return "Sedang (60-85%)", WARNA["sedang"]
    return "Tinggi (≥ 85%)", WARNA["tinggi"]


def fmt(x, d=0):
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def jalur_lokal(cur, xy, a, b, jarak_m):
    """Fallback utk petak yang tidak bisa disusuri di graf rel utama: bangun graf KECIL dari satu layer
    rel cadangan (FALLBACK_REL, dicoba berurutan) hanya di koridor sekitar kedua stasiun, lalu cari jalur
    terpendek. Return (titik_xy, panjang_m, nama_layer) atau None."""
    lons, lats = sorted([a["lon"], b["lon"]]), sorted([a["lat"], b["lat"]])
    pad = KORIDOR_PAD_DERAJAT
    for prov, lay in FALLBACK_REL:
        cur.execute(
            "SELECT ST_AsBinary(geom) AS g FROM map_layers WHERE provinsi=%s AND layer=%s "
            "AND geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)",
            (prov, lay, lons[0] - pad, lats[0] - pad, lons[1] + pad, lats[1] + pad))
        lines = []
        for r in cur.fetchall():
            g = wkb.loads(bytes(r["g"]))
            for part in (g.geoms if g.geom_type.startswith("Multi") else [g]):
                lines.append(list(part.coords))
        if not lines:
            continue
        rail = Rail(lines, xy)
        rail.add_station("A", xy.to_m(a["lon"], a["lat"]))
        rail.add_station("B", xy.to_m(b["lon"], b["lat"]))
        if "A" not in rail.sta_node or "B" not in rail.sta_node:
            continue
        rail.finalize()
        pts, dist = rail.path(rail.sta_node["A"][0], rail.sta_node["B"][0])
        if pts and dist and (jarak_m is None or RASIO_FALLBACK[0] <= dist / jarak_m <= RASIO_FALLBACK[1]):
            return pts, dist, lay
    return None


def proses(pulau, cfg, stasiun_all, cur):
    xy = Xy(cfg["lat0"])
    # cfg["rel"]: satu nama layer rel, atau daftar (layer_provinsi, layer) untuk menggabung beberapa
    # sumber rel; cfg["bbox"] (minlon, minlat, maxlon, maxlat) membatasi layer nasional ke pulau ini.
    rel = cfg["rel"] if isinstance(cfg["rel"], list) else [(None, cfg["rel"])]
    kond, par = [], []
    for prov, lay in rel:
        kond.append("(layer=%s" + (" AND provinsi=%s)" if prov else ")"))
        par += [lay] + ([prov] if prov else [])
    sql = "SELECT ST_AsBinary(geom) AS g FROM map_layers WHERE (" + " OR ".join(kond) + ")"
    if cfg.get("bbox"):
        sql += " AND geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)"
        par += list(cfg["bbox"])
    cur.execute(sql, par)
    lines = []
    for r in cur.fetchall():
        g = wkb.loads(bytes(r["g"]))
        for part in (g.geoms if g.geom_type.startswith("Multi") else [g]):
            lines.append(list(part.coords))
    rail = Rail(lines, xy)
    petak = baca_petak(cfg)
    utama = baca_utama(cfg)
    for pt in petak:
        pt["koridor"], pt["jenis"] = utama.get((pt["awal"], pt["akhir"]), (None, None))
    kode_dipakai = {p["awal"] for p in petak} | {p["akhir"] for p in petak}

    # koordinat stasiun per kode: alias nama -> kode persis; ambigu -> terdekat ke rel
    by_kode, by_nama = {}, {}
    for s in stasiun_all:
        by_kode.setdefault(s["kode"], []).append(s)
        by_nama.setdefault(s["nama"].upper().replace("STASIUN ", "").strip(), []).append(s)
    pilih, tak_ketemu = {}, []
    for kode in sorted(kode_dipakai):
        cands = []
        if kode in ALIAS:
            key = ALIAS[kode]
            cands = [s for n, ss in by_nama.items() if n == key or n.startswith(key) for s in ss]
        if not cands:
            cands = by_kode.get(kode, [])
        best, bd = None, None
        for s in cands:
            d, *_ = rail.nearest(xy.to_m(s["lon"], s["lat"]))
            if d is not None and (bd is None or d < bd):
                best, bd = s, d
        if best is None or bd > SNAP_MAKS_M * 5:
            tak_ketemu.append(kode)
            continue
        pilih[kode] = best
        rail.add_station(kode, xy.to_m(best["lon"], best["lat"]))
    rail.finalize()

    # interpolasi stasiun tak berkoordinat: deret petak berurutan dalam satu lintas
    # (akhir petak i = awal petak i+1); stasiun tak berkoordinat yang diapit dua
    # stasiun berkoordinat diletakkan di jalur rel antara keduanya, sebanding
    # jarak kumulatif petak di sheet.
    interp = {}
    per_lintas = {}
    for pt in petak:
        per_lintas.setdefault(pt["lintas"], []).append(pt)
    for lst in per_lintas.values():
        deret = [[lst[0]]]
        for pt in lst[1:]:
            (deret[-1].append(pt) if pt["awal"] == deret[-1][-1]["akhir"] else deret.append([pt]))
        for seq in deret:
            nodes = [seq[0]["awal"]] + [q["akhir"] for q in seq]
            cum = [0.0]
            for q in seq:
                cum.append(cum[-1] + (q["jarak_m"] or 0.0))
            known = [k for k, n in enumerate(nodes) if n in rail.sta_node]
            for a, b in zip(known, known[1:]):
                if b - a < 2 or not (cum[b] - cum[a]) or any(nodes[k] in pilih for k in range(a + 1, b)):
                    continue
                pts, dist = rail.path(rail.sta_node[nodes[a]][0], rail.sta_node[nodes[b]][0])
                tot = cum[b] - cum[a]
                if not pts or not (0.6 <= dist / tot <= 1.6):
                    continue
                for k in range(a + 1, b):
                    target, acc = dist * (cum[k] - cum[a]) / tot, 0.0
                    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                        seg = math.hypot(x2 - x1, y2 - y1)
                        if acc + seg >= target and seg > 0:
                            f = (target - acc) / seg
                            interp[nodes[k]] = (x1 + f * (x2 - x1), y1 + f * (y2 - y1))
                            break
                        acc += seg
    for kode, q in interp.items():
        if kode not in tak_ketemu:
            continue
        lon, lat = xy.to_ll(*q)
        pilih[kode] = {"kode": kode, "nama": f"{kode} (perkiraan)", "lon": lon, "lat": lat,
                       "attrs": {"KETERANGAN": "Koordinat diinterpolasi (perkiraan)"}, "interp": True}
        rail.add_station(kode, q)
        tak_ketemu.remove(kode)
    if interp:
        rail.finalize()

    fitur, tak_gambar, stasiun_petak, fitur_utama = [], [], {}, []
    for p in petak:
        a, b = pilih.get(p["awal"]), pilih.get(p["akhir"])
        if not a or not b:
            tak_gambar.append(f"{p['awal']}-{p['akhir']} ({p['lintas']})")
            continue
        geom, sumber, glen = None, None, None
        if p["awal"] in rail.sta_node and p["akhir"] in rail.sta_node:
            pts, dist = rail.path(rail.sta_node[p["awal"]][0], rail.sta_node[p["akhir"]][0])
            if pts and dist and (p["jarak_m"] is None or RASIO_WAJAR[0] <= dist / p["jarak_m"] <= RASIO_WAJAR[1]):
                geom = LineString([xy.to_ll(x, y) for x, y in pts])
                sumber, glen = "Menyusuri jalur rel (layer Rel)", dist
        if geom is None:
            lokal = jalur_lokal(cur, xy, a, b, p["jarak_m"])
            if lokal:
                geom = LineString([xy.to_ll(x, y) for x, y in lokal[0]])
                sumber, glen = f"Menyusuri jalur rel (layer cadangan: {lokal[2]})", lokal[1]
        if geom is None and not GARIS_LURUS_DIGAMBAR:
            # permintaan user (25 Sep 2026): garis lurus antar stasiun menyesatkan (tidak di atas rel di
            # peta dasar) -> petak yang tak bisa disusuri di jaringan rel TIDAK digambar sama sekali.
            tak_gambar.append(f"{p['awal']}-{p['akhir']} ({p['lintas']}) [tak ada jalur rel yang tersambung]")
            continue
        if geom is None:
            geom = LineString([(a["lon"], a["lat"]), (b["lon"], b["lat"])])
            glen = math.hypot((a["lon"] - b["lon"]) * xy.kx, (a["lat"] - b["lat"]) * xy.ky)
            # garis lurus selalu <= panjang rel sebenarnya; kalau jauh di luar jarak petak di sheet,
            # berarti koordinat salah satu stasiun salah cocok (kode ganda/stasiun lain) -> lebih baik
            # tidak digambar daripada menggambar garis ratusan km yang menyesatkan.
            if p["jarak_m"] and not (LURUS_RASIO[0] <= glen / p["jarak_m"] <= LURUS_RASIO[1]):
                tak_gambar.append(f"{p['awal']}-{p['akhir']} ({p['lintas']}) [koordinat stasiun tidak konsisten: "
                                  f"garis lurus {glen / 1000:.1f} km vs petak {p['jarak_m'] / 1000:.1f} km]")
                continue
            sumber = "Garis lurus antar stasiun (perkiraan)"
        util = (p["program"] / p["kapasitas"] * 100) if p["program"] is not None and p["kapasitas"] else None
        kat, warna = kategori(util)
        nm_a, nm_b = (nama_tampil(a), nama_tampil(b))
        attrs = {
            "Pulau": pulau, "Divre/Daop": p["divre"], "Lintas": p["lintas"],
            "Petak Jalan": f"{nm_a} ({p['awal']}) – {nm_b} ({p['akhir']})",
            "Jarak petak (km)": fmt(p["jarak_m"] / 1000, 2) if p["jarak_m"] else None,
            "Jalur": p["jalur"], "Vmax prasarana (km/jam)": fmt(p["vmax"]) if p["vmax"] else None,
            "Persinyalan": p["sinyal"],
            "Program KA (KA/hari)": fmt(p["program"]) if p["program"] is not None else None,
            "Kapasitas lintas (KA/hari)": fmt(p["kapasitas"], 1) if p["kapasitas"] else None,
            "Utilisasi (program/kapasitas)": f"{fmt(util, 1)}%" if util is not None else None,
            "Kategori utilisasi": kat,
            "Produktivitas": fmt(p["produktivitas"], 2) if p["produktivitas"] is not None else None,
            "Kondisi prasarana": p["kondisi"],
            "Sumber geometri": sumber, "Panjang garis (km)": fmt(glen / 1000, 2),
            "Koridor utama": p["koridor"], "Jenis lintas (sheet koridor utama)": p["jenis"],
            "No. petak (sheet)": p["no"], "_warna": warna,
        }
        fitur.append((attrs, geom, {
            "PULAU": pulau, "LINTAS": p["lintas"][:80], "AWAL": p["awal"], "AKHIR": p["akhir"],
            "JARAK_M": p["jarak_m"], "JALUR": p["jalur"], "VMAX": p["vmax"], "SINYAL": p["sinyal"],
            "PROGRAM": p["program"], "KAPASITAS": p["kapasitas"], "UTIL_PCT": util,
            "KATEGORI": kat[:20], "GEOM_SRC": ("rel" if sumber.startswith("Menyusuri") else "lurus"),
        }))
        if p["koridor"]:
            au = dict(attrs)
            au["_warna"] = WARNA_KORIDOR.get(p["koridor"].lower().replace(" ", ""), "#6b7280")
            au["_lebar"] = 4
            fitur_utama.append((au, geom, {"KORIDOR": p["koridor"][:40], "AWAL": p["awal"], "AKHIR": p["akhir"],
                                           "PROGRAM": p["program"], "KAPASITAS": p["kapasitas"], "UTIL_PCT": util}))
        for kode in (p["awal"], p["akhir"]):
            stasiun_petak.setdefault(kode, []).append(f"{p['awal']}–{p['akhir']}: {fmt(p['program']) if p['program'] is not None else '-'}/"
                                                      f"{fmt(p['kapasitas']) if p['kapasitas'] else '-'} KA/hari")
    st_fitur = []
    for kode, s in pilih.items():
        if kode not in stasiun_petak:
            continue
        a = s["attrs"]
        nama = nama_tampil(s)
        attrs = {
            "Stasiun": nama, "Kode": kode, "Pulau": pulau, "Provinsi": a.get("PROVINSI"),
            "Kabupaten/Kota": a.get("KABUPATEN/ KOTA"), "Kelas stasiun": a.get("KELAS STASIUN"),
            "Status operasi": a.get("STATUS OPERASI"), "Jumlah jalur": a.get("JUMLAH JALUR"),
            "Petak terhubung (program/kapasitas)": "<br>".join(stasiun_petak[kode]),
            "_label": nama,
        }
        if s.get("interp"):
            attrs["Koordinat"] = "Diinterpolasi di jalur rel antara stasiun tetangga (perkiraan)"
        st_fitur.append((attrs, Point(s["lon"], s["lat"]), {"KODE": kode, "NAMA": nama[:60], "PULAU": pulau}))
    n_lurus = sum(1 for f in fitur if f[2]["GEOM_SRC"] == "lurus")
    print(f"[{pulau}] petak sheet {len(petak)}: digambar {len(fitur)} (garis lurus {n_lurus}); "
          f"stasiun {len(st_fitur)}; kode tanpa koordinat {len(tak_ketemu)}: {tak_ketemu}")
    if tak_gambar:
        print(f"  petak tidak digambar ({len(tak_gambar)}): {', '.join(tak_gambar)}")
    return fitur, st_fitur, tak_gambar, fitur_utama


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pulau", action="append", choices=list(PULAU), help="default: semua")
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    catatan = []
    with db_cursor() as cur:
        stasiun_all = load_stasiun(cur)
        cur.execute("DELETE FROM map_layers WHERE provinsi=%s AND kabupaten = ANY(%s)", (BUCKET, args.pulau or list(PULAU)))
        cur.execute("DELETE FROM map_layer_meta WHERE provinsi=%s AND kabupaten = ANY(%s)", (BUCKET, args.pulau or list(PULAU)))
        for pulau in args.pulau or list(PULAU):
            fitur, st_fitur, tak, fitur_utama = proses(pulau, PULAU[pulau], stasiun_all, cur)
            catatan.append(f"{pulau}: petak tidak digambar (koordinat stasiun tak ditemukan): {', '.join(tak) or '-'}")
            slug = pulau.lower()
            gpd.GeoDataFrame([{**f[2], "geometry": f[1]} for f in fitur], crs="EPSG:4326").to_file(
                OUT_DIR / f"kaplin_petak_{slug}.shp", engine="pyogrio", encoding="utf-8")
            gpd.GeoDataFrame([{**f[2], "geometry": f[1]} for f in st_fitur], crs="EPSG:4326").to_file(
                OUT_DIR / f"kaplin_stasiun_{slug}.shp", engine="pyogrio", encoding="utf-8")
            if fitur_utama:
                gpd.GeoDataFrame([{**f[2], "geometry": f[1]} for f in fitur_utama], crs="EPSG:4326").to_file(
                    OUT_DIR / f"kaplin_koridor_utama_{slug}.shp", engine="pyogrio", encoding="utf-8")
            for layer, label, items in ((LAYER_PETAK, "Kapasitas Lintas KA — Petak Jalan", fitur),
                                        (LAYER_UTAMA, "Kapasitas Lintas KA — Koridor Utama", fitur_utama),
                                        (LAYER_STASIUN, "Kapasitas Lintas KA — Stasiun (label)", st_fitur)):
                if not items:
                    continue
                rows = [(BUCKET, pulau, layer, Json({k: v for k, v in it[0].items() if v is not None}),
                         shapely.force_2d(it[1]).wkb_hex) for it in items]
                cur.executemany(
                    "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
                    "VALUES (%s, %s, %s, %s, ST_GeomFromWKB(decode(%s, 'hex'), 4326))", rows)
                size = sum(len(r[4]) + len(str(r[3].obj)) for r in rows) / 1_048_576
                cur.execute(
                    "INSERT INTO map_layer_meta (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (BUCKET, pulau, layer, label, len(rows), round(size, 2), f"{BUCKET}/kaplin_*_{slug}.shp"))
    (OUT_DIR / "KAMUS_KOLOM.txt").write_text(
        "Sumber: docs/24092026/Data Kapasitas KA.xlsx (sheet KAPLIN SUMATERA / KAPLIN JAWA). WGS84.\n"
        "kaplin_petak_<pulau>.shp : PULAU, LINTAS, AWAL/AKHIR (kode stasiun), JARAK_M, JALUR, VMAX, SINYAL, PROGRAM (KA/hari),\n"
        "  KAPASITAS (KA/hari), UTIL_PCT (=PROGRAM/KAPASITAS*100), KATEGORI, GEOM_SRC (rel = menyusuri layer rel, lurus = perkiraan)\n"
        "kaplin_stasiun_<pulau>.shp : KODE, NAMA, PULAU\n"
        + "\n".join(catatan) + "\n", encoding="utf-8")
    print("Selesai.")


if __name__ == "__main__":
    main()
