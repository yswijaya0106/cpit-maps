"""Import "Database Pelabuhan Laut Indonesia" (ver 20260922) -> 3 tabel + overlay peta
bucket "PELABUHAN RIPN".

Sumber: docs/10102026/(DATA)_Database_Pelabuhan_Laut_Indonesia-ver_20260922.xlsx (Drive
Konektivitas "2. LAUT", diunggah 5 Okt 2026). Kajian & keputusan: lihat CLAUDE.md
(bagian Drive Konektivitas 10 Okt 2026).

Tabel:
  pelabuhan_ripn            sheet "RIPN List Pelabuhan": 636 pelabuhan umum (hierarki PU/PP/PR/PL)
                            + 1.978 terminal khusus (TERSUS/TUKS), semuanya berkoordinat.
                            Hierarki rencana 2017/2022/2027/2037 dari "Sheet2" (penetapan RIPN).
  pelabuhan_kinerja         sheet "Kinerja Pelabuhan 2021-2024" (BPS Statistik Transportasi Laut),
                            636 pelabuhan umum x 4 tahun.
  pelabuhan_fasilitas_komponen  sheet "Fasilitas Pelabuhan" (dermaga, lapangan, gudang, ...).
Sheet "2A_Fasilitas_Ringkas" dan "Database Tambahan Data" TIDAK diimpor: <=1% sel terisi.

Kode wilayah: kode kab di sumber berurutan Kemendagri (Meulaboh/Aceh Barat = 1105, BPS 1107),
jadi kode BPS diturunkan dari TITIK (poligon BATAS KABUPATEN; titik di laut -> kab terdekat
<= 25 km). Kab hasil titik dibandingkan dgn nama kab sumber (PencocokKabupaten); beda dicatat.

Kunci join = id_ripn (nomor baris sheet RIPN), BUKAN kode pelabuhan: kode SEL/SAI/PJA dipakai
dua pelabuhan. Baris kinerja/fasilitas dgn kode ganda dicocokkan lewat nama.

Pengaman (impor DITOLAK bila gagal): 636 umum berhierarki valid + 1.978 khusus; semua titik di
dalam Indonesia; kinerja 636 x 4 tahun dan Total_Ton_Bersih hasil hitung ulang (rumus di sheet:
4 arus bongkar/muat, sel > 100 juta ton = 0) sama dgn sheet "Kinerja Bersih Tahunan"; setiap baris
kinerja/fasilitas tertaut ke tepat satu pelabuhan RIPN.

DELETE + INSERT, aman di-rerun.

Usage (venv aktif):
    python scripts/import_pelabuhan_ripn.py --cek [xlsx]
    python scripts/import_pelabuhan_ripn.py [xlsx]
"""
import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import openpyxl  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from psycopg.types.json import Json  # noqa: E402

load_dotenv(REPO_ROOT / ".env")
from db import db_cursor  # noqa: E402
from wilayah_cocok import PencocokKabupaten  # noqa: E402

XLSX_BAWAAN = REPO_ROOT / "docs" / "10102026" / "(DATA)_Database_Pelabuhan_Laut_Indonesia-ver_20260922.xlsx"
BUCKET = "PELABUHAN RIPN"
LAYER_UMUM = "Pelabuhan Umum (RIPN)"
LAYER_KHUSUS = "Terminal Khusus TERSUS-TUKS (RIPN)"
HIERARKI = {"PU": "Pelabuhan Utama", "PP": "Pelabuhan Pengumpul", "PR": "Pelabuhan Pengumpan Regional",
            "PL": "Pelabuhan Pengumpan Lokal"}
# warna HARUS sama dgn LEGENDA_PER_LAYER di static/js/maps-overlay.js
WARNA_HIERARKI = {"PU": "#B91C1C", "PP": "#EA580C", "PR": "#2563EB", "PL": "#0D9488"}
WARNA_KHUSUS = {"TERSUS": "#6B7280", "TUKS": "#A16207"}
AMBANG_OUTLIER = 100_000_000  # Pendekatan_Kapasitas!B3
RADIUS_LAUT_M = 25_000

