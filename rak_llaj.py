"""Skor Prioritas Pendampingan RAK LLAJ -- level PROVINSI, PARSIAL.

Skema: docs/30092026/Skema Prioritas Pendampingan RAK LLAJ Daerah.pptx (Sekretariat RUNK
LLAJ, Pilar 1). Skor = 0,15 RF100 + 0,10 RF10K + 0,15 Skor Risiko + 0,25 Status RAK
+ 0,25 Gap Kelembagaan + 0,10 Tren; provinsi & kab/kota diranking TERPISAH; kapasitas
fiskal (IKFD) konteks saja, tidak diskor.

Yang bisa dihitung (30 Sep 2026): aspek a (RF100, RF10K, Skor Risiko) dan e (Tren) utk
PROVINSI dari anev_laka_lantas_polda -- total 50% bobot. Aspek b (Status RAK) & d
(Kelembagaan) belum ada datanya -> "belum tersedia", TIDAK diisi 0. Kab/kota tidak diskor
sama sekali (data kecelakaan hanya per POLDA; lihat kolom konteks di profil Road Safety).

Keputusan metode (disetujui user 30 Sep 2026, ditandai "ilustratif" sesuai slide 9):
- RF100/RF10K & frekuensi -> skor lewat rasio thd rata-rata nasional (bukan min-max):
  <=0,75x -> 25, <=1,0x -> 50, <=1,25x -> 75, >1,25x -> 100.
- 2025 hanya Jan-30 Okt (303 hari) -> disetahunkan x365/303, supaya tidak tampak "membaik".
- Level = rata-rata 2023, 2024, 2025*; tren = CAGR antara rata-rata bergerak 3 th
  (2020-2022 -> 2023-2025*, 3 tahun), sesuai anjuran smoothing di slide 6.
- Batas tren (slide tumpang tindih di 0% & -5%): >10% -> 100; >0..10% -> 70;
  -5..0% -> 40; <-5% -> 10.
- Skor Risiko: frekuensi/10rb kendaraan 40% (rasio-nasional) + proporsi korban berat
  (MD+LB)/(MD+LB+LR) 30% + konsentrasi titik LRK+blackspot per 1.000 km jalan 30%
  (keduanya min-max 0-100); sub yg tak tersedia dikeluarkan & bobotnya direnormalisasi.
- Tanah Papua: POLDA Papua Tengah & Papua Barat Daya baru berdata 2025 (2020-2024 kosong/0),
  Papua Selatan & Papua Pegunungan belum punya POLDA -> dua wilayah gabungan (POLDA_GRUP /
  PROVINSI_TANPA_POLDA): Papua+Papua Tengah+Papua Selatan+Papua Pegunungan, dan Papua
  Barat+Papua Barat Daya. Data per tahun & penyebut dijumlah; anggota mendapat nilai wilayah.
"""
import io
import re

import pandas as pd

from db import db_cursor
from shared_cache import SharedCache
import road_safety

SHEETS = ["Skor Provinsi", "Data Kecelakaan POLDA", "Validasi Data", "Keterangan"]

BOBOT = {"RF100": 0.15, "RF10K": 0.10, "RISIKO": 0.15, "RAK": 0.25, "KELEMBAGAAN": 0.25, "TREN": 0.10}
TAHUN_LEVEL = ("2023", "2024", "2025")
TAHUN_AWAL = ("2020", "2021", "2022")
TAHUN_PARSIAL = {"JAN - 30 OKT 2025": ("2025", 365 / 303)}  # label sumber -> (tahun, faktor)
# Wilayah POLDA Tanah Papua berubah di 2025: POLDA Papua Tengah & Papua Barat Daya baru
# punya data 2025 (2020-2024 kosong/0), sementara POLDA Papua & Papua Barat turun tajam di
# 2025 krn wilayahnya dipecah. Agar deret multi-tahun konsisten, POLDA dikelompokkan jadi
# satu wilayah (data per tahun dijumlah, penyebut dijumlah atas semua provinsi anggota):
POLDA_GRUP = {"PAPUA TENGAH": "PAPUA", "PAPUA BARAT DAYA": "PAPUA BARAT"}  # POLDA -> POLDA induk
# provinsi tanpa POLDA sendiri -> POLDA induk wilayahnya (asumsi, konfirmasi ke Korlantas)
PROVINSI_TANPA_POLDA = {"PAPUA SELATAN": "PAPUA", "PAPUA PEGUNUNGAN": "PAPUA"}

