# -*- coding: utf-8 -*-
"""Peta arus perdagangan domestik antar provinsi (IRIO 34 provinsi x 52 industri).

Sumber: docs/24092026/tabel-inter-regional-input-output-indonesia-transaksi-
domestik-atas-dasar-harga-produsen-menurut-34-provinsi-dan-52-industri.xlsx
(dibaca lewat scripts/irio_arus_parse.py: 34 sheet "Penjualan <Provinsi>").

Menghasilkan:
  1. SHP polyline (garis lengkung asal -> tujuan antar ibu kota provinsi) di
     Maps/ARUS PERDAGANGAN ANTAR PROVINSI/ : arus_perdagangan_rupiah.shp dan
     arus_perdagangan_ton.shp (geometri sama, kolom LEBAR_PX = ketebalan garis
     menurut rupiah / ton), + arus_perdagangan_detail_industri.csv (industri
     per pasangan, lengkap) + KAMUS_KOLOM.txt.
  2. Layer overlay PostGIS (map_layers/map_layer_meta): provinsi bucket
     "ARUS PERDAGANGAN ANTAR PROVINSI", layer "ARUS PERDAGANGAN RUPIAH" dan
     "ARUS PERDAGANGAN TON". Atribut popup identify lengkap (top industri,
     jenis muatan, arus balik, persentase moda bila ada).

Ketebalan garis: skala log dari persentil-2 s.d. maks nilai (0.8 - 12 px).
Titik provinsi = ibu kota provinsi (pelabuhan utama umumnya di sana), BUKAN
centroid poligon; Papua = 94 lama (Jayapura), Papua Barat = 91 lama
(Manokwari) sesuai 34 provinsi di sumber. Arus dua arah dibuat garis lengkung
ke sisi berlawanan supaya tidak menumpuk. Arus intra-provinsi (diagonal)
tidak digambar. Persentase moda (Jalan/Laut/Udara/ASDP/KA) di sumber hanya
terisi utk sebagian kecil pasangan -> ditampilkan bila ada, TIDAK diekstrapolasi.

Idempotent (hapus + isi ulang kedua layer). Usage (venv aktif):
    python scripts/import_arus_irio_provinsi.py
"""
import csv
import io
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import geopandas as gpd  # noqa: E402
import shapely  # noqa: E402
from psycopg.types.json import Json  # noqa: E402
from shapely.geometry import LineString  # noqa: E402

from db import db_cursor  # noqa: E402
from irio_arus_parse import parse  # noqa: E402
from wilayah_pulau import PULAU_BY_KODE_PROVINSI  # noqa: E402

BUCKET = "ARUS PERDAGANGAN ANTAR PROVINSI"
OUT_DIR = ROOT / "Maps" / BUCKET
LAYERS = {
    "rp": ("ARUS PERDAGANGAN RUPIAH", "Arus Perdagangan Antar Provinsi — ketebalan = nilai transaksi (Rp)", "arus_perdagangan_rupiah.shp"),
    "ton": ("ARUS PERDAGANGAN TON", "Arus Perdagangan Antar Provinsi — ketebalan = volume (ton)", "arus_perdagangan_ton.shp"),
}
W_MIN, W_MAX = 0.8, 12.0

