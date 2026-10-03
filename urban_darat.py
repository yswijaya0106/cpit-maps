"""Profil Urban & Darat (kerangka "Tim Urban dan Darat", tahap 1).

Kerangka: docs/24092026/Kerangka Berpikir Tim Urban dan Darat.pptx; kajian:
docs/kajian_tim_urban_darat_ketersediaan_data.md. Empat sheet data +
Ketersediaan Data + Keterangan:

  Penyeberangan       per pelabuhan penyeberangan (slide 7)
  Perintis Kab-Kota   per kab/kota (slide 10)
  Integrasi Antarmoda per kab/kota (slide 8-9), TANPA indeks komposit
  Terminal Tipe A     per terminal (slide 6)
  Indikator Slide 8   pemetaan 15 indikator kunci slide 8 -> kolom/status (Tahap A)

Dipakai endpoint /api/urban-darat/* (app.py, moda Darat). Sel kosong = data
tidak tersedia, bukan nol. Tidak ada skor/bobot: deck tidak menetapkannya.
"""
import io
import re
from collections import defaultdict

import numpy as np
import pandas as pd

from shared_cache import SharedCache
from road_safety import _q, kode_kec_dari_nama, load_wilayah, points_by_kab, write_workbook

_CACHE_TTL_DETIK = 600
_cache = SharedCache("urban_darat", _CACHE_TTL_DETIK)  # lihat shared_cache.py

SHEETS = ["Penyeberangan", "Perintis Kab-Kota", "Integrasi Antarmoda", "Terminal Tipe A",
          "Indikator Slide 8", "Ketersediaan Data", "Keterangan"]

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
    (8, "Integrasi antarmoda: indikator kunci per tipologi (jarak transfer, simpul terpadu, cakupan penduduk, jarak ke simpul, MST, kemantapan, layanan perintis per penduduk)", "Proksi (Tahap A)", "Dihitung dari data yang ada -> sheet Integrasi Antarmoda; pemetaan 15 indikator slide 8 -> sheet Indikator Slide 8"),
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
    "Tipologi: 3TP dan KSPEAN dari layer 'Wilayah Prioritas' (ANGKUTAN PERINTIS, 96 kab/kota); Lokus PKSN/Perbatasan dari bappenas_lokus_a (3T = 3TP/PKSN/Perbatasan). LOKPRI RPJMN ditampilkan tetapi TIDAK dipakai sbg penanda 3T karena juga memuat kawasan perkotaan/metropolitan. Wilayah Metropolitan belum ada delineasinya.",
    "'Lokus 3T tanpa titik layanan perintis' = perkiraan: kab/kota berflag 3TP/PKSN/Perbatasan tanpa satu pun titik layer perintis (jalan, penyeberangan, laut, udara, KSPN, barang).",
    "Kolom 'Kode Status Operasi (sumber)' pada sheet Penyeberangan adalah kode mentah STAT_OPS dari layer sumber (makna kode belum terdokumentasi).",
    "Lintas perintis pada sheet Penyeberangan dicocokkan lewat kemiripan nama pelabuhan dengan nama trayek (perkiraan); angkutan_perintis tidak punya kunci join ke pelabuhan.",
    "Tahap A (indikator slide 8): jarak transfer = jarak lurus tiap simpul (stasiun, bandara, pelabuhan laut & penyeberangan, terminal A) ke simpul MODA LAIN terdekat, dimedian per kab/kota; 'simpul terpadu' = ada simpul moda lain <=1 km.",
    "Cakupan penduduk memakai titik representatif kecamatan (bukan grid penduduk): % penduduk kab/kota yang titik kecamatannya <=10 km dari simpul, dan % penduduk di kecamatan yang memiliki simpul. Radius 500 m-1 km pada kerangka tidak bisa dihitung tanpa grid penduduk.",
    "MST jalan nasional hanya terisi utk +/-1/3 panjang jalan nasional (sisanya 0 = tidak diketahui): persentase MST >= 10 ton dihitung dari panjang yang ber-data, lihat kolom 'Data MST Tersedia'. Kemantapan = total_mantap_km / panjang_sk_km iri_ruas_nasional (survei IRI Juli 2026).",
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