KETERANGAN = [
    "Skema: Skema Prioritas Pendampingan RAK LLAJ Daerah (Sekretariat RUNK LLAJ, Pilar 1), docs/30092026/.",
    "PARSIAL: hanya aspek a (RF100 15%, RF10K 10%, Skor Risiko 15%) dan e (Tren 10%) = 50% bobot. "
    "Aspek b Status RAK (25%) dan d Kelembagaan (25%) belum ada datanya -> 'belum tersedia', bukan 0.",
    "Skor Parsial = jumlah bobot x skor komponen yang tersedia (maks 50). Skor Ternormalisasi = Skor Parsial "
    "dibagi bobot tersedia x 100 -- hanya utk membandingkan antarprovinsi selama b & d belum ada; BUKAN skor final.",
    "Hanya level provinsi: data kecelakaan (anev_laka_lantas_polda) hanya per POLDA; kab/kota tidak diskor.",
    "2025 = Jan-30 Okt (303 hari), disetahunkan x365/303. Level = rata-rata 2023-2025; tren = CAGR rata-rata "
    "bergerak 3 th (2020-2022 -> 2023-2025).",
    "Ambang RF100/RF10K/frekuensi: rasio thd rata-rata nasional <=0,75 -> 25; <=1,0 -> 50; <=1,25 -> 75; >1,25 -> 100. "
    "Ambang ILUSTRATIF, belum dikalibrasi (slide 9 skema).",
    "Tren: CAGR >10% -> 100 (memburuk cepat); >0-10% -> 70; -5% s.d. 0% -> 40; <-5% -> 10 (batas 0% dan -5% di slide "
    "tumpang tindih; di sini 0% = stabil, -5% = stabil).",
    "Skor Risiko: frekuensi kejadian/10rb kendaraan 40% (rasio nasional) + proporsi korban berat (MD+LB)/(MD+LB+LR) 30% "
    "+ konsentrasi titik LRK+blackspot per 1.000 km jalan 30% (min-max). Titik LRK/blackspot tidak merata "
    "(LRK 12 provinsi) -> provinsi tanpa titik di layer dianggap konsentrasi tidak tersedia, bukan 0.",
    "Tanah Papua: POLDA Papua Tengah & Papua Barat Daya baru memiliki data 2025 (2020-2024 kosong/0) dan POLDA "
    "Papua/Papua Barat turun tajam di 2025 krn wilayahnya dipecah; Papua Selatan & Papua Pegunungan belum punya "
    "POLDA. Agar deret konsisten dihitung 2 wilayah gabungan: (1) Papua, Papua Tengah, Papua Selatan, Papua "
    "Pegunungan; (2) Papua Barat, Papua Barat Daya. Kecelakaan & penyebut dijumlah; semua anggota mendapat nilai "
    "wilayah yang sama -- ASUMSI, konfirmasi ke Korlantas.",
    "IKFD (kapasitas fiskal) dari kolom SITIA usulan Gubernur -- konteks, tidak masuk skor (slide 7).",
    "Penduduk: penduduk_kecamatan (BPS 2025); kendaraan: si_kendaraan_provinsi tahun terbaru; panjang jalan: "
    "si_panjang_jalan_provinsi tahun terbaru (Statistik Indonesia 2026).",
]

_CACHE_TTL_DETIK = 600
_cache = SharedCache("rak_llaj", _CACHE_TTL_DETIK)  # lihat shared_cache.py


