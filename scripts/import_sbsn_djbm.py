"""Import "List Kegiatan SBSN DJBM Tahun 2015-2026" (paket Ditjen Bina Marga yang dibiayai
Surat Berharga Syariah Negara) -> tabel sbsn_kegiatan_djbm.

Sumber: docs/09102026/SBSN/List Kegiatan SBSN DJBM Tahun 2015-2026.xlsx (Drive "Penambahan
Data" no. 1, 28 Sep 2026). Satu sheet per tahun, FORMAT BERBEDA tiap tahun:
  2015       daftar paket per balai (status SiPP 13 Jan 2016), pagu = PAGU REVISI
  2016       rekonsiliasi realisasi SiPP vs OMSPAN, ada kolom NAMA PROVINSI
  2017-2019  laporan pemantauan & evaluasi triwulan IV (baris satker = subtotal)
  2020-2024  daftar kontrak per satker (baris satker = subtotal)
  2025       rencana percepatan SBSN (skema pinjam pagu), Rp RIBU, pagu = alokasi MENJADI
  2026       DIPA TA 2026 + luncuran per kelompok MYC, Rp RIBU, pagu = REVISI (pengembalian pagu)
Sheet bantu (Sheet2, Sheet3, "SIPP 12Jan16", "SiPP14Jan16 pake") TIDAK diimpor: salinan kerja
2015 / potongan kecil, bukan daftar tahunan.

Semua nilai disimpan dalam RUPIAH. Isinya hampir seluruhnya JALAN/JEMBATAN NASIONAL (satker
PJN), bukan IJD; tidak dipakai skor IJD/NPR. Nilai kontrak MYC = nilai kontrak penuh
(multi-tahun), BUKAN porsi tahun itu -> jangan dijumlah lintas tahun.

Pengaman (impor DITOLAK bila gagal): jumlah paket per satker = baris subtotal satker
(2017-2024), jumlah per kelompok = baris kelompok (2026), total semua paket = baris TOTAL
sheet (pagu; kontrak & realisasi bila baris TOTAL memuatnya). Toleransi Rp 1.000 (pembulatan; sheet Rp ribu Rp 100.000).

Provinsi (sumber tak punya kode wilayah): satker yg sama di Paket LS tahun yg sama (DIPA, 2021-2025,
butuh import_paket_ls_bina_marga.py) -> kolom provinsi bila ada (2016, 2026) -> "PROVINSI X"
di nama satker -> nama balai (2025, "BPJN ACEH") -> kata kunci satker metropolitan/perbatasan
(SATKER_PROVINSI) -> kode satker yang sama di tahun lain. Sisanya NULL + catatan_data.
kode_provinsi BPS dari nama (wilayah_cocok.kunci_provinsi); "Papua"/"Papua Barat" sebelum
2023 = wilayah sebelum pemekaran 2022 (dicatat).

DELETE + INSERT seluruh tabel, aman di-rerun.

Usage (venv aktif):
    python scripts/import_sbsn_djbm.py --cek [xlsx]   # parse + rekonsiliasi saja, tanpa DB tulis
    python scripts/import_sbsn_djbm.py [xlsx]
"""
import argparse
import datetime as dt
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import openpyxl  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")
from db import db_cursor  # noqa: E402
from wilayah_cocok import kunci_provinsi  # noqa: E402

XLSX_BAWAAN = REPO_ROOT / "docs" / "09102026" / "SBSN" / "List Kegiatan SBSN DJBM Tahun 2015-2026.xlsx"
TABEL = "sbsn_kegiatan_djbm"
TOLERANSI = 1000  # rupiah
TOLERANSI_RIBUAN = 100_000  # sheet Rp ribu (2025-2026): sel sumber berdesimal, jumlah 160 baris bisa meleset puluhan ribu

