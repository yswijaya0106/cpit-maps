# -*- coding: utf-8 -*-
"""Impor atribut detail 251 bandara nasional (docs/New/3. UDARA/
Attributes_ Data Bandara.xlsx, sheet "Sheet1") ke tabel referensi
bps_data_bandara -- lihat scripts/schema_bps_data_bandara.sql untuk
skema & alasan tabel terpisah (bukan menimpa layer BANDARA existing),
dan docs/kajian_data_baru_docs_new.md §5 untuk hasil telaah datanya.
TIDAK terkait usulan_inpres/IJD.

Sumbernya punya baris kelanjutan tanpa nomor urut (`NO` kosong) untuk
bandara dengan >1 taxiway -- dideteksi lewat kolom Taxiway (idx 11)
terisi sementara kolom lain kosong, digabung ke baris utama bandara
terakhir yang punya `NO`. Baris separator murni (semua kolom kosong/
whitespace non-breaking-space) dilewati.

Koordinat "Titik Koordinat" berformat DMS notasi Indonesia (LU/LS/BT/
BB) -- diparse ke lat/lon desimal, disimpan di samping teks aslinya.

Idempotent: DELETE + INSERT ulang seluruh tabel tiap run. Hasil
match_bps_data_bandara_kemenhub.py (bandara_kemenhub_id, match_skor)
dipertahankan lintas impor ulang (dibaca dulu sebelum DELETE, kunci `no`).

Lapisan koreksi (3 Okt 2026, docs/kajian_data_udara_bandara.md) -- nilai
asli sumber TIDAK diubah kecuali dua kasus satuan yg jelas, semua dicatat
di `catatan_data`:
  - KP/KD sumber disimpan apa adanya di kode_provinsi/kode_kabupaten.
    Kode BPS yg benar ada di kode_provinsi_bps/kode_kabupaten_bps,
    diturunkan dari titik (poligon BATAS KABUPATEN) dicek silang dgn nama
    kabupaten sumber: KD sumber memakai urutan Kemendagri utk Papua Tengah/
    Pegunungan (join langsung cocok ke kabupaten yg SALAH, mis. 9601 =
    Nabire di sumber tapi Mimika di master BPS), 98xx utk Papua Barat Daya
    (master 92xx), dan beberapa Kab/Kota tertukar (Husein Sastranegara, El
    Tari, dst.).
  - Koordinat diambil dari bandara_kemenhub bila sumber kosong, atau bila
    titik sumber jatuh di luar kabupatennya sendiri sedangkan titik
    Kemenhub di dalamnya (Maimun Saleh tersalin dari Malikussaleh, Namrole
    jatuh di Kota Ambon). `koordinat_sumber` mencatat asalnya.
  - Satuan: runway < 100 "m" dan luas apron pecahan < 1000 = pemisah ribuan
    terbaca desimal (Sam Ratulangi 2,65 / 89,424) -> dikali 1000.
  - Kapasitas valid vs estimasi selisih >10x atau > 2.000 pax/m2 terminal
    -> hanya ditandai (Wunopito 15 juta di terminal 1.080 m2).
  - demand_pax TIDAK dikoreksi tapi satuannya tidak seragam antarbandara
    (hanya 7/100 sebanding dgn penumpang aktual Kemenhub 2025) -- jangan
    dijumlahkan/dibandingkan; pakai bandara_kemenhub.lalu_lintas_penumpang.

Usage (venv aktif):
    python scripts/import_bps_data_bandara.py
"""
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import openpyxl