def _norm_prov(s):
    """Nama provinsi -> kunci. Sendiri (bukan road_safety._norm_prov) supaya "DAERAH KHUSUS IBUKOTA
    JAKARTA" (PROVINSI_POLDA_MAP) = "DKI JAKARTA" (ref_wilayah) tanpa bergantung versi modul lain."""
    s = re.sub(r"[^A-Z ]", " ", (s or "").upper())
    s = re.sub(r"\b(DAERAH KHUSUS IBUKOTA|DAERAH KHUSUS|DAERAH ISTIMEWA|D I|DI|DKI|PROVINSI|PROV)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _q(sql, args=None):
    with db_cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def _skor_rasio(r):
    if r is None:
        return None
    return 25 if r <= 0.75 else 50 if r <= 1.0 else 75 if r <= 1.25 else 100


def _skor_tren(cagr_pct):
    if cagr_pct is None:
        return None, None
    if cagr_pct > 10:
        return 100, "Memburuk cepat"
    if cagr_pct > 0:
        return 70, "Memburuk"
    if cagr_pct >= -5:
        return 40, "Relatif stabil"
    return 10, "Membaik konsisten"


def _minmax(vals):
    ada = [v for v in vals.values() if v is not None]
    if not ada:
        return {k: None for k in vals}
    lo, hi = min(ada), max(ada)
    return {k: (None if v is None else (100.0 if hi == lo else (v - lo) / (hi - lo) * 100)) for k, v in vals.items()}


def _data_polda():
    """-> {polda: {tahun: {kejadian, md, lb, lr}}} dgn tahun parsial disetahunkan, + baris mentah."""
    mentah = _q("select polda, tahun, kejadian, korban_md, korban_lb, korban_lr from anev_laka_lantas_polda "
                "order by polda, tahun")
    out = {}
    for r in mentah:
        tahun, faktor = TAHUN_PARSIAL.get(r["tahun"], (r["tahun"], 1.0))
        slot = out.setdefault(POLDA_GRUP.get(r["polda"], r["polda"]), {}).setdefault(tahun, {})
        for k, c in (("kejadian", "kejadian"), ("md", "korban_md"), ("lb", "korban_lb"), ("lr", "korban_lr")):
            if r[c] is not None:  # anggota grup yg belum ada (None) tidak menihilkan jumlah
                slot[k] = (slot.get(k) or 0) + float(r[c]) * faktor
            else:
                slot.setdefault(k, None)
    return out, mentah


def _ikfd_provinsi():
    rows = _q("select provinsi, max(upper(kapasitas_fiskal)) as f from usulan_inpres "
              "where nama_pengusul ilike 'Gubernur%%' and kapasitas_fiskal is not null group by 1")
    return {_norm_prov(r["provinsi"]): r["f"] for r in rows}


def _build(polda_map):
    prov = _q("""select p.kode_provinsi, p.nama_provinsi, coalesce(sum(k.jumlah_penduduk), 0) as penduduk
                 from ref_wilayah_provinsi p left join penduduk_kecamatan k on k.kode_provinsi = p.kode_provinsi
                 group by 1, 2 order by 1""")
    kend = {r["kode_provinsi"]: (r["tahun"], float(r["jumlah"])) for r in _q(
        """select distinct on (kode_provinsi) kode_provinsi, tahun, jumlah from si_kendaraan_provinsi
           where kode_provinsi > 0 and jumlah is not null order by kode_provinsi, tahun desc""")}
    jalan = {r["kode_provinsi"]: float(r["jumlah_km"]) for r in _q(
        """select distinct on (kode_provinsi) kode_provinsi, jumlah_km from si_panjang_jalan_provinsi
           where kode_provinsi > 0 and jumlah_km is not null order by kode_provinsi, tahun desc""")}
    titik = road_safety.get_sheets()["LRK & Blackspot"]
    titik_per_prov = (titik["Kode Kab/Kota (spasial)"].dropna().astype(str).str[:2].astype(int)
                      .value_counts().to_dict() if len(titik) else {})
    laka, mentah = _data_polda()
    ikfd = _ikfd_provinsi()

    # provinsi -> POLDA (nama dinormalisasi supaya "DKI JAKARTA" = "DAERAH KHUSUS IBUKOTA JAKARTA")
    norm_map = {_norm_prov(k): POLDA_GRUP.get(v, v) for k, v in polda_map.items()}
    for p, polda in PROVINSI_TANPA_POLDA.items():
        norm_map.setdefault(_norm_prov(p), polda)
    anggota = {}
    for p in prov:
        polda = norm_map.get(_norm_prov(p["nama_provinsi"]))
        p["_polda"] = polda
        if polda:
            anggota.setdefault(polda, []).append(p)

    # agregat per POLDA (penyebut dijumlah atas provinsi anggotanya)
    per_polda = {}
    for polda, ps in anggota.items():
        th = laka.get(polda)
        if not th:
            continue
        lvl = [th[t] for t in TAHUN_LEVEL if t in th]
        awal = [th[t] for t in TAHUN_AWAL if t in th]
        rata = lambda rows, k: (sum(r[k] for r in rows) / len(rows)) if rows and all(r[k] is not None for r in rows) else None
        pend = sum(float(p["penduduk"]) for p in ps) or None
        kd = sum(kend[p["kode_provinsi"]][1] for p in ps if p["kode_provinsi"] in kend) or None
        km = sum(jalan.get(p["kode_provinsi"], 0) for p in ps) or None
        n_titik = sum(titik_per_prov.get(p["kode_provinsi"], 0) for p in ps)
        md, kej = rata(lvl, "md"), rata(lvl, "kejadian")
        berat = sum((r["md"] or 0) + (r["lb"] or 0) for r in lvl)
        semua = berat + sum(r["lr"] or 0 for r in lvl)
        md_awal = rata(awal, "md")
        per_polda[polda] = {
            "md": md, "kejadian": kej, "penduduk": pend, "kendaraan": kd, "jalan_km": km,
            "rf100": md / pend * 1e5 if md is not None and pend else None,
            "rf10k": md / kd * 1e4 if md is not None and kd else None,
            "frek": kej / kd * 1e4 if kej is not None and kd else None,
            "berat": berat / semua if semua else None,
            "konsentrasi": n_titik / km * 1000 if km and n_titik else None, "n_titik": n_titik,
            "cagr": ((md / md_awal) ** (1 / 3) - 1) * 100 if md and md_awal else None,
            "gabungan": len(ps) > 1,
        }

    def nas(num, den):
        pairs = [(v[num], v[den]) for v in per_polda.values() if v[num] is not None and v[den]]
        return sum(a for a, _ in pairs) / sum(b for _, b in pairs) if pairs else None
    nas_rf100 = (nas("md", "penduduk") or 0) * 1e5
    nas_rf10k = (nas("md", "kendaraan") or 0) * 1e4
    nas_frek = (nas("kejadian", "kendaraan") or 0) * 1e4
    mm_berat = _minmax({k: v["berat"] for k, v in per_polda.items()})
    mm_kons = _minmax({k: v["konsentrasi"] for k, v in per_polda.items()})

    rows = []
    for p in prov:
        v = per_polda.get(p["_polda"]) if p["_polda"] else None
        s_rf100 = _skor_rasio(v["rf100"] / nas_rf100) if v and v["rf100"] is not None and nas_rf100 else None
        s_rf10k = _skor_rasio(v["rf10k"] / nas_rf10k) if v and v["rf10k"] is not None and nas_rf10k else None
        s_frek = _skor_rasio(v["frek"] / nas_frek) if v and v["frek"] is not None and nas_frek else None
        subs = [(s_frek, 0.4), (mm_berat.get(p["_polda"]) if v else None, 0.3),
                (mm_kons.get(p["_polda"]) if v else None, 0.3)]
        ada = [(s, w) for s, w in subs if s is not None]
        s_risiko = sum(s * w for s, w in ada) / sum(w for _, w in ada) if ada else None
        s_tren, kat_tren = _skor_tren(v["cagr"] if v else None)
        komponen = {"RF100": s_rf100, "RF10K": s_rf10k, "RISIKO": s_risiko, "TREN": s_tren}
        bobot_ada = sum(BOBOT[k] for k, s in komponen.items() if s is not None)
        parsial = sum(BOBOT[k] * s for k, s in komponen.items() if s is not None)
        catatan = []
        if not p["_polda"]:
            catatan.append("tidak ada POLDA terpetakan")
        elif not v:
            catatan.append(f"POLDA {p['_polda']} tanpa data kecelakaan")
        elif v["gabungan"]:
            catatan.append(f"nilai wilayah gabungan POLDA {p['_polda']}"
                           f"{' + ' + ' + '.join(k for k, g in POLDA_GRUP.items() if g == p['_polda']) if p['_polda'] in POLDA_GRUP.values() else ''}"
                           " (Tanah Papua; wilayah POLDA berubah 2025)")
        if v and v["konsentrasi"] is None:
            catatan.append("konsentrasi LRK/blackspot tidak tersedia (Skor Risiko direnormalisasi)")
        r2 = lambda x, n=2: round(x, n) if x is not None else None
        rows.append({
            "Kode Provinsi": p["kode_provinsi"], "Provinsi": p["nama_provinsi"], "POLDA": p["_polda"],
            "Rata-rata MD/th (2023-2025*)": r2(v["md"], 0) if v else None,
            "RF100 (MD/100rb penduduk)": r2(v["rf100"]) if v else None,
            "RF100 / Nasional": r2(v["rf100"] / nas_rf100) if v and v["rf100"] and nas_rf100 else None,
            "Skor RF100": s_rf100,
            "RF10K (MD/10rb kendaraan)": r2(v["rf10k"], 3) if v else None,
            "Skor RF10K": s_rf10k,
            "Frekuensi Kejadian/10rb Kendaraan": r2(v["frek"]) if v else None,
            "Skor Frekuensi": s_frek,
            "Proporsi Korban Berat (MD+LB)": r2(v["berat"] * 100, 1) if v and v["berat"] is not None else None,
            "Titik LRK+Blackspot": v["n_titik"] if v else None,
            "Titik per 1.000 km Jalan": r2(v["konsentrasi"]) if v else None,
            "Skor Risiko Kecelakaan": r2(s_risiko, 1),
            "CAGR Fatalitas (%/th, MA3)": r2(v["cagr"], 1) if v else None,
            "Kategori Tren": kat_tren, "Skor Tren": s_tren,
            "Skor Status RAK (b)": "belum tersedia", "Skor Gap Kelembagaan (d)": "belum tersedia",
            "Bobot Tersedia (%)": round(bobot_ada * 100),
            "Skor Parsial (maks 50)": round(parsial, 1) if bobot_ada else None,
            "Skor Ternormalisasi (0-100, sementara)": round(parsial / bobot_ada, 1) if bobot_ada else None,
            "IKFD (konteks, SITIA)": ikfd.get(_norm_prov(p["nama_provinsi"])),
            "Catatan": "; ".join(catatan) or None,
        })
    skor = pd.DataFrame(rows).sort_values("Skor Ternormalisasi (0-100, sementara)", ascending=False, na_position="last")
    skor.insert(0, "Peringkat (sementara)", range(1, len(skor) + 1))
    skor.loc[skor["Skor Ternormalisasi (0-100, sementara)"].isna(), "Peringkat (sementara)"] = None

    data_polda = pd.DataFrame([{
        "POLDA": r["polda"], "Tahun (sumber)": r["tahun"],
        "Tahun Parsial?": "Ya (disetahunkan x365/303)" if r["tahun"] in TAHUN_PARSIAL else None,
        "Kejadian": r["kejadian"], "MD": r["korban_md"], "LB": r["korban_lb"], "LR": r["korban_lr"]} for r in mentah])
    return {"Skor Provinsi": skor, "Data Kecelakaan POLDA": data_polda,
            "Validasi Data": validasi_df(polda_map), "Keterangan": pd.DataFrame({"Keterangan": KETERANGAN})}


def validasi(polda_map):
    """Pemeriksaan data kecelakaan POLDA (R4) -> list temuan {cek, status, detail}."""
    temuan = []
    mentah = _q("select polda, tahun, kejadian, korban_md, korban_lb, korban_lr from anev_laka_lantas_polda")
    tahun = sorted({r["tahun"] for r in mentah})
    parsial = [t for t in tahun if t in TAHUN_PARSIAL or not t.isdigit()]
    temuan.append({"cek": "Tahun parsial / tidak standar", "status": "PERHATIAN" if parsial else "OK",
                   "detail": ", ".join(parsial) + " -- disetahunkan sebelum dipakai" if parsial else "-"})
    poldas = {r["polda"] for r in mentah}
    dipetakan = set(polda_map.values())
    tak_dipakai = sorted(poldas - dipetakan)
    temuan.append({"cek": "POLDA di data tanpa provinsi", "status": "MASALAH" if tak_dipakai else "OK",
                   "detail": ", ".join(tak_dipakai) or "-"})
    norm = {_norm_prov(k) for k in polda_map}
    tambahan = {_norm_prov(p): g for p, g in PROVINSI_TANPA_POLDA.items()}
    prov = [r["nama_provinsi"] for r in _q("select nama_provinsi from ref_wilayah_provinsi order by 1")]
    tanpa = [p for p in prov if _norm_prov(p) not in norm]
    temuan.append({"cek": "Provinsi tanpa POLDA sendiri", "status": "PERHATIAN" if tanpa else "OK",
                   "detail": ", ".join(f"{p} ({'ikut wilayah POLDA ' + tambahan[_norm_prov(p)] + ', asumsi' if _norm_prov(p) in tambahan else 'tidak terhitung'})"
                                       for p in tanpa) or "-"})
    baru = {}
    for r in mentah:
        if r["tahun"].isdigit() and not r["korban_md"]:
            baru.setdefault(r["polda"], []).append(r["tahun"])
    baru = {p: t for p, t in baru.items() if len(t) >= 3}
    temuan.append({"cek": "POLDA dgn data kosong/0 bertahun-tahun (POLDA baru?)", "status": "PERHATIAN" if baru else "OK",
                   "detail": "; ".join(f"{p}: {', '.join(sorted(t))} kosong/0 -> digabung ke POLDA {POLDA_GRUP.get(p, '?')}"
                                       for p, t in baru.items()) or "-"})
    per = {}
    for r in mentah:
        t, f = TAHUN_PARSIAL.get(r["tahun"], (r["tahun"], 1.0))
        if r["korban_md"] is not None:
            per.setdefault(r["polda"], {})[t] = float(r["korban_md"]) * f
    lonjak = []
    for polda, th in per.items():
        ys = sorted(th)
        for a, b in zip(ys, ys[1:]):
            if th[a] >= 20 and (th[b] / th[a] > 1.5 or th[b] / th[a] < 0.5):
                lonjak.append(f"{polda} {a}->{b}: {th[a]:.0f}->{th[b]:.0f}")
    temuan.append({"cek": "Lonjakan MD antartahun >50% (basis >=20 MD)", "status": "PERHATIAN" if lonjak else "OK",
                   "detail": "; ".join(lonjak) or "-"})
    kosong = [f"{r['polda']} {r['tahun']}" for r in mentah
              if any(r[c] in (None, 0) for c in ("kejadian", "korban_md", "korban_lb", "korban_lr"))]
    temuan.append({"cek": "Nilai kosong/nol pada kejadian atau korban", "status": "PERHATIAN" if kosong else "OK",
                   "detail": ", ".join(kosong) or "-"})
    md_gt = [f"{r['polda']} {r['tahun']}" for r in mentah
             if r["korban_md"] and r["kejadian"] and r["korban_md"] > r["kejadian"]]
    temuan.append({"cek": "MD melebihi jumlah kejadian", "status": "PERHATIAN" if md_gt else "OK",
                   "detail": ", ".join(md_gt) or "-"})
    return temuan


def validasi_df(polda_map):
    return pd.DataFrame([{"Pemeriksaan": t["cek"], "Status": t["status"], "Detail": t["detail"]}
                         for t in validasi(polda_map)])


def get_sheets(polda_map):
    return _cache.get("sheets", lambda: _build(polda_map))


def filter_sheets(sheets, provinsi="", q=""):
    if not provinsi and not q:
        return sheets
    out = dict(sheets)
    for nama in ("Skor Provinsi",):
        df = sheets[nama]
        for s in (provinsi, q):
            if s:
                df = df[df["Provinsi"].str.contains(s, case=False, na=False, regex=False)]
        out[nama] = df
    if q:
        df = sheets["Data Kecelakaan POLDA"]
        out["Data Kecelakaan POLDA"] = df[df["POLDA"].str.contains(q, case=False, na=False, regex=False)]
    return out


def export_bytes(polda_map, provinsi="", q=""):
    buf = io.BytesIO()
    road_safety.write_workbook(filter_sheets(get_sheets(polda_map), provinsi, q), buf)
    buf.seek(0)
    return buf