# Indeks kolom (0-based) per sheet, diverifikasi thd header 9 Okt 2026.
# satker_baris: tahun yg punya baris subtotal per satker (kode + nama satker, kolom paket kosong).
KOLOM = {
    2015: dict(no=0, balai=1, satker=2, paket=3, tgl_kontrak=4, pagu=5, kontrak=6, realisasi=7),
    2016: dict(no=0, balai=2, provinsi=3, kode=4, satker=5, paket=6, nomor_kontrak=7, tgl_kontrak=8,
               pagu=9, kontrak=10, realisasi=11),
    # 2017 tanpa kolom uraian: nama satker & nama paket sama-sama di kolom KEGIATAN (2)
    2017: dict(no=0, kode=1, satker=2, paket=2, nomor_kontrak=3, tgl_akhir=4, pagu=5, kontrak=6,
               rekanan=7, realisasi=13, satker_baris=True),
    2018: dict(no=1, kode=2, satker=3, paket=4, nomor_kontrak=5, tgl_akhir=6, pagu=7, kontrak=8,
               realisasi=9, register=13, satker_baris=True),
    2019: dict(no=1, kode=2, satker=3, paket=4, nomor_kontrak=5, tgl_akhir=6, pagu=7, kontrak=8,
               realisasi=9, register=13, satker_baris=True),
    2020: dict(no=1, kode=2, satker=3, paket=4, nomor_kontrak=5, tgl_akhir=6, pagu=7, kontrak=8,
               realisasi=9, register=11, satker_baris=True),
    2021: dict(no=3, kode=2, satker=3, paket=4, nomor_kontrak=5, tgl_akhir=6, pagu=7, kontrak=8,
               realisasi=9, register=10, izin_myc=11, satker_baris=True),
    2022: dict(no=1, kode=2, satker=3, paket=4, nomor_kontrak=5, tgl_akhir=6, pagu=7, kontrak=8,
               realisasi=9, register=10, izin_myc=11, satker_baris=True),
    2023: dict(no=1, kode=2, satker=3, paket=4, nomor_kontrak=5, tgl_akhir=6, pagu=7, kontrak=8,
               realisasi=9, register=10, satker_baris=True),
    2024: dict(no=0, kode=1, satker=2, paket=3, nomor_kontrak=4, tgl_akhir=5, pagu=6, kontrak=7,
               realisasi=8, register=9, satker_baris=True),
    2025: dict(no=1, paket=2, balai=3, satker=4, dpp=5, jenis_proyek=6, tahun_pendanaan=7, pagu_awal=8,
               pagu=9, keterangan=11, realisasi=12, catatan=15, ribuan=True),
    2026: dict(no=0, paket=1, pagu_awal=2, pagu=3, provinsi=4, dpp=5, tahun_pendanaan=6, ribuan=True),
}
JENIS_PAGU = {2015: "PAGU REVISI", 2025: "ALOKASI TA 2025 (MENJADI, skema pinjam pagu)",
              2026: "REVISI SBSN TA 2026 (pengembalian pagu)"}
JENIS_PAGU_AWAL = {2025: "ALOKASI TA 2025 (SEMULA)", 2026: "DIPA TA 2026 + LUNCURAN"}

# satker tanpa "PROVINSI X" di namanya -> provinsi (kunci = potongan nama, huruf besar)
SATKER_PROVINSI = [
    ("METROPOLITAN MEDAN", "SUMATERA UTARA"), ("METROPOLITAN PALEMBANG", "SUMATERA SELATAN"),
    ("METROPOLITAN I JAKARTA", "DKI JAKARTA"), ("METROPOLITAN II JAKARTA", "DKI JAKARTA"),
    ("DKI JAKARTA", "DKI JAKARTA"), ("METROPOLITAN BANDUNG", "JAWA BARAT"),
    ("METROPOLITAN SEMARANG", "JAWA TENGAH"), ("METROPOLITAN I SURABAYA", "JAWA TIMUR"),
    ("METROPOLITAN II SURABAYA", "JAWA TIMUR"), ("METROPOLITAN SURABAYA", "JAWA TIMUR"),
    ("METROPOLITAN DENPASAR", "BALI"), ("METROPOLITAN MAKAS", "SULAWESI SELATAN"),
    ("PERBATASAN KALIMANTAN TIMUR", "KALIMANTAN TIMUR"), ("PERBATASAN KALIMANTAN UTARA", "KALIMANTAN UTARA"),
    ("PERBATASAN KALIMANTAN BARAT", "KALIMANTAN BARAT"), ("NANGA BADAU", "KALIMANTAN BARAT"),
    ("PULAU BALANG", "KALIMANTAN TIMUR"), ("BALIKPAPAN - SAMARINDA", "KALIMANTAN TIMUR"),
    ("BALIKPAPAN-SAMARINDA", "KALIMANTAN TIMUR"), ("MERAH PUTIH", "MALUKU"),
    ("SOLO - KERTOSONO", "JAWA TENGAH"), ("SOLO-KERTOSONO", "JAWA TENGAH"),
]
# singkatan provinsi di nama satker 2015 ("PROVINSI SULTENG") -- di luar wilayah_cocok.ALIAS_PROVINSI
SINGKATAN_PROV = {
    "SULUT": "SULAWESI UTARA", "SULTENG": "SULAWESI TENGAH", "SULSEL": "SULAWESI SELATAN",
    "SULTRA": "SULAWESI TENGGARA", "SULBAR": "SULAWESI BARAT", "KALBAR": "KALIMANTAN BARAT",
    "KALTENG": "KALIMANTAN TENGAH", "KALSEL": "KALIMANTAN SELATAN", "KALTIM": "KALIMANTAN TIMUR",
    "KALTARA": "KALIMANTAN UTARA", "JABAR": "JAWA BARAT", "JATENG": "JAWA TENGAH", "JATIM": "JAWA TIMUR",
    "MALUT": "MALUKU UTARA", "PABAR": "PAPUA BARAT", "SUMSEL": "SUMATERA SELATAN",
}
POLA_PROV = re.compile(r"PRO[VP]INSI\s+(.+)$", re.I)
POLA_BALAI = re.compile(r"^B+PJN\s+(.+)$", re.I)

