# -*- coding: utf-8 -*-
"""Ekstrak data BPS "Kabupaten/Kota Dalam Angka 2026" untuk Parameter C
(Kemanfaatan) skoring IJD — lihat scripts/schema_ijd_scoring.sql.

Sumber: SEMUA folder provinsi di dalam_angka/ ("data gdrive" pada kerangka
CPIT). Struktur folder: dalam_angka/<kode2digit> <Nama Provinsi>/ berisi
"<kode4digit> <Nama Kab/Kota> Dalam Angka <tahun>.pdf"; kode berakhiran 00 =
buku provinsi. Tambahkan folder provinsi lain lalu jalankan ulang script ini.

Yang diekstrak:
  - Tabel 3.1.1 tiap buku kab/kota : penduduk, laju pertumbuhan, persentase,
    kepadatan per km2, rasio jenis kelamin — per KECAMATAN (A1 kepadatan).
  - Tabel 5.1.1 buku provinsi      : luas panen, produktivitas, produksi padi
    per KABUPATEN/KOTA, 2024 & 2025 (A2 produktivitas — BPS 2026 tidak lagi
    memublikasikan padi per kecamatan; data KSA hanya level kabupaten).
  - Tabel 9.1.2 buku provinsi      : kendaraan bermotor per KABUPATEN/KOTA per
    jenis, 2023-2025 (A3 rasio kepemilikan kendaraan level kabupaten).
  - Tabel "Kendaraan Bermotor Menurut Kecamatan" (tidak semua kab/kota
    menyediakan) : total kendaraan bermotor per KECAMATAN.
  - Tabel 5.1.2/5.1.3 (Padi Sawah/Ladang), 5.3.1 (Luas Areal Perkebunan),
    5.4.1 (Populasi Ternak), 5.5.2/5.5.3 (Prasarana Budidaya/Produksi
    Perikanan Laut) tiap buku kab/kota : dijadikan flag biner "ada potensi"
    per KECAMATAN (bukan volume) -- dasar sub-parameter A3 "Tematik
    Tambahan" IJD 2026 utk kategori Pertanian/Perkebunan/Peternakan/
    Perikanan (lihat scripts/schema_bps_potensi_tematik.sql).
  - Tabel produksi tahun berjalan per KECAMATAN (beda dari tabel flag *_ada
    di atas utk Perkebunan/Peternakan) : 5.1.2+5.1.3 kolom Produksi (ton),
    5.3.2 Produksi Perkebunan (ton), 5.4.4 Produksi Daging (kg), 5.5.3
    Perikanan Laut kolom Jumlah Produksi (ton) -- utk tampilan di viewer
    "Data", tidak dipakai skoring IJD.

Pemakaian:
    python scripts/extract_dalam_angka.py            # ekstrak -> JSON di stdout
    python scripts/extract_dalam_angka.py --load     # ekstrak + muat ke MySQL

Loader butuh kredensial MySQL dari .env (sama dengan app.py) dan schema dari
scripts/schema_bps_kemanfaatan.sql serta scripts/schema_bps_potensi_tematik.sql
sudah dijalankan.
"""
import argparse
import json
import os
import re
import sys

import fitz  # PyMuPDF

DALAM_ANGKA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dalam_angka")

BOOK_RX = re.compile(r"^(\d{4})\s+(.+?)\s+Dalam Angka\s+\d{4}\.pdf$", re.I)
# Sebagian buku provinsi (bukan kab/kota) diunduh dengan nama file slug web
# ("provinsi-sumatera-utara-dalam-angka-2026.pdf") alih-alih pola
# "<kode0000> <Nama> Dalam Angka <tahun>.pdf" — tidak punya kode 4 digit sama
# sekali, jadi dicek terpisah dari BOOK_RX.
PROV_BOOK_SLUG_RX = re.compile(r"^provinsi-.+-dalam-angka-\d{4}\.pdf$", re.I)
# Sebagian buku provinsi punya kode dengan digit ekstra ("16200 Kalimantan
# Tengah..." alih-alih "6200 Kalimantan Tengah...") — BOOK_RX (persis 4
# digit) tidak match. Kode-nya sendiri tidak dipakai (prov_book cuma 1 path
# per provinsi, tidak keyed by kode seperti buku kab/kota), jadi longgarkan
# jumlah digit di sini asal masih diakhiri "00".
PROV_BOOK_CODE_RX = re.compile(r"^\d+00\s+.+?\s+Dalam Angka\s+\d{4}\.pdf$", re.I)


def discover_provinces(base=DALAM_ANGKA_DIR):
    """Scan dalam_angka/: return list of dict per provinsi:
    {prov_book: path|None, books: {kode: path}, names: {kode: nama}}."""
    provinces = []
    for folder in sorted(os.listdir(base)):
        fpath = os.path.join(base, folder)
        if not os.path.isdir(fpath):
            continue
        prov_book, books, names = None, {}, {}
        for fname in sorted(os.listdir(fpath)):
            m = BOOK_RX.match(fname)
            if not m:
                if not prov_book and (PROV_BOOK_SLUG_RX.match(fname) or PROV_BOOK_CODE_RX.match(fname)):
                    prov_book = os.path.join(fpath, fname)
                continue
            kode, nama = m.group(1), m.group(2).strip()
            if kode.endswith("00"):
                prov_book = os.path.join(fpath, fname)
            else:
                books[kode] = os.path.join(fpath, fname)
                names[kode] = nama
        if books or prov_book:
            provinces.append({"folder": folder, "prov_book": prov_book,
                              "books": books, "names": names})
    if not provinces:
        raise RuntimeError(f"Tidak ada buku Dalam Angka ditemukan di {base}")
    return provinces

MARKER = re.compile(r"^\(\d+\)$")
NUMERICISH = re.compile(r"^[\d.,\s]+$")
DASH = re.compile(r"^[–—-]$")
STOPLINE = re.compile(r"^(Lanjutan Tabel|Sumber/Source|Catatan/Note|https?://)")