from db import db_cursor as pg_cursor  # noqa: E402
from wilayah_cocok import PencocokKabupaten  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
# file identik (md5 sama) ada di dua lokasi kiriman data; pakai yang tersedia
XLSX_CANDIDATES = [
    REPO_ROOT / "docs" / "New" / "3. UDARA-20260820T015257Z-1-001" / "3. UDARA" / "Attributes_ Data Bandara.xlsx",
    REPO_ROOT / "docs" / "Konektivitas" / "3. UDARA" / "Attributes_ Data Bandara.xlsx",
]
XLSX_PATH = next((p for p in XLSX_CANDIDATES if p.exists()), XLSX_CANDIDATES[0])
JARAK_KOORDINAT_BEDA_KM = 20   # titik sumber vs Kemenhub dianggap berbeda di atas ini
# titik dianggap "di sebelah" kabupaten namanya -> lokasi titik dipercaya (Kab/Kota tertukar,
# label kabupaten tetangga). 50 km, bukan lebih kecil: kabupaten Papua/Sulawesi luas --
# Lagaligo (19 km), Beoga (20), Ayawasi (37) benar di titiknya; Tiom (188 km) yg salah koordinat.
JARAK_KAB_TETANGGA_KM = 50
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_bps_data_bandara.sql"

# Kolom (0-based tuple index, diverifikasi manual thd baris data --
# header 2-baris merge di sumber xlsx tidak bisa dipercaya index-nya
# begitu saja): 0=NO, 1=Nama Bandara, 2=Hirarki, 3=Kelas, 4=Provinsi,
# 5=Kabupaten, 6=Status, 7=Operator, 8=Runway Length, 9=Runway Width,
# 10=Apron Area, 11=Taxiway, 12=Terminal Penumpang, 13=Demand Pax,
# 14=Terminal Kargo, 15=Critical Aircraft, 16=Kapasitas Eksisting Valid,
# 17=Kapasitas Eksisting Estimasi, 18=Titik Koordinat, 19=KP, 20=KD.
COL_NO, COL_NAMA, COL_HIRARKI, COL_KELAS = 0, 1, 2, 3
COL_PROVINSI, COL_KABUPATEN, COL_STATUS, COL_OPERATOR = 4, 5, 6, 7
COL_RW_LEN, COL_RW_WID, COL_APRON, COL_TAXIWAY = 8, 9, 10, 11
COL_TERM_PAX, COL_DEMAND, COL_TERM_KARGO, COL_CRITICAL_AC = 12, 13, 14, 15
COL_KAP_VALID, COL_KAP_ESTIMASI = 16, 17
COL_KOORDINAT, COL_KP, COL_KD = 18, 19, 20

_DMS_RE = re.compile(r"(\d+)\D+(\d+)\D+([\d.,]+)\D*(N|S|E|W|LU|LS|BT|BB)", re.IGNORECASE)
_NEGATIVE_HEMI = {"S", "W", "LS", "BB"}


def _parse_dms(s):
    if not s:
        return None
    m = _DMS_RE.search(str(s))
    if not m:
        return None
    deg, minute, sec, hemi = m.groups()
    sec = sec.replace(",", ".")
    try:
        val = float(deg) + float(minute) / 60 + float(sec) / 3600
    except ValueError:
        return None
    return -val if hemi.upper() in _NEGATIVE_HEMI else val


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None  # mis. "Tidak Terdefinisi"


def _text(v):
    if v is None:
        return None
    s = str(v).replace("\xa0", "").strip()
    return s or None