DDL = f"""
CREATE TABLE IF NOT EXISTS {TABEL} (
    id SERIAL PRIMARY KEY,
    tahun SMALLINT NOT NULL,
    no_sumber TEXT,
    balai TEXT,
    satker_kode TEXT,
    satker_nama TEXT,
    provinsi TEXT,                 -- nama provinsi hasil penelusuran (lihat dasar_provinsi)
    kode_provinsi SMALLINT,        -- ID BPS
    dasar_provinsi TEXT,           -- kolom provinsi / nama satker / balai / kata kunci satker / kode satker tahun lain
    nama_paket TEXT,
    nomor_kontrak TEXT,
    tgl_kontrak DATE,
    tgl_akhir_kontrak DATE,
    rekanan TEXT,
    jenis_proyek TEXT,             -- SYC/MYC (2025: kolom sumber; lainnya: kelompok 2026 / penanda MYC di nama/kontrak)
    myc BOOLEAN,                   -- kontrak tahun jamak (dari kolom jenis/kelompok, atau "MYC" di nama paket/nomor kontrak)
    tahun_pendanaan TEXT,          -- mis. '2025 - 2027' (2025-2026)
    dpp TEXT,                      -- PEMBANGUNAN / PENINGKATAN (2025-2026)
    kode_register TEXT,            -- kode register SBSN (mis. M0330422)
    izin_myc TEXT,                 -- nomor/tanggal/pagu izin MYC Kemenkeu (2021-2022)
    pagu_rp NUMERIC,               -- pagu SBSN tahun itu; arti per tahun di jenis_pagu
    jenis_pagu TEXT,
    pagu_awal_rp NUMERIC,          -- 2025: alokasi semula; 2026: DIPA + luncuran
    nilai_kontrak_rp NUMERIC,      -- nilai kontrak PENUH (MYC = seluruh tahun), bukan porsi tahun itu
    realisasi_rp NUMERIC,
    keterangan TEXT,
    catatan_data TEXT,
    sumber_sheet TEXT,
    diimpor_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_{TABEL}_tahun ON {TABEL} (tahun);
CREATE INDEX IF NOT EXISTS idx_{TABEL}_prov ON {TABEL} (kode_provinsi);
"""


class Gagal(Exception):
    pass


def teks(v):
    if v is None:
        return None
    if isinstance(v, (dt.datetime, dt.date)):
        return v.strftime("%Y-%m-%d")
    s = re.sub(r"\s+", " ", str(v).replace("\xa0", " ")).strip()
    return s or None


def uang(v, ribuan=False):
    """-> rupiah (float) / None; sel galat Excel (#REF!, #N/A) = None."""
    if v is None or isinstance(v, (dt.datetime, dt.date)):
        return None
    if isinstance(v, str):
        s = v.strip()
        if not s or s.startswith("#") or s == "-":
            return None
        try:
            v = float(s.replace(",", ""))
        except ValueError:
            return None
    return float(v) * (1000 if ribuan else 1)