# frasa Indonesia -> nama field; urutan kemunculan di blok header halaman =
# urutan kolom nilai pada halaman itu
FIELD_PHRASES = [
    (re.compile(r"Jumlah\s+Penduduk|^Penduduk\s*$"), "penduduk"),
    (re.compile(r"Laju\s+Pertumbuhan"), "laju_pertumbuhan_pct"),
    (re.compile(r"Persentase\s+Penduduk"), "persentase_penduduk"),
    (re.compile(r"Kepadatan\s+Penduduk"), "kepadatan_per_km2"),
    (re.compile(r"Rasio\s+Jenis\s+Kelamin"), "rasio_jenis_kelamin"),
]


def num(s):
    """'1.007,63' -> 1007.63 ; '2,620.24' -> 2620.24 ; '–' -> None.

    Sebagian besar buku pakai koma sebagai desimal ('.' = ribuan, gaya
    Indonesia), tapi ada dua pengecualian:
      - sebagian buku kab/kota (mis. Banyuasin) mencetak pecahan dengan titik
        ('105.48' = rasio 105,48, bukan 10548) tanpa koma sama sekali di
        halaman itu. Tanpa koma, titik hanya sah sebagai pemisah ribuan bila
        diikuti persis 3 digit di tiap kelompok ('42.364'); bila kelompok
        terakhir bukan 3 digit ('84.66'), itu titik desimal.
      - sebagian tabel (mis. Kota Serang, Perikanan) pakai gaya Inggris
        ('2,620.24' = 2620.24, koma ribuan/titik desimal) -- kalau titik DAN
        koma sama-sama ada, yang muncul TERAKHIR di string itu desimalnya
        (baik "1.234,56" gaya Indonesia maupun "1,234.56" gaya Inggris).
    """
    s = s.strip()
    if not s or DASH.match(s):
        return None
    s = s.replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        parts = s.split(".")
        if len(parts) > 1 and len(parts[-1]) != 3:
            s = "".join(parts[:-1]) + "." + parts[-1]
        else:
            s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def page_lines(page):
    return [ln.strip() for ln in page.get_text().splitlines() if ln.strip()]


def parse_stat_page(lines):
    """Halaman tabel BPS satu-token-per-baris. Return (fields, rows) dengan
    rows = list of (nama, [nilai...]). fields=None bila bukan halaman tabel."""
    marker_idx = [i for i, ln in enumerate(lines) if MARKER.match(ln)]
    if len(marker_idx) < 2:
        return None, []
    ncols = len(marker_idx) - 1
    first_marker, last_marker = marker_idx[0], marker_idx[-1]
    # blok header kolom = dari kemunculan terakhir baris "Kecamatan" sebelum
    # marker pertama (judul tabel di atasnya juga memuat frasa yang sama)
    header_start = 0
    for i in range(first_marker - 1, -1, -1):
        if lines[i] in ("Kecamatan", "Kabupaten/Kota"):
            header_start = i
            break
    fields = []
    for ln in lines[header_start:first_marker]:
        for rx, field in FIELD_PHRASES:
            if rx.search(ln) and field not in fields:
                fields.append(field)
    if len(fields) != ncols:
        return None, []

    rows, name, values = [], None, []
    for ln in lines[last_marker + 1:]:
        if STOPLINE.match(ln):
            break
        if NUMERICISH.match(ln) or DASH.match(ln):
            if name is None:
                continue  # nomor halaman / angka nyasar
            values.append(num(ln))
            if len(values) == ncols:
                rows.append((_clean_name(name), values))
                name, values = None, []
        else:
            if name is not None and not values:
                continue  # baris alias bahasa Inggris (mis. "Pandeglang Regency")
            name, values = ln, []
    return fields, rows


def extract_kecamatan_demografi(books, total_names=()):
    """Tabel 3.1.1 tiap buku kab/kota -> dict[(kode_kab, kecamatan)] = fields."""
    out = {}
    for kode, path in books.items():
        fname = os.path.basename(path)
        doc = fitz.open(path)
        # cari halaman judul tabel demografi per kecamatan (di sebagian buku,
        # mis. Kota Tangerang, judulnya tidak memuat nomor "3.1.1")
        start = None
        for pno in range(doc.page_count):
            text = doc[pno].get_text()
            head = text[:1600]
            if "DAFTAR" in head[:400]:
                continue
            if ("Kepadatan Penduduk" in head and "Menurut Kecamatan" in head
                    and "\nKecamatan\n" in text and "(2)" in text):
                start = pno
                break
        if start is None:
            # buku dipindai sebagai gambar (tanpa lapisan teks) atau tata
            # letak menyimpang jauh dari pola standar — lewati, jangan
            # gagalkan seluruh batch provinsi karena satu buku
            print(f"  WARNING: Tabel 3.1.1 tidak ditemukan di {fname} — dilewati",
                  file=sys.stderr)
            doc.close()
            continue
        for pno in range(start, min(start + 10, doc.page_count)):
            text = doc[pno].get_text()
            fields, rows = parse_stat_page(page_lines(doc[pno]))
            if pno > start:
                is_lanjutan = "Lanjutan Tabel/Continued Table 3.1.1" in text
                new_title = re.search(r"Table\s*3\.1\.[2-9]", text[:1600])
                # halaman lanjutan kadang tanpa label "Lanjutan" (Kab. Serang);
                # terima selama masih bisa diparse dan bukan judul tabel baru
                if not is_lanjutan and (new_title or not fields):
                    break
            if not fields:
                continue
            for name, values in rows:
                if _is_total_row(name, total_names):
                    continue
                rec = out.setdefault((kode, name), {})
                rec.update({f: v for f, v in zip(fields, values)})
        doc.close()
    return out


def _is_total_row(name, total_names=()):
    # baris total: "Kabupaten X"/"Kota X"/"Jumlah"/nama provinsi polos
    return (name in total_names or name.startswith(("Kabupaten ", "Kota "))
            or name.startswith("Jumlah"))


