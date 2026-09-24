"""Profil Urban & Darat (kerangka "Tim Urban dan Darat", tahap 1).

Kerangka: docs/24092026/Kerangka Berpikir Tim Urban dan Darat.pptx; kajian:
docs/kajian_tim_urban_darat_ketersediaan_data.md. Empat sheet data +
Ketersediaan Data + Keterangan:

  Penyeberangan       per pelabuhan penyeberangan (slide 7)
  Perintis Kab-Kota   per kab/kota (slide 10)
  Integrasi Antarmoda per kab/kota (slide 8-9), TANPA indeks komposit
  Terminal Tipe A     per terminal (slide 6)

Dipakai endpoint /api/urban-darat/* (app.py, moda Darat). Sel kosong = data
tidak tersedia, bukan nol. Tidak ada skor/bobot: deck tidak menetapkannya.
"""
import io
import re
import time
from collections import defaultdict

import numpy as np
import pandas as pd

from road_safety import _q, load_wilayah, points_by_kab, write_workbook

_CACHE_TTL_DETIK = 600
_cache = {"ts": 0.0, "sheets": None}

SHEETS = ["Penyeberangan", "Perintis Kab-Kota", "Integrasi Antarmoda", "Terminal Tipe A",
          "Ketersediaan Data", "Keterangan"]

# Slide kerangka -> status data (dokumen kajian §1-2), agar celah terlihat langsung di file.
KETERSEDIAAN = [
    (2, "Jaringan transportasi umum perkotaan (koridor, headway, load factor, overlay guna lahan)", "Belum ada", "Tidak ada SHP jaringan angkutan umum, headway, load factor, guna lahan, job density. Ada sebagian: od_lrt_jabodebek, ka_perkotaan_layanan, rekap_penumpang_ka_nasional, layer RTRW"),
    (3, "Kebutuhan pengembangan transportasi publik: kapasitas fiskal", "Tersedia", "kemantapan_ijd_2026 (rasio_kfd, kategori_fiskal) -> sheet Integrasi Antarmoda"),
    (3, "Kebutuhan pengembangan transportasi publik: LoS, kelembagaan, dokumen SUMP/Masterplan", "Belum ada", "Perlu diminta ke daerah/Kemenhub"),
    (4, "Data suplai-demand metropolitan", "Belum ada", "Slide berisi daftar permintaan data (Dishub, operator, BPTJ, Bappeda, BPS), bukan analisis"),
    (5, "Arus barang perkotaan", "Belum ada", "Slide berisi daftar permintaan data; tidak ada data pasar/hub/loading zone/jam larangan truk"),
    (6, "Terminal: titik (nama, koordinat)", "Sebagian", "125 titik Terminal Tipe A, 29 provinsi -> sheet Terminal Tipe A. Tipe B/C tidak ada"),
    (6, "Terminal: data fisik, operasional (penumpang, bus, trayek), kebijakan (RITP, SK)", "Belum ada", "Skoring prioritas penanganan terminal belum layak"),
    (7, "Penyeberangan: titik, kelas, dermaga, kapasitas kapal, status operasi", "Tersedia", "Layer PELABUHAN PENYEBRANGAN (254) -> sheet Penyeberangan"),
    (7, "Penyeberangan: lintas perintis, target trip", "Tersedia", "angkutan_perintis jenis PENYEBERANGAN_PERINTIS (265, target_trip_2026)"),
    (7, "Penyeberangan: arus penumpang/kendaraan, load factor, frekuensi trip", "Belum ada", "bps_kinerja_pelabuhan terutama pelabuhan laut; load factor/frekuensi tidak ada"),
    (7, "Penyeberangan: kedalaman kolam/alur, batimetri, kerawanan pesisir", "Belum ada", "-"),
    (8, "Integrasi antarmoda: jumlah simpul per moda, tipologi 3T/KSPEAN", "Tersedia", "-> sheet Integrasi Antarmoda (flag 3TP/KSPEAN dari layer Wilayah Prioritas + lokus Bappenas)"),
    (8, "Integrasi antarmoda: delineasi wilayah metropolitan (WM)", "Belum ada", "Perlu daftar kab/kota metropolitan dari pemilik kerangka"),
    (8, "Integrasi antarmoda: jadwal, headway, tarif/tiket, waktu transfer, O-D, biaya logistik", "Belum ada", "Hanya O-D LRT Jabodebek"),
    (9, "Indeks keterpaduan antarmoda", "Belum dihitung", "Bobot per tipologi tidak ditetapkan di deck; sheet Integrasi Antarmoda hanya memuat variabel penyusunnya"),
    (10, "Perintis: trayek, lintas, rute eksisting; wilayah layanan (3T, KSPN, prioritas)", "Tersedia", "angkutan_perintis (632) + layer rute/titik perintis -> sheet Perintis Kab-Kota"),
    (10, "Perintis: realisasi trip, penumpang, muatan, subsidi, harga komoditas, kunjungan wisata", "Belum ada", "Hanya target_trip_2026 untuk penyeberangan"),
]

