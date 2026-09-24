"""Profil Road Safety per kab/kota TANPA data kecelakaan/fatalitas.

Kerangka: docs/24092026/Kerangka Berpikir - Road Safety.pptx; kajian:
docs/kajian_road_safety_ketersediaan_data.md. Data kecelakaan/fatalitas
(anev_laka_lantas_*) sengaja tidak dipakai -- hanya ada di level POLDA.

Dipakai oleh endpoint /api/road-safety/kabupaten/* (app.py, moda Darat di
panel "Jelajahi Usulan Inpres") dan scripts/export_road_safety_kabupaten.py.
Sel kosong = data tidak tersedia, bukan nol.
"""
import io
import re
import time
from collections import defaultdict

import pandas as pd

from db import db_cursor

_CACHE_TTL_DETIK = 600  # sama dgn _IJD_BULK_CACHE_TTL_DETIK: perubahan data via CLI ikut terlihat
_cache = {"ts": 0.0, "sheets": None}

_ALIAS_KAB = {  # ejaan sumber -> ejaan master BPS
    "PARE PARE": "PAREPARE", "TOLITOLI": "TOLI TOLI",
    "OKU TIMUR": "OGAN KOMERING ULU TIMUR", "KOTA SIANTAR": "PEMATANGSIANTAR",
    "SIANTAR": "PEMATANGSIANTAR", "LUBUK LINGGAU": "LUBUKLINGGAU",
    "PANGKAJENE KEPULAUAN": "PANGKAJENE DAN KEPULAUAN",
}

KETERANGAN = [
    "Profil Road Safety per kab/kota TANPA data kecelakaan & fatalitas (RF100, RF10K, Skor Risiko Kecelakaan tidak dihitung).",
    "Sumber kajian: docs/kajian_road_safety_ketersediaan_data.md.",
    "Master wilayah: kab/kota dari penduduk_kecamatan (BPS 2025).",
    "Sel kosong = data tidak tersedia untuk wilayah itu (bukan nol). Hitungan titik (LRK, blackspot, titik potong, SS KA) bernilai 0 hanya bila provinsinya tercakup layer tetapi tidak ada titik di kab itu; di provinsi yang tidak tercakup layer sel dikosongkan.",
    "LRK/Blackspot/Titik Potong/SS KA dipetakan ke kab/kota lewat spatial join ke poligon BATAS KECAMATAN (kode kab dari KODE_KECAMATAN; fallback nama). Cakupan layer tidak nasional: LRK 12 provinsi, Titik Potong 12 provinsi, JPL prioritas 9 provinsi.",
    "Blackspot/LRK hanya titik; tidak memuat jumlah kejadian/korban sehingga bukan ukuran frekuensi kecelakaan.",
    "Kendaraan: tahun terbaru per kab (2023-2025); pertumbuhan = CAGR antara tahun pertama dan terakhir bila >= 2 tahun; cakupan kab tidak lengkap.",
    "LHR/VCR: hanya ruas jalan nasional (data tahun bervariasi 2010-2023); ruas lintas kab dihitung untuk tiap kab yang dilaluinya.",
    "Jalan Tidak Mantap (%) dari kemantapan_ijd_2026; panjang jalan dari bps_kabupaten_jalan 2025.",
    "PSC 119: survei 187 PSC / 27 provinsi; kab/kota tanpa baris ditulis 'Tidak ada data' (bukan berarti tidak punya PSC). PSC tidak memiliki koordinat, jarak/waktu tempuh ke LRK/JPL belum dihitung. Waktu respons adalah teks bebas dari survei.",
    "Data yang belum ada di database: RS/puskesmas, inventaris rambu/marka/APILL/guardrail/PJU, uji kendaraan, kelembagaan, program/anggaran, RAK LLAJ, kebijakan (No. 8-11 kerangka).",
]


