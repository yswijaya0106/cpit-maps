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
    python scripts/extract_dalam_angka.py --load     # ekstrak + muat ke PostgreSQL
    python scripts/extract_dalam_angka.py --load --workers 4  # paralel per provinsi

Loader butuh kredensial PostgreSQL (PG_*) dari .env (sama dengan app.py) dan schema dari
scripts/schema_bps_kemanfaatan.sql serta scripts/schema_bps_potensi_tematik.sql
sudah dijalankan.

--workers N (default 1, sekuensial -- sama seperti sebelumnya): parsing PDF
per provinsi CPU-bound & saling independen (tidak ada provinsi yang baca
file provinsi lain), jadi aman dibagi ke N proses OS lewat
ProcessPoolExecutor -- BUKAN threading, karena GIL bikin threading biasa
tidak mempercepat kerja CPU-bound seperti parsing regex/teks. Tiap worker
proses mengembalikan hasil murni di memori (list of dict); PostgreSQL TETAP
ditulis sekali di proses utama setelah semua worker selesai (load_pg()
tidak dipanggil per-worker) -- proses tidak bisa berbagi koneksi psycopg,
dan tidak perlu: menulis di akhir jauh lebih murah drpd parsing PDF-nya.
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
# "-?" -- laju pertumbuhan penduduk BISA negatif (kecamatan yang penduduknya
# menyusut, mis. "-0,09"); tanpa ini baris minus dikira nama kecamatan baru
# dan menggeser seluruh nilai baris-baris berikutnya (lihat docs/MEMORY.md).
NUMERICISH = re.compile(r"^-?[\d.,\s]+$")
DASH = re.compile(r"^[–—-]$")
STOPLINE = re.compile(r"^(Lanjutan Tabel|Sumber/Source|Catatan/Note|https?://)")
ROW_NUMBERING = re.compile(r"^\d+\.\s*")  # "1. Kepulauan Mentawai" -> "Kepulauan Mentawai"


def strip_row_numbering(name):
    return ROW_NUMBERING.sub("", name)

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
    # Baris total: nama kab/kota polos ("Aceh Besar") ATAU berprefiks
    # "Kabupaten X"/"Kota X" -- TAPI prefiks itu HARUS dicocokkan balik ke
    # total_names (nama bare kab/kota ybs.), bukan startswith("Kota ") polos
    # -- 41 kecamatan nasional namanya SENDIRI diawali "Kota " (mis. Kota
    # Jantho di Aceh Besar, 5 kecamatan Kota Barat/Selatan/Timur/Utara/
    # Tengah di Gorontalo) dan sebelumnya TERTELAN sbg baris total,
    # datanya hilang total dari bps_kecamatan_potensi_tematik (bug
    # ditemukan 21 Jul 2026 lewat cross-check ekstraksi per-komoditas).
    if name in total_names or name.startswith("Jumlah"):
        return True
    if name.startswith(("Kabupaten ", "Kota ")):
        bare = re.sub(r"^(Kabupaten|Kota)\s+", "", name)
        return bare in total_names
    return False


def _clean_name(name):
    # sebagian tabel memberi nomor urut pada nama kecamatan ("1. Curug")
    return re.sub(r"^\d+\.\s*", "", name).strip()