def _load_rows():
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True, read_only=True)
    ws = wb["Sheet1"]
    rows = []
    current = None  # dict baris bandara aktif (menampung baris kelanjutan taxiway)

    for row in ws.iter_rows(min_row=4, values_only=True):
        no = row[COL_NO]
        if isinstance(no, (int, float)):
            if current is not None:
                rows.append(current)
            lat = _parse_dms(row[COL_KOORDINAT])
            lon = None
            if row[COL_KOORDINAT]:
                # DMS dua pasang (lat lalu lon) dlm satu string -- cari pasangan kedua
                m_all = list(_DMS_RE.finditer(str(row[COL_KOORDINAT])))
                if len(m_all) >= 2:
                    d, mi, se, hemi = m_all[1].groups()
                    se = se.replace(",", ".")
                    try:
                        lon = float(d) + float(mi) / 60 + float(se) / 3600
                        if hemi.upper() in _NEGATIVE_HEMI:
                            lon = -lon
                    except ValueError:
                        lon = None
            current = {
                "no": int(no), "nama_bandara": _text(row[COL_NAMA]),
                "hirarki": _text(row[COL_HIRARKI]), "kelas": _text(row[COL_KELAS]),
                "provinsi": _text(row[COL_PROVINSI]), "kabupaten": _text(row[COL_KABUPATEN]),
                "status": _text(row[COL_STATUS]), "operator": _text(row[COL_OPERATOR]),
                "runway_length_m": _num(row[COL_RW_LEN]), "runway_width_m": _num(row[COL_RW_WID]),
                "apron_area_m2": _num(row[COL_APRON]),
                "taxiway": [t for t in [_text(row[COL_TAXIWAY])] if t],
                "terminal_penumpang_m2": _num(row[COL_TERM_PAX]), "demand_pax": _num(row[COL_DEMAND]),
                "terminal_kargo": _text(row[COL_TERM_KARGO]), "critical_aircraft": _text(row[COL_CRITICAL_AC]),
                "kapasitas_eksisting_valid": _num(row[COL_KAP_VALID]),
                "kapasitas_eksisting_estimasi": _num(row[COL_KAP_ESTIMASI]),
                "titik_koordinat_dms": _text(row[COL_KOORDINAT]),
                "lat": lat, "lon": lon,
                "kode_provinsi": int(row[COL_KP]) if isinstance(row[COL_KP], (int, float)) else None,
                "kode_kabupaten": int(row[COL_KD]) if isinstance(row[COL_KD], (int, float)) else None,
            }
        elif current is not None:
            tw = _text(row[COL_TAXIWAY])
            if tw:
                current["taxiway"].append(tw)

    if current is not None:
        rows.append(current)

    for r in rows:
        r["taxiway"] = "; ".join(r["taxiway"]) or None
        r["catatan"] = []
    return rows


# ---------------------------------------------------------------- koreksi

def _kab_di_titik(cur, lat, lon):
    """kode kabupaten BPS poligon BATAS KABUPATEN yg memuat titik; titik di
    laut/pantai (mis. Miangas) -> poligon terdekat bila <= 2 km."""
    cur.execute("SELECT (attrs->>'KODE_KABUPATEN')::int AS k FROM map_layers WHERE provinsi='BATAS KABUPATEN' "
                "AND ST_Intersects(geom, ST_SetSRID(ST_Point(%s, %s), 4326)) LIMIT 1", (lon, lat))
    r = cur.fetchone()
    if r:
        return r["k"]
    cur.execute("SELECT (attrs->>'KODE_KABUPATEN')::int AS k, ST_Distance(geom::geography, "
                "ST_SetSRID(ST_Point(%s, %s), 4326)::geography) AS m FROM map_layers WHERE provinsi='BATAS KABUPATEN' "
                "ORDER BY geom <-> ST_SetSRID(ST_Point(%s, %s), 4326) LIMIT 1", (lon, lat, lon, lat))
    r = cur.fetchone()
    return r["k"] if r and r["m"] <= 2000 else None


def _jarak_ke_kab_km(cur, kode_kab, lat, lon):
    cur.execute("SELECT min(ST_Distance(geom::geography, ST_SetSRID(ST_Point(%s, %s), 4326)::geography)) / 1000 AS km "
                "FROM map_layers WHERE provinsi='BATAS KABUPATEN' AND attrs->>'KODE_KABUPATEN' = %s",
                (lon, lat, str(kode_kab)))
    r = cur.fetchone()
    return float(r["km"]) if r and r["km"] is not None else None


def _jarak_km(lat1, lon1, lat2, lon2):
    import math
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