# kode BPS 34 provinsi -> (lat, lon) ibu kota provinsi
IBUKOTA = {
    11: (5.548, 95.323), 12: (3.595, 98.672), 13: (-0.947, 100.417), 14: (0.507, 101.447),
    15: (-1.610, 103.613), 16: (-2.976, 104.775), 17: (-3.800, 102.256), 18: (-5.429, 105.261),
    19: (-2.130, 106.114), 21: (0.918, 104.446), 31: (-6.208, 106.846), 32: (-6.917, 107.619),
    33: (-6.966, 110.417), 34: (-7.797, 110.370), 35: (-7.250, 112.751), 36: (-6.120, 106.150),
    51: (-8.650, 115.217), 52: (-8.583, 116.117), 53: (-10.178, 123.607), 61: (-0.026, 109.342),
    62: (-2.210, 113.917), 63: (-3.319, 114.591), 64: (-0.502, 117.154), 65: (2.838, 117.366),
    71: (1.474, 124.842), 72: (-0.900, 119.870), 73: (-5.147, 119.433), 74: (-3.972, 122.515),
    75: (0.540, 123.060), 76: (-2.674, 118.888), 81: (-3.695, 128.181), 82: (0.735, 127.569),
    91: (-0.862, 134.062), 94: (-2.533, 140.717),
}
MODA_LABEL = {"jalan": "Jalan", "laut": "Laut", "udara": "Udara", "asdp": "ASDP (penyeberangan)", "ka": "KA"}


def busur(a, b, arah_sisi, n=24, lengkung=0.16):
    """Kurva bezier kuadrat a->b (lat,lon); titik kontrol digeser tegak lurus."""
    (la, lo), (lb, lb2) = a, b
    mx, my = (lo + lb2) / 2, (la + lb) / 2
    dx, dy = lb2 - lo, lb - la
    cx, cy = mx + arah_sisi * -dy * lengkung, my + arah_sisi * dx * lengkung
    pts = []
    for i in range(n + 1):
        t = i / n
        x = (1 - t) ** 2 * lo + 2 * (1 - t) * t * cx + t ** 2 * lb2
        y = (1 - t) ** 2 * la + 2 * (1 - t) * t * cy + t ** 2 * lb
        pts.append((x, y))
    return LineString(pts)


def fmt(x, d=0):
    s = f"{x:,.{d}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def lebar(nilai, lo, hi):
    if nilai <= 0:
        return W_MIN
    t = (math.log(max(nilai, lo)) - math.log(lo)) / (math.log(hi) - math.log(lo)) if hi > lo else 1
    return round(W_MIN + (W_MAX - W_MIN) * min(1.0, max(0.0, t)), 2)


def top_industri(ind, vals, k=5, satuan=""):
    idx = sorted(range(len(vals)), key=lambda i: -vals[i])[:k]
    return [f"{ind[i][0]}: {fmt(vals[i])}{satuan}" for i in idx if vals[i] > 0]