def tanggal(v):
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return None


def sel(r, k, c):
    j = k.get(c)
    return r[j] if j is not None and j < len(r) else None


def adalah_total(r):
    return any(isinstance(c, str) and re.match(r"^(TOTAL|JUMLAH)\b", c.strip(), re.I) for c in r[:6])


def parse_sheet(tahun, rows):
    k = KOLOM[tahun]
    rb = k.get("ribuan", False)
    paket, subtotal, total = [], [], None
    satker_aktif = {}
    balai_aktif = provinsi_aktif = None
    kelompok = None
    for i, r in enumerate(rows):
        r = list(r)
        if adalah_total(r):
            if total is None:  # baris TOTAL pertama (2018: ada baris kedua = target)
                total = dict(baris=i + 1, pagu=uang(sel(r, k, "pagu"), rb), kontrak=uang(sel(r, k, "kontrak"), rb),
                             realisasi=uang(sel(r, k, "realisasi"), rb))
            continue
        no = teks(sel(r, k, "no"))
        nama = teks(sel(r, k, "paket"))
        # 2026: baris kelompok "MYC 2025 - 2026" (kolom NO kosong, ada angka) = subtotal kelompok
        if tahun == 2026 and not no and nama and re.match(r"^(MYC|SYC)\b", nama, re.I):
            kelompok = nama
            subtotal.append(dict(kunci=nama, baris=i + 1, pagu=uang(sel(r, k, "pagu"), rb),
                                 pagu_awal=uang(sel(r, k, "pagu_awal"), rb)))
            continue
        # 2025: baris judul balai ("BPJN ACEH" di kolom paket & balai, tanpa nomor)
        if tahun == 2025 and not no and nama and nama == teks(sel(r, k, "balai")):
            balai_aktif = nama
            continue
        if tahun == 2016:
            balai_aktif = teks(sel(r, k, "balai")) or balai_aktif
            provinsi_aktif = teks(sel(r, k, "provinsi")) or provinsi_aktif
        if tahun == 2015:
            balai_aktif = teks(sel(r, k, "balai")) or balai_aktif
        kode = teks(sel(r, k, "kode"))
        if kode and not re.fullmatch(r"\d{5,7}", kode):
            kode = None
        if k.get("satker_baris"):
            nm_satker = teks(sel(r, k, "satker"))
            if tahun == 2017:
                # satker (mis. "PARALEL PERBATASAN NANGA BADAU ...") = berkode, tanpa nomor & tgl kontrak
                is_satker = kode and nm_satker and not teks(sel(r, k, "nomor_kontrak")) and not sel(r, k, "tgl_akhir")
            else:  # kode satker kadang kosong di baris satker (2018 baris 105)
                is_satker = nm_satker and not nama and uang(sel(r, k, "pagu"), rb) is not None
            if is_satker:
                satker_aktif = dict(kode=kode, nama=nm_satker)
                subtotal.append(dict(kunci=f"{kode} {nm_satker}", baris=i + 1, pagu=uang(sel(r, k, "pagu"), rb),
                                     kontrak=uang(sel(r, k, "kontrak"), rb), realisasi=uang(sel(r, k, "realisasi"), rb)))
                continue
        if not nama or re.fullmatch(r"[\d().=+ ]+", nama) or (no and not re.match(r"^\d+$", no)):
            continue  # baris kosong / nomor kolom "(1) (2)" / catatan
        # paket tanpa nomor urut tetap diambil bila ada pagu (2020 baris 41: sisa pagu belum berkontrak)
        pagu = uang(sel(r, k, "pagu"), rb)
        if pagu is None:  # catatan kaki ("Data realisasi yang di rekonsiliasi ...") tanpa pagu
            continue
        if tahun == 2016:
            if kode and teks(sel(r, k, "satker")):
                satker_aktif = dict(kode=kode, nama=teks(sel(r, k, "satker")))
            elif kode and kode != satker_aktif.get("kode"):
                satker_aktif = dict(kode=kode, nama=None)
        if tahun in (2015, 2025):
            satker_aktif = dict(kode=None, nama=teks(sel(r, k, "satker")))
            if tahun == 2025:
                balai_aktif = teks(sel(r, k, "balai")) or balai_aktif
        izin = None
        if k.get("izin_myc") is not None:
            izin_bag = [teks(r[j]) if j < len(r) else None for j in range(k["izin_myc"], k["izin_myc"] + 3)]
            izin_bag = [x for x in izin_bag if x and not x.startswith("#")]
            izin = " | ".join(izin_bag) or None
        jenis = teks(sel(r, k, "jenis_proyek")) or kelompok
        nomor = teks(sel(r, k, "nomor_kontrak"))
        myc = bool(re.search(r"\bMYC\b", " ".join(filter(None, [jenis, nama, nomor, izin and "MYC"])), re.I))
        paket.append(dict(
            tahun=tahun, no_sumber=no, balai=balai_aktif,
            satker_kode=satker_aktif.get("kode"), satker_nama=satker_aktif.get("nama"),
            _provinsi_kolom=provinsi_aktif if tahun == 2016 else teks(sel(r, k, "provinsi")),
            nama_paket=nama, nomor_kontrak=nomor if nomor not in ("-",) else None,
            tgl_kontrak=tanggal(sel(r, k, "tgl_kontrak")), tgl_akhir_kontrak=tanggal(sel(r, k, "tgl_akhir")),
            rekanan=teks(sel(r, k, "rekanan")), jenis_proyek=jenis, myc=myc,
            tahun_pendanaan=teks(sel(r, k, "tahun_pendanaan")), dpp=teks(sel(r, k, "dpp")),
            kode_register=teks(sel(r, k, "register")), izin_myc=izin,
            pagu_rp=pagu, jenis_pagu=JENIS_PAGU.get(tahun, "PAGU"),
            pagu_awal_rp=uang(sel(r, k, "pagu_awal"), rb), jenis_pagu_awal=JENIS_PAGU_AWAL.get(tahun),
            nilai_kontrak_rp=uang(sel(r, k, "kontrak"), rb), realisasi_rp=uang(sel(r, k, "realisasi"), rb),
            keterangan="; ".join(filter(None, [teks(sel(r, k, "keterangan")), teks(sel(r, k, "catatan"))])) or None,
            _kunci_subtotal=(f"{satker_aktif.get('kode')} {satker_aktif.get('nama')}" if k.get("satker_baris")
                             else kelompok),
            sumber_sheet=str(tahun),
        ))
    return paket, subtotal, total