def koreksi_satuan(r):
    rw = r["runway_length_m"]
    if rw is not None and rw != int(rw) and rw < 100:  # pecahan saja: 2,65 = 2.650 m
        r["catatan"].append(f"Runway sumber {rw:g} (pemisah ribuan terbaca desimal) -> {rw * 1000:g} m")
        r["runway_length_m"] = round(rw * 1000)
    elif rw is not None and rw < 300:  # bulat kecil (mis. Teraplu 84): tak bisa ditebak, tandai saja
        r["catatan"].append(f"Runway {rw:g} m tidak wajar; nilai tidak diubah")
    ap = r["apron_area_m2"]
    if ap is not None and ap != int(ap) and ap < 1000:
        r["catatan"].append(f"Apron sumber {ap:g} (pemisah ribuan terbaca desimal) -> {ap * 1000:g} m2")
        r["apron_area_m2"] = round(ap * 1000)


def tandai_kapasitas(r):
    v, e, t = r["kapasitas_eksisting_valid"], r["kapasitas_eksisting_estimasi"], r["terminal_penumpang_m2"]
    if v and e and max(v, e) / min(v, e) > 10:
        r["catatan"].append(f"Kapasitas valid {v:,.0f} vs estimasi {e:,.0f} selisih >10x; kemungkinan salah ketik")
    for label, k in (("valid", v), ("estimasi", e)):
        if k and t and k / t > 2000:
            r["catatan"].append(f"Kapasitas {label} {k:,.0f} pax/thn utk terminal {t:,.0f} m2 (>2.000 pax/m2) tidak wajar")


def koreksi_lokasi(cur, r, pencocok, kemenhub):
    """Isi lat/lon (bila perlu dari Kemenhub), koordinat_sumber, kode_*_bps."""
    m = pencocok.cari(r["provinsi"], r["kabupaten"])
    kode_nama = int(m["kode_kabupaten"]) if m else None
    km = kemenhub.get(r["bandara_kemenhub_id"]) if r.get("bandara_kemenhub_id") else None
    r["koordinat_sumber"] = "sumber" if r["lat"] is not None else None

    if r["lat"] is None and km:
        r["lat"], r["lon"], r["koordinat_sumber"] = km["lat"], km["lon"], "bandara_kemenhub"
        r["catatan"].append("Koordinat kosong di sumber; diisi dari bandara_kemenhub")
    elif r["lat"] is not None and km and kode_nama:
        d = _jarak_km(r["lat"], r["lon"], km["lat"], km["lon"])
        if d > JARAK_KOORDINAT_BEDA_KM:
            k_src = _kab_di_titik(cur, r["lat"], r["lon"])
            k_kmh = _kab_di_titik(cur, km["lat"], km["lon"])
            if k_src != kode_nama and k_kmh == kode_nama:
                r["catatan"].append(f"Koordinat sumber jatuh di luar kab. {r['kabupaten']} ({d:.0f} km dari titik "
                                    f"Kemenhub); dipakai koordinat bandara_kemenhub")
                r["lat"], r["lon"], r["koordinat_sumber"] = km["lat"], km["lon"], "bandara_kemenhub"
            else:
                r["catatan"].append(f"Koordinat sumber berbeda {d:.0f} km dari bandara_kemenhub; koordinat sumber "
                                    f"dipertahankan (konsisten dgn kabupatennya)")

    kode = None
    if r["lat"] is not None:
        kode_titik = _kab_di_titik(cur, r["lat"], r["lon"])
        if kode_titik and kode_nama and kode_titik != kode_nama:
            jarak = _jarak_ke_kab_km(cur, kode_nama, r["lat"], r["lon"])
            if jarak is not None and jarak <= JARAK_KAB_TETANGGA_KM:
                kode = kode_titik  # label sumber kab tetangga (Kab/Kota tertukar dst.) -> lokasi yg dipakai
                if kode_titik != r["kode_kabupaten"]:  # KD sumber sudah = titik -> nama polos ambigu saja, bukan temuan
                    r["catatan"].append(f"Kabupaten sumber '{r['kabupaten']}' tapi titik di kab. {kode_titik}; "
                                        f"dipakai lokasi titik")
            else:
                kode = kode_nama
                r["catatan"].append(f"Titik jatuh di kab. {kode_titik}, {jarak:.0f} km dari kab. sumber "
                                    f"'{r['kabupaten']}'; koordinat perlu dicek, dipakai kode dari nama")
        else:
            kode = kode_titik or kode_nama
    else:
        kode = kode_nama
    r["kode_kabupaten_bps"] = kode
    r["kode_provinsi_bps"] = kode // 100 if kode else None
    if kode and r["kode_kabupaten"] != kode:
        r["catatan"].append(f"KD sumber {r['kode_kabupaten']} -> kode BPS {kode}")
    if r["kode_provinsi"] and kode and r["kode_provinsi"] != kode // 100:
        r["catatan"].append(f"KP sumber {r['kode_provinsi']} tidak sesuai kode kabupaten")