DDL = """
CREATE TABLE IF NOT EXISTS pelabuhan_ripn (
    id_ripn INTEGER PRIMARY KEY,       -- nomor baris sheet RIPN (kunci join; kode pelabuhan tidak unik)
    kode_pelabuhan TEXT,               -- kode Kemenhub (UN/LOCODE-style), kosong utk terminal khusus
    nama_pelabuhan TEXT,
    tipe TEXT,                         -- Umum / Khusus
    hierarki TEXT,                     -- PU/PP/PR/PL (umum), sesuai daftar RIPN
    hierarki_nama TEXT,
    hierarki_2017 TEXT, hierarki_2022 TEXT, hierarki_2027 TEXT, hierarki_2037 TEXT,  -- rencana RIPN (Sheet2)
    keterangan_ripn TEXT,              -- penanda Sheet2 (*, **, DW, ...) apa adanya
    tipe_khusus TEXT,                  -- TERSUS / TUKS
    lampiran TEXT,
    lat DOUBLE PRECISION, lon DOUBLE PRECISION,
    provinsi_sumber TEXT, kab_sumber TEXT, kode_kab_sumber TEXT,  -- sumber apa adanya (urutan Kemendagri)
    kode_provinsi INTEGER, kode_kabupaten INTEGER,                 -- BPS, dari titik
    provinsi TEXT, kabupaten_kota TEXT,
    dasar_kode TEXT,                   -- 'titik di poligon' / 'kab terdekat (titik di laut, x km)'
    catatan_data TEXT,
    diimpor_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pelabuhan_ripn_kab ON pelabuhan_ripn (kode_kabupaten);
CREATE INDEX IF NOT EXISTS idx_pelabuhan_ripn_kode ON pelabuhan_ripn (kode_pelabuhan);
CREATE TABLE IF NOT EXISTS pelabuhan_kinerja (
    id SERIAL PRIMARY KEY,
    id_ripn INTEGER, kode_pelabuhan TEXT, nama_pelabuhan TEXT, tahun SMALLINT,
    kode_provinsi INTEGER, kode_kabupaten INTEGER,   -- dari pelabuhan_ripn
    unit_dn NUMERIC, gt_dn NUMERIC, avg_gt_dn NUMERIC, unit_ln NUMERIC, gt_ln NUMERIC, avg_gt_ln NUMERIC,
    penumpang_datang_dn NUMERIC, penumpang_berangkat_dn NUMERIC,
    penumpang_datang_ln NUMERIC, penumpang_berangkat_ln NUMERIC,
    bongkar_dn_ton NUMERIC, muat_dn_ton NUMERIC, bongkar_ln_ton NUMERIC, muat_ln_ton NUMERIC,
    total_ton_bersih NUMERIC,          -- 4 arus barang, sel > 100 juta ton dianggap galat (= 0), sama dgn sumber
    keterangan TEXT,                   -- 'BPS - Diusahakan' / 'Tidak Diusahakan' / '-' (tanpa data)
    catatan_data TEXT
);
CREATE INDEX IF NOT EXISTS idx_pelabuhan_kinerja_ripn ON pelabuhan_kinerja (id_ripn);
CREATE TABLE IF NOT EXISTS pelabuhan_fasilitas_komponen (
    id SERIAL PRIMARY KEY,
    id_ripn INTEGER, kode_pelabuhan TEXT, nama_pelabuhan TEXT, tahun SMALLINT,
    kode_provinsi INTEGER, kode_kabupaten INTEGER,   -- dari pelabuhan_ripn (provinsi di sheet ini ada yg salah)
    jenis_komponen TEXT, nama_komponen TEXT,
    panjang_m NUMERIC, lebar_m NUMERIC, luas NUMERIC, satuan_luas TEXT, keterangan TEXT,
    catatan_data TEXT
);
CREATE INDEX IF NOT EXISTS idx_pelabuhan_fas_ripn ON pelabuhan_fasilitas_komponen (id_ripn);
"""