def rekonsiliasi(tahun, paket, subtotal, total):
    """-> list pesan galat (kosong = cocok)."""
    tol = TOLERANSI_RIBUAN if KOLOM[tahun].get("ribuan") else TOLERANSI
    galat = []
    if total is None:
        return [f"{tahun}: baris TOTAL tidak ditemukan"]
    for f in ("pagu", "kontrak", "realisasi"):
        if total.get(f) is None:
            continue
        kol = {"pagu": "pagu_rp", "kontrak": "nilai_kontrak_rp", "realisasi": "realisasi_rp"}[f]
        s = sum(p[kol] or 0 for p in paket)
        if abs(s - total[f]) > tol:
            galat.append(f"{tahun} TOTAL {f}: paket {s:,.0f} != sumber {total[f]:,.0f} (selisih {s - total[f]:,.0f})")
    per = defaultdict(lambda: defaultdict(float))
    for p in paket:
        for f, kol in (("pagu", "pagu_rp"), ("kontrak", "nilai_kontrak_rp"), ("realisasi", "realisasi_rp"),
                       ("pagu_awal", "pagu_awal_rp")):
            per[p["_kunci_subtotal"]][f] += p[kol] or 0
    for st in subtotal:
        for f in ("pagu", "kontrak", "realisasi", "pagu_awal"):
            if st.get(f) is None:
                continue
            s = per.get(st["kunci"], {}).get(f, 0)
            if abs(s - st[f]) > tol:
                galat.append(f"{tahun} subtotal '{st['kunci'][:50]}' (baris {st['baris']}) {f}: "
                             f"paket {s:,.0f} != sumber {st[f]:,.0f}")
    return galat