def _clean_name(name):
    # sebagian tabel memberi nomor urut pada nama kecamatan ("1. Curug")
    return re.sub(r"^\d+\.\s*", "", name).strip()


def _find_prov_page(doc, table_no, must_contain):
    rx = re.compile(r"Table " + re.escape(table_no))
    for pno in range(doc.page_count):
        head = doc[pno].get_text()[:1600]
        if "DAFTAR" in head[:400]:
            continue
        if rx.search(head) and must_contain in head:
            return pno
    raise RuntimeError(f"Tabel {table_no} tidak ditemukan di buku provinsi")


def build_prov_row_maps(names):
    """Nama baris di tabel provinsi -> kode kab, dari nama buku kab/kota.
    Nama kab & kota sama-sama polos di tabel ("Tangerang" muncul dua kali) —
    dibedakan lewat baris seksi "Kabupaten/Regency" vs "Kota/Municipality"."""
    row_kab, row_kota = {}, {}
    for kode, nama in names.items():
        if nama.startswith("Kabupaten "):
            row_kab[nama[len("Kabupaten "):]] = kode
        elif nama.startswith("Kota "):
            row_kota[nama[len("Kota "):]] = kode
    return row_kab, row_kota


def parse_prov_rows(lines, ncols, row_kab, row_kota):
    """Return dict[kode_kab] = [nilai...] utk halaman tabel provinsi."""
    marker_idx = [i for i, ln in enumerate(lines) if MARKER.match(ln)]
    if not marker_idx:
        return {}
    out, section, name, values = {}, None, None, []
    for ln in lines[marker_idx[-1] + 1:]:
        if STOPLINE.match(ln):
            break
        if ln.startswith("Kabupaten/"):
            section, name, values = row_kab, None, []
            continue
        if ln.startswith("Kota/"):
            section, name, values = row_kota, None, []
            continue
        if NUMERICISH.match(ln) or DASH.match(ln):
            if name is None:
                continue
            values.append(num(ln))
            if len(values) == ncols:
                if section and name in section:
                    out[section[name]] = values
                name, values = None, []
        else:
            name, values = ln, []
    return out


def extract_padi_provinsi(doc, row_kab, row_kota):
    """Tabel 5.1.1 provinsi: luas panen & produktivitas (hal 1), produksi
    (hal lanjutan). Return list of dict per kab per tahun."""
    p = _find_prov_page(doc, "5.1.1", "Luas Panen")
    page1 = parse_prov_rows(page_lines(doc[p]), 4, row_kab, row_kota)      # LP24 LP25 Y24 Y25
    page2 = parse_prov_rows(page_lines(doc[p + 1]), 2, row_kab, row_kota)  # Prod24 Prod25
    rows = []
    for kode, v in page1.items():
        prod = page2.get(kode, [None, None])
        for i, tahun in enumerate((2024, 2025)):
            rows.append({
                "kode_kab": kode, "tahun": tahun,
                "luas_panen_ha": v[i],
                "produktivitas_ku_ha": v[2 + i],
                "produksi_ton": prod[i],
            })
    return rows


def extract_kendaraan_provinsi(doc, row_kab, row_kota):
    """Tabel 9.1.2 provinsi: kendaraan per kab per jenis. Baris per kab = 3
    tahun (2023/2024/2025) x 5 nilai + label tahun di kolom (2)... label tahun
    ('20231', '20242', '2025*,2') ikut tertangkap sebagai baris numerik/nama —
    tangani khusus."""
    p = _find_prov_page(doc, "9.1.2", "Kendaraan Bermotor")
    out = {}
    for pno in (p, p + 1):
        lines = page_lines(doc[pno])
        marker_idx = [i for i, ln in enumerate(lines) if MARKER.match(ln)]
        if not marker_idx:
            continue
        section, name, tahun, values = None, None, None, []
        for ln in lines[marker_idx[-1] + 1:]:
            if STOPLINE.match(ln):
                break
            if ln.startswith("Kabupaten/"):
                section, name = row_kab, None
                continue
            if ln.startswith("Kota/"):
                section, name = row_kota, None
                continue
            m = re.match(r"^(20\d\d)\W*\d?$", ln)  # label tahun: 20231 / 2025*,2
            if m and len(ln) <= 8 and not values:
                tahun, values = int(m.group(1)), []
                continue
            if NUMERICISH.match(ln) or DASH.match(ln):
                if name is None or tahun is None:
                    continue
                values.append(num(ln))
                if len(values) == 5:
                    if section and name in section:
                        out[(section[name], tahun)] = values
                    tahun, values = None, []
            else:
                name, tahun, values = ln, None, []
    rows = []
    for (kode, tahun), v in sorted(out.items()):
        rows.append({
            "kode_kab": kode, "tahun": tahun,
            "mobil_penumpang": v[0], "bus": v[1], "mobil_barang": v[2],
            "sepeda_motor": v[3], "jumlah": v[4],
        })
    return rows