KOL_KINERJA = [("Unit DN", "unit_dn"), ("GT DN", "gt_dn"), ("Avg GT DN", "avg_gt_dn"), ("Unit LN", "unit_ln"),
               ("GT LN", "gt_ln"), ("Avg GT LN", "avg_gt_ln"), ("Datang DN", "penumpang_datang_dn"),
               ("Berangkat DN", "penumpang_berangkat_dn"), ("Datang LN", "penumpang_datang_ln"),
               ("Berangkat LN", "penumpang_berangkat_ln"), ("Bongkar DN", "bongkar_dn_ton"),
               ("Muat DN", "muat_dn_ton"), ("Bongkar LN", "bongkar_ln_ton"), ("Muat LN", "muat_ln_ton")]


class Gagal(Exception):
    pass


def teks(v):
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v).replace("\xa0", " ")).strip()
    return s or None


def angka(v):
    if v is None or (isinstance(v, str) and v.strip() in ("", "-")):
        return None
    try:
        return float(str(v).replace(",", "")) if isinstance(v, str) else float(v)
    except ValueError:
        return None


def norm(s):
    s = (s or "").upper()
    s = re.sub(r"\bPULAU\b", "P", s)
    s = re.sub(r"\bTANJUNG\b", "TG", s)
    return re.sub(r"[^A-Z0-9]", "", s)


def baca_tabel(wb, sheet, kolom_kunci):
    rows = list(wb[sheet].iter_rows(values_only=True))
    for i, r in enumerate(rows):
        if kolom_kunci in [teks(c) for c in r]:
            h = [teks(c) for c in r]
            return [(i + 2 + n, {h[j]: c for j, c in enumerate(row) if j < len(h) and h[j]})
                    for n, row in enumerate(rows[i + 1:]) if any(c not in (None, "") for c in row)]
    raise Gagal(f"{sheet}: header '{kolom_kunci}' tidak ditemukan")


