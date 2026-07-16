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

Pemakaian:
    python scripts/extract_dalam_angka.py            # ekstrak -> JSON di stdout
    python scripts/extract_dalam_angka.py --load     # ekstrak + muat ke MySQL

Loader butuh kredensial MySQL dari .env (sama dengan app.py) dan schema dari
scripts/schema_bps_kemanfaatan.sql sudah dijalankan.
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
    """'1.007,63' -> 1007.63 ; '–' -> None"""
    s = s.strip()
    if not s or DASH.match(s):
        return None
    s = s.replace(" ", "").replace(".", "").replace(",", ".")
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
            raise RuntimeError(f"Tabel 3.1.1 tidak ditemukan di {fname}")
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


def extract_all():
    kecamatan_rows, padi_all, kendaraan_all = [], [], []
    for prov in discover_provinces():
        names = prov["names"]
        # nama provinsi polos (baris total di tabel) dari nama folder "36 Banten"
        prov_name = re.sub(r"^\d+\s*", "", prov["folder"]).strip()
        totals = {prov_name}
        print(f"Memproses {prov['folder']}: {len(prov['books'])} buku kab/kota"
              + ("" if prov["prov_book"] else " (buku provinsi TIDAK ada)"),
              file=sys.stderr)

        demografi = extract_kecamatan_demografi(prov["books"], totals)
        kendaraan_kec = extract_kendaraan_kecamatan(prov["books"], totals)
        for (kode, nama), rec in sorted(demografi.items()):
            penduduk = rec.get("penduduk")
            kepadatan = rec.get("kepadatan_per_km2")
            kecamatan_rows.append({
                "kode_kab": kode, "nama_kab": names[kode], "kecamatan": nama,
                "tahun": 2025,
                "jumlah_penduduk": int(penduduk) if penduduk is not None else None,
                "laju_pertumbuhan_pct": rec.get("laju_pertumbuhan_pct"),
                "persentase_penduduk": rec.get("persentase_penduduk"),
                "kepadatan_per_km2": kepadatan,
                "rasio_jenis_kelamin": rec.get("rasio_jenis_kelamin"),
                "luas_km2_derived": round(penduduk / kepadatan, 2)
                    if penduduk and kepadatan else None,
                "total_kendaraan": int(kendaraan_kec[(kode, nama)])
                    if (kode, nama) in kendaraan_kec else None,
            })

        if prov["prov_book"]:
            row_kab, row_kota = build_prov_row_maps(names)
            doc = fitz.open(prov["prov_book"])
            for r in extract_padi_provinsi(doc, row_kab, row_kota):
                r["nama_kab"] = names[r["kode_kab"]]
                padi_all.append(r)
            for r in extract_kendaraan_provinsi(doc, row_kab, row_kota):
                r["nama_kab"] = names[r["kode_kab"]]
                kendaraan_all.append(r)
            doc.close()

    return {
        "kecamatan_demografi": kecamatan_rows,
        "kabupaten_padi": padi_all,
        "kabupaten_kendaraan": kendaraan_all,
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
        conn.commit()
    counts = {k: len(v) for k, v in data.items()}
    print(f"Loaded ke MySQL: {counts}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--load", action="store_true", help="muat hasil ke MySQL")
    args = ap.parse_args()
    data = extract_all()
    json.dump(data, sys.stdout, ensure_ascii=False, indent=1)
    if args.load:
        load_mysql(data)


if __name__ == "__main__":
    main()