def extract_kendaraan_kecamatan(books, total_names=()):
    """Tabel "Kendaraan Bermotor Menurut Kecamatan" (nomor tabel berbeda tiap
    buku; tidak semua kab/kota menyediakan): total kendaraan per kecamatan =
    jumlah seluruh kolom jenis kendaraan di seluruh halaman lanjutan tabel."""
    out = {}
    for kode, path in books.items():
        doc = fitz.open(path)
        # cari halaman judul + nomor tabelnya
        start, table_no = None, None
        for pno in range(doc.page_count):
            head = doc[pno].get_text()[:1500]
            if "DAFTAR" in head[:400]:
                continue
            if ("Kendaraan Bermotor" in head
                    and re.search(r"Menurut\s+Kecamatan", head)):
                m = re.search(r"Table\s+(\d+\.\d+\.\d+)", head)
                if m:
                    start, table_no = pno, m.group(1)
                    break
        if start is None:
            doc.close()
            continue  # buku ini tidak memublikasikan kendaraan per kecamatan
        rx_lanjut = re.compile(r"Lanjutan Tabel/Continued Table " + re.escape(table_no))
        for pno in range(start, min(start + 12, doc.page_count)):
            text = doc[pno].get_text()
            if pno > start and not rx_lanjut.search(text):
                break
            lines = page_lines(doc[pno])
            marker_idx = [i for i, ln in enumerate(lines) if MARKER.match(ln)]
            if len(marker_idx) < 2:
                continue
            ncols = len(marker_idx) - 1
            name, values = None, []
            for ln in lines[marker_idx[-1] + 1:]:
                if STOPLINE.match(ln):
                    break
                if NUMERICISH.match(ln) or DASH.match(ln):
                    if name is None:
                        continue
                    values.append(num(ln) or 0)
                    if len(values) == ncols:
                        cname = _clean_name(name)
                        if not _is_total_row(cname, total_names):
                            out[(kode, cname)] = out.get((kode, cname), 0) + sum(values)
                        name, values = None, []
                else:
                    if name is not None and not values:
                        continue
                    name, values = ln, []
        doc.close()
    return out


POTENSI_TABLES = {
    "pertanian_ada": [
        (("Padi Sawah", "Menurut Kecamatan"), ()),
        (("Padi Ladang", "Menurut Kecamatan"), ()),
    ],
    "perkebunan_ada": [
        (("Perkebunan", "Menurut Kecamatan", "Jenis Tanaman"), ()),
    ],
    "peternakan_ada": [
        (("Populasi Ternak", "Kecamatan"), ()),
    ],
    "perikanan_ada": [
        (("Prasarana Produksi Budidaya Perikanan", "Kecamatan"), ()),
        (("Perikanan Laut", "Kecamatan"), ("Nilai Tukar",)),
        (("Produksi Ikan", "Penangkapan", "Kecamatan"), ()),
    ],
}

# Angka produksi tahun berjalan per kategori -- tabel BEDA dari POTENSI_TABLES
# utk Perkebunan/Peternakan (yang dipakai utk "ada" itu tabel luas areal/
# populasi, bukan produksi) dan KOLOM SPESIFIK (bukan sum semua kolom) utk
# Pertanian/Perikanan yang tabelnya mencampur kolom luas (ha) dgn produksi
# (ton) atau produksi (ton) dgn nilai rupiah dalam satu tabel yang sama --
# menjumlah semua kolom di situ akan mencampur satuan. col_index=None berarti
# sum semua kolom (aman krn semua kolom situ memang sama-sama produksi per
# jenis tanaman/ternak, satuan konsisten).
PRODUKSI_TABLES = {
    "pertanian_produksi_ton": [
        (("Padi Sawah", "Menurut Kecamatan"), (), 2, None),   # kolom ke-3: Produksi (Ton)
        (("Padi Ladang", "Menurut Kecamatan"), (), 2, None),
        (("Jagung", "Menurut Kecamatan"), (), 2, None),        # sama pola 3-kolom Luas Tanam/Panen/Produksi
    ],
    "perkebunan_produksi_ton": [
        (("Produksi Perkebunan", "Menurut Kecamatan", "Jenis Tanaman"), (), None, None),
        # Varian judul Pandeglang: "Produksi TANAMAN Perkebunan ... (kuintal)"
        # -- elemen ke-5 opsional = faktor skala satuan (kuintal -> ton).
        (("Produksi Tanaman Perkebunan", "Menurut Kecamatan", "Jenis Tanaman"), (), None, None, 0.1),
    ],
    "peternakan_produksi_daging_kg": [
        (("Produksi Daging", "Kecamatan"), (), None, None),
    ],
    "peternakan_produksi_telur_kg": [
        (("Produksi Telur", "Kecamatan"), (), None, None),
    ],
    "perikanan_produksi_ton": [
        (("Perikanan Laut", "Kecamatan"), ("Nilai Tukar",), 0, None),  # kolom ke-1: Jumlah Produksi (Ton) -- laut saja
        # varian lain (mis. Kota Serang): "Produksi Ikan Menurut Tempat
        # Penangkapan/Budidaya" -- kolom Laut(Pelabuhan)+Laut(Non Pelabuhan)+
        # Sungai+Rawa/Danau (tangkap darat & laut) di HALAMAN PERTAMA saja;
        # halaman "lanjutan"-nya ganti makna jadi budidaya (tambak/kolam/
        # sawah) -- max_pages=1 supaya tidak ikut tercampur ke angka tangkap.
        (("Produksi Ikan", "Penangkapan", "Kecamatan"), (), None, 1),
    ],
}


def _find_kecamatan_table_start(doc, must_all, forbid=()):
    """Cari halaman judul tabel "X Menurut Kecamatan" mana pun posisi judulnya
    dalam halaman (sebagian buku menaruh judul di footer halaman data,
    bukan di atas -- lihat Tabel 5.1.2 Aceh Besar). Return (pno, text,
    table_no) atau (None, None, None)."""
    for pno in range(doc.page_count):
        text = doc[pno].get_text()
        if "DAFTAR" in text[:400]:
            continue
        if "\nKecamatan\n" not in text or "(2)" not in text:
            continue
        # judul tabel kadang terbungkus baris (mis. "Padi \nSawah") -- bandingkan
        # dgn whitespace dirapatkan supaya newline di tengah frasa tidak lolos.
        norm = re.sub(r"\s+", " ", text)
        if not all(s in norm for s in must_all):
            continue
        if any(s in norm for s in forbid):
            continue
        m = re.search(r"Table\s+(\d+\.\d+\.\d+)", text)
        return pno, text, (m.group(1) if m else None)
    return None, None, None