def parse(wb):
    cek = []
    ripn = []
    for baris, r in baca_tabel(wb, "RIPN List Pelabuhan", "Kode Pelabuhan"):
        tipe = teks(r.get("Tipe Pelabuhan"))
        hier = teks(r.get("Hierarki Pelabuhan Umum"))
        tk = teks(r.get("Tipe Pelabuhan Khusus"))
        catatan = []
        if tk == "TESUS":
            tk = "TERSUS"
            catatan.append("Tipe khusus di sumber 'TESUS' (salah ketik), dibaca TERSUS")
        lat, lon = angka(r.get("Lat")), angka(r.get("Lon"))
        if not lat and not lon:  # (0, 0) di sumber = tanpa koordinat (Pawi, Janggerbun)
            lat = lon = None
            catatan.append("Koordinat di sumber (0, 0) -- tidak digambar di peta; kode wilayah dari nama kab")
        ripn.append(dict(
            id_ripn=baris, kode_pelabuhan=teks(r.get("Kode Pelabuhan")), nama_pelabuhan=teks(r.get("Nama Pelabuhan")),
            tipe=tipe, hierarki=hier, hierarki_nama=HIERARKI.get(hier), tipe_khusus=tk,
            lampiran=teks(r.get("Kode Lampiran")), lat=lat, lon=lon,
            provinsi_sumber=teks(r.get("Provinsi")), kab_sumber=teks(r.get("Kota/Kab")),
            kode_kab_sumber=teks(r.get("Kode Kota/Kab")), _catatan=catatan,
            hierarki_2017=None, hierarki_2022=None, hierarki_2027=None, hierarki_2037=None, keterangan_ripn=None,
        ))
    umum = [p for p in ripn if p["tipe"] == "Umum"]
    khusus = [p for p in ripn if p["tipe"] == "Khusus"]
    if len(umum) != 636 or len(khusus) != 1978 or len(ripn) != 2614:
        raise Gagal(f"RIPN: {len(umum)} umum / {len(khusus)} khusus / {len(ripn)} total, harus 636/1978/2614")
    salah = [p["id_ripn"] for p in umum if p["hierarki"] not in HIERARKI] + \
            [p["id_ripn"] for p in khusus if p["tipe_khusus"] not in WARNA_KHUSUS]
    luar = [p["id_ripn"] for p in ripn if p["lat"] is not None and not (-11.5 < p["lat"] < 6.5 and 94 < p["lon"] < 141.5)]
    tanpa = [p["nama_pelabuhan"] for p in ripn if p["lat"] is None]
    if len(tanpa) > 5:
        raise Gagal(f"RIPN: {len(tanpa)} pelabuhan tanpa koordinat (>5), periksa sumber")
    if salah or luar:
        raise Gagal(f"RIPN: hierarki/tipe tak valid {salah[:10]}, titik di luar Indonesia {luar[:10]}")
    cek.append(f"RIPN: 636 umum ({dict(sorted(Counter(p['hierarki'] for p in umum).items()))}) + 1.978 khusus "
               f"({dict(Counter(p['tipe_khusus'] for p in khusus))}); titik di luar Indonesia 0; tanpa koordinat {tanpa}")

    # hierarki rencana (Sheet2, Lampiran I): cocok nama pelabuhan + kab sumber
    rencana = defaultdict(list)
    for r in wb["Sheet2"].iter_rows(values_only=True):
        r = list(r) + [None] * 12
        # kolom nomor urut nasional (r[1]) sering tersimpan "#####" -> pakai nomor per kab (r[3]) + kode hierarki
        if teks(r[0]) == "Lampiran I" and re.fullmatch(r"\d+(\.0)?", str(r[3] or "")) and teks(r[4]) \
                and teks(r[5]) in HIERARKI:
            rencana[norm(r[4])].append(dict(kab=norm(r[2]), h=[teks(x) for x in r[5:9]], ket=teks(r[9])))
    cocok = berbeda = 0
    for p in umum:
        # nama + kab wajib cocok (nama sama bisa di kab lain: Tanjung Tiram Batubara vs Karimun)
        kab = norm(re.sub(r"^(KAB(UPATEN)?\.?|KOTA)\s+", "", p["kab_sumber"] or "", flags=re.I))
        cand = [c for c in rencana.get(norm(p["nama_pelabuhan"]), [])
                if c["kab"] and (c["kab"] in kab or kab in c["kab"])]
        if len(cand) == 1:
            c = cand[0]
            p["hierarki_2017"], p["hierarki_2022"], p["hierarki_2027"], p["hierarki_2037"] = c["h"]
            p["keterangan_ripn"] = c["ket"]
            cocok += 1
            if p["hierarki"] not in c["h"]:
                berbeda += 1
                p["_catatan"].append(f"Hierarki daftar ({p['hierarki']}) tidak ada di rencana 2017-2037 ({'/'.join(map(str, c['h']))})")
    cek.append(f"Hierarki rencana RIPN 2017-2037 (Sheet2): {cocok}/636 tertaut, {berbeda} beda dgn hierarki daftar")

    # tautan kode -> id_ripn (kode ganda: cocokkan nama)
    per_kode = defaultdict(list)
    for p in umum:
        per_kode[p["kode_pelabuhan"]].append(p)

    per_nama = defaultdict(list)
    for p in umum:
        per_nama[norm(p["nama_pelabuhan"])].append(p)

    def tautkan(kode, nama, label, wajib=True):
        cand = per_kode.get(teks(kode), []) if teks(kode) else per_nama.get(norm(nama), [])
        if len(cand) > 1:
            cand = [p for p in cand if norm(p["nama_pelabuhan"]) == norm(nama)]
        if len(cand) != 1:
            if not wajib:
                return None
            raise Gagal(f"{label}: kode {kode!r} / nama {nama!r} tertaut ke {len(cand)} pelabuhan RIPN")
        return cand[0]

    kinerja = []
    for baris, r in baca_tabel(wb, "Kinerja Pelabuhan 2021-2024", "Kode Pelabuhan"):
        p = tautkan(r.get("Kode Pelabuhan"), teks(r.get("Pelabuhan")), f"Kinerja baris {baris}")
        d = dict(id_ripn=p["id_ripn"], kode_pelabuhan=p["kode_pelabuhan"], nama_pelabuhan=teks(r.get("Pelabuhan")),
                 tahun=int(float(r["Tahun"])), keterangan=teks(r.get("Keterangan")), _p=p)
        for src, col in KOL_KINERJA:
            d[col] = angka(r.get(src))
        arus = [d[c] for c in ("bongkar_dn_ton", "muat_dn_ton", "bongkar_ln_ton", "muat_ln_ton")]
        d["total_ton_bersih"] = sum(0 if (x is None or x > AMBANG_OUTLIER) else x for x in arus)
        outlier = [c for c in ("bongkar_dn_ton", "muat_dn_ton", "bongkar_ln_ton", "muat_ln_ton")
                   if d[c] is not None and d[c] > AMBANG_OUTLIER]
        d["catatan_data"] = (f"Arus > {AMBANG_OUTLIER:,} ton dianggap galat sumber (tidak dihitung di total): "
                             + ", ".join(outlier)) if outlier else None
        kinerja.append(d)
    pasangan = Counter((k["id_ripn"], k["tahun"]) for k in kinerja)
    if len(kinerja) != 636 * 4 or len(pasangan) != 636 * 4:
        raise Gagal(f"Kinerja: {len(kinerja)} baris / {len(pasangan)} pasangan unik, harus 2.544")
    bersih = {}
    for _, r in baca_tabel(wb, "Kinerja Bersih Tahunan", "Kode_Pelabuhan"):
        if teks(r.get("Kode_Pelabuhan")) and r.get("Tahun") is not None:
            bersih.setdefault((teks(r["Kode_Pelabuhan"]), int(float(r["Tahun"]))), []).append(angka(r.get("Total_Ton_Bersih")) or 0)
    hitung = defaultdict(list)
    for k in kinerja:
        hitung[(k["kode_pelabuhan"], k["tahun"])].append(k["total_ton_bersih"])
    beda = [k for k in hitung if sorted(round(x) for x in hitung[k]) != sorted(round(x) for x in bersih.get(k, []))]
    if beda:
        raise Gagal(f"Total_Ton_Bersih hitung ulang != sheet 'Kinerja Bersih Tahunan' utk {len(beda)} pasangan, mis. {beda[:5]}")
    n_out = sum(1 for k in kinerja if k["catatan_data"])
    cek.append(f"Kinerja: 636 x 4 tahun; Total_Ton_Bersih hitung ulang = sheet 'Kinerja Bersih Tahunan' "
               f"({len(hitung)}/{len(hitung)}), {n_out} baris punya sel outlier; tanpa data "
               f"{sum(1 for k in kinerja if k['keterangan'] in (None, '-'))}")

    fasilitas = []
    for baris, r in baca_tabel(wb, "Fasilitas Pelabuhan", "Kode_Pelabuhan"):
        # kode kosong di sebagian baris -> nama (hanya bila tunggal); sisanya disimpan tanpa tautan
        p = tautkan(r.get("Kode_Pelabuhan"), teks(r.get("Nama_Pelabuhan")), f"Fasilitas baris {baris}", wajib=False)
        catatan = None
        if p is None:
            catatan = "Tidak tertaut ke daftar RIPN (kode kosong/nama tidak unik)"
            p = {}
        elif norm(teks(r.get("Provinsi"))) != norm(p["provinsi_sumber"]):  # beda ejaan nama pelabuhan wajar
            catatan = (f"Di sheet fasilitas tertulis {teks(r.get('Nama_Pelabuhan'))} / {teks(r.get('Provinsi'))}; "
                       f"daftar RIPN: {p['nama_pelabuhan']} / {p['provinsi_sumber']}")
        fasilitas.append(dict(
            id_ripn=p.get("id_ripn"), kode_pelabuhan=p.get("kode_pelabuhan") or teks(r.get("Kode_Pelabuhan")),
            nama_pelabuhan=teks(r.get("Nama_Pelabuhan")),
            tahun=int(float(r["Tahun"])) if r.get("Tahun") else None,
            jenis_komponen=teks(r.get("Jenis_Komponen")), nama_komponen=teks(r.get("Nama_Komponen")),
            panjang_m=angka(r.get("Panjang_m")), lebar_m=angka(r.get("Lebar_m")), luas=angka(r.get("Luas_m2_Ha")),
            satuan_luas=teks(r.get("Satuan_Luas")), keterangan=teks(r.get("Keterangan")), catatan_data=catatan, _p=p))
    cek.append(f"Fasilitas komponen: {len(fasilitas)} baris, {len({f['id_ripn'] for f in fasilitas})} pelabuhan, "
               f"{sum(1 for f in fasilitas if 'daftar RIPN:' in (f['catatan_data'] or ''))} baris nama/provinsi beda "
               f"dgn daftar RIPN, tak tertaut {sum(1 for f in fasilitas if f['id_ripn'] is None)} "
               f"{sorted({f['nama_pelabuhan'] for f in fasilitas if f['id_ripn'] is None})[:10]}")
    return ripn, kinerja, fasilitas, cek


