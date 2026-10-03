# -*- coding: utf-8 -*-
"""Impor data BPSDM Perhubungan (docs/Konektivitas/7. BPSDM PERHUBUNGAN/, 7 xlsx)
ke 7 tabel `bpsdm_*` (menu Data) + overlay titik UPT di `map_layers` (bucket flat
"BPSDM PERHUBUNGAN"). Telaah datanya: docs/kajian_data_bpsdm_perhubungan.md.

Kunci gabung = `kode_upt` (kode 13 digit dari file 1, satu-satunya ID UPT di
sumber). File lain hanya memakai nama/singkatan yang berbeda-beda ("PTDI-STTD",
"Sekolah Tinggi Transportasi Darat", "PPI Madiun" vs "PPI Curug" -- PPI dua arti),
dan Kode Daerah TIDAK unik per UPT (7371 dipakai 3 UPT), jadi nama dipetakan ke
kode_upt lewat aturan kata kunci eksplisit `kode_upt_dari_nama()`. Nama yang tak
terpetakan menggagalkan skrip (bukan dilewati diam-diam).

Kode wilayah: kode_kabupaten diturunkan dari KOORDINAT (point-in-polygon layer
BATAS KABUPATEN), bukan dari "Kode Daerah" sumber -- 3 UPT kodenya tidak cocok
dgn lokasinya (Sorong 9806 -> 9271, PPI Madiun 3519 -> 3577, Poltektrans SDP
3519 1671 -> 1607 Banyuasin). Kode sumber tetap disimpan (kode_daerah_sumber) dan
selisihnya dicatat di catatan_data. Poligon DKI Jakarta tidak ber-KODE_KABUPATEN
-> pakai kode sumber.

Koreksi angka (ditandai di catatan_data, nilai mentah tidak hilang):
  - sertifikat: angka pecahan < 1000 (mis. Barombong "84.536") = pemisah ribuan
    terbaca desimal -> x1000.
  - sertifikat: nilai > 5x median tahun lain UPT yg sama (BP3IP 2023 475.448)
    HANYA ditandai, tidak diubah.
  - "-"/"--" = tidak ada data/tidak ada kegiatan -> NULL, bukan 0.
  - Subtotal UPT/matra/nasional di file 5-7 TIDAK diimpor (8 UPT subtotalnya
    kosong sehingga total sumber kurang ~2.600 mahasiswa); agregat dihitung dari
    baris prodi.

Idempotent: tabel DELETE + INSERT, layer overlay dihapus & diisi ulang.
Cache layer di server berkunci imported_at -> tidak perlu restart.

Usage (venv aktif):
    python scripts/import_bpsdm_perhubungan.py
"""
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import openpyxl  # noqa: E402
from psycopg.types.json import Json  # noqa: E402

from db import db_cursor  # noqa: E402

SRC = ROOT / "docs" / "Konektivitas" / "7. BPSDM PERHUBUNGAN"
F_TITIK = "1. Titik Koordinat di Lingkungan BPSDMP.xlsx"
F_PRODI = "2. Daftar Program Studi di Lingkungan BPSDMP.xlsx"
F_FASILITAS = "3. Data Fasilitas di Lingkungan BPSDMP.xlsx"
F_DOSEN = "4. Jumlah Tenaga Pengajar di Lingkungan BPSDMP.xlsx"
F_MHS = "5-7. Jumlah Peminat, Mahasiswa, Lulusan di Lingkungan BPSDMP.xlsx"
F_SERTIFIKAT = "8. Jumlah dan Jenis Sertifikat di Lingkungan BPSDMP.xlsx"
F_SERAP = "9. Jumlah Lulusan BPSDMP Yang Terserap di Dunia Kerja.xlsx"

BUCKET = "BPSDM PERHUBUNGAN"