def _q(sql, args=None):
    with db_cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def _norm_prov(s):
    s = re.sub(r"[^A-Z ]", " ", (s or "").upper())
    s = re.sub(r"\b(DAERAH ISTIMEWA|D I|DI|DKI|PROVINSI|PROV)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _norm_kab(s):
    """-> (tipe, nama) dengan tipe 'KOTA'/'KAB' agar homonim tidak tertukar."""
    u = re.sub(r"[^A-Z ]", " ", (s or "").upper())
    u = re.sub(r"\bADM\b|\bADMINISTRASI\b", " ", u)
    tipe = "KOTA" if re.search(r"\bKOTA\b", u) else "KAB"
    u = re.sub(r"\b(KABUPATEN|KAB|KOTA)\b", " ", u)
    return tipe, re.sub(r"\s+", " ", u).strip()


def load_wilayah():
    """-> (master DataFrame kab/kota BPS 2025, kode_from_text(prov, kab)).
    kode_from_text mencocokkan nama teks bebas ke kode kab BPS (None bila gagal)."""
    master = pd.DataFrame(_q("""
        select kode_kabupaten::text as kode_kab, min(provinsi) as provinsi,
               min(kabupaten_kota) as kabupaten_kota,
               count(distinct kode_kecamatan) as jumlah_kecamatan,
               sum(jumlah_penduduk) as penduduk_2025
        from penduduk_kecamatan group by kode_kabupaten order by 1"""))
    key_to_kode = {}
    for r in master.itertuples():
        _, n = _norm_kab(r.kabupaten_kota)
        # penduduk_kecamatan tidak menandai tipe; kode_kab xx71-xx79 = kota
        tipe = "KOTA" if int(r.kode_kab[2:]) >= 71 else "KAB"
        key_to_kode[(_norm_prov(r.provinsi), tipe, n)] = r.kode_kab

    def kode_from_text(prov, kab):
        t, n = _norm_kab(kab)
        n = _ALIAS_KAB.get(n, n)
        p = _norm_prov(prov)
        # tipe tidak selalu tertulis di sumber (mis. "Jakarta Barat"): coba kedua tipe
        return key_to_kode.get((p, t, n)) or key_to_kode.get((p, "KOTA" if t == "KAB" else "KAB", n))

    return master, kode_from_text


def points_by_kab(kode_from_text, layer_provinsi, layer):
    """Titik layer map_layers -> kab/kota lewat spatial join ke poligon BATAS KECAMATAN."""
    rows = _q("""
        select p.attrs as pattrs, ST_Y(p.geom) as lat, ST_X(p.geom) as lon, k.attrs as kattrs
        from map_layers p
        left join lateral (
            select attrs from map_layers k
            where k.provinsi='BATAS KECAMATAN' and ST_Intersects(k.geom, p.geom)
            limit 1) k on true
        where p.provinsi=%s and p.layer=%s""", (layer_provinsi, layer))
    out = []
    for r in rows:
        ka = r["kattrs"] or {}
        kode = None
        if ka.get("KODE_KECAMATAN"):
            kode = str(int(ka["KODE_KECAMATAN"]) // 1000)
        elif ka:
            kode = kode_from_text(ka.get("PROVINSI"), ka.get("KABUPATEN_KOTA"))
        out.append({**r["pattrs"], "_kode_kab": kode, "_lat": r["lat"], "_lon": r["lon"],
                    "_kab_poligon": ka.get("KABUPATEN_KOTA"), "_kec_poligon": ka.get("KECAMATAN")})
    return out


def _build():
    """Hitung ulang semua sheet -> dict nama_sheet -> DataFrame."""
    master, kode_from_text = load_wilayah()

    lrk = points_by_kab(kode_from_text, "JALAN NASIONAL", "LOKASI RAWAN KECELAKAAN 2026")
    blk = points_by_kab(kode_from_text, "JALAN NASIONAL", "BLACKSPOT KECELAKAAN")
    xrel = points_by_kab(kode_from_text, "TITIK POTONG JALAN-REL KA", "Titik Potong Jalan - Rel KA")
    ssk = points_by_kab(kode_from_text, "PERLINTASAN SEBIDANG KA", "Rencana Penanganan SS KA (Titik JPL)")

    def count_by(rows, pred=None):
        c = defaultdict(int)
        for r in rows:
            if r["_kode_kab"] and (pred is None or pred(r)):
                c[r["_kode_kab"]] += 1
        return c

    def prov_tercakup(rows):
        return {r["_kode_kab"][:2] for r in rows if r["_kode_kab"]}

    def hit(counter, cov, k):
        """0 hanya bila provinsi termasuk cakupan layer; di luar cakupan -> kosong."""
        return counter.get(k, 0) if k[:2] in cov else None

    c_lrk, c_blk, c_xrel, c_ss = count_by(lrk), count_by(blk), count_by(xrel), count_by(ssk)
    c_xrel_nas = count_by(xrel, lambda r: r.get("jenis_jalan") in ("Nasional", "Provinsi"))
    cov_lrk, cov_blk = prov_tercakup(lrk), prov_tercakup(blk)
    cov_xrel, cov_ss = prov_tercakup(xrel), prov_tercakup(ssk)

    # --- kendaraan
    kend = pd.DataFrame(_q("""select kode_kab, tahun, jumlah from bps_kabupaten_kendaraan
                              where jumlah is not null order by kode_kab, tahun"""))
    kend_last, kend_tumbuh = {}, {}
    for kode, g in (kend.groupby("kode_kab") if len(kend) else []):
        last, first = g.iloc[-1], g.iloc[0]
        kend_last[kode] = (int(last.tahun), int(last.jumlah))
        if len(g) >= 2 and first.jumlah > 0 and last.tahun != first.tahun:
            yrs = int(last.tahun - first.tahun)
            kend_tumbuh[kode] = ((last.jumlah / first.jumlah) ** (1 / yrs) - 1) * 100

    # --- jalan
    jalan = {r["kode_kab"]: r for r in _q("""select kode_kab, panjang_negara_km, panjang_provinsi_km,
        panjang_kabkota_km, panjang_total_km from bps_kabupaten_jalan where tahun=2025""")}
    kemantapan = {str(r["kode_wilayah"]): r for r in _q(
        "select kode_wilayah, tidak_mantap_pct from kemantapan_ijd_2026 where jenis_adm in ('Kab.','Kota')")}

    # --- LHR ruas nasional (kolom kabupaten bisa berisi beberapa kab dipisah ';')
    lhr = defaultdict(list)
    for r in _q("""select provinsi, kabupaten, aadt_total, vcr from bps_lhr_ruas_nasional
                   where kabupaten is not null"""):
        for kab in r["kabupaten"].split(";"):
            kode = kode_from_text(r["provinsi"], kab.strip())
            if kode:
                lhr[kode].append(r)

    # --- PSC / JPL
    psc_rows = _q("select * from psc119_layanan order by provinsi, kabupaten_kota")
    psc_by = defaultdict(list)
    for r in psc_rows:
        r["_kode_kab"] = kode_from_text(r["provinsi"], r["kabupaten_kota"])
        if r["_kode_kab"]:
            psc_by[r["_kode_kab"]].append(r)
    jpl_rows = _q("select * from jpl_prioritas_djka order by provinsi, kota_kab, no")
    jpl_by = defaultdict(list)
    for r in jpl_rows:
        r["_kode_kab"] = kode_from_text(r["provinsi"], r["kota_kab"])
        if r["_kode_kab"]:
            jpl_by[r["_kode_kab"]].append(r)

    # --- sheet utama
    def _f(v):
        return float(v) if v is not None else None

    rows = []
    for m in master.itertuples():
        k = m.kode_kab
        pend = int(m.penduduk_2025) or None  # 0 = belum ada data penduduk
        j, kem, ky = jalan.get(k), kemantapan.get(k), kend_last.get(k)
        lh = lhr.get(k, [])
        vcrs = [float(x["vcr"]) for x in lh if x["vcr"] is not None]
        psc, jp = psc_by.get(k, []), jpl_by.get(k, [])
        ada_psc = bool(psc)
        ambulans = sum(p["jumlah_ambulans_aktif"] or 0 for p in psc) if ada_psc else None
        total_km = float(j["panjang_total_km"]) if j and j["panjang_total_km"] else None
        rows.append({
            "Kode Kab/Kota": k, "Provinsi": m.provinsi, "Kabupaten/Kota": m.kabupaten_kota,
            "Jumlah Kecamatan": m.jumlah_kecamatan, "Penduduk 2025": pend,
            # exposure (No. 5)
            "Kendaraan Bermotor": ky[1] if ky else None,
            "Tahun Data Kendaraan": ky[0] if ky else None,
            "Kendaraan per 1.000 Penduduk": round(ky[1] / pend * 1000, 1) if ky and pend else None,
            "Pertumbuhan Kendaraan (%/thn)": round(kend_tumbuh[k], 2) if k in kend_tumbuh else None,
            "Jumlah Ruas Jalan Nasional (LHR)": len(lh) or None,
            "Rata-rata VCR Ruas Nasional": round(sum(vcrs) / len(vcrs), 3) if vcrs else None,
            "VCR Maksimum Ruas Nasional": round(max(vcrs), 3) if vcrs else None,
            "AADT Maksimum Ruas Nasional": max((x["aadt_total"] or 0) for x in lh) if lh else None,
            # jalan & prasarana (No. 4)
            "Panjang Jalan Total (km, 2025)": total_km,
            "Panjang Jalan Nasional (km)": _f(j["panjang_negara_km"]) if j else None,
            "Panjang Jalan Provinsi (km)": _f(j["panjang_provinsi_km"]) if j else None,
            "Panjang Jalan Kab/Kota (km)": _f(j["panjang_kabkota_km"]) if j else None,
            "Jalan Tidak Mantap (%)": _f(kem["tidak_mantap_pct"]) if kem else None,
            "Kendaraan per km Jalan": round(ky[1] / total_km, 1) if ky and total_km else None,
            "Jumlah LRK 2026": hit(c_lrk, cov_lrk, k),
            "Jumlah Blackspot": hit(c_blk, cov_blk, k),
            "Titik Potong Jalan-Rel KA": hit(c_xrel, cov_xrel, k),
            "  - di Jalan Nasional/Provinsi": hit(c_xrel_nas, cov_xrel, k),
            "Jumlah JPL Prioritas DJKA": len(jp) or None,
            "  - Tidak Dijaga": sum(1 for x in jp if "tidak dijaga" in (x["status_penjagaan"] or "").lower()) if jp else None,
            "Titik Penanganan SS KA (Rencana)": hit(c_ss, cov_ss, k),
            # penanganan korban (No. 6)
            "Ada PSC 119 (survei)": "Ya" if ada_psc else "Tidak ada data",
            "PSC - Jumlah Ambulans Aktif": ambulans,
            "Ambulans per 100.000 Penduduk": round(ambulans / pend * 100000, 2) if ada_psc and pend else None,
            "PSC - Waktu Respons (laporan)": "; ".join(sorted({p["rata_rata_waktu_respon"] for p in psc if p["rata_rata_waktu_respon"]})) if ada_psc else None,
            "PSC - Operasional 24 Jam": ("Ya" if any((p["status_operasional_2026"] or "").lower().startswith("24") for p in psc) else "Tidak") if ada_psc else None,
            "PSC - Terintegrasi RS": ("Ya" if any(p["integrasi_rumah_sakit"] == "Ya" for p in psc) else "Tidak") if ada_psc else None,
            "PSC - Kasus Kecelakaan Ditangani": sum(p["kasus_kecelakaan_ditangani"] or 0 for p in psc) if ada_psc else None,
        })
    utama = pd.DataFrame(rows)

    sheet_psc = pd.DataFrame([{
        "Kode Kab/Kota (cocok)": r["_kode_kab"], "Provinsi": r["provinsi"], "Kab/Kota": r["kabupaten_kota"],
        "Nama PSC": r["nama_psc"], "Lokasi PSC": r["lokasi_psc"], "Status": r["status_psc"],
        "Operasional": r["status_operasional_2026"], "Operator": r["jumlah_operator_call_center"],
        "Personel Lapangan": r["jumlah_personel_lapangan"], "Ambulans Aktif": r["jumlah_ambulans_aktif"],
        "GPS Tracking": r["kesediaan_gps_tracking"], "Integrasi RS": r["integrasi_rumah_sakit"],
        "Kasus Kecelakaan Ditangani": r["kasus_kecelakaan_ditangani"],
        "Waktu Respons": r["rata_rata_waktu_respon"], "Kendala": r["kendala_tantangan"],
        "Estimasi Anggaran/Tahun": r["estimasi_anggaran_pertahun"]} for r in psc_rows])
    sheet_jpl = pd.DataFrame([{
        "Kode Kab/Kota (cocok)": r["_kode_kab"], "Provinsi": r["provinsi"], "Kota/Kab": r["kota_kab"],
        "Wilayah BTP": r["btp_wilayah_kerja"], "Petak Stasiun": r["petak_stasiun"], "No JPL": r["no_jpl"],
        "KM/HM": r["lokasi_km_hm"], "Status Penjagaan": r["status_penjagaan"],
        "Kategori Jalan": r["kategori_jalan"], "Nama Jalan": r["nama_jalan"],
        "Lebar Jalan (m)": _f(r["lebar_jalan_m"]), "Jenis Jalur KA": r["jenis_jalur_ka"],
        "Frekuensi KA": r["frekuensi_ka"], "Headway": r["headway_ka"], "Daop/Divre": r["daop_divre"],
        "Jumlah Kecelakaan": r["jumlah_kecelakaan"]} for r in jpl_rows])

    def titik(rows_, jenis):
        return [{"Jenis": jenis, "Kode Kab/Kota (spasial)": r["_kode_kab"],
                 "Kab/Kota (poligon)": r["_kab_poligon"], "Kecamatan (poligon)": r["_kec_poligon"],
                 "Provinsi (sumber)": r.get("provinsi") or r.get("prov"),
                 "Nama Ruas": r.get("nama_ruas"), "Latitude": r["_lat"], "Longitude": r["_lon"]}
                for r in rows_]

    return {
        "Profil Kab-Kota": utama,
        "PSC 119": sheet_psc,
        "JPL Prioritas": sheet_jpl,
        "LRK & Blackspot": pd.DataFrame(titik(lrk, "LRK 2026") + titik(blk, "Blackspot")),
        "Keterangan": pd.DataFrame({"Keterangan": KETERANGAN}),
    }


def get_sheets():
    """Hasil _build() di-cache in-process (TTL 10 menit): spatial join titik->kecamatan
    memakan beberapa detik, tidak layak diulang tiap halaman preview."""
    if _cache["sheets"] is None or time.time() - _cache["ts"] > _CACHE_TTL_DETIK:
        _cache["sheets"] = _build()
        _cache["ts"] = time.time()
    return _cache["sheets"]


def filter_sheets(sheets, provinsi="", q=""):
    """Filter sheet Profil per provinsi/nama kab (contains, case-insensitive);
    sheet PSC/JPL/titik ikut lewat kode kab hasil filter itu."""
    utama = sheets["Profil Kab-Kota"]
    if provinsi:
        utama = utama[utama["Provinsi"].str.contains(re.escape(provinsi), case=False, na=False)]
    if q:
        utama = utama[utama["Kabupaten/Kota"].str.contains(re.escape(q), case=False, na=False)]
    if not provinsi and not q:
        return sheets
    kode = set(utama["Kode Kab/Kota"])
    out = dict(sheets, **{"Profil Kab-Kota": utama})
    for nama, kol in (("PSC 119", "Kode Kab/Kota (cocok)"), ("JPL Prioritas", "Kode Kab/Kota (cocok)"),
                      ("LRK & Blackspot", "Kode Kab/Kota (spasial)")):
        df = sheets[nama]
        out[nama] = df[df[kol].isin(kode)] if len(df) else df
    return out


def to_json_rows(df):
    """DataFrame -> list baris JSON-aman (NaN -> None, tipe numpy -> Python)."""
    return df.astype(object).where(pd.notna(df), None).values.tolist()


def write_workbook(sheets, target):
    """Tulis semua sheet ke `target` (path atau BytesIO), dengan freeze panes,
    filter, dan lebar kolom otomatis."""
    with pd.ExcelWriter(target, engine="openpyxl") as xw:
        for nama, df in sheets.items():
            df.to_excel(xw, sheet_name=nama, index=False)
        for ws in xw.book.worksheets:
            ws.freeze_panes = "D2" if ws.title == "Profil Kab-Kota" else "A2"
            ws.auto_filter.ref = ws.dimensions
            for col in ws.columns:
                w = max(len(str(c.value)) if c.value is not None else 0 for c in list(col)[:200])
                ws.column_dimensions[col[0].column_letter].width = min(
                    max(10, w + 2), 150 if ws.title == "Keterangan" else 60)


def export_bytes(provinsi="", q=""):
    buf = io.BytesIO()
    write_workbook(filter_sheets(get_sheets(), provinsi, q), buf)
    buf.seek(0)
    return buf