def isi_wilayah(cur, ripn, master):
    """kode BPS dari titik; bandingkan dgn nama kab sumber."""
    cur.execute("CREATE TEMP TABLE tmp_ripn_titik (id_ripn INTEGER, geom geometry(Point, 4326)) ON COMMIT DROP")
    cur.executemany("INSERT INTO tmp_ripn_titik VALUES (%s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))",
                    [(p["id_ripn"], p["lon"], p["lat"]) for p in ripn if p["lat"] is not None])
    cur.execute("""
        SELECT t.id_ripn, k.kode, k.prov, k.dalam, k.jarak_m, k.poly_id
        FROM tmp_ripn_titik t
        CROSS JOIN LATERAL (
            SELECT (m.attrs->>'KODE_KABUPATEN')::numeric::int AS kode, m.attrs->>'PROVINSI' AS prov, m.id AS poly_id,
                   ST_Intersects(m.geom, t.geom) AS dalam,
                   ST_Distance(m.geom::geography, t.geom::geography) AS jarak_m
            FROM map_layers m
            WHERE m.provinsi = 'BATAS KABUPATEN' AND m.attrs->>'KODE_KABUPATEN' IS NOT NULL
            ORDER BY m.geom <-> t.geom LIMIT 1) k""")
    hasil = {r["id_ripn"]: r for r in cur.fetchall()}
    by_kode = {int(m["kode_kabupaten"]): m for m in master}
    pencocok = PencocokKabupaten(master)
    for p in ripn:
        h = hasil.get(p["id_ripn"])
        if h is None:  # tanpa koordinat -> dari nama kab sumber
            m = pencocok.cari(p["provinsi_sumber"], p["kab_sumber"])
            p["kode_kabupaten"] = int(m["kode_kabupaten"]) if m else None
            p["kode_provinsi"] = int(m["kode_provinsi"]) if m else None
            p["dasar_kode"] = "nama kab sumber (tanpa koordinat)" if m else None
            if m:
                p["provinsi"] = str(m["provinsi"]).title()
                p["kabupaten_kota"] = ("Kota " if p["kode_kabupaten"] % 100 >= 71 else "Kab. ") + str(m["kabupaten_kota"]).title()
            continue
        if not h["dalam"] and h["jarak_m"] > RADIUS_LAUT_M:
            p["kode_kabupaten"] = p["kode_provinsi"] = None
            p["dasar_kode"] = None
            p["_catatan"].append(f"Titik {h['jarak_m'] / 1000:.0f} km dari daratan kab terdekat -- kode wilayah tidak ditetapkan")
            continue
        p["kode_kabupaten"], p["_prov_poly"] = h["kode"], h["prov"]
        p["kode_provinsi"] = h["kode"] // 100
        p["dasar_kode"] = "titik di poligon kab" if h["dalam"] else f"kab terdekat (titik di laut, {h['jarak_m'] / 1000:.1f} km)"
        m = by_kode.get(h["kode"])
        p["provinsi"] = str(m["provinsi"]).title() if m else h["prov"]
        p["kabupaten_kota"] = (("Kota " if h["kode"] % 100 >= 71 else "Kab. ") + str(m["kabupaten_kota"]).title()) if m else None
        nama = pencocok.cari(p["provinsi_sumber"], p["kab_sumber"])
        if nama is not None and int(nama["kode_kabupaten"]) != h["kode"]:
            p["_catatan"].append(f"Kab di sumber '{p['kab_sumber']}' (BPS {nama['kode_kabupaten']}) beda dgn kab lokasi titik "
                                 f"({p['kabupaten_kota']}, {h['kode']})")
    return Counter(p["dasar_kode"].split(" (")[0] if p["dasar_kode"] else "tanpa kode" for p in ripn)