def kunci_satker(nama):
    """Nama satker dinormalkan utk dicocokkan ke Paket LS: 'PELAKSANAAN JALAN NASIONAL WILAYAH IX
    PROVINSI PAPUA (BIAK SERUI)' dan 'PJN WILAYAH IX PROVINSI PAPUA (BIAK)' -> 'PJN IX PROVINSI PAPUA BIAK'."""
    s = (nama or "").upper().replace("PROPINSI", "PROVINSI")
    s = re.sub(r"^\s*(SATKER|SATUAN KERJA)\s+", "", s)
    s = re.sub(r"PELAKSANAAN JALAN NASIONAL", "PJN", s)
    s = re.sub(r"\bWILAYAH\s+", "", s)
    s = re.sub(r"\(\s*([A-Z]+)[^)]*\)?", r" \1", s)  # isi kurung -> kata pertama
    return re.sub(r"[^A-Z0-9]+", " ", s).strip()


def isi_provinsi(paket, prov_master, dipa=None):
    """Tetapkan provinsi/kode_provinsi/dasar_provinsi + catatan.

    dipa: {(tahun, kunci_satker): {kode_provinsi}} dari paket_ls_bina_marga (DIPA, TA 2021-2025),
    dipakai PERTAMA bila tunggal: sejak pemekaran 2022 nama satker Tanah Papua masih "PROVINSI PAPUA
    (JAYAWIJAYA)" padahal DIPA-nya tercatat di provinsi baru (Papua Pegunungan)."""
    dipa = dipa or {}
    kunci_by_kode = {v[0]: k for k, v in prov_master.items()}
    def resolve(nama):
        if not nama:
            return None
        nama = re.sub(r"^(NANGGROE ACEH DARUSSALAM|NAD)$", "ACEH", nama.strip(), flags=re.I)
        nama = SINGKATAN_PROV.get(nama.split(" (")[0].strip().upper(), nama)
        k = kunci_provinsi(nama)
        if k in prov_master:
            return k
        # "SUMATERA UTARA (SATKER ...)" / "ACEH." / "JAWA TIMUR-BALI" -> ambil awalan yang cocok terpanjang
        cocok = [p for p in prov_master if k.startswith(p)]
        return max(cocok, key=len) if cocok else None

    kode_satker = defaultdict(Counter)
    for p in paket:
        cand = []
        if p["_provinsi_kolom"]:
            cand.append((p["_provinsi_kolom"], "kolom provinsi"))
        nm = (p["satker_nama"] or "").upper()
        m = POLA_PROV.search(nm)
        if m:
            cand.append((m.group(1), "nama satker"))
        mb = POLA_BALAI.match(p["balai"] or "")
        if mb:
            cand.append((mb.group(1), "nama balai"))
        for potongan, prov in SATKER_PROVINSI:
            if potongan in nm:
                cand.append((prov, "kata kunci satker"))
                break
        p["_kprov"] = p["dasar_provinsi"] = None
        kode_dipa = dipa.get((p["tahun"], kunci_satker(p["satker_nama"])))
        if kode_dipa and len(kode_dipa) == 1 and next(iter(kode_dipa)) in kunci_by_kode:
            p["_kprov"], p["dasar_provinsi"] = kunci_by_kode[next(iter(kode_dipa))], "satker DIPA (Paket LS tahun sama)"
            cand = []
        for nama, dasar in cand:
            kp = resolve(nama)
            if kp:
                p["_kprov"], p["dasar_provinsi"] = kp, dasar
                break
        if p["_kprov"] and p["satker_kode"]:
            kode_satker[p["satker_kode"]][p["_kprov"]] += 1
    for p in paket:  # kode satker yg sama di baris/tahun lain (hanya bila tunggal)
        if not p["_kprov"] and p["satker_kode"] and len(kode_satker[p["satker_kode"]]) == 1:
            p["_kprov"] = next(iter(kode_satker[p["satker_kode"]]))
            p["dasar_provinsi"] = "kode satker sama di baris lain"
    for p in paket:
        catatan = []
        if p["_kprov"]:
            kode, nama = prov_master[p["_kprov"]]
            p["kode_provinsi"], p["provinsi"] = kode, nama.title()
            if p["tahun"] <= 2022 and p["_kprov"] in ("PAPUA", "PAPUABARAT"):
                catatan.append("Provinsi sebelum pemekaran 2022 (wilayah induk)")
        else:
            p["kode_provinsi"] = p["provinsi"] = None
            catatan.append("Provinsi tidak dapat ditentukan dari sumber")
        if p["realisasi_rp"] and p["pagu_rp"] and p["realisasi_rp"] > p["pagu_rp"] + TOLERANSI:
            catatan.append("Realisasi > pagu")
        p["catatan_data"] = "; ".join(catatan) or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx", nargs="?", default=str(XLSX_BAWAAN))
    ap.add_argument("--cek", action="store_true", help="parse + rekonsiliasi saja, tanpa menulis DB")
    a = ap.parse_args()

    wb = openpyxl.load_workbook(a.xlsx, read_only=True, data_only=True)
    semua, galat = [], []
    for tahun in sorted(KOLOM):
        paket, subtotal, total = parse_sheet(tahun, list(wb[str(tahun)].iter_rows(values_only=True)))
        g = rekonsiliasi(tahun, paket, subtotal, total)
        galat += g
        pagu = sum(p["pagu_rp"] or 0 for p in paket)
        print(f"TA {tahun}: {len(paket):>3} paket, {len(subtotal):>3} subtotal, pagu Rp {pagu / 1e12:,.2f} T, "
              f"MYC {sum(p['myc'] for p in paket)} -- {'COCOK' if not g else f'{len(g)} SELISIH'} dgn TOTAL"
              f"{'/subtotal' if subtotal else ''} sumber")
        semua += paket
    if galat:
        print("\n".join(galat[:40]))
        sys.exit(f"DITOLAK: {len(galat)} selisih rekonsiliasi")

    with db_cursor() as cur:
        cur.execute("SELECT DISTINCT kode_provinsi, provinsi FROM penduduk_kecamatan")
        prov_master = {kunci_provinsi(r["provinsi"]): (int(r["kode_provinsi"]), r["provinsi"]) for r in cur.fetchall()}
        dipa = defaultdict(set)
        cur.execute("SELECT to_regclass('paket_ls_bina_marga') AS t")
        if cur.fetchone()["t"]:
            cur.execute("SELECT DISTINCT tahun, satker_nama, kode_provinsi FROM paket_ls_bina_marga "
                        "WHERE kode_provinsi IS NOT NULL")
            for r in cur.fetchall():
                dipa[(r["tahun"], kunci_satker(r["satker_nama"]))].add(r["kode_provinsi"])
        else:
            print("PERINGATAN: paket_ls_bina_marga belum ada -> provinsi hanya dari nama (jalankan "
                  "import_paket_ls_bina_marga.py dulu)")
    isi_provinsi(semua, prov_master, dipa)
    tanpa = Counter(p["tahun"] for p in semua if p["kode_provinsi"] is None)
    print(f"Provinsi: {sum(p['kode_provinsi'] is not None for p in semua)}/{len(semua)} terisi; dasar "
          f"{dict(Counter(p['dasar_provinsi'] for p in semua))}; tanpa provinsi per tahun {dict(sorted(tanpa.items()))}")
    for p in [p for p in semua if p["kode_provinsi"] is None][:15]:
        print(f"  tanpa provinsi: {p['tahun']} satker={p['satker_nama']!r} balai={p['balai']!r} paket={p['nama_paket'][:50]!r}")
    if a.cek:
        print("Mode --cek: tidak menulis ke database.")
        return

    kolom = ["tahun", "no_sumber", "balai", "satker_kode", "satker_nama", "provinsi", "kode_provinsi",
             "dasar_provinsi", "nama_paket", "nomor_kontrak", "tgl_kontrak", "tgl_akhir_kontrak", "rekanan",
             "jenis_proyek", "myc", "tahun_pendanaan", "dpp", "kode_register", "izin_myc", "pagu_rp",
             "jenis_pagu", "pagu_awal_rp", "nilai_kontrak_rp", "realisasi_rp", "keterangan", "catatan_data",
             "sumber_sheet"]
    with db_cursor() as cur:
        cur.execute(DDL)
        cur.execute(f"DELETE FROM {TABEL}")
        cur.executemany(f"INSERT INTO {TABEL} ({', '.join(kolom)}) VALUES ({', '.join(['%s'] * len(kolom))})",
                        [[p[c] for c in kolom] for p in semua])
        cur.execute(f"SELECT tahun, COUNT(*) n, ROUND(SUM(pagu_rp) / 1e12, 2) pagu_t, COUNT(kode_provinsi) prov "
                    f"FROM {TABEL} GROUP BY tahun ORDER BY tahun")
        for r in cur.fetchall():
            print(f"DB {r['tahun']}: {r['n']} paket, pagu Rp {r['pagu_t']} T, berprovinsi {r['prov']}")


if __name__ == "__main__":
    main()