# ---------------------------------------------------------------------------
# Tahap A (29 Sep 2026): indikator keterpaduan slide 8 yang BISA dihitung dari data
# yang ada, per kab/kota -- tanpa indeks/bobot (deck tidak menetapkannya). Semua jarak
# garis lurus (haversine); "cakupan penduduk" memakai titik representatif kecamatan
# (bukan grid penduduk), jadi radius 500 m-1 km WM tidak bisa dihitung -- dipakai 10 km.
# ---------------------------------------------------------------------------
RADIUS_SIMPUL_TERPADU_KM = 1.0
RADIUS_CAKUPAN_KM = 10.0
KOLOM_TAHAP_A = [  # urutan kolom di sheet Integrasi Antarmoda
    "Jarak Transfer Median antar Moda (km)",
    f"Simpul Terpadu <={RADIUS_SIMPUL_TERPADU_KM:g} km (jumlah)", f"Simpul Terpadu <={RADIUS_SIMPUL_TERPADU_KM:g} km (%)",
    f"Penduduk <={RADIUS_CAKUPAN_KM:g} km dari Simpul (%)", "Penduduk di Kecamatan Bersimpul (%)",
    "Jarak Median Kecamatan ke Simpul Terdekat (km)",
    "Jalan Nasional (km)", "Data MST Tersedia (% panjang)", "Jalan Nasional MST >= 10 ton (% panjang ber-data MST)",
    "Kemantapan Jalan Nasional (IRI, % mantap)",
]

# Pemetaan indikator slide 8 -> kolom sheet Integrasi Antarmoda / status (sheet "Indikator Slide 8").
INDIKATOR_SLIDE8 = [
    ("WM", "Jarak dan waktu transfer antarsimpul", "Proksi",
     "Jarak Transfer Median antar Moda (km) -- jarak lurus ke simpul moda lain terdekat; waktu transfer belum ada"),
    ("WM", "Cakupan penduduk dalam radius 500 m-1 km dari simpul", "Proksi",
     "Penduduk <=10 km dari Simpul (%) & Penduduk di Kecamatan Bersimpul (%) -- grid penduduk tidak ada, radius 500 m-1 km tak bisa dihitung"),
    ("WM", "Headway, waktu tunggu, dan kesesuaian jadwal antarmoda", "Belum ada", "Jadwal/headway tidak ada di database"),
    ("WM", "Pangsa angkutan umum dan jumlah perpindahan moda", "Belum ada", "Hanya O-D LRT Jabodebek"),
    ("WM", "Ketersediaan tiket serta informasi perjalanan terpadu", "Belum ada", "-"),
    ("KSPEAN", "Waktu dan jarak tempuh sentra produksi ke simpul terdekat", "Proksi",
     "Jarak Median Kecamatan ke Simpul Terdekat (km) -- titik kecamatan sbg proksi sentra; jarak lurus, bukan jarak tempuh"),
    ("KSPEAN", "Biaya logistik per ton-km dan jumlah alih muat", "Belum ada", "-"),
    ("KSPEAN", "Kelas jalan dan daya dukung terhadap MST kendaraan angkut", "Sebagian",
     "Jalan Nasional MST >= 10 ton (% panjang ber-data MST); data MST hanya ada utk +/-1/3 panjang jalan nasional"),
    ("KSPEAN", "Volume komoditas terhadap kapasitas simpul", "Belum ada", "Kapasitas simpul & volume komoditas per simpul tidak ada"),
    ("KSPEAN", "Ketersediaan gudang, cold storage, dan alat bongkar muat", "Belum ada", "-"),
    ("3T", "Jumlah pulau atau desa yang belum terlayani reguler", "Proksi",
     "Lokus 3T tanpa Titik Layanan Perintis (perkiraan) -- per kab/kota, belum per desa/pulau"),
    ("3T", "Frekuensi layanan per minggu dan waktu tunggu transfer", "Belum ada", "Hanya target_trip_2026 penyeberangan perintis (per lintas)"),
    ("3T", "Waktu tempuh ke ibu kota kabupaten dan fasilitas dasar", "Belum ada", "Titik ibu kota kab & mesin rute belum ada"),
    ("3T", "Keterisian dan cakupan layanan perintis atau subsidi", "Sebagian",
     "Titik Layanan Perintis per 100rb Penduduk (cakupan); keterisian tidak ada"),
    ("3T", "Ketersediaan simpul alih moda di titik naik-turun", "Proksi",
     "Simpul Terpadu <=1 km (jumlah & %) -- simpul yang punya simpul moda lain dalam 1 km"),
]