def main():
    pairs, provs = parse()
    kode_nama = {}
    for _, dest in provs:
        for k, n in dest:
            kode_nama[k] = n
    kode_asal = {t.replace("Penjualan ", ""): dest[i][0] for i, (t, dest) in enumerate(provs)}
    assert set(kode_asal.values()) == set(IBUKOTA), "kode provinsi sumber tidak cocok dgn tabel ibu kota"

    # agregat per pasangan (asal != tujuan)
    data = {}
    for (asal, kt), p in pairs.items():
        ka = kode_asal[asal]
        if ka == kt:
            continue
        ind = p["industri"]
        ton_kind = {"kontainer": 0.0, "curah": 0.0, "mp": 0.0}
        rp_barang = rp_jasa = 0.0
        for i, (_, jenis) in enumerate(ind):
            if jenis in ton_kind:
                ton_kind[jenis] += p["ton"][i]
                rp_barang += p["rp"][i]
            else:
                rp_jasa += p["rp"][i]
        data[(ka, kt)] = {
            "p": p, "rp": sum(p["rp"]), "ton": sum(p["ton"]),
            "rp_barang": rp_barang, "rp_jasa": rp_jasa, **{f"ton_{k}": v for k, v in ton_kind.items()},
        }
    for key, d in data.items():
        rev = data.get((key[1], key[0]))
        d["rp_balik"], d["ton_balik"] = (rev["rp"], rev["ton"]) if rev else (0.0, 0.0)

    def rank(field):
        order = sorted(data, key=lambda k: -data[k][field])
        return {k: i + 1 for i, k in enumerate(order)}
    rank_rp, rank_ton = rank("rp"), rank("ton")
    n = len(data)

    def batas(field):
        v = sorted(d[field] for d in data.values() if d[field] > 0)
        return v[int(len(v) * 0.02)], v[-1]
    rng = {"rp": batas("rp"), "ton": batas("ton")}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    feats = {"rp": [], "ton": []}
    for (ka, kt), d in sorted(data.items()):
        p = d["p"]
        a, b = IBUKOTA[ka], IBUKOTA[kt]
        sisi = 1 if ka < kt else -1
        geom = busur(a, b, sisi)
        na, nt = kode_nama[ka], kode_nama[kt]
        moda = "; ".join(f"{MODA_LABEL[k]} {v * 100:.2f}%" for k, v in p["moda"].items()) or None
        top_rp = top_industri(p["industri"], p["rp"], 5, " juta Rp")
        top_ton = top_industri(p["industri"], p["ton"], 5, " ton")
        base = {
            "Provinsi Asal": na, "Provinsi Tujuan": nt,
            "Transaksi": f"Rp {fmt(d['rp'])} juta (≈ Rp {fmt(d['rp'] / 1e6, 2)} triliun)",
            "Volume": f"{fmt(d['ton'])} ton",
            "Peringkat Rupiah": f"{rank_rp[(ka, kt)]} dari {n} pasangan",
            "Peringkat Ton": f"{rank_ton[(ka, kt)]} dari {n} pasangan",
            "Ton per jenis muatan": f"Kontainer {fmt(d['ton_kontainer'])} · Curah {fmt(d['ton_curah'])} · Multipurpose {fmt(d['ton_mp'])}",
            "Rupiah barang / jasa": f"Barang Rp {fmt(d['rp_barang'])} juta · Jasa Rp {fmt(d['rp_jasa'])} juta",
            "Arus balik (tujuan→asal)": f"Rp {fmt(d['rp_balik'])} juta · {fmt(d['ton_balik'])} ton",
            "Neraca (asal−balik)": f"Rp {fmt(d['rp'] - d['rp_balik'])} juta · {fmt(d['ton'] - d['ton_balik'])} ton",
            "Top 5 industri (Rp)": "<br>".join(top_rp) or None,
            "Top 5 industri (ton)": "<br>".join(top_ton) or None,
            "Persentase moda (sumber)": moda,
        }
        for k in ("rp", "ton"):
            if d[k] <= 0:
                continue
            w = lebar(d[k], *rng[k])
            attrs = dict(base)
            attrs["Pulau Asal"] = PULAU_BY_KODE_PROVINSI.get(ka)
            attrs["Pulau Tujuan"] = PULAU_BY_KODE_PROVINSI.get(kt)
            attrs["Ketebalan garis (px)"] = w
            # awalan "_" = atribut teknis utk legenda/filter frontend, tidak
            # ditampilkan di popup identify (map-tools.js)
            attrs["_nilai"] = round(d[k], 2)
            shp = {
                "ASAL": na, "TUJUAN": nt, "KODE_ASAL": ka, "KODE_TUJ": kt,
                "RP_JUTA": round(d["rp"], 2), "TON": round(d["ton"], 2),
                "RP_BARANG": round(d["rp_barang"], 2), "RP_JASA": round(d["rp_jasa"], 2),
                "TON_KONT": round(d["ton_kontainer"], 2), "TON_CURAH": round(d["ton_curah"], 2),
                "TON_MP": round(d["ton_mp"], 2), "RP_BALIK": round(d["rp_balik"], 2),
                "TON_BALIK": round(d["ton_balik"], 2), "RANK_RP": rank_rp[(ka, kt)],
                "RANK_TON": rank_ton[(ka, kt)], "LEBAR_PX": w,
                "PULAU_ASAL": PULAU_BY_KODE_PROVINSI.get(ka), "PULAU_TUJ": PULAU_BY_KODE_PROVINSI.get(kt),
                "TOP_RP": "; ".join(top_rp)[:250], "TOP_TON": "; ".join(top_ton)[:250],
                "MODA": (moda or "")[:250], "geometry": geom,
            }
            feats[k].append((attrs, shp, geom))

    # 1. SHP + CSV detail
    for k, (_, _, fname) in LAYERS.items():
        gdf = gpd.GeoDataFrame([f[1] for f in feats[k]], crs="EPSG:4326")
        gdf.to_file(OUT_DIR / fname, engine="pyogrio", encoding="utf-8")
        print(f"  SHP {fname}: {len(gdf)} garis")
    with open(OUT_DIR / "arus_perdagangan_detail_industri.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["kode_asal", "provinsi_asal", "kode_tujuan", "provinsi_tujuan", "industri",
                    "jenis_muatan", "transaksi_juta_rp", "volume_ton"])
        for (ka, kt), d in sorted(data.items()):
            p = d["p"]
            for i, (nama, jenis) in enumerate(p["industri"]):
                if p["rp"][i] or p["ton"][i]:
                    w.writerow([ka, kode_nama[ka], kt, kode_nama[kt], nama, jenis or "jasa",
                                round(p["rp"][i], 4), round(p["ton"][i], 4)])
    (OUT_DIR / "KAMUS_KOLOM.txt").write_text(
        "Sumber: IRIO 34 provinsi x 52 industri, transaksi domestik atas dasar harga produsen (sheet Penjualan <Provinsi>).\n"
        "Garis lengkung asal->tujuan antar ibu kota provinsi; intra-provinsi tidak digambar. WGS84.\n"
        "ASAL/TUJUAN/KODE_ASAL/KODE_TUJ : provinsi asal & tujuan (kode BPS lama 34 provinsi)\n"
        "RP_JUTA : total transaksi (juta rupiah), RP_BARANG barang berwujud, RP_JASA jasa\n"
        "TON : total volume (ton) = rupiah x faktor ton/rupiah per industri (sheet); TON_KONT/TON_CURAH/TON_MP per jenis muatan\n"
        "RP_BALIK/TON_BALIK : arus sebaliknya (tujuan->asal); RANK_RP/RANK_TON : peringkat dari semua pasangan\n"
        "PULAU_ASAL/PULAU_TUJ : gugus pulau (Sumatera, Jawa, Bali & Nusa Tenggara, Kalimantan, Sulawesi, Maluku, Papua)\n"
        "LEBAR_PX : ketebalan garis (skala log, 0.8-12 px) menurut rupiah (file _rupiah) atau ton (file _ton)\n"
        "TOP_RP/TOP_TON : 5 industri terbesar (dipotong 250 karakter); MODA : persentase moda bila ada di sumber (sebagian kecil pasangan)\n"
        "Detail lengkap industri: arus_perdagangan_detail_industri.csv\n", encoding="utf-8")

    # 2. PostGIS
    with db_cursor() as cur:
        for k, (layer, label, fname) in LAYERS.items():
            cur.execute("DELETE FROM map_layers WHERE provinsi=%s AND kabupaten='' AND layer=%s", (BUCKET, layer))
            cur.execute("DELETE FROM map_layer_meta WHERE provinsi=%s AND kabupaten='' AND layer=%s", (BUCKET, layer))
            rows = [(BUCKET, "", layer, Json({a: v for a, v in at.items() if v is not None}), shapely.force_2d(g).wkb_hex)
                    for at, _, g in feats[k]]
            cur.executemany(
                "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
                "VALUES (%s, %s, %s, %s, ST_GeomFromWKB(decode(%s, 'hex'), 4326))", rows)
            size = sum(len(r[4]) + len(str(r[3].obj)) for r in rows) / 1_048_576
            cur.execute(
                "INSERT INTO map_layer_meta (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp) "
                "VALUES (%s, '', %s, %s, %s, %s, %s)",
                (BUCKET, layer, label, len(rows), round(size, 2), f"{BUCKET}/{fname}"))
            print(f"  PostGIS {layer}: {len(rows)} fitur")
    print("Selesai.")


if __name__ == "__main__":
    main()