# kode_upt -> (singkatan, matra, jenis). Kode dari kolom "kode" file 1.
MASTER = {
    "8000000000000": ("BPSDMP", "Lintas Matra", "Kantor Pusat"),
    "8001000000000": ("Sekretariat BPSDMP", "Lintas Matra", "Kantor Pusat"),
    "0": ("Kemenhub", "Lintas Matra", "Kantor Pusat"),
    "8002000000000": ("PPSDM Perhubungan Darat", "Darat", "PPSDM"),
    "8003000000000": ("PPSDM Perhubungan Laut", "Laut", "PPSDM"),
    "8004000000000": ("PPSDM Perhubungan Udara", "Udara", "PPSDM"),
    "8006000000000": ("PPSDM Aparatur Perhubungan", "Lintas Matra", "PPSDM"),
    "8008016000000": ("BP3KSDMT Pasir Jambu", "Lintas Matra", "Balai Diklat"),
    "8016000000000": ("PTDI-STTD Bekasi", "Darat", "Perguruan Tinggi"),
    "8014000000000": ("PKTJ Tegal", "Darat", "Perguruan Tinggi"),
    "8026000000000": ("PPI Madiun", "Darat", "Perguruan Tinggi"),
    "8009000000000": ("Poltektrans SDP Palembang", "Darat", "Perguruan Tinggi"),
    "8020000000000": ("Poltrada Bali", "Darat", "Perguruan Tinggi"),
    "8008005000000": ("BP2TD Mempawah", "Darat", "Balai Diklat"),
    "8017000000000": ("STIP Jakarta", "Laut", "Perguruan Tinggi"),
    "8018000000000": ("PIP Semarang", "Laut", "Perguruan Tinggi"),
    "8019000000000": ("PIP Makassar", "Laut", "Perguruan Tinggi"),
    "8011000000000": ("Poltekpel Surabaya", "Laut", "Perguruan Tinggi"),
    "8021000000000": ("Poltekpel Banten", "Laut", "Perguruan Tinggi"),
    "8013000000000": ("Poltekpel Barombong", "Laut", "Perguruan Tinggi"),
    "8022000000000": ("Poltekpel Sorong", "Laut", "Perguruan Tinggi"),
    "8025000000000": ("Poltekpel Malahayati", "Laut", "Perguruan Tinggi"),
    "8010000000000": ("Poltekpel Sumatera Barat", "Laut", "Perguruan Tinggi"),
    "8027000000000": ("Poltekpel Sulawesi Utara", "Laut", "Perguruan Tinggi"),
    "8015000000000": ("BP3IP Jakarta", "Laut", "Balai Diklat"),
    "8008002000000": ("BP2TL Jakarta", "Laut", "Balai Diklat"),
    "8007000000000": ("PPI Curug", "Udara", "Perguruan Tinggi"),
    "8012000000000": ("Poltekbang Surabaya", "Udara", "Perguruan Tinggi"),
    "8029000000000": ("Poltekbang Medan", "Udara", "Perguruan Tinggi"),
    "8030000000000": ("Poltekbang Makassar", "Udara", "Perguruan Tinggi"),
    "8023000000000": ("Poltekbang Palembang", "Udara", "Perguruan Tinggi"),
    "8024000000000": ("Poltekbang Jayapura", "Udara", "Perguruan Tinggi"),
    "8028000000000": ("API Banyuwangi", "Udara", "Perguruan Tinggi"),
    "8008006000000": ("BP3 Curug", "Udara", "Balai Diklat"),
}

# Layer overlay per matra; Kantor Pusat & PPSDM digabung satu layer.
LAYER_MATRA = {
    "Darat": "UPT MATRA DARAT", "Laut": "UPT MATRA LAUT", "Udara": "UPT MATRA UDARA",
}
LAYER_PUSAT = "KANTOR PUSAT & PPSDM"
LAYER_LABEL = {
    "UPT MATRA DARAT": "UPT Pendidikan Matra Darat",
    "UPT MATRA LAUT": "UPT Pendidikan Matra Laut",
    "UPT MATRA UDARA": "UPT Pendidikan Matra Udara",
    LAYER_PUSAT: "Kantor Pusat, PPSDM & Balai Lintas Matra",
}