def _extract_kecamatan_table_sum(doc, must_all, forbid, total_names, col_index=None, max_pages=None):
    """Jumlahkan kolom numerik per kecamatan pada tabel yang judulnya cocok
    must_all/forbid, termasuk halaman lanjutan ("Lanjutan Tabel"). Dengan
    col_index=None, semua kolom pada baris dijumlahkan (dipakai utk deteksi
    "ada potensi" tanpa peduli satuan kolom); dengan col_index=<int>, cuma
    kolom itu yang diambil (dipakai utk angka produksi bersatuan tunggal,
    mis. kolom "Produksi" di tabel Luas Tanam/Luas Panen/Produksi -- jangan
    dijumlah dgn kolom luas yg satuannya beda). max_pages=1 membatasi cuma
    halaman pertama (tanpa ikut "Lanjutan Tabel") -- dipakai kalau halaman
    lanjutan sebenarnya kelompok kolom yang beda makna (mis. Tabel 5.4.1 Kota
    Serang: hal.1 = tangkap laut/sungai, "lanjutan"-nya = budidaya tambak/
    kolam -- beda kategori, jangan dijumlah jadi satu). Sama seperti
    extract_kendaraan_kecamatan tapi generik utk tabel manapun berpola
    satu-token-per-baris dgn marker (1)(2)(3)."""
    start, text0, table_no = _find_kecamatan_table_start(doc, must_all, forbid)
    if start is None:
        return {}
    rx_lanjut = re.compile(r"Lanjutan Tabel/Continued Table " + re.escape(table_no)) if table_no else None
    out = {}
    for pno in range(start, min(start + 12, doc.page_count)):
        if max_pages is not None and pno >= start + max_pages:
            break
        text = doc[pno].get_text()
        if pno > start:
            is_lanjutan = rx_lanjut.search(text) if rx_lanjut else "Lanjutan Tabel" in text[:400]
            if not is_lanjutan:
                break
        lines = page_lines(doc[pno])
        marker_idx = [i for i, ln in enumerate(lines) if MARKER.match(ln)]
        if len(marker_idx) < 2:
            continue
        ncols = len(marker_idx) - 1
        if col_index is not None and col_index >= ncols:
            continue  # halaman lanjutan dgn kolom lain (jenis tanaman berbeda) -- lewati
        # Banyak tabel produksi memasang PASANGAN kolom tahun per jenis tanaman
        # ("2024 | 2025*" berulang, mis. Tabel 5.2.2/5.3.2 perkebunan) --
        # menjumlah semua kolom berarti dobel hitung 2024+2025. Kalau semua
        # kolom berlabel tahun (persis ncols baris tahun di header sebelum
        # marker "(1)"), jumlahkan hanya kolom tahun terbaru. Cuma berlaku utk
        # col_index=None; pemanggil dgn col_index sudah menunjuk kolom pasti.
        year_cols = None
        if col_index is None and ncols > 0:
            header_years = [int(m.group(1)) for ln in lines[:marker_idx[0]]
                            if (m := re.fullmatch(r"((?:19|20)\d{2})\s*\*?", ln.strip()))]
            if len(header_years) >= ncols:
                years = header_years[-ncols:]
                if len(set(years)) > 1:
                    latest = max(years)
                    year_cols = [i for i, y in enumerate(years) if y == latest]
        name, values = None, []
        for ln in lines[marker_idx[-1] + 1:]:
            if STOPLINE.match(ln):
                break
            if NUMERICISH.match(ln) or DASH.match(ln):
                if name is None:
                    continue
                values.append(num(ln) or 0)
                if len(values) == ncols:
                    cname = _clean_name(name)
                    if col_index is not None:
                        tambahan = values[col_index]
                    elif year_cols is not None:
                        tambahan = sum(values[i] for i in year_cols)
                    else:
                        tambahan = sum(values)
                    # Baris total kab/prov tidak dibuang lagi, tapi disimpan di
                    # kunci "__TOTAL__" -- dipakai pemanggil sbg pembanding
                    # kewajaran (sel typo BPS bisa > total tabelnya sendiri,
                    # mis. Kelapa Angsana Pandeglang "45.918.000" kuintal).
                    key = "__TOTAL__" if _is_total_row(cname, total_names) else cname
                    out[key] = out.get(key, 0) + tambahan
                    name, values = None, []
            else:
                if name is not None and not values:
                    continue
                name, values = ln, []
    return out


def extract_kecamatan_potensi(books, names, total_names=()):
    """4 kategori A3 (pertanian/perkebunan/peternakan/perikanan) -> dict
    keyed (kode_kab, kecamatan) = {field: bool|float}. Flag "*_ada" (bool):
    kecamatan yang tidak muncul di tabel terkait sama sekali tidak masuk
    dict utk field itu (dianggap False saat load). Field "*_produksi_*"
    (float, dari PRODUKSI_TABLES): angka produksi tahun berjalan, None kalau
    tabel produksinya tidak ditemukan/tidak dipublikasikan buku ybs."""
    out = {}
    for kode, path in books.items():
        doc = fitz.open(path)
        kab_bare = re.sub(r"^(Kabupaten|Kota)\s+", "", names.get(kode, ""))
        totals_here = set(total_names) | {kab_bare}
        for field, variants in POTENSI_TABLES.items():
            found_any = False
            for must_all, forbid in variants:
                sums = _extract_kecamatan_table_sum(doc, must_all, forbid, totals_here)
                sums.pop("__TOTAL__", None)  # flag ada/tidak: total tabel tidak dipakai
                if sums:
                    found_any = True
                for cname, total in sums.items():
                    rec = out.setdefault((kode, cname), {})
                    if total and total > 0:
                        rec[field] = True
                    else:
                        rec.setdefault(field, False)
            if not found_any:
                print(f"  WARNING: tabel potensi '{field}' tidak ditemukan di "
                      f"{os.path.basename(path)} — dilewati", file=sys.stderr)
        for field, variants in PRODUKSI_TABLES.items():
            found_any = False
            for variant in variants:
                must_all, forbid, col_index, max_pages = variant[:4]
                scale = variant[4] if len(variant) > 4 else 1  # faktor satuan (kuintal->ton dsb.)
                sums = _extract_kecamatan_table_sum(doc, must_all, forbid, totals_here, col_index, max_pages)
                total_ref = sums.pop("__TOTAL__", None)
                if sums:
                    found_any = True
                for cname, total in sums.items():
                    if total_ref and total > total_ref * 1.05:
                        print(f"  WARNING: {field} '{cname}' = {total} melebihi total tabel "
                              f"({total_ref}) di {os.path.basename(path)} — kemungkinan typo "
                              f"BPS, diabaikan", file=sys.stderr)
                        continue
                    rec = out.setdefault((kode, cname), {})
                    rec[field] = round(rec.get(field, 0) + total * scale, 2)
            if not found_any:
                print(f"  WARNING: tabel produksi '{field}' tidak ditemukan di "
                      f"{os.path.basename(path)} — dilewati", file=sys.stderr)
        doc.close()
    return out