KETERANGAN = [
    "Profil Urban & Darat (tahap 1) dari kerangka 'Tim Urban dan Darat'. Kajian: docs/kajian_tim_urban_darat_ketersediaan_data.md.",
    "Sel kosong = data tidak tersedia (bukan nol). Tidak ada skor/indeks komposit: bobot tidak ditetapkan di kerangka.",
    "Titik layer (pelabuhan, terminal, stasiun, bandara, titik perintis) dipetakan ke kab/kota lewat spatial join ke poligon BATAS KECAMATAN.",
    "Jarak antarsimpul = garis lurus (haversine), bukan jarak tempuh jalan. Jarak ke jalan nasional dibatasi radius ~55 km (kosong bila lebih jauh).",
    "Terminal Tipe A hanya tercakup di 29 provinsi; di provinsi lain kolom jumlah terminal dikosongkan, bukan 0.",
    "Tipologi: 3TP dan KSPEAN dari layer 'Wilayah Prioritas' (ANGKUTAN PERINTIS, 96 kab/kota); Lokus PKSN/Perbatasan/LOKPRI dari bappenas_lokus_a. Wilayah Metropolitan belum ada delineasinya.",
    "'Lokus 3T tanpa titik layanan perintis' = perkiraan: kab/kota berflag 3TP/PKSN/Perbatasan/LOKPRI tanpa satu pun titik layer perintis (jalan, penyeberangan, laut, udara, KSPN, barang).",
    "Kolom 'Kode Status Operasi (sumber)' pada sheet Penyeberangan adalah kode mentah STAT_OPS dari layer sumber (makna kode belum terdokumentasi).",
    "Lintas perintis pada sheet Penyeberangan dicocokkan lewat kemiripan nama pelabuhan dengan nama trayek (perkiraan); angkutan_perintis tidak punya kunci join ke pelabuhan.",
    "Metropolitan/KSPEAN resmi, terminal tipe B/C, realisasi layanan perintis, LoS/kelembagaan/SUMP, dan data suplai-demand perkotaan belum ada di database (lihat sheet Ketersediaan Data).",
]


def _haversine_min(lat, lon, targets):
    """Jarak (km) & indeks titik terdekat dari (lat, lon) ke array targets (n,2 lat/lon)."""
    if targets is None or not len(targets):
        return None, None
    la1, lo1 = np.radians(lat), np.radians(lon)
    la2, lo2 = np.radians(targets[:, 0]), np.radians(targets[:, 1])
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    d = 2 * 6371.0088 * np.arcsin(np.sqrt(a))
    i = int(np.argmin(d))
    return float(d[i]), i