def _ns(s) -> str:
    """Nama dinormalkan: huruf kecil, hanya huruf/angka, TANPA spasi
    ("PPICurug" dan "PPI Curug" sama-sama 'ppicurug')."""
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def kode_upt_dari_nama(nama: str) -> str:
    """Nama UPT (format bebas dari file 2-9) -> kode_upt. Urutan aturan
    penting: yang lebih spesifik lebih dulu (mis. BP3IP mengandung "ilmu
    pelayaran", STIP juga; "Balai ... Curug" sebelum "Curug")."""
    n = _ns(nama)
    has = lambda *k: any(x in n for x in k)  # noqa: E731
    if has("kementerianperhubungan"):
        return "0"
    if has("sekretariat"):
        return "8001000000000"
    if has("aparatur"):
        return "8006000000000"
    if has("ppsdm", "pusatpengembangan"):
        for kunci, kode in (("darat", "8002000000000"), ("laut", "8003000000000"), ("udara", "8004000000000")):
            if kunci in n:
                return kode
    if has("badanpengembangan"):
        return "8000000000000"
    if has("bp3ksdmt", "karakter", "pasirjambu"):
        return "8008016000000"
    if has("bp3ip", "penyegaran"):
        return "8015000000000"
    if has("bp2tl", "transportasilaut"):
        return "8008002000000"
    if has("mempawah"):
        return "8008005000000"
    if "curug" in n:
        return "8008006000000" if has("balai", "bp3") else "8007000000000"
    if has("banyuwangi"):
        return "8028000000000"
    if has("sttd", "ptdi", "transportasidaratindonesia", "sekolahtinggitransportasidarat"):
        return "8016000000000"
    if has("pktj", "keselamatantransportasijalan"):
        return "8014000000000"
    if has("madiun"):
        return "8026000000000"
    if has("sdp", "sungai"):
        return "8009000000000"
    if has("poltrada", "transportasidaratbali", "darat") and "bali" in n:
        return "8020000000000"
    if has("stip", "sekolahtinggiilmupelayaran"):
        return "8017000000000"
    if has("ilmupelayaran", "pip"):
        if "semarang" in n:
            return "8018000000000"
        if "makassar" in n:
            return "8019000000000"
    if has("barombong"):
        return "8013000000000"
    if has("malahayati"):
        return "8025000000000"
    if has("sorong"):
        return "8022000000000"
    if has("sumbar", "sumaterabarat"):
        return "8010000000000"
    if has("sulut", "sulawesiutara"):
        return "8027000000000"
    if has("pelayaran", "poltekpel"):
        if "banten" in n:
            return "8021000000000"
        if "surabaya" in n:
            return "8011000000000"
    if has("penerbangan", "poltekbang"):
        for kunci, kode in (("surabaya", "8012000000000"), ("medan", "8029000000000"),
                            ("makassar", "8030000000000"), ("makasar", "8030000000000"),
                            ("palembang", "8023000000000"), ("jayapura", "8024000000000")):
            if kunci in n:
                return kode
    raise ValueError(f"Nama UPT tidak terpetakan ke kode_upt: {nama!r} -- tambahkan aturan di kode_upt_dari_nama()")