def main():
    if not XLSX_PATH.exists():
        print(f"GAGAL: tidak ditemukan {XLSX_PATH}")
        sys.exit(1)

    with pg_cursor() as cur:
        cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

    print(f"Membaca {XLSX_PATH.name}...")
    rows = _load_rows()
    print(f"  {len(rows)} bandara")

    with pg_cursor() as cur:
        # pertahankan hasil match ke bandara_kemenhub lintas impor ulang
        cur.execute("SELECT no, bandara_kemenhub_id, match_skor FROM bps_data_bandara")
        match = {x["no"]: x for x in cur.fetchall()}
        cur.execute("SELECT bandara_id, lat, lon FROM bandara_kemenhub WHERE lat IS NOT NULL AND lon IS NOT NULL")
        kemenhub = {x["bandara_id"]: {"lat": float(x["lat"]), "lon": float(x["lon"])} for x in cur.fetchall()}
        cur.execute("SELECT DISTINCT kode_provinsi, provinsi, kode_kabupaten, kabupaten_kota FROM penduduk_kecamatan")
        pencocok = PencocokKabupaten(cur.fetchall())
        for r in rows:
            mm = match.get(r["no"]) or {}
            r["bandara_kemenhub_id"], r["match_skor"] = mm.get("bandara_kemenhub_id"), mm.get("match_skor")
            koreksi_satuan(r)
            tandai_kapasitas(r)
            koreksi_lokasi(cur, r, pencocok, kemenhub)
            r["catatan_data"] = "; ".join(r.pop("catatan")) or None

    cols = ["no", "nama_bandara", "hirarki", "kelas", "provinsi", "kabupaten", "status",
            "operator", "runway_length_m", "runway_width_m", "apron_area_m2", "taxiway",
            "terminal_penumpang_m2", "demand_pax", "terminal_kargo", "critical_aircraft",
            "kapasitas_eksisting_valid", "kapasitas_eksisting_estimasi",
            "titik_koordinat_dms", "lat", "lon", "kode_provinsi", "kode_kabupaten",
            "kode_provinsi_bps", "kode_kabupaten_bps", "koordinat_sumber", "catatan_data",
            "bandara_kemenhub_id", "match_skor"]
    placeholders = ", ".join(["%s"] * len(cols))

    with pg_cursor() as cur:
        cur.execute("DELETE FROM bps_data_bandara")
        cur.executemany(
            f"INSERT INTO bps_data_bandara ({', '.join(cols)}) VALUES ({placeholders})",
            [tuple(r[c] for c in cols) for r in rows],
        )

    n_cat = sum(1 for r in rows if r["catatan_data"])
    print(f"  kode_kabupaten_bps terisi: {sum(1 for r in rows if r['kode_kabupaten_bps'])}/{len(rows)}; "
          f"KD sumber != kode BPS: {sum(1 for r in rows if r['kode_kabupaten_bps'] and r['kode_kabupaten'] != r['kode_kabupaten_bps'])}")
    print(f"  koordinat dari bandara_kemenhub: {sum(1 for r in rows if r['koordinat_sumber'] == 'bandara_kemenhub')}; "
          f"tanpa koordinat: {sum(1 for r in rows if r['lat'] is None)}; baris bercatatan: {n_cat}")
    print("\nSelesai: bps_data_bandara di-refresh.")


if __name__ == "__main__":
    main()