def _nearest_road(points):
    """points: [(lat, lon)] -> [(nama, kelas, fungsi, jarak_km) | None] ruas jalan nasional
    terdekat dalam radius 0.5 derajat (~55 km); ST_DWithin memakai indeks spasial."""
    if not points:
        return []
    vals = ",".join(f"({i},{float(lo)},{float(la)})" for i, (la, lo) in enumerate(points))
    rows = _q(f"""
        select v.i, r.nm, r.cls, r.fn, r.d
        from (values {vals}) as v(i, lon, lat)
        left join lateral (
            select attrs->>'LINK_NAME' nm, attrs->>'ROAD_CLASS' cls, attrs->>'ROAD_FUNCT' fn,
                   ST_Distance(geom::geography, ST_SetSRID(ST_Point(v.lon, v.lat), 4326)::geography)/1000 d
            from map_layers
            where provinsi='JALAN NASIONAL' and layer='Jalan Nasional'
              and ST_DWithin(geom, ST_SetSRID(ST_Point(v.lon, v.lat), 4326), 0.5)
            order by geom <-> ST_SetSRID(ST_Point(v.lon, v.lat), 4326) limit 1) r on true
        order by v.i""")
    return [(r["nm"], r["cls"], r["fn"], float(r["d"])) if r["nm"] else None for r in rows]


def _arr(rows):
    return np.array([[r["_lat"], r["_lon"]] for r in rows]) if rows else None


def _r(v, n=1):
    return None if v is None else round(v, n)