def attrs_peta(p):
    a = {"Nama Pelabuhan": p["nama_pelabuhan"], "Kode Pelabuhan": p["kode_pelabuhan"]}
    if p["tipe"] == "Umum":
        a.update({"Hierarki": f"{p['hierarki']} - {p['hierarki_nama']}",
                  "Hierarki rencana 2017/2022/2027/2037": "/".join(x or "-" for x in (
                      p["hierarki_2017"], p["hierarki_2022"], p["hierarki_2027"], p["hierarki_2037"]))
                  if p["hierarki_2017"] else None,
                  "_warna": WARNA_HIERARKI[p["hierarki"]]})
    else:
        a.update({"Tipe": p["tipe_khusus"], "_warna": WARNA_KHUSUS[p["tipe_khusus"]]})
    a.update({"Kabupaten/Kota": p.get("kabupaten_kota"), "Provinsi": p.get("provinsi"),
              "Kab/Kota (sumber)": p["kab_sumber"], "Catatan data": p["catatan_data"],
              "ID Pelabuhan RIPN": p["id_ripn"],
              "Sumber": "Database Pelabuhan Laut Indonesia ver 22-09-2026 (RIPN, Kemenhub)"})
    return {k: v for k, v in a.items() if v not in (None, "")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx", nargs="?", default=str(XLSX_BAWAAN))
    ap.add_argument("--cek", action="store_true")
    a = ap.parse_args()
    wb = openpyxl.load_workbook(a.xlsx, read_only=True, data_only=True)
    try:
        ripn, kinerja, fasilitas, cek = parse(wb)
    except Gagal as e:
        sys.exit(f"DITOLAK: {e}")
    for c in cek:
        print("OK", c)

    with db_cursor() as cur:
        cur.execute("SELECT DISTINCT kode_provinsi, provinsi, kode_kabupaten, kabupaten_kota FROM penduduk_kecamatan")
        master = cur.fetchall()
        dasar = isi_wilayah(cur, ripn, master)
        for p in ripn:
            p["catatan_data"] = "; ".join(p["_catatan"]) or None
        n_beda = sum(1 for p in ripn if "beda dgn kab lokasi titik" in (p["catatan_data"] or ""))
        print(f"OK Kode wilayah dari titik: {dict(dasar)}; kab sumber beda dgn kab titik: {n_beda}; "
              f"kode kab sumber = kode BPS titik: {sum(1 for p in ripn if p['kode_kab_sumber'] and p.get('kode_kabupaten') and str(p['kode_kabupaten']) == p['kode_kab_sumber'].split('.')[0])}/{len(ripn)}")
        if a.cek:
            print("Mode --cek: tidak menulis ke database.")
            return
        for k in kinerja + fasilitas:
            k["kode_provinsi"], k["kode_kabupaten"] = k["_p"].get("kode_provinsi"), k["_p"].get("kode_kabupaten")

        cur.execute(DDL)
        kol_r = ["id_ripn", "kode_pelabuhan", "nama_pelabuhan", "tipe", "hierarki", "hierarki_nama", "hierarki_2017",
                 "hierarki_2022", "hierarki_2027", "hierarki_2037", "keterangan_ripn", "tipe_khusus", "lampiran", "lat",
                 "lon", "provinsi_sumber", "kab_sumber", "kode_kab_sumber", "kode_provinsi", "kode_kabupaten",
                 "provinsi", "kabupaten_kota", "dasar_kode", "catatan_data"]
        kol_k = ["id_ripn", "kode_pelabuhan", "nama_pelabuhan", "tahun", "kode_provinsi", "kode_kabupaten"] + \
                [c for _, c in KOL_KINERJA] + ["total_ton_bersih", "keterangan", "catatan_data"]
        kol_f = ["id_ripn", "kode_pelabuhan", "nama_pelabuhan", "tahun", "kode_provinsi", "kode_kabupaten",
                 "jenis_komponen", "nama_komponen", "panjang_m", "lebar_m", "luas", "satuan_luas", "keterangan", "catatan_data"]
        for tabel, kol, data in (("pelabuhan_ripn", kol_r, ripn), ("pelabuhan_kinerja", kol_k, kinerja),
                                 ("pelabuhan_fasilitas_komponen", kol_f, fasilitas)):
            cur.execute(f"DELETE FROM {tabel}")
            cur.executemany(f"INSERT INTO {tabel} ({', '.join(kol)}) VALUES ({', '.join(['%s'] * len(kol))})",
                            [[d.get(c) for c in kol] for d in data])

        cur.execute("DELETE FROM map_layers WHERE provinsi=%s", (BUCKET,))
        cur.execute("DELETE FROM map_layer_meta WHERE provinsi=%s", (BUCKET,))
        cur.executemany(
            "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom, wilayah_provinsi) "
            "VALUES (%s, '', %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s)",
            [(BUCKET, LAYER_UMUM if p["tipe"] == "Umum" else LAYER_KHUSUS, Json(attrs_peta(p)), p["lon"], p["lat"],
              [p["_prov_poly"]] if p.get("_prov_poly") else []) for p in ripn if p["lat"] is not None])
        cur.execute("""
            INSERT INTO map_layer_meta (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp)
            SELECT provinsi, kabupaten, layer, layer, COUNT(*),
                   ROUND((SUM(pg_column_size(geom) + pg_column_size(attrs)) / 1048576.0)::numeric, 2),
                   'Database Pelabuhan Laut Indonesia ver 20260922 (scripts/import_pelabuhan_ripn.py)'
            FROM map_layers WHERE provinsi = %s GROUP BY provinsi, kabupaten, layer""", (BUCKET,))
        for t in ("pelabuhan_ripn", "pelabuhan_kinerja", "pelabuhan_fasilitas_komponen"):
            cur.execute(f"SELECT COUNT(*) n, COUNT(kode_kabupaten) kab FROM {t}")
            r = cur.fetchone()
            print(f"DB {t}: {r['n']} baris, berkode kab {r['kab']}")
        cur.execute("SELECT layer, feature_count FROM map_layer_meta WHERE provinsi=%s", (BUCKET,))
        for r in cur.fetchall():
            print(f"Layer {r['layer']}: {r['feature_count']} titik")


if __name__ == "__main__":
    main()