def _clamp_dec62(value, field, kode, nama):
    """Baris "total kota" yang lolos _is_total_row (nama buku tak selalu diawali
    "Kota "/"Kabupaten ") kadang menghasilkan angka acak di kolom persentase —
    DECIMAL(6,2) di skema hanya muat s.d. 9999.99; buang ke None drpd gagalkan
    seluruh batch load."""
    if value is not None and abs(value) > 9999.99:
        print(f"  WARNING: {field}={value} di luar jangkauan wajar untuk {nama} ({kode}) — diabaikan (None)",
              file=sys.stderr)
        return None
    return value


# --- Panjang jalan per kab/kota (bab 8 Transportasi) ---------------------
# Tabel 8.1.1 "Panjang Jalan Menurut Tingkat Kewenangan Pemerintahan" +
# Tabel "Panjang Jalan (Kabupaten) Menurut Kondisi Jalan" -- pembanding
# independen kemantapan_ijd_2026 (baris 39 sheet Kumpulan Data file 2) dan
# kandidat komponen A1 (panjang jalan) pagu provinsi. Pola tabelnya BEDA dari
# tabel per-kecamatan: baris = label kategori (Negara/Provinsi/Kabupaten,
# Baik/Sedang/Rusak/Rusak Berat), kolom = tahun (2023-2025) -- diambil nilai
# kolom tahun TERAKHIR. Catatan cakupan: tabel kondisi umumnya hanya untuk
# jalan kewenangan kab/kota ybs. (judul "Panjang Jalan Kabupaten..."), bukan
# seluruh jalan di wilayahnya.

_JALAN_STOPLINE = re.compile(r"^(Tabel$|Table |Catatan/Note|Sumber/Source|https?://)")


def _label_match(ln, prefix):
    """Cocokkan label baris dgn toleransi digit footnote yang menempel:
    "Negara2/State2" cocok dgn prefix "Negara/" (angka catatan kaki BPS
    ditulis superscript dan menempel ke teks saat diekstrak)."""
    if prefix.endswith("/"):
        return re.match(re.escape(prefix[:-1]) + r"\d?\s*/", ln) is not None
    return ln.startswith(prefix)


def _extract_label_year_table(doc, must_all, prefix_fields):
    """Tabel kecil berpola baris-label x kolom-tahun: return
    ({field: nilai_tahun_terakhir}, tahun_terakhir) atau ({}, None).
    prefix_fields dicek berurutan per baris -- taruh prefix yang lebih
    spesifik dulu ("Rusak Berat/" sebelum "Rusak/"). Baris terjemahan
    Inggris di antara label dan angka ("Kabupaten2" lalu "Regency2")
    dilewati; header tahun boleh menempel footnote ("20252" = 2025)."""
    for pno in range(doc.page_count):
        text = doc[pno].get_text()
        if "DAFTAR" in text[:400]:
            continue
        norm = re.sub(r"\s+", " ", text)
        if not all(m in norm for m in must_all):
            continue
        lines = page_lines(doc[pno])
        marker_idx = [i for i, ln in enumerate(lines) if MARKER.match(ln)]
        if len(marker_idx) < 2:
            continue
        nyears = len(marker_idx) - 1
        years = [int(m.group(1)) for ln in lines[:marker_idx[-1]]
                 if (m := re.fullmatch(r"((?:19|20)\d{2})\d?\*?", ln.strip()))]
        out = {}
        i = marker_idx[-1] + 1
        while i < len(lines):
            ln = lines[i]
            if _JALAN_STOPLINE.match(ln):
                break
            field = next((f for p, f in prefix_fields if _label_match(ln, p)), None)
            if field is None or field in out:
                i += 1
                continue
            vals, j = [], i + 1
            while j < len(lines) and len(vals) < nyears:
                if NUMERICISH.match(lines[j]) or DASH.match(lines[j]):
                    vals.append(num(lines[j]) or 0)
                elif vals or j - i > 3:
                    break  # angka sudah putus / label ternyata bukan baris data
                j += 1
            if vals:
                out[field] = vals[-1]  # kolom tahun terakhir
            i = j
        if out:
            return out, (years[-nyears:][-1] if years else 2025)
    return {}, None


def extract_jalan_kabupaten(books):
    """Panjang jalan per kab/kota: kewenangan (8.1.1) + kondisi (8.1.3)."""
    rows = []
    for kode, path in books.items():
        doc = fitz.open(path)
        kew, th_kew = _extract_label_year_table(
            doc, ("Panjang Jalan", "Kewenangan Pemerintahan"), [
                ("Negara/", "panjang_negara_km"),
                ("Provinsi/", "panjang_provinsi_km"),
                ("Kabupaten", "panjang_kabkota_km"),
                ("Kota", "panjang_kabkota_km"),
                ("Jumlah/", "panjang_total_km"),
            ])
        kon, th_kon = _extract_label_year_table(
            doc, ("Panjang Jalan", "Menurut Kondisi Jalan"), [
                ("Baik/", "kondisi_baik_km"),
                ("Sedang/", "kondisi_sedang_km"),
                ("Rusak Berat/", "kondisi_rusak_berat_km"),
                ("Rusak/", "kondisi_rusak_km"),
                ("Jumlah/", "kondisi_total_km"),
            ])
        doc.close()
        if not kew and not kon:
            print(f"  WARNING: tabel panjang jalan tidak ditemukan di "
                  f"{os.path.basename(path)} — dilewati", file=sys.stderr)
            continue
        rows.append({"kode_kab": kode, "tahun": th_kon or th_kew or 2025, **kew, **kon})
    return rows