def _build():
    master, kode_from_text = load_wilayah()
    pend = dict(zip(master.kode_kab, master.penduduk_2025))
    prov_kab = dict(zip(master.kode_kab, master.provinsi))

    pp = points_by_kab(kode_from_text, "PELABUHAN PENYEBRANGAN", "PP")
    term = points_by_kab(kode_from_text, "TERMINAL TIPE A", "TERMINAL TIPE A")
    stasiun = points_by_kab(kode_from_text, "KERETA API", "Stasiun Kereta Api")
    bandara = points_by_kab(kode_from_text, "BANDARA", "Bandara")
    plaut = points_by_kab(kode_from_text, "PELABUHAN LAUT", "PELABUHAN_PT")
    perintis_layers = {
        "Titik Jalan Perintis": "Titik Jalan Perintis",
        "Titik Penyeberangan Perintis": "Titik Penyeberangan Perintis",
        "Titik Angkutan Penumpang Laut": "Titik Angkutan Penumpang Laut",
        "Titik Angkutan Barang Laut": "Titik Angkutan Barang Laut",
        "Titik Angkutan Darat Barang": "Titik Angkutan Darat Barang",
        "Titik Udara": "Titik Udara",
        "Titik KSPN": "Titik KSPN",
    }
    perintis_pts = {k: points_by_kab(kode_from_text, "ANGKUTAN PERINTIS", v) for k, v in perintis_layers.items()}

    def cnt(rows):
        c = defaultdict(int)
        for r in rows:
            if r["_kode_kab"]:
                c[r["_kode_kab"]] += 1
        return c

    A_st, A_bd, A_pl, A_pp, A_tm = _arr(stasiun), _arr(bandara), _arr(plaut), _arr(pp), _arr(term)

    # ---- flag tipologi & lokus per kab
    wilayah_prioritas = {}
    for r in _q("""select attrs from map_layers where provinsi='ANGKUTAN PERINTIS' and layer='Wilayah Prioritas'"""):
        a = r["attrs"]
        k = kode_from_text(a.get("Provinsi"), a.get("Kab/Kota"))
        if k:
            wilayah_prioritas[k] = a
    lokus = defaultdict(set)
    for r in _q("""select kriteria, kode_kabupaten from bappenas_lokus_a
                   where kriteria in ('PKSN','PERBATASAN','LOKPRI_RPJMN') and kode_kabupaten is not null"""):
        lokus[r["kriteria"]].add(str(r["kode_kabupaten"]))
    fiskal = {str(r["kode_wilayah"]): r for r in _q(
        "select kode_wilayah, rasio_kfd, kategori_fiskal from kemantapan_ijd_2026 where jenis_adm in ('Kab.','Kota')")}

    # ---- perintis tabel (barang & BTS punya kolom wilayah teks)
    perintis_rows = _q("select * from angkutan_perintis")
    perintis_tabel_kab = defaultdict(int)
    for r in perintis_rows:
        if r["wilayah"]:
            k = kode_from_text(r["provinsi"], r["wilayah"])
            if k:
                perintis_tabel_kab[k] += 1
    penyeb_perintis = [r for r in perintis_rows if r["jenis"] == "PENYEBERANGAN_PERINTIS"]

    # ================= Sheet Penyeberangan
    road_pp = _nearest_road([(r["_lat"], r["_lon"]) for r in pp])
    rows_pp = []
    for r, road in zip(pp, road_pp):
        lat, lon = r["_lat"], r["_lon"]
        d_st, _ = _haversine_min(lat, lon, A_st)
        d_bd, _ = _haversine_min(lat, lon, A_bd)
        d_tm, _ = _haversine_min(lat, lon, A_tm)
        d_pl, _ = _haversine_min(lat, lon, A_pl)
        nm = (r.get("NAMOBJ") or "").upper().strip()
        prov = (r.get("PROV") or "").upper()
        lintas = sorted({t["nama_trayek"] for t in penyeb_perintis
                         if nm and len(nm) > 3 and nm in (t["nama_trayek"] or "").upper()
                         and (not prov or prov.split()[0] in (t["provinsi"] or "").upper())})
        k = r["_kode_kab"]
        rows_pp.append({
            "Kode Kab/Kota": k, "Provinsi": r.get("PROV") or prov_kab.get(k), "Kab/Kota (sumber)": r.get("KABKOT"),
            "Kab/Kota (poligon)": r["_kab_poligon"], "Kecamatan (poligon)": r["_kec_poligon"],
            "Nama Pelabuhan": r.get("NAMOBJ"), "Lintas (sumber)": None if r.get("LINTAS") in (None, "-") else r.get("LINTAS"),
            "Kelas": {0.0: None, 996.0: None}.get(r.get("KELAS"), r.get("KELAS")),
            "Kode Status Operasi (sumber)": r.get("STAT_OPS"),
            "Tipe Dermaga": None if r.get("TPDRM") in (None, "-") else r.get("TPDRM"),
            "Jumlah Dermaga": r.get("JML_DMG"), "Panjang Dermaga (m)": r.get("PNJ_DMG"),
            "Kapasitas Maks Kapal": r.get("KPSMAX"),
            "Konstruksi": None if r.get("KONFBM") in (None, "-") else r.get("KONFBM"),
            "Terminal Penumpang (kode)": r.get("TERM_PNP"),
            "Latitude": lat, "Longitude": lon,
            "Penduduk Kab/Kota 2025": int(pend[k]) if k in pend and pend[k] else None,
            "Jarak ke Stasiun KA Terdekat (km)": _r(d_st), "Jarak ke Bandara Terdekat (km)": _r(d_bd),
            "Jarak ke Terminal Tipe A Terdekat (km)": _r(d_tm), "Jarak ke Pelabuhan Laut Terdekat (km)": _r(d_pl),
            "Jalan Nasional Terdekat": road[0] if road else None,
            "Kelas/Fungsi Jalan": f"{road[1]}/{road[2]}" if road else None,
            "Jarak ke Jalan Nasional (km)": _r(road[3], 2) if road else None,
            "Lintas Perintis Penyeberangan (cocok nama, perkiraan)": "; ".join(lintas) or None,
            "Lokus 3TP (Wilayah Prioritas)": ("Ya" if wilayah_prioritas[k].get("3TP") else "Tidak") if k in wilayah_prioritas else None,
        })
    sh_pp = pd.DataFrame(rows_pp)

    # ================= Sheet Terminal
    road_tm = _nearest_road([(r["_lat"], r["_lon"]) for r in term])
    rows_tm = []
    for r, road in zip(term, road_tm):
        lat, lon = r["_lat"], r["_lon"]
        d = {n: _haversine_min(lat, lon, a)[0] for n, a in
             (("st", A_st), ("bd", A_bd), ("pl", A_pl), ("pp", A_pp))}
        k = r["_kode_kab"]
        rows_tm.append({
            "Kode Kab/Kota": k, "Provinsi": r.get("provinsi") or prov_kab.get(k), "Nama Terminal": r.get("nama_terminal"),
            "Kab/Kota (poligon)": r["_kab_poligon"], "Kecamatan (poligon)": r["_kec_poligon"],
            "Latitude": lat, "Longitude": lon, "Sumber Koordinat": r.get("sumber_koordinat"),
            "Penduduk Kab/Kota 2025": int(pend[k]) if k in pend and pend[k] else None,
            "Jarak ke Stasiun KA Terdekat (km)": _r(d["st"]), "Jarak ke Bandara Terdekat (km)": _r(d["bd"]),
            "Jarak ke Pelabuhan Laut Terdekat (km)": _r(d["pl"]),
            "Jarak ke Pelabuhan Penyeberangan Terdekat (km)": _r(d["pp"]),
            "Jalan Nasional Terdekat": road[0] if road else None,
            "Kelas/Fungsi Jalan": f"{road[1]}/{road[2]}" if road else None,
            "Jarak ke Jalan Nasional (km)": _r(road[3], 2) if road else None,
            "Tipe": "A", "Kelengkapan Fasilitas/Operasional": "Data belum tersedia",
        })
    sh_tm = pd.DataFrame(rows_tm)

    # ================= Sheet Perintis & Integrasi per kab
    c_pp, c_tm, c_st, c_bd, c_pl = cnt(pp), cnt(term), cnt(stasiun), cnt(bandara), cnt(plaut)
    c_per = {k: cnt(v) for k, v in perintis_pts.items()}
    cov_term = {r["_kode_kab"][:2] for r in term if r["_kode_kab"]}

    rows_per, rows_int = [], []
    for m in master.itertuples():
        k = m.kode_kab
        wp = wilayah_prioritas.get(k)
        f3tp = bool(wp and wp.get("3TP"))
        fks = bool(wp and wp.get("KSPEAN"))
        pksn, perb, lokpri = k in lokus["PKSN"], k in lokus["PERBATASAN"], k in lokus["LOKPRI_RPJMN"]
        total_per = sum(c_per[n].get(k, 0) for n in c_per)
        lokus3t = f3tp or pksn or perb or lokpri
        fs = fiskal.get(k)
        penduduk = int(m.penduduk_2025) or None

        base = {"Kode Kab/Kota": k, "Provinsi": m.provinsi, "Kabupaten/Kota": m.kabupaten_kota, "Penduduk 2025": penduduk}
        row_per = dict(base)
        row_per.update({
            "Titik Jalan Perintis": c_per["Titik Jalan Perintis"].get(k, 0),
            "Titik Penyeberangan Perintis": c_per["Titik Penyeberangan Perintis"].get(k, 0),
            "Titik Angkutan Penumpang Laut (Perintis)": c_per["Titik Angkutan Penumpang Laut"].get(k, 0),
            "Titik Angkutan Barang Laut (Perintis)": c_per["Titik Angkutan Barang Laut"].get(k, 0),
            "Titik Angkutan Darat Barang": c_per["Titik Angkutan Darat Barang"].get(k, 0),
            "Titik Udara (Perintis)": c_per["Titik Udara"].get(k, 0),
            "Titik KSPN": c_per["Titik KSPN"].get(k, 0),
            "Total Titik Layanan Perintis": total_per,
            "Trayek Perintis di Tabel (Barang/BTS, cocok nama)": perintis_tabel_kab.get(k) or None,
            "Wilayah Prioritas (layer)": None if wp is None else "Ya",
            "3TP": None if wp is None else ("Ya" if f3tp else "Tidak"),
            "KSPEAN": None if wp is None else ("Ya" if fks else "Tidak"),
            "Lokus PKSN": "Ya" if pksn else "Tidak", "Lokus Perbatasan": "Ya" if perb else "Tidak",
            "Lokus LOKPRI RPJMN": "Ya" if lokpri else "Tidak",
            "Lokus 3T tanpa Titik Layanan Perintis (perkiraan)": "Ya" if lokus3t and total_per == 0 else "Tidak",
            "IPM (Wilayah Prioritas)": wp.get("IPM") if wp else None,
            "Persen Penduduk Miskin (Wilayah Prioritas)": wp.get("Pct_Miskin") if wp else None,
        })
        rows_per.append(row_per)

        moda = {"Terminal Tipe A": (c_tm.get(k, 0) if k[:2] in cov_term else None),
                "Stasiun KA": c_st.get(k, 0), "Pelabuhan Laut": c_pl.get(k, 0),
                "Pelabuhan Penyeberangan": c_pp.get(k, 0), "Bandara": c_bd.get(k, 0)}
        tipologi = [t for t, on in (("3T", f3tp or pksn or perb or lokpri), ("KSPEAN", fks)) if on]
        row_int = dict(base)
        row_int.update({
            "Tipologi Wilayah (proksi)": ", ".join(tipologi) or "Belum terklasifikasi (WM belum ada delineasi)",
            "3TP": row_per["3TP"], "KSPEAN": row_per["KSPEAN"],
            "Kategori Fiskal": fs["kategori_fiskal"] if fs else None,
            "Rasio KFD": float(fs["rasio_kfd"]) if fs and fs["rasio_kfd"] is not None else None,
            **moda,
            "Jumlah Jenis Simpul Tersedia (dari 5)": sum(1 for v in moda.values() if v),
            "Total Titik Layanan Perintis": total_per,
            "Lokus 3T tanpa Titik Layanan Perintis (perkiraan)": row_per["Lokus 3T tanpa Titik Layanan Perintis (perkiraan)"],
        })
        rows_int.append(row_int)

    sh_ket = pd.DataFrame(KETERSEDIAAN, columns=["Slide", "Kebutuhan Kerangka", "Status Data", "Keterangan / Sumber"])
    return {
        "Penyeberangan": sh_pp,
        "Perintis Kab-Kota": pd.DataFrame(rows_per),
        "Integrasi Antarmoda": pd.DataFrame(rows_int),
        "Terminal Tipe A": sh_tm,
        "Ketersediaan Data": sh_ket,
        "Keterangan": pd.DataFrame({"Keterangan": KETERANGAN}),
    }