def _find_prov_page(doc, table_no, must_contain):
    # "Table" dan nomor tabel bisa tercetak di baris terpisah tergantung buku
    # provinsi (mis. "Table\n9.1.2" di Sumut/Jateng vs "Table 9.1.2" satu
    # baris di Jabar/Banten) -- "\s+" (termasuk newline) supaya keduanya cocok.
    rx = re.compile(r"Table\s+" + re.escape(table_no))
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
    """Return dict[kode_kab] = [nilai...] utk halaman tabel provinsi. Sama
    dua varian format yang ditangani extract_kendaraan_provinsi(): nama
    bilingual dua baris ("Kabupaten Bogor/" + "Bogor Regency") dan baris
    angka yang menggabungkan >1 nilai kolom dalam satu teks."""
    marker_idx = [i for i, ln in enumerate(lines) if MARKER.match(ln)]
    if not marker_idx:
        return {}
    out, section, name, values = {}, None, None, []
    awaiting_continuation = False
    for ln in lines[marker_idx[-1] + 1:]:
        if STOPLINE.match(ln):
            break
        if ln.startswith("Kabupaten/"):
            section, name, values, awaiting_continuation = row_kab, None, [], False
            continue
        if ln.startswith("Kota/"):
            section, name, values, awaiting_continuation = row_kota, None, [], False
            continue
        if ln.endswith("/") and (ln.startswith("Kabupaten ") or ln.startswith("Kota ")):
            sect = row_kab if ln.startswith("Kabupaten ") else row_kota
            prefix_len = len("Kabupaten ") if ln.startswith("Kabupaten ") else len("Kota ")
            section, name, values = sect, ln[prefix_len:-1], []
            awaiting_continuation = True
            continue
        if NUMERICISH.match(ln) or DASH.match(ln):
            awaiting_continuation = False
            if name is None:
                continue
            for tok in ln.split():
                values.append(num(tok))
                if len(values) == ncols:
                    # lihat catatan sama di extract_kendaraan_provinsi() --
                    # sebagian buku provinsi tak punya baris pemisah kab/kota
                    # sama sekali, section tetap None selamanya.
                    target = section
                    if target is None:
                        if name in row_kab:
                            target = row_kab
                        elif name in row_kota:
                            target = row_kota
                    if target and name in target:
                        out[target[name]] = values
                    name, values = None, []
        elif awaiting_continuation:
            awaiting_continuation = False  # baris kedua nama bilingual (Inggris)
        else:
            name, values = strip_row_numbering(ln), []
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
    tahun (2023/2024/2025) x N nilai + label tahun di kolom (2)... label tahun
    ('20231', '20242', '2025*,2') ikut tertangkap sebagai baris numerik/nama —
    tangani khusus. Dua varian nama baris teramati antar provinsi:
      - polos satu baris ("Pandeglang", section header "Kabupaten/Regency")
      - bilingual dua baris ("Kabupaten Bogor/" lalu "Bogor Regency") — baris
        kedua (Inggris) harus dilewati, bukan menimpa nama.
    Sebagian buku (kolom sempit) juga menggabungkan 2 nilai kolom terakhir
    dalam satu baris teks ('1.433.350  1.664.859') — NUMERICISH tetap cocok
    (spasi diizinkan), jadi tiap baris numerik dipecah per token, bukan
    diperlakukan sebagai satu nilai.

    N (jumlah nilai per baris tahun) TIDAK selalu 5 (Mobil Penumpang/Bus/
    Mobil Barang/Sepeda Motor/Jumlah) -- ditemukan 23 Jul 2026 (audit narasi
    AI usulan NTT, lihat docs/verifikasi_kendaraan_ntt.md): tabel 9.1.2
    provinsi NTT 2026 cuma py 3 kolom (Mobil Penumpang/Bus/Mobil Barang,
    TANPA Sepeda Motor/Jumlah). Juga ditemukan 27 Jul 2026 (audit
    bps_kabupaten_kendaraan Kaltim/Bali): buku 2026 provinsi lain punya 6
    kolom, bukan 5 -- ada kolom "Kendaraan Khusus" di antara Sepeda Motor
    dan Jumlah. N dihitung dinamis dari jumlah marker "(n)" di header
    tabel (dikurangi 2 kolom non-nilai: Kabupaten/Kota dan Akhir Tahun),
    BUKAN di-hardcode. Kode LAMA menunggu tepat 5 token sebelum commit satu
    baris (kab, tahun) -- utk tabel 3-kolom (NTT) ini artinya token dari
    baris tahun BERIKUTNYA (termasuk LABEL TAHUN itu sendiri) ikut
    "ditelan" jadi nilai kolom ke-4/ke-5, mencemari kab & tahun sebelumnya;
    utk tabel 6-kolom (Kaltim/Bali) kolom ke-5 (Kendaraan Khusus) malah
    KETIMPA jadi "jumlah" dan token Jumlah asli (token ke-6) dibuang --
    skor_ternormalisasi C.A3 (kendaraan/km) jadi salah karena "jumlah" bukan
    total sebenarnya. Diperbaiki: commit baris pending SEKARANG JUGA begitu
    ketemu penanda baris baru (label tahun baru / nama kab baru / akhir
    tabel), bukan menunggu token ke-N_EXPECTED persis -- panjang values per
    baris jadi APA ADANYA (3, 5, atau 6), row-builder di bawah memetakan
    field sesuai panjang aktual. Kalau varian ini 0 baris (label tahun tak
    pernah cocok sama sekali), coba varian lain lewat
    extract_kendaraan_provinsi_grouped() sebelum menyerah — beda provinsi
    beda tata letak kolom, lihat docstring fungsi itu."""
    p = _find_prov_page(doc, "9.1.2", "Kendaraan Bermotor")
    header_text = doc[p].get_text()[:2000]
    n_markers = len(re.findall(r"\(\d+\)", header_text))
    # kolom (1)=Kabupaten/Kota, (2)=Akhir Tahun, sisanya kolom nilai per jenis
    # kendaraan; fallback ke 5 (format lama) kalau markernya tak terbaca sama sekali
    n_expected = n_markers - 2 if n_markers >= 3 else 5
    out = {}

    def _commit(section, name, tahun, values):
        if name is None or tahun is None or not values:
            return
        # sebagian buku provinsi (mis. Sumatera Utara) TIDAK punya baris
        # pemisah "Kabupaten/Regency"/"Kota/Municipality" sama sekali -- kab
        # & kota tercampur satu daftar rata. Kalau section belum pernah
        # ke-set dari header, coba cocokkan ke kedua kamus (row_kab lalu
        # row_kota) alih-alih membuang baris.
        target = section
        if target is None:
            if name in row_kab:
                target = row_kab
            elif name in row_kota:
                target = row_kota
        if target and name in target:
            out[(target[name], tahun)] = values

    for pno in (p, p + 1):
        lines = page_lines(doc[pno])
        marker_idx = [i for i, ln in enumerate(lines) if MARKER.match(ln)]
        if not marker_idx:
            continue
        section, name, tahun, values = None, None, None, []
        awaiting_continuation = False
        for ln in lines[marker_idx[-1] + 1:]:
            if STOPLINE.match(ln):
                _commit(section, name, tahun, values)
                break
            if ln.startswith("Kabupaten/"):
                _commit(section, name, tahun, values)
                section, name, tahun, values, awaiting_continuation = row_kab, None, None, [], False
                continue
            if ln.startswith("Kota/"):
                _commit(section, name, tahun, values)
                section, name, tahun, values, awaiting_continuation = row_kota, None, None, [], False
                continue
            # baris nama bilingual per-kab, mis. "Kabupaten Bogor/" / "Kota Bogor/"
            if ln.endswith("/") and (ln.startswith("Kabupaten ") or ln.startswith("Kota ")):
                _commit(section, name, tahun, values)
                sect = row_kab if ln.startswith("Kabupaten ") else row_kota
                prefix_len = len("Kabupaten ") if ln.startswith("Kabupaten ") else len("Kota ")
                section, name = sect, ln[prefix_len:-1]
                tahun, values, awaiting_continuation = None, [], True
                continue
            m = re.match(r"^(20\d\d)\W*\d?$", ln)  # label tahun: 20231 / 2025*,2
            if m and len(ln) <= 8:
                _commit(section, name, tahun, values)  # tutup baris tahun sebelumnya dulu
                tahun, values, awaiting_continuation = int(m.group(1)), [], False
                continue
            if NUMERICISH.match(ln) or DASH.match(ln):
                awaiting_continuation = False
                if name is None or tahun is None:
                    continue
                for tok in ln.split():
                    values.append(num(tok))
                    if len(values) == n_expected:
                        # commit persis begitu genap n_expected (SEBELUM baris
                        # tahun berikutnya sempat kebaca, jadi tidak pernah
                        # ikut ke cabang _commit di atas).
                        _commit(section, name, tahun, values)
                        tahun, values = None, []
            elif awaiting_continuation:
                # baris kedua nama bilingual (Inggris) — bukan nama baru
                awaiting_continuation = False
            else:
                _commit(section, name, tahun, values)
                name, tahun, values = strip_row_numbering(ln), None, []
        _commit(section, name, tahun, values)  # baris terakhir halaman (mis. tahun 2025 tanpa penutup)
    rows = []
    for (kode, tahun), v in sorted(out.items()):
        if len(v) == 6:
            # varian 6-kolom (mis. Kaltim/Bali 2026): kolom Kendaraan Khusus
            # ditambahkan sebelum Jumlah -- Jumlah tetap dipakai apa adanya
            # dari sumber, BUKAN sum(v[:5]), karena definisi resminya
            # mencakup Kendaraan Khusus juga.
            row = {"mobil_penumpang": v[0], "bus": v[1], "mobil_barang": v[2],
                   "sepeda_motor": v[3], "kendaraan_khusus": v[4], "jumlah": v[5]}
        elif len(v) == 5:
            row = {"mobil_penumpang": v[0], "bus": v[1], "mobil_barang": v[2],
                   "sepeda_motor": v[3], "kendaraan_khusus": None, "jumlah": v[4]}
        elif len(v) == 3:
            # varian 3-kolom (mis. NTT 2026) -- tidak ada kolom Sepeda
            # Motor/Jumlah resmi, "jumlah" dihitung ulang (sum 3 jenis yang
            # ada) drpd dikarang dari token yang salah baca.
            row = {"mobil_penumpang": v[0], "bus": v[1], "mobil_barang": v[2],
                   "sepeda_motor": None, "kendaraan_khusus": None,
                   "jumlah": sum(x for x in v if x is not None)}
        else:
            continue  # jumlah token tak dikenali (bukan 3, 5, atau 6) -- lewati drpd menebak
        row["kode_kab"], row["tahun"] = kode, tahun
        rows.append(row)
    if not rows:
        rows = extract_kendaraan_provinsi_grouped(doc, row_kab, row_kota)
    return rows


def extract_kendaraan_provinsi_grouped(doc, row_kab, row_kota):
    """Varian Tabel 9.1.2 tanpa label tahun per blok (beda dari varian
    default di atas) -- ditemukan di Jawa Timur (audit 20 Jul 2026, lihat
    checklist_implementasi_cpit.md). Kolom dikelompokkan per JENIS
    kendaraan lalu per tahun berurutan (Mobil Penumpang 2023/24/25, Bus
    2023/24/25 di halaman utama; Mobil Barang/Sepeda Motor 2023/24/25 di
    halaman "Lanjutan Tabel") -- SATU baris per kab berisi 6 token numerik
    langsung (bukan 3 baris terpisah per tahun x label tahun spt varian
    default), pola persis sama dgn parse_prov_rows() generik yang sudah
    dipakai extract_padi_provinsi() (ncols=nilai per baris, tanpa parsing
    label tahun). Tidak ada kolom "Jumlah" total di sumbernya -- dihitung
    ulang (sum ke-4 jenis) drpd dipercaya dari BPS."""
    p = _find_prov_page(doc, "9.1.2", "Kendaraan Bermotor")
    page1 = parse_prov_rows(page_lines(doc[p]), 6, row_kab, row_kota)      # MP23 MP24 MP25 Bus23 Bus24 Bus25
    page2 = parse_prov_rows(page_lines(doc[p + 1]), 6, row_kab, row_kota)  # MB23 MB24 MB25 SM23 SM24 SM25
    rows = []
    for kode in sorted(set(page1) | set(page2)):
        v1 = page1.get(kode, [None] * 6)
        v2 = page2.get(kode, [None] * 6)
        for i, tahun in enumerate((2023, 2024, 2025)):
            mp, bus, mb, sm = v1[i], v1[3 + i], v2[i], v2[3 + i]
            terisi = [v for v in (mp, bus, mb, sm) if v is not None]
            rows.append({
                "kode_kab": kode, "tahun": tahun,
                "mobil_penumpang": mp, "bus": bus, "mobil_barang": mb,
                "sepeda_motor": sm, "kendaraan_khusus": None,
                "jumlah": sum(terisi) if terisi else None,
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
        # forbid=KBLI -- sebagian kab/kota (mis. Sumba Timur) TIDAK
        # menerbitkan tabel produksi Padi/Jagung per kecamatan tahun ini;
        # tanpa forbid ini, must_all ("Padi"/"Jagung" + "Menurut Kecamatan")
        # salah nyantol ke tabel INDUSTRI penggilingan (Tabel 6.2.4/6.2.6
        # "Jumlah Industri Penggilingan ... (KBLI: ...)") yang judulnya
        # kebetulan memuat frasa yang sama tapi kolomnya nilai investasi/
        # produksi RUPIAH, bukan ton -- lihat
        # docs/verifikasi_npr_ciparay_cikumpay.md temuan Sumba Timur.
        (("Padi Sawah", "Menurut Kecamatan"), ("KBLI",), 2, None),   # kolom ke-3: Produksi (Ton)
        (("Padi Ladang", "Menurut Kecamatan"), ("KBLI",), 2, None),
        # forbid=Kedelai -- sebagian buku (mis. Sanggau Tabel 5.3.3 "Produksi
        # Jagung dan Kedelai Menurut Kecamatan") menerbitkan Jagung DIGABUNG
        # Kedelai dlm 1 tabel 2-kolom (bukan pola 3-kolom Luas Tanam/Luas
        # Panen/Produksi yang diasumsikan col_index=2 di sini) -- col_index=2
        # thd tabel begini salah ambil kolom (bahkan menelan kode kecamatan
        # baris berikutnya krn ncols kurang hitung, lihat
        # docs/verifikasi_npr_ciparay_cikumpay.md). Belum ada varian parser
        # utk pola gabungan ini -- lebih aman dilewati (tersedia:false) drpd
        # data salah.
        (("Jagung", "Menurut Kecamatan"), ("KBLI", "Kedelai"), 2, None),
    ],
    "perkebunan_produksi_ton": [
        (("Produksi Perkebunan", "Menurut Kecamatan", "Jenis Tanaman"), ("KBLI",), None, None),
        # Varian judul Pandeglang: "Produksi TANAMAN Perkebunan ... (kuintal)"
        # -- elemen ke-5 opsional = faktor skala satuan (kuintal -> ton).
        (("Produksi Tanaman Perkebunan", "Menurut Kecamatan", "Jenis Tanaman"), ("KBLI",), None, None, 0.1),
    ],
    "peternakan_produksi_daging_kg": [
        (("Produksi Daging", "Kecamatan"), ("KBLI",), None, None),
    ],
    "peternakan_produksi_telur_kg": [
        # exclude_trailing_total=True -- tabel ini biasanya diakhiri kolom
        # "Jumlah/Total" yang ISINYA sendiri penjumlahan kolom2 sebelumnya
        # (Ayam Buras+Ayam Petelur+Itik/Entok) -- tanpa exclude ini,
        # col_index=None (sum semua kolom) ikut menjumlah kolom Total itu
        # sendiri, PERSIS DOBEL dari nilai sebenarnya -- lihat
        # docs/verifikasi_npr_ciparay_cikumpay.md temuan Lombok Utara.
        (("Produksi Telur", "Kecamatan"), ("KBLI",), None, None, 1, True),
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


def _scan_trailing_years(header_lines: list) -> list:
    """Baris tahun kolom TEPAT SEBELUM marker (1) -- scan MUNDUR dari akhir
    header_lines, berhenti begitu ketemu baris yang bukan pola tahun murni
    ("2024"/"2025*"). Cuma window mundur-kontigu yang diambil, jadi imun
    thd polusi teks lain lebih jauh di atas (mis. judul tabel yang
    terbungkus baris PDF bisa menyisakan pecahan "2025*" sendirian di
    barisnya sendiri, jauh dari marker -- lihat
    docs/verifikasi_npr_ciparay_cikumpay.md, temuan Tabel 5.2.2 Sanggau)."""
    year_rx = re.compile(r"((?:19|20)\d{2})\s*\*?$")
    i = len(header_lines) - 1
    years = []
    while i >= 0:
        m = year_rx.fullmatch(header_lines[i].strip())
        if not m:
            break
        years.append(int(m.group(1)))
        i -= 1
    years.reverse()
    return years


def _trailing_total_columns(header_lines: list) -> int:
    """Deteksi kolom "Jumlah/Total" bawaan di UJUNG header tabel (label
    Indonesia+Inggris tepat sebelum marker (1), pola 2-baris-per-kolom sama
    seperti _detect_column_groups) -- return 1 kalau ketemu, 0 kalau tidak.
    Dipakai exclude_trailing_total di _extract_kecamatan_table_sum supaya
    kolom penjumlahan bawaan BPS tidak ikut ke-double-count saat col_index
    None menjumlah semua kolom."""
    if len(header_lines) < 2:
        return 0
    id_label, en_label = header_lines[-2].strip(), header_lines[-1].strip()
    if re.fullmatch(r"Jumlah", id_label, re.I) or re.fullmatch(r"Total", en_label, re.I):
        return 1
    return 0


def _extract_kecamatan_table_sum(doc, must_all, forbid, total_names, col_index=None, max_pages=None,
                                  exclude_trailing_total=False):
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
    kolam -- beda kategori, jangan dijumlah jadi satu). exclude_trailing_total
    = True membuang kolom terakhir dari sum kalau labelnya "Jumlah/Total" --
    sebagian tabel BPS (mis. 5.4.5 Produksi Telur) sudah menyertakan kolom
    total bawaan; ikut menjumlahkannya (col_index=None) berarti dobel-hitung
    (lihat docs/verifikasi_npr_ciparay_cikumpay.md). Sama seperti
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
        # Banyak tabel produksi memasang PASANGAN kolom tahun per jenis tanaman
        # ("2024 | 2025*" berulang, mis. Tabel 5.2.2/5.3.2 perkebunan) --
        # menjumlah semua kolom berarti dobel hitung 2024+2025. Kalau semua
        # kolom berlabel tahun (baris tahun kontigu tepat sebelum marker
        # "(1)"), jumlahkan hanya kolom tahun terbaru. Cuma berlaku utk
        # col_index=None; pemanggil dgn col_index sudah menunjuk kolom pasti.
        year_cols = None
        if col_index is None and ncols > 0:
            trailing_years = _scan_trailing_years(lines[:marker_idx[0]])
            if trailing_years:
                if len(trailing_years) != ncols:
                    # Sebagian buku kab/kota menomori kolom "Kode Wilayah"
                    # TERPISAH dari "Kecamatan" (2 kolom teks bermarker,
                    # bukan cuma 1) -- ncols dari jumlah marker jadi
                    # kelebihan hitung. Deret tahun kontigu ini authoritative
                    # (dia scan mundur PERSIS dari marker, imun thd itu),
                    # jadi override ncols dgn panjangnya supaya baris tidak
                    # "kurang nilai" & menelan kode kecamatan berikutnya
                    # sbg data (bug ditemukan & diverifikasi lewat PDF
                    # Sanggau Tabel 5.2.2, lihat
                    # docs/verifikasi_npr_ciparay_cikumpay.md).
                    ncols = len(trailing_years)
                years = trailing_years
                if len(set(years)) > 1:
                    latest = max(years)
                    year_cols = [i for i, y in enumerate(years) if y == latest]
        if col_index is not None and col_index >= ncols:
            continue  # halaman lanjutan dgn kolom lain (jenis tanaman berbeda) -- lewati
        trailing_total = (_trailing_total_columns(lines[:marker_idx[0]])
                           if exclude_trailing_total and col_index is None and year_cols is None else 0)
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
                    elif trailing_total:
                        tambahan = sum(values[:ncols - trailing_total])
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


def _detect_column_groups(header_lines: list, ncols: int) -> list:
    """Deteksi label kolom-per-komoditas dari header tabel "Menurut Kecamatan
    dan Jenis Tanaman" (mis. Tabel 5.3.2 Produksi Perkebunan). Header PDF-nya
    (get_text urutan baca) taruh SEMUA label komoditas dulu ("Kelapa Sawit/
    Oil Palm", "Kelapa/Coconut", ...), BARU SETELAHNYA seluruh baris tahun
    ("2024","2025*", berurutan per komoditas) -- bukan interleaved
    label-tahun-label-tahun. Judul tabel/nomor halaman di ATAS "Kecamatan/
    District" itu noise, bukan label komoditas -- makanya discan dari
    BELAKANG (dekat marker kolom), bukan dari depan: kumpulkan baris tahun
    trailing dulu, lalu baris non-tahun setelahnya sbg label, berhenti begitu
    ketemu "Kecamatan"/"District" (batas kolom nama baris). Return
    [(label, [col_idx,...])] atau [] kalau polanya tidak cocok (jumlah baris
    tahun tidak habis dibagi jumlah label, atau tidak ada label sama sekali)
    -- pemanggil harus lewati halaman itu. `ncols` HARUS sudah dikoreksi
    pemanggil (lihat _extract_kecamatan_table_by_group) memakai panjang
    deret tahun ini kalau beda dari hitungan marker -- fungsi ini tidak
    lagi menolak cuma krn len(years) != ncols, supaya kasus kolom teks
    ekstra ("Kode Wilayah" bermarker terpisah dari "Kecamatan", lihat
    docs/verifikasi_npr_ciparay_cikumpay.md) tetap bisa diproses."""
    years = _scan_trailing_years(header_lines)
    i = len(header_lines) - 1 - len(years)
    labels = []
    while i >= 0:
        s = header_lines[i].strip()
        if not s or s.lower() in ("kecamatan", "district"):
            break
        labels.append(s)
        i -= 1
    labels.reverse()
    if not labels or not years or ncols % len(labels) != 0:
        return []
    per_label = ncols // len(labels)
    return [(labels[i], list(range(i * per_label, (i + 1) * per_label))) for i in range(len(labels))]


def _extract_kecamatan_table_by_group(doc, must_all, forbid, total_names, max_pages=None):
    """Varian _extract_kecamatan_table_sum yang MEMPERTAHANKAN pemisahan per
    komoditas/jenis tanaman (kolom dikelompokkan via _detect_column_groups)
    alih-alih menjumlahkan semua kolom jadi satu angka. Dalam grup yang sama,
    tetap ambil kolom TAHUN TERBARU saja (hindari dobel-hitung 2024+2025,
    pola sama dgn col_index=None di _extract_kecamatan_table_sum). Return
    {kecamatan: {label_komoditas: nilai}}; baris total kab/kota disimpan di
    kunci "__TOTAL__" per label (dibuang oleh pemanggil, dipakai cuma utk
    sanity check kalau dibutuhkan nanti)."""
    start, text0, table_no = _find_kecamatan_table_start(doc, must_all, forbid)
    if start is None:
        return {}
    rx_lanjut = re.compile(r"Lanjutan Tabel/Continued Table " + re.escape(table_no)) if table_no else None
    out: dict = {}
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
        trailing_years = _scan_trailing_years(lines[:marker_idx[0]])
        if trailing_years and len(trailing_years) != ncols:
            # Kolom teks ekstra bermarker terpisah ("Kode Wilayah" selain
            # "Kecamatan") -- lihat docs/verifikasi_npr_ciparay_cikumpay.md.
            ncols = len(trailing_years)
        groups = _detect_column_groups(lines[:marker_idx[0]], ncols)
        if not groups:
            continue  # halaman yang polanya tak terdeteksi -- lewati drpd salah kelompok
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
                    key = "__TOTAL__" if _is_total_row(cname, total_names) else cname
                    rec = out.setdefault(key, {})
                    for label, cols in groups:
                        # cols per grup (biasanya 2 kolom tahun, mis. 2024 lalu
                        # 2025*) -- ambil kolom TERAKHIR grup (tahun terbaru),
                        # hindari dobel-hitung 2024+2025 seperti col_index=None
                        # di _extract_kecamatan_table_sum.
                        rec[label] = rec.get(label, 0) + values[cols[-1]]
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
                exclude_trailing_total = variant[5] if len(variant) > 5 else False
                sums = _extract_kecamatan_table_sum(doc, must_all, forbid, totals_here, col_index, max_pages,
                                                     exclude_trailing_total)
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


# Tabel "Menurut Kecamatan dan Jenis Tanaman" (kolom dikelompokkan per
# komoditas, lihat _extract_kecamatan_table_by_group) -- pelengkap
# PRODUKSI_TABLES["perkebunan_produksi_ton"] di atas (yang menjumlah SEMUA
# komoditas jadi satu angka). Baru PERKEBUNAN yang punya pola tabel begini;
# Pertanian (Padi/Jagung) sudah terpisah di level TABEL sendiri-sendiri
# (bukan kolom dlm 1 tabel), jadi tidak butuh fungsi ini.
KOMODITAS_TABLES = {
    "PERKEBUNAN": [
        (("Produksi Perkebunan", "Menurut Kecamatan", "Jenis Tanaman"), ()),
        (("Produksi Tanaman Perkebunan", "Menurut Kecamatan", "Jenis Tanaman"), (), 0.1),
    ],
}


def extract_kecamatan_komoditas(books, names, total_names=()):
    """Produksi PER KOMODITAS (Kelapa Sawit/Karet/Kopi/dst. terpisah),
    pelengkap extract_kecamatan_potensi() yang menjumlah semua komoditas
    sektor yang sama jadi satu angka. Return list of dict siap load ke
    bps_kecamatan_produksi_komoditas."""
    out = []
    for kode, path in books.items():
        doc = fitz.open(path)
        kab_bare = re.sub(r"^(Kabupaten|Kota)\s+", "", names.get(kode, ""))
        totals_here = set(total_names) | {kab_bare}
        for kategori, variants in KOMODITAS_TABLES.items():
            found_any = False
            for variant in variants:
                must_all, forbid = variant[0], variant[1]
                scale = variant[2] if len(variant) > 2 else 1
                groups = _extract_kecamatan_table_by_group(doc, must_all, forbid, totals_here)
                groups.pop("__TOTAL__", None)
                if groups:
                    found_any = True
                for cname, per_komoditas in groups.items():
                    for jenis, nilai in per_komoditas.items():
                        out.append({
                            "kode_kab": kode, "nama_kab": names[kode], "kecamatan": cname,
                            "tahun": 2025, "kategori": kategori, "jenis_tanaman": jenis,
                            "produksi_ton": round(nilai * scale, 2),
                        })
            if not found_any:
                print(f"  WARNING: tabel komoditas '{kategori}' tidak ditemukan di "
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


_EMPTY_EXTRACT = {
    "kecamatan_demografi": [], "kabupaten_padi": [], "kabupaten_kendaraan": [],
    "kecamatan_potensi": [], "kabupaten_jalan": [], "kecamatan_komoditas": [],
}


def _extract_province(prov):
    """Ekstrak SATU provinsi -- unit kerja worker ProcessPoolExecutor
    (lihat extract_all). Provinsi lain sama sekali tidak disentuh (tidak
    ada file/tabel/state yang di-share), jadi aman dipanggil paralel tanpa
    locking apa pun. TIDAK menulis ke PostgreSQL di sini -- return murni dict
    hasil, digabung & ditulis sekali oleh main process (koneksi psycopg
    tidak bisa dibagi antar proses)."""
    kecamatan_rows, padi_all, kendaraan_all, potensi_rows, jalan_rows = [], [], [], [], []
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
    komoditas_rows = extract_kecamatan_komoditas(prov["books"], names, totals)
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
        "kecamatan_komoditas": komoditas_rows,
    }


def _merge_extract(acc, part):
    for k in acc:
        acc[k].extend(part[k])


def extract_all(prov_filter=None, workers=1):
    provinces = [p for p in discover_provinces()
                 if not prov_filter or prov_filter.lower() in p["folder"].lower()]
    merged = {k: [] for k in _EMPTY_EXTRACT}

    if workers <= 1 or len(provinces) <= 1:
        for prov in provinces:
            _merge_extract(merged, _extract_province(prov))
        return merged

    # ProcessPoolExecutor, BUKAN threading -- parsing PDF itu CPU-bound
    # (regex/iterasi teks), GIL bikin threading biasa tidak mempercepat
    # kerja begini. Tiap provinsi baca file sendiri & tidak share state,
    # jadi partisi per-provinsi ini aman tanpa locking.
    from concurrent.futures import ProcessPoolExecutor, as_completed
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_extract_province, prov): prov for prov in provinces}
        for fut in as_completed(futures):
            prov = futures[fut]
            try:
                _merge_extract(merged, fut.result())
            except Exception as e:
                print(f"  ERROR provinsi {prov['folder']} — dilewati: {e}", file=sys.stderr)
    return merged


def load_pg(data):
    import psycopg
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(DALAM_ANGKA_DIR), ".env"))
        load_dotenv()  # cwd fallback
    except ImportError:
        pass
    conn = psycopg.connect(
        host=os.getenv("PG_HOST", "127.0.0.1"),
        port=int(os.getenv("PG_PORT", "5432")),
        user=os.getenv("PG_USER", "postgres"),
        password=os.getenv("PG_PASS", ""),
        dbname=os.getenv("PG_DB", "route_gis"),
    )
    with conn:
        with conn.cursor() as cur:
            for r in data["kecamatan_demografi"]:
                cur.execute(
                    """INSERT INTO bps_kecamatan_demografi
                       (kode_kab, nama_kab, kecamatan, tahun, jumlah_penduduk,
                        laju_pertumbuhan_pct, persentase_penduduk, kepadatan_per_km2,
                        rasio_jenis_kelamin, luas_km2_derived, total_kendaraan)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (kode_kab, kecamatan, tahun) DO UPDATE SET
                       nama_kab=EXCLUDED.nama_kab, jumlah_penduduk=EXCLUDED.jumlah_penduduk,
                       laju_pertumbuhan_pct=EXCLUDED.laju_pertumbuhan_pct,
                       persentase_penduduk=EXCLUDED.persentase_penduduk,
                       kepadatan_per_km2=EXCLUDED.kepadatan_per_km2,
                       rasio_jenis_kelamin=EXCLUDED.rasio_jenis_kelamin,
                       luas_km2_derived=EXCLUDED.luas_km2_derived,
                       total_kendaraan=EXCLUDED.total_kendaraan""",
                    (r["kode_kab"], r["nama_kab"], r["kecamatan"], r["tahun"],
                     r["jumlah_penduduk"], r["laju_pertumbuhan_pct"],
                     r["persentase_penduduk"], r["kepadatan_per_km2"],
                     r["rasio_jenis_kelamin"], r["luas_km2_derived"],
                     r["total_kendaraan"]))
            for r in data["kabupaten_padi"]:
                cur.execute(
                    """INSERT INTO bps_kabupaten_padi
                       (kode_kab, nama_kab, tahun, luas_panen_ha,
                        produktivitas_ku_ha, produksi_ton)
                       VALUES (%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (kode_kab, tahun) DO UPDATE SET
                       nama_kab=EXCLUDED.nama_kab, luas_panen_ha=EXCLUDED.luas_panen_ha,
                       produktivitas_ku_ha=EXCLUDED.produktivitas_ku_ha,
                       produksi_ton=EXCLUDED.produksi_ton""",
                    (r["kode_kab"], r["nama_kab"], r["tahun"],
                     r["luas_panen_ha"], r["produktivitas_ku_ha"], r["produksi_ton"]))
            for r in data["kabupaten_kendaraan"]:
                cur.execute(
                    """INSERT INTO bps_kabupaten_kendaraan
                       (kode_kab, nama_kab, tahun, mobil_penumpang, bus,
                        mobil_barang, sepeda_motor, kendaraan_khusus, jumlah)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (kode_kab, tahun) DO UPDATE SET
                       nama_kab=EXCLUDED.nama_kab, mobil_penumpang=EXCLUDED.mobil_penumpang,
                       bus=EXCLUDED.bus, mobil_barang=EXCLUDED.mobil_barang,
                       sepeda_motor=EXCLUDED.sepeda_motor,
                       kendaraan_khusus=EXCLUDED.kendaraan_khusus, jumlah=EXCLUDED.jumlah""",
                    (r["kode_kab"], r["nama_kab"], r["tahun"],
                     r["mobil_penumpang"], r["bus"], r["mobil_barang"],
                     r["sepeda_motor"], r.get("kendaraan_khusus"), r["jumlah"]))
            # DELETE dulu utk kode_kab yang diproses run ini, SEBELUM INSERT --
            # tanpa ini, kecamatan yang tabel produksinya dulu SALAH NYANTOL
            # (mis. bug row-shift/tabel-salah yg baru diperbaiki) tapi sekarang
            # correctly gagal cocok (found_any=False) TIDAK PERNAH ditulis
            # ulang (INSERT cuma menyentuh baris yang muncul di data run ini)
            # -- baris lamanya yang SALAH tertinggal permanen di DB. Ditemukan
            # 21 Jul 2026: setelah perbaikan parser Sumba Timur/Sanggau, re-run
            # --load masih menyisakan angka lama krn kena persis kasus ini.
            # kode_kab_scope diambil dari kecamatan_demografi (tabel yang
            # nyaris selalu ada per kab/kota, cakupan run ini) supaya kab
            # yang TIDAK ikut diproses (mis. run dgn --provinsi parsial)
            # tidak ikut ke-DELETE.
            kode_kab_scope = {r["kode_kab"] for r in data["kecamatan_demografi"]} | \
                              {r["kode_kab"] for r in data["kecamatan_potensi"]}
            if kode_kab_scope:
                cur.execute(
                    "DELETE FROM bps_kecamatan_potensi_tematik WHERE kode_kab = ANY(%s)",
                    (list(kode_kab_scope),),
                )
            for r in data["kecamatan_potensi"]:
                cur.execute(
                    """INSERT INTO bps_kecamatan_potensi_tematik
                       (kode_kab, nama_kab, kecamatan, tahun, pertanian_ada,
                        perkebunan_ada, peternakan_ada, perikanan_ada,
                        pertanian_produksi_ton, perkebunan_produksi_ton,
                        peternakan_produksi_daging_kg, peternakan_produksi_telur_kg,
                        perikanan_produksi_ton)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (kode_kab, kecamatan, tahun) DO UPDATE SET
                       nama_kab=EXCLUDED.nama_kab, pertanian_ada=EXCLUDED.pertanian_ada,
                       perkebunan_ada=EXCLUDED.perkebunan_ada, peternakan_ada=EXCLUDED.peternakan_ada,
                       perikanan_ada=EXCLUDED.perikanan_ada,
                       pertanian_produksi_ton=EXCLUDED.pertanian_produksi_ton,
                       perkebunan_produksi_ton=EXCLUDED.perkebunan_produksi_ton,
                       peternakan_produksi_daging_kg=EXCLUDED.peternakan_produksi_daging_kg,
                       peternakan_produksi_telur_kg=EXCLUDED.peternakan_produksi_telur_kg,
                       perikanan_produksi_ton=EXCLUDED.perikanan_produksi_ton""",
                    (r["kode_kab"], r["nama_kab"], r["kecamatan"], r["tahun"],
                     r["pertanian_ada"], r["perkebunan_ada"],
                     r["peternakan_ada"], r["perikanan_ada"],
                     r["pertanian_produksi_ton"], r["perkebunan_produksi_ton"],
                     r["peternakan_produksi_daging_kg"], r["peternakan_produksi_telur_kg"],
                     r["perikanan_produksi_ton"]))
            # Panjang jalan per kab/kota + produksi per komoditas -- tabel
            # sudah dibuat via scripts/migrate_pg_01_schema.py (bukan lagi
            # inline CREATE TABLE spt versi MySQL) -- cek eksistensi saja.
            cur.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='bps_kabupaten_jalan'"
            )
            if not cur.fetchone():
                raise RuntimeError(
                    "Tabel bps_kabupaten_jalan belum ada di PostgreSQL -- jalankan "
                    "scripts/migrate_pg_01_schema.py dulu."
                )
            for r in data.get("kabupaten_jalan", []):
                cur.execute(
                    """INSERT INTO bps_kabupaten_jalan
                       (kode_kab, nama_kab, tahun, panjang_negara_km, panjang_provinsi_km,
                        panjang_kabkota_km, panjang_total_km, kondisi_baik_km,
                        kondisi_sedang_km, kondisi_rusak_km, kondisi_rusak_berat_km,
                        kondisi_total_km)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (kode_kab, tahun) DO UPDATE SET
                       nama_kab=EXCLUDED.nama_kab, panjang_negara_km=EXCLUDED.panjang_negara_km,
                       panjang_provinsi_km=EXCLUDED.panjang_provinsi_km,
                       panjang_kabkota_km=EXCLUDED.panjang_kabkota_km,
                       panjang_total_km=EXCLUDED.panjang_total_km,
                       kondisi_baik_km=EXCLUDED.kondisi_baik_km,
                       kondisi_sedang_km=EXCLUDED.kondisi_sedang_km,
                       kondisi_rusak_km=EXCLUDED.kondisi_rusak_km,
                       kondisi_rusak_berat_km=EXCLUDED.kondisi_rusak_berat_km,
                       kondisi_total_km=EXCLUDED.kondisi_total_km""",
                    (r["kode_kab"], r["nama_kab"], r["tahun"],
                     r.get("panjang_negara_km"), r.get("panjang_provinsi_km"),
                     r.get("panjang_kabkota_km"), r.get("panjang_total_km"),
                     r.get("kondisi_baik_km"), r.get("kondisi_sedang_km"),
                     r.get("kondisi_rusak_km"), r.get("kondisi_rusak_berat_km"),
                     r.get("kondisi_total_km")))
            cur.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='bps_kecamatan_produksi_komoditas'"
            )
            if not cur.fetchone():
                raise RuntimeError(
                    "Tabel bps_kecamatan_produksi_komoditas belum ada di PostgreSQL -- "
                    "jalankan scripts/migrate_pg_01_schema.py dulu."
                )
            for r in data.get("kecamatan_komoditas", []):
                cur.execute(
                    """INSERT INTO bps_kecamatan_produksi_komoditas
                       (kode_kab, nama_kab, kecamatan, tahun, kategori, jenis_tanaman, produksi_ton)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (kode_kab, kecamatan, tahun, kategori, jenis_tanaman) DO UPDATE SET
                       nama_kab=EXCLUDED.nama_kab, produksi_ton=EXCLUDED.produksi_ton""",
                    (r["kode_kab"], r["nama_kab"], r["kecamatan"], r["tahun"],
                     r["kategori"], r["jenis_tanaman"], r["produksi_ton"]))
        conn.commit()
    counts = {k: len(v) for k, v in data.items()}
    print(f"Loaded ke PostgreSQL: {counts}", file=sys.stderr)


def main():
    # Konsol Windows default ke cp1252, yang tidak bisa encode sebagian nama
    # buku/kecamatan (mis. huruf Turki "İ" yang pernah bikin crash) -- paksa
    # UTF-8 di stdout/stderr biar print+dump JSON aman lintas platform.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--load", action="store_true", help="muat hasil ke PostgreSQL")
    ap.add_argument("--provinsi", default=None,
                    help="hanya folder provinsi yang namanya mengandung teks ini "
                         "(mis. '36 Banten' atau 'banten'); default semua provinsi")
    ap.add_argument("--workers", type=int, default=1,
                    help="jumlah proses paralel utk parsing PDF per provinsi "
                         "(default 1 = sekuensial, sama seperti sebelumnya). "
                         "PostgreSQL tetap ditulis sekali di akhir, bukan per-worker.")
    args = ap.parse_args()
    data = extract_all(args.provinsi, workers=args.workers)
    # --load dulu SEBELUM print JSON ke stdout -- supaya crash pas nulis ke
    # stdout (mis. konsol Windows default cp1252, tidak bisa encode sebagian
    # karakter nama buku/kecamatan non-Latin1) tidak menyebabkan hasil
    # ekstraksi yang sudah susah payah didapat (bisa berjam-jam utk cakupan
    # nasional) hilang percuma krn belum sempat tersimpan ke PostgreSQL.
    if args.load:
        load_pg(data)
    try:
        json.dump(data, sys.stdout, ensure_ascii=False, indent=1)
    except UnicodeEncodeError as e:
        print(f"\n(dump JSON ke stdout dilewati -- encoding konsol tidak mendukung "
              f"karakter tertentu: {e}; data {'sudah tersimpan ke PostgreSQL' if args.load else 'ada di memori tapi tidak tercetak'})",
              file=sys.stderr)


if __name__ == "__main__":
    main()