def extract_all(prov_filter=None):
    kecamatan_rows, padi_all, kendaraan_all, potensi_rows = [], [], [], []
    jalan_rows = []
    for prov in discover_provinces():
        if prov_filter and prov_filter.lower() not in prov["folder"].lower():
            continue
        names = prov["names"]
        # nama provinsi polos (baris total di tabel) dari nama folder "36 Banten"
        prov_name = re.sub(r"^\d+\s*", "", prov["folder"]).strip()
        totals = {prov_name}
        print(f"Memproses {prov['folder']}: {len(prov['books'])} buku kab/kota"
              + ("" if prov["prov_book"] else " (buku provinsi TIDAK ada)"),
              file=sys.stderr)

        demografi = extract_kecamatan_demografi(prov["books"], totals)
        kendaraan_kec = extract_kendaraan_kecamatan(prov["books"], totals)
        potensi = extract_kecamatan_potensi(prov["books"], names, totals)
        for r in extract_jalan_kabupaten(prov["books"]):
            r["nama_kab"] = names[r["kode_kab"]]
            jalan_rows.append(r)
        for (kode, nama), rec in sorted(potensi.items()):
            potensi_rows.append({
                "kode_kab": kode, "nama_kab": names[kode], "kecamatan": nama,
                "tahun": 2025,
                "pertanian_ada": rec.get("pertanian_ada", False),
                "perkebunan_ada": rec.get("perkebunan_ada", False),
                "peternakan_ada": rec.get("peternakan_ada", False),
                "perikanan_ada": rec.get("perikanan_ada", False),
                "pertanian_produksi_ton": rec.get("pertanian_produksi_ton"),
                "perkebunan_produksi_ton": rec.get("perkebunan_produksi_ton"),
                "peternakan_produksi_daging_kg": rec.get("peternakan_produksi_daging_kg"),
                "peternakan_produksi_telur_kg": rec.get("peternakan_produksi_telur_kg"),
                "perikanan_produksi_ton": rec.get("perikanan_produksi_ton"),
            })
        for (kode, nama), rec in sorted(demografi.items()):
            penduduk = rec.get("penduduk")
            kepadatan = rec.get("kepadatan_per_km2")
            kecamatan_rows.append({
                "kode_kab": kode, "nama_kab": names[kode], "kecamatan": nama,
                "tahun": 2025,
                "jumlah_penduduk": int(penduduk) if penduduk is not None else None,
                "laju_pertumbuhan_pct": _clamp_dec62(rec.get("laju_pertumbuhan_pct"), "laju_pertumbuhan_pct", kode, nama),
                "persentase_penduduk": _clamp_dec62(rec.get("persentase_penduduk"), "persentase_penduduk", kode, nama),
                "kepadatan_per_km2": kepadatan,
                "rasio_jenis_kelamin": _clamp_dec62(rec.get("rasio_jenis_kelamin"), "rasio_jenis_kelamin", kode, nama),
                "luas_km2_derived": round(penduduk / kepadatan, 2)
                    if penduduk and kepadatan else None,
                "total_kendaraan": int(kendaraan_kec[(kode, nama)])
                    if (kode, nama) in kendaraan_kec else None,
            })

        if prov["prov_book"]:
            row_kab, row_kota = build_prov_row_maps(names)
            doc = fitz.open(prov["prov_book"])
            try:
                for r in extract_padi_provinsi(doc, row_kab, row_kota):
                    r["nama_kab"] = names[r["kode_kab"]]
                    padi_all.append(r)
            except RuntimeError as e:
                print(f"  WARNING: padi provinsi — {e}", file=sys.stderr)
            try:
                for r in extract_kendaraan_provinsi(doc, row_kab, row_kota):
                    r["nama_kab"] = names[r["kode_kab"]]
                    kendaraan_all.append(r)
            except RuntimeError as e:
                print(f"  WARNING: kendaraan provinsi — {e}", file=sys.stderr)
            doc.close()

    return {
        "kecamatan_demografi": kecamatan_rows,
        "kabupaten_padi": padi_all,
        "kabupaten_kendaraan": kendaraan_all,
        "kecamatan_potensi": potensi_rows,
        "kabupaten_jalan": jalan_rows,
    }