def get_sheets():
    """Cache in-process 10 menit (spatial join titik->kecamatan + jarak jalan terdekat)."""
    if _cache["sheets"] is None or time.time() - _cache["ts"] > _CACHE_TTL_DETIK:
        _cache["sheets"] = _build()
        _cache["ts"] = time.time()
    return _cache["sheets"]


def _filter_df(df, provinsi, q):
    if provinsi and "Provinsi" in df.columns:
        df = df[df["Provinsi"].astype(str).str.contains(re.escape(provinsi), case=False, na=False)]
    if q:
        txt_cols = [c for c in df.columns if df[c].dtype == object][:6]
        if txt_cols:
            blob = df[txt_cols].fillna("").astype(str).agg(" ".join, axis=1)
            df = df[blob.str.contains(re.escape(q), case=False, na=False)]
    return df


def filter_sheets(sheets, provinsi="", q=""):
    """Filter sheet berdata (bukan Ketersediaan/Keterangan) per provinsi & kata kunci."""
    if not provinsi and not q:
        return sheets
    return {n: (df if n in ("Ketersediaan Data", "Keterangan") else _filter_df(df, provinsi, q))
            for n, df in sheets.items()}


def export_bytes(provinsi="", q=""):
    buf = io.BytesIO()
    write_workbook(filter_sheets(get_sheets(), provinsi, q), buf)
    buf.seek(0)
    return buf
