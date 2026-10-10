"""Import latihan "Kebutuhan Angkutan Bersubsidi 2026" + kandidat skema tahun jamak (MYC)
-> tabel angkutan_bersubsidi_2026 (514 kab/kota x sektor penumpang/barang) dan overlay
peta bucket "ANGKUTAN BERSUBSIDI".

Sumber: docs/Konektivitas/10. MULTIMODA-INFRASTRUKTUR LOGISTIK/ (Drive "Penambahan Data"
no. 3-7, 28 Sep 2026, Dit. Konektivitas & Infrastruktur Logistik Bappenas). Kajian:
docs/kajian_multimoda_infrastruktur_logistik.md (rekomendasi §7 diikuti di sini).

- Data bersih: Angk_Subsidi_Penumpang_2026 / Angk_Subsidi_Barang_2026 (punya kolom
  Provinsi; sheet "Data Bersih Penumpang" di workbook Exercise tidak). Isinya dicek SAMA
  dgn sheet Data Bersih di workbook Exercise.
- Status mentah (sebelum "pembersihan"): sheet "Angkutan Perintis Penumpang" dan
  "Angkutan Perintis Barang (RAPI)". Disimpan supaya perubahan definisi terlihat
  (barang: penyeberangan ikut dihitung moda barang, 79 -> 147 terlayani; penumpang:
  layanan perkotaan dikeluarkan) -- kajian §4.2/§4.3.
- Tier MYC: sheet "Tier" (= "Daftar Wilayah" di Analisis_Skema_Tahun_Jamak_2026.xlsx).
  Aturannya DIHITUNG ULANG dari data bersih dan impor DITOLAK bila tidak 59/59 sama:
  semesta = urgensi Tinggi (kecuali Kep. Seribu, sudah dilayani kapal APBD DKI);
  Tier 1 = kedua sektor terlayani & salah satu hanya 1 moda; Tier 2 = kedua sektor
  terlayani & masing-masing >1 moda; Tier 3 = hanya satu sektor; Tier 4 = belum
  keduanya. Ini KANDIDAT, belum diuji gerbang Analisa 2 (riwayat gangguan layanan).
- Urgensi = penilaian naratif penyusun (label = awal kalimat narasi), BUKAN skor.
- Potensi integrasi: sheet "Potensi Integrasi Penumpang/Barang" (klasifikasi x jumlah moda).

Pengaman lain (impor ditolak bila gagal): 514 baris per sektor, 514 kode kab/kota BPS
unik = seluruh master; isi file salinan = sheet workbook induk; tabulasi urgensi x
status = sheet Recap Penumpang/Barang.

Kode wilayah dari NAMA (wilayah_cocok.PencocokKabupaten, kolom Jenis menentukan
Kab/Kota). Provinsi sumber yg salah (Lingga di "Riau", Kab. Sorong dkk. di "Papua
Barat") tetap disimpan di provinsi_sumber + catatan_data.

DELETE + INSERT, aman di-rerun. Restart server tidak wajib (imported_at di
map_layer_meta ikut berubah).

Usage (venv aktif):
    python scripts/import_angkutan_bersubsidi.py --cek [folder]   # parse + validasi, tanpa DB tulis
    python scripts/import_angkutan_bersubsidi.py [folder]
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import openpyxl  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from psycopg.types.json import Json  # noqa: E402

load_dotenv(REPO_ROOT / ".env")
from db import db_cursor  # noqa: E402
from wilayah_cocok import PencocokKabupaten, kunci_provinsi  # noqa: E402

FOLDER_BAWAAN = REPO_ROOT / "docs" / "Konektivitas" / "10. MULTIMODA-INFRASTRUKTUR LOGISTIK"
F_PENUMPANG = "Angk_Subsidi_Penumpang_2026 (4agustus26_21.20).xlsx"
F_BARANG = "Angk_Subsidi_Barang_2026 (4agustus26_21.29).xlsx"
F_EXERCISE = "Exercise Kebutuhan Angkutan bersubsidi 2026.xlsx"
F_MYC = "Analisis_Skema_Tahun_Jamak_2026.xlsx"

TABEL = "angkutan_bersubsidi_2026"
BUCKET = "ANGKUTAN BERSUBSIDI"
LAYER_SEKTOR = {"penumpang": "Angkutan Bersubsidi Penumpang 2026",
                "barang": "Angkutan Bersubsidi Barang 2026"}
LAYER_MYC = "Kandidat Skema Tahun Jamak (MYC) 2026"
# warna HARUS sama dgn ANGKUTAN_SUBSIDI_LEGEND di static/js/maps-overlay.js
WARNA_STATUS = {"Terlayani": "#0072B2", "Tidak Terlayani": "#E69F00"}
WARNA_TIER = {"Tier 1": "#B91C1C", "Tier 2": "#F97316", "Tier 3": "#FACC15", "Tier 4": "#6B7280"}
TANPA_TIER = {3101}  # Kep. Seribu: sengaja dikeluarkan penyusun (kapal APBD DKI)

DDL = f"""
CREATE TABLE IF NOT EXISTS {TABEL} (
    id SERIAL PRIMARY KEY,
    sektor TEXT NOT NULL,              -- 'penumpang' | 'barang'
    kode_provinsi INTEGER NOT NULL,    -- ID BPS (dari nama kab/kota, bukan label provinsi sumber)
    kode_kabupaten INTEGER NOT NULL,
    provinsi TEXT,                     -- nama master BPS
    kabupaten_kota TEXT,               -- nama master BPS (Kab./Kota)
    provinsi_sumber TEXT,              -- label di file sumber apa adanya (ada yg salah, lihat catatan_data)
    nama_sumber TEXT,
    klasifikasi TEXT,                  -- Prioritas / Strategis / Non-Prioritas (pemetaan kewilayahan Kemenhub)
    region TEXT,                       -- Barat / Timur
    pulau TEXT,                        -- hanya ada di sumber sektor barang
    jenis TEXT,                        -- Kabupaten / Kota
    jumlah_moda SMALLINT,              -- moda BERSUBSIDI yg melayani (versi data bersih)
    moda TEXT,
    status_layanan TEXT,               -- Terlayani / Tidak Terlayani (versi data bersih)
    jumlah_moda_mentah SMALLINT,       -- versi sheet mentah, sebelum perubahan definisi
    moda_mentah TEXT,
    status_mentah TEXT,
    status_berubah BOOLEAN,            -- status bersih != status mentah
    direkonstruksi TEXT,               -- penumpang saja; arti kolom belum jelas (kajian §4.3)
    perlu_dicek TEXT,                  -- barang saja
    keterangan TEXT,                   -- tipologi: 3TP, KSPEAN, KEK/KI, Pariwisata, ...
    potensi_daerah TEXT,
    urgensi TEXT,                      -- Tinggi / Sedang / Rendah: penilaian NARATIF penyusun, bukan skor
    urgensi_narasi TEXT,
    potensi_integrasi TEXT,            -- Sangat Tinggi / Tinggi / Sedang (klasifikasi x jumlah moda), NULL bila <2 moda
    jenis_integrasi TEXT,
    tier_myc TEXT,                     -- per wilayah (sama di kedua sektor); KANDIDAT, belum diuji gerbang Analisa 2
    rekomendasi_myc TEXT,
    catatan_data TEXT,
    sumber_file TEXT,
    diimpor_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_{TABEL}_kab ON {TABEL} (kode_kabupaten);
CREATE INDEX IF NOT EXISTS idx_{TABEL}_prov ON {TABEL} (kode_provinsi);
"""


class Gagal(Exception):
    pass


def teks(v):
    if v is None:
        return None
    s = str(v).replace("\xa0", " ").strip()
    return s or None


def angka(v):
    return None if v in (None, "", "-") else int(float(v))


def baca(path, sheet=None):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet] if sheet else wb.worksheets[0]
    return [r for r in ws.iter_rows(values_only=True)]


def tabel_header(rows, kolom_wajib):
    """Baris header = baris pertama yg memuat kolom_wajib -> list dict baris data (non-kosong)."""
    for i, r in enumerate(rows):
        if kolom_wajib in [teks(c) for c in r]:
            h = [teks(c) for c in r]
            return [{h[j]: c for j, c in enumerate(row) if j < len(h) and h[j]}
                    for row in rows[i + 1:] if any(c not in (None, "") for c in row)]
    raise Gagal(f"header '{kolom_wajib}' tidak ditemukan")


def nama_cari(nama, jenis=None):
    """Kolom Jenis menentukan Kab/Kota; nama tanpa awalan + jenis Kota -> 'Kota X'."""
    nama = teks(nama)
    if jenis == "Kota" and not re.match(r"^\s*kota\s", nama, re.I):
        return "Kota " + nama
    return nama


def label_urgensi(narasi):
    m = re.match(r"\s*(Tinggi|Sedang|Rendah)\b", narasi or "", re.I)
    return m.group(1).title() if m else None


def cocokkan(pencocok, baris, kol_prov, kol_nama, kol_jenis, label):
    """Isi _m (baris master) tiap baris; tolak bila ada yg gagal / kode ganda."""
    gagal, per_kode = [], {}
    for b in baris:
        prov = teks(b.get(kol_prov)) if kol_prov else None
        m = pencocok.cari(prov, nama_cari(b[kol_nama], teks(b.get(kol_jenis)) if kol_jenis else None))
        if m is None and kol_jenis:  # Jenis salah di sumber: Kotabaru/Kotawaringin ditandai "Kota"
            m = pencocok.cari(prov, teks(b[kol_nama]))
        if m is None:
            gagal.append(b[kol_nama])
            continue
        b["_m"] = m
        per_kode.setdefault(int(m["kode_kabupaten"]), []).append(b[kol_nama])
    ganda = {k: v for k, v in per_kode.items() if len(v) > 1}
    if gagal or ganda:
        raise Gagal(f"{label}: {len(gagal)} nama tak cocok {gagal[:10]}, kode ganda {list(ganda.items())[:5]}")
    return {int(b["_m"]["kode_kabupaten"]): b for b in baris}


def parse(folder, master):
    pencocok = PencocokKabupaten(master)
    semua_kab = {int(m["kode_kabupaten"]) for m in master}
    ex = folder / F_EXERCISE
    cek = []  # baris laporan validasi

    bersih = {}
    for sektor, f, sheet_induk in (("penumpang", F_PENUMPANG, "Data Bersih Penumpang"),
                                   ("barang", F_BARANG, "Data Bersih Barang")):
        rows = tabel_header(baca(folder / f), "Kota/Kabupaten")
        if len(rows) != 514:
            raise Gagal(f"{f}: {len(rows)} baris, harus 514")
        per_kab = cocokkan(pencocok, rows, "Provinsi", "Kota/Kabupaten", "Jenis", f)
        if set(per_kab) != semua_kab:
            raise Gagal(f"{f}: kode kab tidak sama dgn master ({len(set(per_kab) ^ semua_kab)} beda)")
        # salinan == sheet di workbook induk (kolom yg ada di keduanya, kunci nama+jenis)
        induk = tabel_header(baca(ex, sheet_induk), "Kota/Kabupaten")
        kunci = lambda r: (teks(r["Kota/Kabupaten"]), teks(r.get("Jenis")))  # noqa: E731
        induk_by = {kunci(r): r for r in induk}
        beda = []
        for r in rows:
            i = induk_by.get(kunci(r))
            for k in ("Jumlah Moda", "Moda yang Melayani", "Status Layanan", "Urgensi Layanan Angkutan Bersubsidi"):
                a, b = r.get(k), (i or {}).get(k)
                if k == "Jumlah Moda":
                    a, b = angka(a), angka(b)
                if i is None or teks(a) != teks(b):
                    beda.append((kunci(r), k))
        if beda:
            raise Gagal(f"{f} != sheet '{sheet_induk}' di {F_EXERCISE}: {len(beda)} sel beda, mis. {beda[:5]}")
        cek.append(f"{sektor}: 514 baris, 514 kode kab/kota unik = master; identik dgn sheet '{sheet_induk}'")
        bersih[sektor] = per_kab

    # status mentah
    mentah = {
        "penumpang": cocokkan(pencocok, tabel_header(baca(ex, "Angkutan Perintis Penumpang"), "Kota/Kabupaten"),
                              "Provinsi", "Kota/Kabupaten", None, "mentah penumpang"),
        "barang": cocokkan(pencocok, tabel_header(baca(ex, "Angkutan Perintis Barang (RAPI)"), "Kota/Kab"),
                           "Provinsi", "Kota/Kab", None, "mentah barang"),
    }
    kol_mentah = {"penumpang": ("Jumlah Moda", "Moda yang Melayani", "Status Layanan"),
                  "barang": ("Jumlah Moda", "Jenis Moda", "Dilayani/Tidak Dilayani Transportasi Bersubsidi")}
    for sektor, d in mentah.items():
        if set(d) != semua_kab:
            raise Gagal(f"sheet mentah {sektor}: kode kab tidak sama dgn master")

    # potensi integrasi
    integrasi = {}
    for sektor, sheet in (("penumpang", "Potensi Integrasi Penumpang"), ("barang", "Potensi Integrasi Barang")):
        rows = tabel_header(baca(ex, sheet), "Prioritas Integrasi")
        integrasi[sektor] = cocokkan(pencocok, rows, "Provinsi", "Kota/Kabupaten", None, sheet)

    # tier MYC: sheet induk == file salinan, lalu hitung ulang
    tier_sheet = tabel_header(baca(ex, "Tier"), "Tier")
    tier_salinan = tabel_header(baca(folder / F_MYC, "Daftar Wilayah"), "Tier")
    tier = cocokkan(pencocok, tier_sheet, "Provinsi", "Kab/Kota", None, "Tier")
    salinan = cocokkan(pencocok, tier_salinan, "Provinsi", "Kab/Kota", None, "Daftar Wilayah")
    norm_t = lambda d: {k: (teks(r["Tier"]), teks(r["Rekomendasi"])) for k, r in d.items()}  # noqa: E731
    if norm_t(tier) != norm_t(salinan):  # dibanding per kode: ejaan beda ("Fak Fak"/"Fakfak")
        raise Gagal(f"sheet Tier {F_EXERCISE} != 'Daftar Wilayah' {F_MYC}")
    hitung = {}
    for k in semua_kab - TANPA_TIER:
        p, b = bersih["penumpang"][k], bersih["barang"][k]
        up, ub = (label_urgensi(teks(x["Urgensi Layanan Angkutan Bersubsidi"])) for x in (p, b))
        if (up == "Tinggi") != (ub == "Tinggi"):  # label lain boleh beda antar sektor
            raise Gagal(f"urgensi Tinggi hanya di satu sektor utk kode {k} ({up}/{ub}); semesta tier perlu ditinjau")
        if up != "Tinggi":
            continue
        okp, okb = (x["Status Layanan"] == "Terlayani" for x in (p, b))
        mp, mb = angka(p["Jumlah Moda"]), angka(b["Jumlah Moda"])
        hitung[k] = ("Tier 1" if okp and okb and 1 in (mp, mb) else "Tier 2" if okp and okb
                     else "Tier 3" if okp or okb else "Tier 4")
    lembar = {k: teks(r["Tier"]) for k, r in tier.items()}
    if hitung != lembar:
        selisih = sorted(set(hitung.items()) ^ set(lembar.items()))
        raise Gagal(f"aturan tier tidak mereproduksi sheet Tier: {selisih[:10]}")
    cek.append(f"Tier MYC: aturan direproduksi {len(hitung)}/{len(lembar)} ({dict(sorted(Counter(lembar.values()).items()))})")

    # rekap urgensi x status = sheet Recap
    for sektor, sheet in (("penumpang", "Recap Penumpang"), ("barang", "Recap Barang")):
        rek = {}
        for r in baca(ex, sheet):
            if len(r) >= 3 and teks(r[0]) in ("Tinggi", "Sedang", "Rendah") and isinstance(r[1], (int, float)) and len(rek) < 3:
                rek[teks(r[0])] = (int(r[1]), int(r[2]))
        hit = Counter((label_urgensi(teks(x["Urgensi Layanan Angkutan Bersubsidi"])), x["Status Layanan"])
                      for x in bersih[sektor].values())
        hit = {u: (hit[(u, "Terlayani")], hit[(u, "Tidak Terlayani")]) for u in ("Tinggi", "Sedang", "Rendah")}
        if hit != rek:
            raise Gagal(f"{sheet}: rekap sumber {rek} != hitung {hit}")
        cek.append(f"{sheet}: urgensi x status cocok {hit}")

    # susun baris tabel
    hasil = []
    for sektor, per_kab in bersih.items():
        km, km_int = kol_mentah[sektor], integrasi[sektor]
        for k, r in sorted(per_kab.items()):
            m, mt = r["_m"], mentah[sektor][k]
            narasi = teks(r.get("Urgensi Layanan Angkutan Bersubsidi"))
            catatan = []
            if kunci_provinsi(r.get("Provinsi")) != kunci_provinsi(m["provinsi"]):
                catatan.append(f"Provinsi di sumber '{teks(r.get('Provinsi'))}' tidak sesuai kab/kota "
                               f"(BPS: {str(m['provinsi']).title()})")
            pot = teks(r.get("Potensi Daerah")) or ""
            if "Sabang" in pot and k != 1172:
                catatan.append("Potensi Daerah menyebut 'KPBPB Sabang' (di Aceh) -- kemungkinan salah salin")
            st_m = teks(mt.get(km[2]))
            if st_m != r["Status Layanan"]:
                catatan.append(f"Status berubah dari sheet mentah ({st_m} -> {r['Status Layanan']})")
            if k in TANPA_TIER:
                catatan.append("Dikeluarkan dari tier MYC oleh penyusun (sudah dilayani kapal APBD DKI)")
            ti = tier.get(k)
            it = km_int.get(k)
            jenis = "Kota" if k % 100 >= 71 else "Kabupaten"
            if teks(r.get("Jenis")) != jenis:
                catatan.append(f"Jenis di sumber '{teks(r.get('Jenis'))}', seharusnya {jenis}")
            hasil.append(dict(
                sektor=sektor, kode_provinsi=int(m["kode_provinsi"]), kode_kabupaten=k,
                provinsi=str(m["provinsi"]).title(),
                kabupaten_kota=("Kota " if jenis == "Kota" else "Kab. ") + str(m["kabupaten_kota"]).title(),
                provinsi_sumber=teks(r.get("Provinsi")), nama_sumber=teks(r["Kota/Kabupaten"]),
                klasifikasi=teks(r.get("Klasifikasi")), region=teks(r.get("Region")), pulau=teks(r.get("Pulau")),
                jenis=jenis, jumlah_moda=angka(r.get("Jumlah Moda")), moda=teks(r.get("Moda yang Melayani")),
                status_layanan=teks(r.get("Status Layanan")),
                jumlah_moda_mentah=angka(mt.get(km[0])), moda_mentah=teks(mt.get(km[1])), status_mentah=st_m,
                status_berubah=st_m != teks(r.get("Status Layanan")),
                direkonstruksi=teks(r.get("Direkonstruksi")), perlu_dicek=teks(r.get("Perlu Dicek")),
                keterangan=teks(r.get("Keterangan")), potensi_daerah=teks(r.get("Potensi Daerah")),
                urgensi=label_urgensi(narasi), urgensi_narasi=narasi,
                potensi_integrasi=teks(it.get("Prioritas Integrasi")) if it else None,
                jenis_integrasi=teks(it.get("Jenis Integrasi")) if it else None,
                tier_myc=teks(ti["Tier"]) if ti else None, rekomendasi_myc=teks(ti["Rekomendasi"]) if ti else None,
                catatan_data="; ".join(catatan) or None,
                sumber_file=F_PENUMPANG if sektor == "penumpang" else F_BARANG,
            ))
    for sektor in ("penumpang", "barang"):
        rs = [h for h in hasil if h["sektor"] == sektor]
        cek.append(f"{sektor}: terlayani {sum(h['status_layanan'] == 'Terlayani' for h in rs)} (mentah "
                   f"{sum(h['status_mentah'] == 'Terlayani' for h in rs)}), status berubah "
                   f"{sum(h['status_berubah'] for h in rs)}, potensi integrasi {sum(bool(h['potensi_integrasi']) for h in rs)}, "
                   f"provinsi sumber salah {sum('Provinsi di sumber' in (h['catatan_data'] or '') for h in rs)}")
    return hasil, cek


def attrs_peta(h, layer):
    a = {
        "Kabupaten/Kota": h["kabupaten_kota"], "Provinsi": h["provinsi"], "Klasifikasi": h["klasifikasi"],
        "Keterangan (tipologi)": h["keterangan"], "Potensi Daerah": h["potensi_daerah"],
    }
    if layer == LAYER_MYC:
        a.update({"Tier MYC": h["tier_myc"], "Rekomendasi penyusun": h["rekomendasi_myc"],
                  "Status": "KANDIDAT -- belum diuji gerbang Analisa 2 (riwayat gangguan layanan)"})
        a["_warna"] = WARNA_TIER[h["tier_myc"]]
    else:
        a.update({"Status Layanan": h["status_layanan"], "Jumlah Moda": h["jumlah_moda"], "Moda": h["moda"],
                  "Status (sheet mentah)": h["status_mentah"] if h["status_berubah"] else None,
                  "Potensi Integrasi": h["potensi_integrasi"], "Jenis Integrasi": h["jenis_integrasi"],
                  "Tier MYC (kandidat)": h["tier_myc"]})
        a["_warna"] = WARNA_STATUS[h["status_layanan"]]
    a.update({"Urgensi (penilaian naratif penyusun)": h["urgensi"], "Narasi urgensi": h["urgensi_narasi"],
              "Catatan data": h["catatan_data"], "Kode wilayah (BPS)": h["kode_kabupaten"],
              "Sumber": "Bappenas Dit. Konektivitas & Infrastruktur Logistik -- latihan 2026 (draf)"})
    return {k: v for k, v in a.items() if v not in (None, "", "-")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", default=str(FOLDER_BAWAAN))
    ap.add_argument("--cek", action="store_true", help="parse + validasi saja, tanpa menulis DB")
    a = ap.parse_args()

    with db_cursor() as cur:
        cur.execute("SELECT DISTINCT kode_provinsi, provinsi, kode_kabupaten, kabupaten_kota FROM penduduk_kecamatan")
        master = cur.fetchall()
    try:
        hasil, cek = parse(Path(a.folder), master)
    except Gagal as e:
        sys.exit(f"DITOLAK: {e}")
    for c in cek:
        print("OK", c)
    if a.cek:
        print("Mode --cek: tidak menulis ke database.")
        return

    kolom = [k for k in hasil[0]]
    with db_cursor() as cur:
        cur.execute(DDL)
        cur.execute(f"DELETE FROM {TABEL}")
        cur.executemany(f"INSERT INTO {TABEL} ({', '.join(kolom)}) VALUES ({', '.join(['%s'] * len(kolom))})",
                        [[h[k] for k in kolom] for h in hasil])

        cur.execute("SELECT id, attrs->>'PROVINSI' AS prov, (attrs->>'KODE_KABUPATEN')::numeric::int AS kode "
                    "FROM map_layers WHERE provinsi='BATAS KABUPATEN' AND attrs->>'KODE_KABUPATEN' IS NOT NULL")
        poli = {}
        for r in cur.fetchall():
            poli.setdefault(r["kode"], r["id"])
        sisip, tanpa = [], set()
        for h in hasil:
            pid = poli.get(h["kode_kabupaten"])
            if pid is None:
                tanpa.add(h["kabupaten_kota"])
                continue
            sisip.append((LAYER_SEKTOR[h["sektor"]], Json(attrs_peta(h, LAYER_SEKTOR[h["sektor"]])), pid))
            if h["sektor"] == "penumpang" and h["tier_myc"]:
                sisip.append((LAYER_MYC, Json(attrs_peta(h, LAYER_MYC)), pid))
        cur.execute("DELETE FROM map_layers WHERE provinsi=%s", (BUCKET,))
        cur.execute("DELETE FROM map_layer_meta WHERE provinsi=%s", (BUCKET,))
        cur.executemany(
            "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom, wilayah_provinsi) "
            "SELECT %s, '', %s, %s, s.geom, ARRAY[s.attrs->>'PROVINSI'] FROM map_layers s WHERE s.id = %s",
            [(BUCKET, layer, attrs, pid) for layer, attrs, pid in sisip])
        cur.execute("""
            INSERT INTO map_layer_meta (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp)
            SELECT provinsi, kabupaten, layer, layer, COUNT(*),
                   ROUND((SUM(pg_column_size(geom) + pg_column_size(attrs)) / 1048576.0)::numeric, 2),
                   'tabel angkutan_bersubsidi_2026 x poligon BATAS KABUPATEN (scripts/import_angkutan_bersubsidi.py)'
            FROM map_layers WHERE provinsi = %s GROUP BY provinsi, kabupaten, layer""", (BUCKET,))

        cur.execute(f"SELECT sektor, COUNT(*) n, COUNT(DISTINCT kode_kabupaten) kab, COUNT(tier_myc) tier "
                    f"FROM {TABEL} GROUP BY sektor ORDER BY sektor")
        for r in cur.fetchall():
            print(f"DB {r['sektor']}: {r['n']} baris, {r['kab']} kab/kota, {r['tier']} bertier MYC")
        cur.execute("SELECT layer, feature_count, size_mb FROM map_layer_meta WHERE provinsi=%s ORDER BY layer", (BUCKET,))
        for r in cur.fetchall():
            print(f"Layer {r['layer']}: {r['feature_count']} poligon ({r['size_mb']} MB)")
    if tanpa:
        print(f"Tanpa poligon BATAS KABUPATEN ({len(tanpa)}): {sorted(tanpa)}")


if __name__ == "__main__":
    main()
