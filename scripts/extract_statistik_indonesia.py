# -*- coding: utf-8 -*-
"""Ekstrak tabel level provinsi dari BPS "Statistik Indonesia 2026"
(docs/docs/00 Statistik Indonesia 2026.pdf) untuk kebutuhan CPIT/IJD:

  - Tabel 10.1.1 : panjang jalan per provinsi per tingkat kewenangan
                   (nasional/provinsi/kab-kota), 2023-2025 -> komponen A1
                   skor Pagu Indikatif Provinsi.
  - Tabel 10.1.2 : kendaraan bermotor per provinsi per jenis, 2023-2025
                   -> rasio kepemilikan kendaraan (C.A3) level provinsi.
  - Tabel 5.1.6  : luas wilayah + luas lahan baku sawah per provinsi
                   (2019 & 2024) -> pendekatan Indeks Penanaman (C.A2).

Pemakaian:
    python scripts/extract_statistik_indonesia.py            # JSON ke stdout
    python scripts/extract_statistik_indonesia.py --load     # + muat ke MySQL

Schema: scripts/schema_statistik_indonesia.sql (dijalankan otomatis saat --load).
"""
import argparse
import json
import os
import re
import sys

import fitz  # PyMuPDF

PDF_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs", "docs", "00 Statistik Indonesia 2026.pdf")

# kode BPS 2 digit (sinkron dengan tabel penduduk_kecamatan); 0 = Indonesia
PROV_KODE = {
    "ACEH": 11, "SUMATERA UTARA": 12, "SUMATERA BARAT": 13, "RIAU": 14,
    "JAMBI": 15, "SUMATERA SELATAN": 16, "BENGKULU": 17, "LAMPUNG": 18,
    "KEPULAUAN BANGKA BELITUNG": 19, "KEPULAUAN RIAU": 21, "DKI JAKARTA": 31,
    "JAWA BARAT": 32, "JAWA TENGAH": 33, "DI YOGYAKARTA": 34, "JAWA TIMUR": 35,
    "BANTEN": 36, "BALI": 51, "NUSA TENGGARA BARAT": 52,
    "NUSA TENGGARA TIMUR": 53, "KALIMANTAN BARAT": 61, "KALIMANTAN TENGAH": 62,
    "KALIMANTAN SELATAN": 63, "KALIMANTAN TIMUR": 64, "KALIMANTAN UTARA": 65,
    "SULAWESI UTARA": 71, "SULAWESI TENGAH": 72, "SULAWESI SELATAN": 73,
    "SULAWESI TENGGARA": 74, "GORONTALO": 75, "SULAWESI BARAT": 76,
    "MALUKU": 81, "MALUKU UTARA": 82, "PAPUA BARAT": 91, "PAPUA BARAT DAYA": 92,
    "PAPUA": 94, "PAPUA SELATAN": 95, "PAPUA TENGAH": 96, "PAPUA PEGUNUNGAN": 97,
    "INDONESIA": 0,
}

MARKER = re.compile(r"^\(\d+\)$")
# label tahun bisa membawa catatan kaki/penanda: "2023", "20231", "2025*", "2025*,2"
YEAR = re.compile(r"^(20\d\d)\s*(?:[r*]{0,2}|\d|\*,?\d?)$")
NUMERICISH = re.compile(r"^[\d.,\s]+[r*]{0,2}$")
DASH = re.compile(r"^[–—-]$")
STOPLINE = re.compile(r"^(Sumber/Source|Catatan/Note|https?://)")


def num(s):
    """'19.864r' -> 19864 ; '2.139,97' -> 2139.97 ; '–' -> None"""
    s = s.strip().rstrip("r*").strip()
    if not s or DASH.match(s):
        return None
    s = s.replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def clean_prov_name(name):
    # buang penanda catatan kaki ("Papua Barat1") dan spasi ganda
    return re.sub(r"\d+$", "", name).strip()


def page_lines(doc, pno):
    return [ln.strip() for ln in doc[pno].get_text().splitlines() if ln.strip()]


def find_table_page(doc, table_no, keyword):
    rx = re.compile(re.escape(table_no) + r"\s")
    for pno in range(doc.page_count):
        text = doc[pno].get_text()
        if "....." in text:  # halaman daftar isi/tabel
            continue
        if rx.search(text) and keyword in text and "Lanjutan" not in text[:600]:
            return pno
    raise RuntimeError(f"Tabel {table_no} ({keyword}) tidak ditemukan")


def parse_year_table(doc, start, ncols, max_pages=8):
    """Tabel provinsi x tahun (blok 3 tahun per provinsi). Return
    dict[(kode, tahun)] = (nama, [nilai x ncols]). Berhenti saat sebuah
    halaman tidak menyumbang baris lagi."""
    out = {}
    for pno in range(start, min(start + max_pages, doc.page_count)):
        lines = page_lines(doc, pno)
        marker_idx = [i for i, ln in enumerate(lines) if MARKER.match(ln)]
        if len(marker_idx) != ncols + 2:  # (1) provinsi + (2) tahun + ncols nilai
            if pno == start:
                raise RuntimeError(f"Jumlah kolom tak terduga di halaman {pno + 1}")
            break
        added = 0
        name, kode, tahun, values = None, None, None, []
        for ln in lines[marker_idx[-1] + 1:]:
            if STOPLINE.match(ln):
                break
            m = YEAR.match(ln)
            if m and not values:
                tahun, values = int(m.group(1)), []
                continue
            if NUMERICISH.match(ln) or DASH.match(ln):
                if kode is None or tahun is None:
                    continue
                values.append(num(ln))
                if len(values) == ncols:
                    out[(kode, tahun)] = (name, values)
                    added += 1
                    tahun, values = None, []
            else:
                name = clean_prov_name(ln)
                kode = PROV_KODE.get(name.upper())
                tahun, values = None, []
        if added == 0 and pno > start:
            break
    return out