def load_mysql(data):
    import pymysql
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(DALAM_ANGKA_DIR), ".env"))
        load_dotenv()  # cwd fallback
    except ImportError:
        pass
    conn = pymysql.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASS", ""),
        database=os.getenv("MYSQL_DB", "route_gis"),
        charset="utf8mb4",
    )
    with conn:
        with conn.cursor() as cur:
            for r in data["kecamatan_demografi"]:
                cur.execute(
                    """REPLACE INTO bps_kecamatan_demografi
                       (kode_kab, nama_kab, kecamatan, tahun, jumlah_penduduk,
                        laju_pertumbuhan_pct, persentase_penduduk, kepadatan_per_km2,
                        rasio_jenis_kelamin, luas_km2_derived, total_kendaraan)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (r["kode_kab"], r["nama_kab"], r["kecamatan"], r["tahun"],
                     r["jumlah_penduduk"], r["laju_pertumbuhan_pct"],
                     r["persentase_penduduk"], r["kepadatan_per_km2"],
                     r["rasio_jenis_kelamin"], r["luas_km2_derived"],
                     r["total_kendaraan"]))
            for r in data["kabupaten_padi"]:
                cur.execute(
                    """REPLACE INTO bps_kabupaten_padi
                       (kode_kab, nama_kab, tahun, luas_panen_ha,
                        produktivitas_ku_ha, produksi_ton)
                       VALUES (%s,%s,%s,%s,%s,%s)""",
                    (r["kode_kab"], r["nama_kab"], r["tahun"],
                     r["luas_panen_ha"], r["produktivitas_ku_ha"], r["produksi_ton"]))
            for r in data["kabupaten_kendaraan"]:
                cur.execute(
                    """REPLACE INTO bps_kabupaten_kendaraan
                       (kode_kab, nama_kab, tahun, mobil_penumpang, bus,
                        mobil_barang, sepeda_motor, jumlah)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (r["kode_kab"], r["nama_kab"], r["tahun"],
                     r["mobil_penumpang"], r["bus"], r["mobil_barang"],
                     r["sepeda_motor"], r["jumlah"]))
            for r in data["kecamatan_potensi"]:
                cur.execute(
                    """REPLACE INTO bps_kecamatan_potensi_tematik
                       (kode_kab, nama_kab, kecamatan, tahun, pertanian_ada,
                        perkebunan_ada, peternakan_ada, perikanan_ada,
                        pertanian_produksi_ton, perkebunan_produksi_ton,
                        peternakan_produksi_daging_kg, peternakan_produksi_telur_kg,
                        perikanan_produksi_ton)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (r["kode_kab"], r["nama_kab"], r["kecamatan"], r["tahun"],
                     r["pertanian_ada"], r["perkebunan_ada"],
                     r["peternakan_ada"], r["perikanan_ada"],
                     r["pertanian_produksi_ton"], r["perkebunan_produksi_ton"],
                     r["peternakan_produksi_daging_kg"], r["peternakan_produksi_telur_kg"],
                     r["perikanan_produksi_ton"]))
            # Panjang jalan per kab/kota -- tabel dibuat di sini (bukan file
            # schema terpisah yang harus dijalankan manual) supaya job per
            # provinsi yang sudah berjalan bisa langsung menulis begitu kode
            # ini terbaca proses berikutnya; lihat scripts/schema_bps_jalan.sql
            # utk dokumentasi kolom.
            cur.execute(
                """CREATE TABLE IF NOT EXISTS bps_kabupaten_jalan (
                     kode_kab   CHAR(4)     NOT NULL,
                     nama_kab   VARCHAR(60) NOT NULL,
                     tahun      SMALLINT    NOT NULL,
                     panjang_negara_km      DECIMAL(10,2) NULL,
                     panjang_provinsi_km    DECIMAL(10,2) NULL,
                     panjang_kabkota_km     DECIMAL(10,2) NULL,
                     panjang_total_km       DECIMAL(10,2) NULL,
                     kondisi_baik_km        DECIMAL(10,2) NULL,
                     kondisi_sedang_km      DECIMAL(10,2) NULL,
                     kondisi_rusak_km       DECIMAL(10,2) NULL,
                     kondisi_rusak_berat_km DECIMAL(10,2) NULL,
                     kondisi_total_km       DECIMAL(10,2) NULL,
                     PRIMARY KEY (kode_kab, tahun)
                   ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
            for r in data.get("kabupaten_jalan", []):
                cur.execute(
                    """REPLACE INTO bps_kabupaten_jalan
                       (kode_kab, nama_kab, tahun, panjang_negara_km, panjang_provinsi_km,
                        panjang_kabkota_km, panjang_total_km, kondisi_baik_km,
                        kondisi_sedang_km, kondisi_rusak_km, kondisi_rusak_berat_km,
                        kondisi_total_km)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (r["kode_kab"], r["nama_kab"], r["tahun"],
                     r.get("panjang_negara_km"), r.get("panjang_provinsi_km"),
                     r.get("panjang_kabkota_km"), r.get("panjang_total_km"),
                     r.get("kondisi_baik_km"), r.get("kondisi_sedang_km"),
                     r.get("kondisi_rusak_km"), r.get("kondisi_rusak_berat_km"),
                     r.get("kondisi_total_km")))
        conn.commit()
    counts = {k: len(v) for k, v in data.items()}
    print(f"Loaded ke MySQL: {counts}", file=sys.stderr)


def main():
    # Konsol Windows default ke cp1252, yang tidak bisa encode sebagian nama
    # buku/kecamatan (mis. huruf Turki "İ" yang pernah bikin crash) -- paksa
    # UTF-8 di stdout/stderr biar print+dump JSON aman lintas platform.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--load", action="store_true", help="muat hasil ke MySQL")
    ap.add_argument("--provinsi", default=None,
                    help="hanya folder provinsi yang namanya mengandung teks ini "
                         "(mis. '36 Banten' atau 'banten'); default semua provinsi")
    args = ap.parse_args()
    data = extract_all(args.provinsi)
    # --load dulu SEBELUM print JSON ke stdout -- supaya crash pas nulis ke
    # stdout (mis. konsol Windows default cp1252, tidak bisa encode sebagian
    # karakter nama buku/kecamatan non-Latin1) tidak menyebabkan hasil
    # ekstraksi yang sudah susah payah didapat (bisa berjam-jam utk cakupan
    # nasional) hilang percuma krn belum sempat tersimpan ke MySQL.
    if args.load:
        load_mysql(data)
    try:
        json.dump(data, sys.stdout, ensure_ascii=False, indent=1)
    except UnicodeEncodeError as e:
        print(f"\n(dump JSON ke stdout dilewati -- encoding konsol tidak mendukung "
              f"karakter tertentu: {e}; data {'sudah tersimpan ke MySQL' if args.load else 'ada di memori tapi tidak tercetak'})",
              file=sys.stderr)


if __name__ == "__main__":
    main()