def _jarak_matriks(a, b):
    """Jarak haversine (km) semua pasangan a (n,2) x b (m,2)."""
    la1, lo1 = np.radians(a[:, 0])[:, None], np.radians(a[:, 1])[:, None]
    la2, lo2 = np.radians(b[:, 0])[None, :], np.radians(b[:, 1])[None, :]
    h = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0088 * np.arcsin(np.sqrt(h))


def _indikator_tahap_a(simpul_per_moda, kode_from_text):
    """simpul_per_moda: {nama_moda: rows points_by_kab}. -> {kode_kab: {kolom: nilai}}."""
    hasil = defaultdict(dict)

    # 1. transfer antarmoda: tiap simpul -> simpul MODA LAIN terdekat
    semua = [(m, r) for m, rows in simpul_per_moda.items() for r in rows
             if r["_lat"] is not None and r["_lon"] is not None]
    if semua:
        xy = np.array([[r["_lat"], r["_lon"]] for _, r in semua])
        moda = np.array([m for m, _ in semua])
        d_min = np.full(len(semua), np.inf)
        for i0 in range(0, len(semua), 500):  # per blok, hemat memori
            d = _jarak_matriks(xy[i0:i0 + 500], xy)
            d[moda[i0:i0 + 500][:, None] == moda[None, :]] = np.inf  # abaikan moda yang sama
            d_min[i0:i0 + 500] = d.min(axis=1)
        per_kab = defaultdict(list)
        for (_, r), dm in zip(semua, d_min):
            if r["_kode_kab"] and np.isfinite(dm):
                per_kab[r["_kode_kab"]].append(dm)
        for k, ds in per_kab.items():
            ds = np.array(ds)
            hasil[k]["Jarak Transfer Median antar Moda (km)"] = _r(float(np.median(ds)))
            hasil[k][f"Simpul Terpadu <={RADIUS_SIMPUL_TERPADU_KM:g} km (jumlah)"] = int((ds <= RADIUS_SIMPUL_TERPADU_KM).sum())
            hasil[k][f"Simpul Terpadu <={RADIUS_SIMPUL_TERPADU_KM:g} km (%)"] = _r(100 * float((ds <= RADIUS_SIMPUL_TERPADU_KM).mean()))

    # 2. cakupan penduduk: titik representatif kecamatan -> simpul terdekat (moda apa pun)
    # KODE_KECAMATAN kosong di sebagian poligon (seluruh DKI Jakarta) -> kode dari nama kab + kecamatan
    pdd_kec = {str(r["kode_kecamatan"]): r["jumlah_penduduk"] for r in _q(
        "select kode_kecamatan, jumlah_penduduk from penduduk_kecamatan")}
    kec = []
    for r in _q("""select k.attrs->>'KODE_KECAMATAN' as kode, k.attrs->>'PROVINSI' as prov,
                          k.attrs->>'KABUPATEN_KOTA' as kab, k.attrs->>'KECAMATAN' as nama,
                          ST_Y(ST_PointOnSurface(k.geom)) as lat, ST_X(ST_PointOnSurface(k.geom)) as lon
                   from map_layers k where k.provinsi = 'BATAS KECAMATAN'"""):
        kode = (str(int(float(r["kode"]))) if r["kode"]
                else kode_kec_dari_nama(kode_from_text(r["prov"], r["kab"]), r["nama"]))
        if kode and kode in pdd_kec:
            kec.append({"kode_kec": int(kode), "lat": r["lat"], "lon": r["lon"], "pdd": pdd_kec[kode]})
    kec_bersimpul = {r["_kode_kec"] for _, r in semua if r.get("_kode_kec")}
    if kec and semua:
        kxy = np.array([[r["lat"], r["lon"]] for r in kec])
        d_kec = np.concatenate([_jarak_matriks(kxy[i0:i0 + 1000], xy).min(axis=1)
                                for i0 in range(0, len(kec), 1000)])
        agg = defaultdict(lambda: {"pdd": 0.0, "dekat": 0.0, "bersimpul": 0.0, "jarak": []})
        for r, dk in zip(kec, d_kec):
            kk = str(r["kode_kec"] // 1000)
            pdd = float(r["pdd"] or 0)
            a = agg[kk]
            a["pdd"] += pdd
            a["dekat"] += pdd if dk <= RADIUS_CAKUPAN_KM else 0
            a["bersimpul"] += pdd if str(r["kode_kec"]) in kec_bersimpul else 0
            a["jarak"].append(dk)
        for k, a in agg.items():
            if a["pdd"] > 0:
                hasil[k][f"Penduduk <={RADIUS_CAKUPAN_KM:g} km dari Simpul (%)"] = _r(100 * a["dekat"] / a["pdd"])
                hasil[k]["Penduduk di Kecamatan Bersimpul (%)"] = _r(100 * a["bersimpul"] / a["pdd"])
            hasil[k]["Jarak Median Kecamatan ke Simpul Terdekat (km)"] = _r(float(np.median(a["jarak"])))

    # 3. jalan nasional per kab (CITY_ID = kode kab BPS): panjang, MST, kemantapan (IRI)
    for r in _q("""
        with seg as (
            select attrs->>'CITY_ID' as kab, attrs->>'LINKID' as linkid,
                   nullif((attrs->>'MST')::numeric, 0) as mst,
                   ST_Length(geom::geography) / 1000 as km
            from map_layers where provinsi = 'JALAN NASIONAL' and layer = 'Jalan Nasional')
        select s.kab, sum(s.km) as km,
               sum(s.km) filter (where s.mst is not null) as km_mst,
               sum(s.km) filter (where s.mst >= 10) as km_mst10,
               (select sum(i.total_mantap_km) / nullif(sum(i.panjang_sk_km), 0) * 100
                  from iri_ruas_nasional i where i.linkid = any(array_agg(distinct s.linkid))) as pct_mantap
        from seg s group by s.kab"""):
        k = r["kab"]
        if not k:
            continue
        km, km_mst = float(r["km"] or 0), float(r["km_mst"] or 0)
        hasil[k]["Jalan Nasional (km)"] = _r(km)
        hasil[k]["Data MST Tersedia (% panjang)"] = _r(100 * km_mst / km) if km else None
        hasil[k]["Jalan Nasional MST >= 10 ton (% panjang ber-data MST)"] = (
            _r(100 * float(r["km_mst10"] or 0) / km_mst) if km_mst else None)
        hasil[k]["Kemantapan Jalan Nasional (IRI, % mantap)"] = _r(float(r["pct_mantap"])) if r["pct_mantap"] is not None else None
    return hasil


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
    ind_a = _indikator_tahap_a({"Stasiun KA": stasiun, "Bandara": bandara, "Pelabuhan Laut": plaut,
                                "Pelabuhan Penyeberangan": pp, "Terminal Tipe A": term}, kode_from_text)
    kolom_ind_a = sorted({c for v in ind_a.values() for c in v}, key=lambda c: KOLOM_TAHAP_A.index(c))

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
        lokus3t = f3tp or pksn or perb  # LOKPRI tidak dipakai: memuat kawasan perkotaan/metropolitan
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
        tipologi = [t for t, on in (("3T", lokus3t), ("KSPEAN", fks)) if on]
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
            # Tahap A -- indikator slide 8 (proksi; lihat sheet "Indikator Slide 8")
            "Titik Layanan Perintis per 100rb Penduduk": _r(100000 * total_per / penduduk, 2) if penduduk else None,
            **{c: ind_a.get(k, {}).get(c) for c in kolom_ind_a},
        })
        rows_int.append(row_int)

    sh_ket = pd.DataFrame(KETERSEDIAAN, columns=["Slide", "Kebutuhan Kerangka", "Status Data", "Keterangan / Sumber"])
    return {
        "Penyeberangan": sh_pp,
        "Perintis Kab-Kota": pd.DataFrame(rows_per),
        "Integrasi Antarmoda": pd.DataFrame(rows_int),
        "Terminal Tipe A": sh_tm,
        "Indikator Slide 8": pd.DataFrame(INDIKATOR_SLIDE8, columns=["Tipologi", "Indikator Kunci (slide 8)", "Status",
                                                                     "Kolom di Sheet Integrasi Antarmoda / Keterangan"]),
        "Ketersediaan Data": sh_ket,
        "Keterangan": pd.DataFrame({"Keterangan": KETERANGAN}),
    }


def get_sheets():
    """Cache 10 menit dibagi antar worker, basi-sambil-diperbarui (shared_cache.py):
    spatial join titik->kecamatan + jarak jalan terdekat."""
    return _cache.get("sheets", _build)


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