def num(v):
    """Sel angka -> float/int; "-", "--", kosong -> None (bukan 0)."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if s in ("", "-", "--"):
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def rows_of(fname, sheet=None):
    wb = openpyxl.load_workbook(SRC / fname, read_only=True, data_only=True)
    ws = wb[sheet] if sheet else wb.worksheets[0]
    return [list(r) for r in ws.iter_rows(values_only=True)]


def bersih(s):
    return re.sub(r"\s+", " ", str(s)).strip() if s is not None else None


# ---------------------------------------------------------------- parser per file

def parse_titik():
    out = []
    for r in rows_of(F_TITIK)[1:]:
        if r[0] is None:
            continue
        kode = str(int(r[3])) if r[3] is not None else None
        if kode not in MASTER:
            raise ValueError(f"kode UPT {kode} ({r[2]}) belum ada di MASTER")
        lat, lon = [float(x) for x in re.split(r"\s*,\s*", str(r[4]).strip())]
        out.append({"kode_upt": kode, "nama": bersih(r[2]), "kode_daerah_sumber": int(r[1]),
                    "lat": lat, "lon": lon, "situs": bersih(r[5])})
    return out


def parse_prodi():
    out, upt = [], None
    for r in rows_of(F_PRODI):
        if r[3] == "Program Studi":
            continue
        if isinstance(r[0], int) and r[2]:
            upt = kode_upt_dari_nama(r[2])
            nama_sumber = bersih(r[2])
        if upt and r[3]:
            prodi = bersih(r[3])
            m = re.match(r"^(D[-.\s]?(?:I{1,3}V?|IV)|S[-.\s]?I{1,2})\s+(.*)$", prodi)
            out.append({"kode_upt": upt, "nama_upt_sumber": nama_sumber,
                        "jenjang": m.group(1).replace(".", "-").replace(" ", "-") if m else None,
                        "program_studi": prodi})
    return out


def parse_dosen():
    """Sheet1: per prodi (dgn akreditasi). Header UPT = baris berhuruf + nama."""
    out, upt, matra = [], None, None
    for r in rows_of(F_DOSEN, "Sheet1"):
        a = r[0]
        if isinstance(a, str) and a.strip().upper().startswith("MATRA"):
            matra = a.strip().title().replace("Matra ", "")
            continue
        if isinstance(a, str) and len(a.strip()) == 1 and r[1]:
            upt = kode_upt_dari_nama(r[1])
            nama_sumber = bersih(r[1])
            continue
        if isinstance(a, int) and upt and r[2]:
            out.append({"kode_upt": upt, "nama_upt_sumber": nama_sumber, "matra": matra,
                        "jenjang": bersih(r[1]), "program_studi": bersih(r[2]),
                        "akreditasi": bersih(r[3]),
                        "asisten_ahli": num(r[4]), "lektor": num(r[5]), "lektor_kepala": num(r[6]),
                        "guru_besar": num(r[7]), "jumlah_dosen": num(r[8])})
    return out


def parse_prodi_berjenjang(fname, kolom):
    """File 5-7 & 9: bagian 'I.'/'II.', header UPT huruf (+ Kode Daerah), baris
    prodi angka. Subtotal UPT/TOTAL tidak diambil."""
    out, upt = [], None
    for r in rows_of(fname):
        a = r[0]
        if isinstance(a, str) and a.strip().endswith("."):
            upt = None
            continue
        if isinstance(a, str) and len(a.strip()) == 1 and r[2]:
            upt = kode_upt_dari_nama(r[2])
            nama_sumber = bersih(r[2])
            continue
        if isinstance(a, int) and upt and r[2]:
            rec = {"kode_upt": upt, "nama_upt_sumber": nama_sumber, "program_studi": bersih(r[2])}
            rec.update({k: num(r[i]) for k, i in kolom.items()})
            out.append(rec)
    return out


KOLOM_MHS = {"mahasiswa_2026": 3,
             **{f"peminat_mandiri_{t}": 4 + i for i, t in enumerate(range(2022, 2027))},
             **{f"peminat_polbit_{t}": 9 + i for i, t in enumerate(range(2022, 2027))},
             **{f"lulusan_{t}": 14 + i for i, t in enumerate(range(2022, 2027))}}
KOLOM_SERAP = {"pns": 3, "ppnpn": 4, "bumn_bumd": 5, "swasta": 6, "belum_bekerja": 7,
               "total_bekerja": 8, "total_lulusan": 9}


def periksa_penyerapan(r):
    """Cek konsistensi baris prodi file 9 (bekerja = PNS+PPNPN+BUMN+swasta,
    lulusan = bekerja + belum bekerja). Kolom total di sumber rusak di beberapa
    UPT, dgn pola berbeda -- yang polanya jelas diperbaiki, sisanya ditandai."""
    v = {k: r.get(k) or 0 for k in KOLOM_SERAP}
    komponen = v["pns"] + v["ppnpn"] + v["bumn_bumd"] + v["swasta"]
    catatan = None
    if all(r.get(k) is None for k in KOLOM_SERAP):
        pass
    elif v["total_bekerja"] == komponen and v["total_bekerja"] + v["belum_bekerja"] == v["total_lulusan"]:
        pass
    elif (r.get("belum_bekerja") is None and v["total_bekerja"] == komponen
          and r.get("total_lulusan") is not None and v["total_lulusan"] >= komponen):
        # pola PPI Madiun: kolom belum bekerja kosong, total lulusan & bekerja konsisten
        r["belum_bekerja"] = v["total_lulusan"] - komponen
        catatan = "Kolom belum bekerja kosong di sumber; diisi selisih total lulusan - total bekerja"
    elif not v["total_bekerja"] and komponen:
        # pola Poltekpel Surabaya: komponen benar, kolom total 0 / = belum bekerja
        catatan = (f"Kolom total di sumber tidak konsisten (bekerja {r.get('total_bekerja')}, lulusan "
                   f"{r.get('total_lulusan')}); dihitung ulang dari komponen")
        r["total_bekerja"], r["total_lulusan"] = komponen, komponen + v["belum_bekerja"]
    elif v["pns"] and v["pns"] == v["total_lulusan"] and v["total_bekerja"] == komponen - v["pns"]:
        # pola Poltekpel Barombong: kolom PNS berisi total lulusan prodi
        catatan = f"Kolom PNS di sumber ({v['pns']}) = total lulusan, bukan jumlah PNS; dikosongkan"
        r["pns"] = None
    else:
        catatan = (f"Komponen tidak konsisten di sumber: PNS+PPNPN+BUMN+swasta={komponen}, "
                   f"total bekerja={r.get('total_bekerja')}, belum={r.get('belum_bekerja')}, "
                   f"total lulusan={r.get('total_lulusan')}; nilai tidak diubah")
    r["catatan_data"] = catatan


def parse_sertifikat():
    periode = [("2022", 3), ("2023", 5), ("2024", 7), ("2025", 9), ("2026 TW-II", 11)]
    out = []
    for r in rows_of(F_SERTIFIKAT):
        if not isinstance(r[0], int) or not r[2]:
            continue
        upt = kode_upt_dari_nama(r[2])
        recs = []
        for per, i in periode:
            jenis, orang = num(r[i]), num(r[i + 1])
            cat = []
            if isinstance(orang, float) and orang != int(orang) and orang < 1000:
                cat.append(f"Sumber tertulis {orang} (pemisah ribuan terbaca desimal) -> dikali 1000")
                orang = round(orang * 1000)
            recs.append({"kode_upt": upt, "nama_upt_sumber": bersih(r[2]), "periode": per,
                         "tahun": int(per[:4]), "jumlah_jenis_sertifikat": jenis,
                         "jumlah_orang_tersertifikasi": orang, "catatan": cat})
        # outlier: > 5x nilai TERTINGGI tahun penuh lain -> tandai saja (pembanding
        # max, bukan median: pertumbuhan wajar spt Poltekbang Makassar 49->303->742
        # tidak boleh ikut tertandai)
        for rec in recs:
            lain = [x["jumlah_orang_tersertifikasi"] for x in recs
                    if x is not rec and x["jumlah_orang_tersertifikasi"] and "TW" not in x["periode"]]
            v = rec["jumlah_orang_tersertifikasi"]
            if v and len(lain) >= 2 and v > 5 * max(lain):
                rec["catatan"].append(f"Kemungkinan salah ketik: > 5x nilai tertinggi tahun lain ({max(lain):,.0f}); nilai tidak diubah")
        out += recs
    for rec in out:
        rec["catatan_data"] = "; ".join(rec.pop("catatan")) or None
    return out


def parse_fasilitas():
    """Dua sheet: simulator & kendaraan latih (ber-Kode Daerah) dan Prasarana
    (TANPA Kode Daerah, baris 'Orang' = kapasitas lalu 'Unit' = jumlah)."""
    data = {}

    def slot(upt, nama, tahun):
        return data.setdefault((upt, tahun), {"kode_upt": upt, "nama_upt_sumber": nama, "tahun": tahun})

    for r in rows_of(F_FASILITAS, "simulator_kapallatih"):
        if isinstance(r[1], int) and r[2]:
            upt = kode_upt_dari_nama(r[2])
            for i, t in enumerate(range(2021, 2026)):
                s = slot(upt, bersih(r[2]), t)
                s["simulator_unit"] = num(r[4 + 2 * i])
                s["kendaraan_kapal_pesawat_latih_unit"] = num(r[5 + 2 * i])

    upt = None
    for r in rows_of(F_FASILITAS, "Prasarana"):
        if isinstance(r[1], str) and r[2] == "Orang":
            upt = kode_upt_dari_nama(r[1])
            nama = bersih(r[1])
            jenis = "kapasitas_orang"
        elif r[2] == "Unit" and upt and r[1] is None:
            jenis = "unit"
        else:
            if isinstance(r[1], str) and r[2] not in ("person",):
                upt = None
            continue
        for i, t in enumerate(range(2021, 2026)):
            s = slot(upt, nama, t)
            for j, fas in enumerate(("kelas", "laboratorium", "asrama", "aula")):
                s[f"{fas}_{jenis}"] = num(r[3 + 4 * i + j])
        if jenis == "unit":
            upt = None
    return list(data.values())


# ---------------------------------------------------------------- DB

DDL = """
CREATE TABLE IF NOT EXISTS bpsdm_upt (
  kode_upt TEXT PRIMARY KEY, nama_upt TEXT, singkatan TEXT, matra TEXT, jenis TEXT,
  kode_provinsi INTEGER, provinsi TEXT, kode_kabupaten INTEGER, kabupaten_kota TEXT,
  kode_daerah_sumber INTEGER, lat DOUBLE PRECISION, lon DOUBLE PRECISION, situs TEXT,
  jumlah_prodi INTEGER, jumlah_dosen INTEGER, mahasiswa_2026 INTEGER, lulusan_2025 INTEGER,
  lulusan_2025_terserap_bekerja INTEGER, lulusan_2025_terserap_pct NUMERIC(5,1),
  sertifikat_orang_2025 INTEGER, simulator_2025 INTEGER, kendaraan_kapal_pesawat_latih_2025 INTEGER,
  catatan_data TEXT
);
CREATE TABLE IF NOT EXISTS bpsdm_prodi (
  id SERIAL PRIMARY KEY, kode_upt TEXT, upt TEXT, matra TEXT, kode_provinsi INTEGER, kode_kabupaten INTEGER,
  nama_upt_sumber TEXT, jenjang TEXT, program_studi TEXT
);
CREATE TABLE IF NOT EXISTS bpsdm_dosen_prodi (
  id SERIAL PRIMARY KEY, kode_upt TEXT, upt TEXT, matra TEXT, kode_provinsi INTEGER, kode_kabupaten INTEGER,
  nama_upt_sumber TEXT, jenjang TEXT, program_studi TEXT, akreditasi TEXT,
  asisten_ahli INTEGER, lektor INTEGER, lektor_kepala INTEGER, guru_besar INTEGER, jumlah_dosen INTEGER
);
CREATE TABLE IF NOT EXISTS bpsdm_mahasiswa_lulusan (
  id SERIAL PRIMARY KEY, kode_upt TEXT, upt TEXT, matra TEXT, kode_provinsi INTEGER, kode_kabupaten INTEGER,
  nama_upt_sumber TEXT, program_studi TEXT, mahasiswa_2026 INTEGER,
  {mhs_cols}
);
CREATE TABLE IF NOT EXISTS bpsdm_penyerapan_lulusan (
  id SERIAL PRIMARY KEY, kode_upt TEXT, upt TEXT, matra TEXT, kode_provinsi INTEGER, kode_kabupaten INTEGER,
  nama_upt_sumber TEXT, program_studi TEXT,
  pns INTEGER, ppnpn INTEGER, bumn_bumd INTEGER, swasta INTEGER, belum_bekerja INTEGER,
  total_bekerja INTEGER, total_lulusan INTEGER, terserap_pct NUMERIC(5,1), catatan_data TEXT
);
CREATE TABLE IF NOT EXISTS bpsdm_sertifikat (
  id SERIAL PRIMARY KEY, kode_upt TEXT, upt TEXT, matra TEXT, kode_provinsi INTEGER, kode_kabupaten INTEGER,
  nama_upt_sumber TEXT, periode TEXT, tahun INTEGER,
  jumlah_jenis_sertifikat INTEGER, jumlah_orang_tersertifikasi INTEGER, catatan_data TEXT
);
CREATE TABLE IF NOT EXISTS bpsdm_fasilitas (
  id SERIAL PRIMARY KEY, kode_upt TEXT, upt TEXT, matra TEXT, kode_provinsi INTEGER, kode_kabupaten INTEGER,
  nama_upt_sumber TEXT, tahun INTEGER,
  simulator_unit INTEGER, kendaraan_kapal_pesawat_latih_unit INTEGER,
  kelas_unit INTEGER, kelas_kapasitas_orang INTEGER, laboratorium_unit INTEGER, laboratorium_kapasitas_orang INTEGER,
  asrama_unit INTEGER, asrama_kapasitas_orang INTEGER, aula_unit INTEGER, aula_kapasitas_orang INTEGER
);
""".format(mhs_cols=",\n  ".join(f"{k} INTEGER" for k in KOLOM_MHS if k != "mahasiswa_2026"))

KOLOM_UPT_DENORM = ("upt", "matra", "kode_provinsi", "kode_kabupaten")


def insert_rows(cur, table, rows, upt_info):
    if not rows:
        return
    for r in rows:
        u = upt_info[r["kode_upt"]]
        r["upt"], r["matra"] = u["singkatan"], u["matra"]
        r["kode_provinsi"], r["kode_kabupaten"] = u["kode_provinsi"], u["kode_kabupaten"]
        for k, v in list(r.items()):
            if isinstance(v, float) and k not in ("lat", "lon", "terserap_pct", "lulusan_2025_terserap_pct"):
                r[k] = round(v)
    cols = list(dict.fromkeys(k for r in rows for k in r))  # gabungan kunci, urutan stabil
    cur.execute(f"DELETE FROM {table}")
    cur.executemany(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
        [tuple(r.get(c) for c in cols) for r in rows])


def lokasi_upt(cur, titik):
    """kode_kabupaten dari koordinat (BATAS KABUPATEN), fallback kode sumber."""
    cur.execute("SELECT kode_kabupaten, kode_provinsi, nama_provinsi, nama_kabupaten_kota, jenis_kabupaten "
                "FROM ref_wilayah_kabupaten")
    ref = {r["kode_kabupaten"]: r for r in cur.fetchall()}
    out = {}
    for t in titik:
        cur.execute("SELECT attrs->>'KODE_KABUPATEN' AS k FROM map_layers WHERE provinsi='BATAS KABUPATEN' "
                    "AND ST_Intersects(geom, ST_SetSRID(ST_Point(%s, %s), 4326)) LIMIT 1", (t["lon"], t["lat"]))
        row = cur.fetchone()
        k_geo = int(row["k"]) if row and row["k"] else None
        catatan = []
        kode = k_geo or t["kode_daerah_sumber"]
        if k_geo and k_geo != t["kode_daerah_sumber"]:
            asal = ref.get(t["kode_daerah_sumber"])
            asal_nm = f"{asal['jenis_kabupaten'].title()} {asal['nama_kabupaten_kota'].title()}" if asal else "tidak ada di master BPS"
            catatan.append(f"Kode Daerah sumber {t['kode_daerah_sumber']} ({asal_nm}) tidak cocok dgn koordinat; "
                           f"dipakai {k_geo} sesuai lokasi titik")
        r = ref.get(kode)
        if r is None:
            catatan.append(f"kode {kode} tidak ada di ref_wilayah")
        out[t["kode_upt"]] = {
            "kode_kabupaten": kode,
            "kode_provinsi": r["kode_provinsi"] if r else kode // 100,
            "provinsi": re.sub(r"^(Dki|Di) ", lambda m: m.group(1).upper() + " ", r["nama_provinsi"].title()) if r else None,
            "kabupaten_kota": f"{r['jenis_kabupaten'].title()} {r['nama_kabupaten_kota'].title()}" if r else None,
            "catatan": catatan,
        }
    return out


def main():
    titik = parse_titik()
    prodi = parse_prodi()
    dosen = parse_dosen()
    mhs = parse_prodi_berjenjang(F_MHS, KOLOM_MHS)
    serap = parse_prodi_berjenjang(F_SERAP, KOLOM_SERAP)
    for r in serap:
        periksa_penyerapan(r)
        r["terserap_pct"] = round(100 * r["total_bekerja"] / r["total_lulusan"], 1) \
            if r.get("total_bekerja") is not None and r.get("total_lulusan") else None
    sertifikat = parse_sertifikat()
    fasilitas = parse_fasilitas()

    def jumlah(rows, kode, kol, **filt):
        vals = [r[kol] for r in rows if r["kode_upt"] == kode and r.get(kol) is not None
                and all(r.get(k) == v for k, v in filt.items())]
        return round(sum(vals)) if vals else None

    with db_cursor() as cur:
        for stmt in DDL.split(";"):
            if stmt.strip():
                cur.execute(stmt)
        lokasi = lokasi_upt(cur, titik)

        upt_rows, upt_info = [], {}
        for t in titik:
            k = t["kode_upt"]
            singkatan, matra, jenis = MASTER[k]
            lok = lokasi[k]
            lul25 = jumlah(mhs, k, "lulusan_2025")
            bekerja = jumlah(serap, k, "total_bekerja")
            lulusan_serap = jumlah(serap, k, "total_lulusan")
            catatan = list(lok["catatan"])
            if lul25 is not None and lulusan_serap is not None and lul25 != lulusan_serap:
                catatan.append(f"Lulusan 2025 file 5-7 ({lul25}) beda dgn total lulusan file penyerapan ({lulusan_serap})")
            rec = {
                "kode_upt": k, "nama_upt": t["nama"], "singkatan": singkatan, "matra": matra, "jenis": jenis,
                "kode_provinsi": lok["kode_provinsi"], "provinsi": lok["provinsi"],
                "kode_kabupaten": lok["kode_kabupaten"], "kabupaten_kota": lok["kabupaten_kota"],
                "kode_daerah_sumber": t["kode_daerah_sumber"], "lat": t["lat"], "lon": t["lon"], "situs": t["situs"],
                "jumlah_prodi": sum(1 for p in prodi if p["kode_upt"] == k) or None,
                "jumlah_dosen": jumlah(dosen, k, "jumlah_dosen"),
                "mahasiswa_2026": jumlah(mhs, k, "mahasiswa_2026"),
                "lulusan_2025": lul25,
                "lulusan_2025_terserap_bekerja": bekerja,
                "lulusan_2025_terserap_pct": round(100 * bekerja / lulusan_serap, 1) if bekerja is not None and lulusan_serap else None,
                "sertifikat_orang_2025": jumlah(sertifikat, k, "jumlah_orang_tersertifikasi", periode="2025"),
                "simulator_2025": jumlah(fasilitas, k, "simulator_unit", tahun=2025),
                "kendaraan_kapal_pesawat_latih_2025": jumlah(fasilitas, k, "kendaraan_kapal_pesawat_latih_unit", tahun=2025),
                "catatan_data": "; ".join(catatan) or None,
            }
            upt_rows.append(rec)
            upt_info[k] = {"singkatan": singkatan, "matra": matra,
                           "kode_provinsi": rec["kode_provinsi"], "kode_kabupaten": rec["kode_kabupaten"]}

        cur.execute("DELETE FROM bpsdm_upt")
        cols = list(upt_rows[0].keys())
        cur.executemany(f"INSERT INTO bpsdm_upt ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                        [tuple(r[c] for c in cols) for r in upt_rows])
        for table, rows in (("bpsdm_prodi", prodi), ("bpsdm_dosen_prodi", dosen),
                            ("bpsdm_mahasiswa_lulusan", mhs), ("bpsdm_penyerapan_lulusan", serap),
                            ("bpsdm_sertifikat", sertifikat), ("bpsdm_fasilitas", fasilitas)):
            for r in rows:
                r.pop("matra", None)  # dosen punya matra dari sheet; pakai matra master
            insert_rows(cur, table, rows, upt_info)
            print(f"  {table}: {len(rows)} baris")
        print(f"  bpsdm_upt: {len(upt_rows)} UPT/kantor")

        # ---- overlay titik
        cur.execute("DELETE FROM map_layers WHERE provinsi=%s", (BUCKET,))
        cur.execute("DELETE FROM map_layer_meta WHERE provinsi=%s", (BUCKET,))
        per_layer = {}
        for u in upt_rows:
            layer = LAYER_MATRA.get(u["matra"]) if u["jenis"] in ("Perguruan Tinggi", "Balai Diklat") else None
            layer = layer or LAYER_PUSAT
            attrs = {
                "Nama UPT": u["nama_upt"], "Singkatan": u["singkatan"], "Jenis": u["jenis"], "Matra": u["matra"],
                "Kabupaten/Kota": u["kabupaten_kota"], "Provinsi": u["provinsi"],
                "Jumlah program studi": u["jumlah_prodi"], "Jumlah dosen": u["jumlah_dosen"],
                "Mahasiswa 2026": u["mahasiswa_2026"], "Lulusan 2025": u["lulusan_2025"],
                "Lulusan 2025 terserap kerja (%)": u["lulusan_2025_terserap_pct"],
                "Sertifikat diterbitkan 2025 (orang)": u["sertifikat_orang_2025"],
                "Simulator 2025 (unit)": u["simulator_2025"],
                "Kendaraan/kapal/pesawat latih 2025 (unit)": u["kendaraan_kapal_pesawat_latih_2025"],
                "Situs": u["situs"], "Catatan data": u["catatan_data"],
                "Kode UPT BPSDMP": u["kode_upt"],
            }
            attrs = {k: (float(v) if k.endswith("(%)") else v) for k, v in attrs.items() if v is not None}
            per_layer.setdefault(layer, []).append((Json(attrs), u["lon"], u["lat"]))
        for layer, rows in per_layer.items():
            cur.executemany(
                "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
                "VALUES (%s, '', %s, %s, ST_SetSRID(ST_Point(%s, %s), 4326))",
                [(BUCKET, layer, a, lon, lat) for a, lon, lat in rows])
            cur.execute(
                "INSERT INTO map_layer_meta (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp) "
                "VALUES (%s, '', %s, %s, %s, 0.01, %s)",
                (BUCKET, layer, LAYER_LABEL[layer], len(rows), f"docs/Konektivitas/7. BPSDM PERHUBUNGAN/{F_TITIK}"))
            print(f"  layer {layer}: {len(rows)} titik")

        for u in upt_rows:
            if u["catatan_data"]:
                print(f"  ! {u['singkatan']}: {u['catatan_data']}")
        for s in sertifikat:
            if s["catatan_data"]:
                print(f"  ! sertifikat {s['upt']} {s['periode']}: {s['catatan_data']}")


if __name__ == "__main__":
    main()