def extract_panjang_jalan(doc):
    p = find_table_page(doc, "10.1.1", "Panjang Jalan")
    rows = []
    for (kode, tahun), (nama, v) in sorted(parse_year_table(doc, p, 4).items()):
        rows.append({"kode_provinsi": kode, "provinsi": nama, "tahun": tahun,
                     "nasional_km": v[0], "provinsi_km": v[1],
                     "kabkota_km": v[2], "jumlah_km": v[3]})
    return rows


def extract_kendaraan(doc):
    p = find_table_page(doc, "10.1.2", "Kendaraan Bermotor")
    rows = []
    for (kode, tahun), (nama, v) in sorted(parse_year_table(doc, p, 5).items()):
        rows.append({"kode_provinsi": kode, "provinsi": nama, "tahun": tahun,
                     "mobil_penumpang": v[0], "bus": v[1], "mobil_barang": v[2],
                     "sepeda_motor": v[3], "jumlah": v[4]})
    return rows


def extract_lahan_sawah(doc):
    """Tabel 5.1.6: satu halaman, per provinsi 5 nilai (luas wilayah,
    lahan baku sawah 2019/2024, persentase 2019/2024)."""
    p = find_table_page(doc, "5.1.6", "Lahan Baku Sawah")
    lines = page_lines(doc, p)
    marker_idx = [i for i, ln in enumerate(lines) if MARKER.match(ln)]
    if len(marker_idx) != 6:
        raise RuntimeError("Struktur Tabel 5.1.6 tak terduga")
    rows, name, kode, values = [], None, None, []
    for ln in lines[marker_idx[-1] + 1:]:
        if STOPLINE.match(ln) or ln.startswith("5.1."):
            break
        if NUMERICISH.match(ln) or DASH.match(ln):
            if kode is None:
                continue
            values.append(num(ln))
            if len(values) == 5:
                rows.append({"kode_provinsi": kode, "provinsi": name,
                             "luas_wilayah_km2": values[0],
                             "lahan_sawah_2019_km2": values[1],
                             "lahan_sawah_2024_km2": values[2],
                             "persen_2019": values[3], "persen_2024": values[4]})
                name, kode, values = None, None, []
        else:
            name = clean_prov_name(ln)
            kode = PROV_KODE.get(name.upper())
            values = []
    return rows


def extract_all():
    doc = fitz.open(PDF_PATH)
    data = {
        "panjang_jalan_provinsi": extract_panjang_jalan(doc),
        "kendaraan_provinsi": extract_kendaraan(doc),
        "lahan_sawah_provinsi": extract_lahan_sawah(doc),
    }
    doc.close()
    return data


def load_mysql(data):
    import pymysql
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(os.path.dirname(PDF_PATH)), ".env"))
        load_dotenv()
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
    schema = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "schema_statistik_indonesia.sql")
    with conn:
        with conn.cursor() as cur:
            with open(schema, encoding="utf-8") as f:
                stmts = "\n".join(ln for ln in f
                                  if not ln.lstrip().startswith("--"))
            for stmt in [s.strip() for s in stmts.split(";") if s.strip()]:
                cur.execute(stmt)
            for r in data["panjang_jalan_provinsi"]:
                cur.execute(
                    """REPLACE INTO si_panjang_jalan_provinsi
                       (kode_provinsi, provinsi, tahun, nasional_km,
                        provinsi_km, kabkota_km, jumlah_km)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (r["kode_provinsi"], r["provinsi"], r["tahun"],
                     r["nasional_km"], r["provinsi_km"], r["kabkota_km"],
                     r["jumlah_km"]))
            for r in data["kendaraan_provinsi"]:
                cur.execute(
                    """REPLACE INTO si_kendaraan_provinsi
                       (kode_provinsi, provinsi, tahun, mobil_penumpang, bus,
                        mobil_barang, sepeda_motor, jumlah)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (r["kode_provinsi"], r["provinsi"], r["tahun"],
                     r["mobil_penumpang"], r["bus"], r["mobil_barang"],
                     r["sepeda_motor"], r["jumlah"]))
            for r in data["lahan_sawah_provinsi"]:
                cur.execute(
                    """REPLACE INTO si_lahan_sawah_provinsi
                       (kode_provinsi, provinsi, luas_wilayah_km2,
                        lahan_sawah_2019_km2, lahan_sawah_2024_km2,
                        persen_2019, persen_2024)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (r["kode_provinsi"], r["provinsi"], r["luas_wilayah_km2"],
                     r["lahan_sawah_2019_km2"], r["lahan_sawah_2024_km2"],
                     r["persen_2019"], r["persen_2024"]))
        conn.commit()
    print("Loaded ke MySQL:", {k: len(v) for k, v in data.items()},
          file=sys.stderr)


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
