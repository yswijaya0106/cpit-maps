# -*- coding: utf-8 -*-
"""Scrape daftar maskapai dari situs resmi Ditjen Perhubungan Udara Kemenhub
(https://hubud.kemenhub.go.id/maskapai-organisasi), kedua kategori: "Maskapai
Dalam Negeri" (param page_negeri, kode 121-xxx/135-xxx/AOC-xxx) dan "Maskapai
Asing" (param page_asing, kode 129-xxx) + halaman detail tiap maskapai,
simpan ke tabel maskapai_organisasi. Lihat
scripts/schema_maskapai_organisasi.sql. TIDAK terkait usulan_inpres/IJD.

Bukan file lokal (xlsx/PDF) spt import_*.py lain -- ini live scraping,
server-rendered HTML (bukan SPA/JS-rendered), diparsing dgn BeautifulSoup.
Sopan ke server: 1 request per REQUEST_DELAY detik, User-Agent jelas.

Idempotent: UPSERT per kode_organisasi (ON CONFLICT DO UPDATE), aman
dijalankan ulang -- jalankan lagi kapan saja utk menyegarkan data.

Usage (venv aktif):
    python scripts/scrape_maskapai_organisasi.py                    # negeri (1-11) + asing (1-6)
    python scripts/scrape_maskapai_organisasi.py --kategori negeri  # cuma satu kategori
    python scripts/scrape_maskapai_organisasi.py --kategori asing --max-page 6
"""
import argparse
import io
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import requests
from bs4 import BeautifulSoup

from db import db_cursor as pg_cursor  # noqa: E402

BASE_URL = "https://hubud.kemenhub.go.id/maskapai-organisasi"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; analytic-maps/1.0; data referensi Ditjen Hubud)"}
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_maskapai_organisasi.sql"
REQUEST_DELAY = 0.4
REQUEST_TIMEOUT = 20

# kategori -> (param query, id kontainer div, default halaman terakhir)
KATEGORI = {
    "negeri": ("page_negeri", "content-maskapai-negeri", 11),
    "asing": ("page_asing", "content-maskapai-asing", 6),
}


def _clean_text(v):
    if v is None:
        return None
    v = re.sub(r"\s+,", ",", v)
    v = re.sub(r"\s+", " ", v).strip()
    return v or None


def _fetch(url, params=None):
    resp = requests.get(url, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def _parse_listing(html, container_id):
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find(id=container_id)
    if not container:
        return []
    rows = []
    for tr in container.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        kode = _clean_text(tds[0].get_text())
        nama = _clean_text(tds[1].get_text())
        telepon = _clean_text(tds[2].get_text())
        a = tds[3].find("a")
        detail_url = a["href"] if a and a.get("href") else None
        if kode and detail_url:
            rows.append((kode, nama, telepon, detail_url))
    return rows


def _parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    dl = soup.find("dl")
    data = {}
    if not dl:
        return data
    for dt in dl.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if not dd:
            continue
        label = _clean_text(dt.get_text())
        value = _clean_text(dd.get_text(" "))
        if label:
            data[label] = value
    return data


def _scrape_kategori(kategori, max_page):
    param_name, container_id, _ = KATEGORI[kategori]
    listing_rows = []
    for page in range(1, max_page + 1):
        print(f"[{kategori}] Mengambil daftar halaman {page}/{max_page}...")
        params = {param_name: page} if page > 1 else None
        html = _fetch(BASE_URL, params=params)
        rows = _parse_listing(html, container_id)
        if not rows:
            print(f"  (kosong, berhenti di halaman {page})")
            break
        listing_rows.extend(rows)
        time.sleep(REQUEST_DELAY)
    print(f"[{kategori}] Total {len(listing_rows)} maskapai ditemukan di daftar.\n")

    saved = 0
    for i, (kode, nama, telepon_listing, detail_url) in enumerate(listing_rows, start=1):
        print(f"[{kategori} {i}/{len(listing_rows)}] {kode} {nama}...")
        try:
            detail_html = _fetch(detail_url)
            detail = _parse_detail(detail_html)
        except requests.RequestException as e:
            print(f"  GAGAL ambil detail: {e}")
            detail = {}
        time.sleep(REQUEST_DELAY)

        with pg_cursor() as cur:
            cur.execute(
                """INSERT INTO maskapai_organisasi
                       (kode_organisasi, kategori, nama_maskapai, telepon_listing, nama_perusahaan,
                        dba_name, alamat_perusahaan, telepon, fax, email,
                        perpanjangan_terakhir_sertifikat, status_operasi, detail_url)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (kode_organisasi) DO UPDATE SET
                       kategori=EXCLUDED.kategori,
                       nama_maskapai=EXCLUDED.nama_maskapai,
                       telepon_listing=EXCLUDED.telepon_listing,
                       nama_perusahaan=EXCLUDED.nama_perusahaan,
                       dba_name=EXCLUDED.dba_name,
                       alamat_perusahaan=EXCLUDED.alamat_perusahaan,
                       telepon=EXCLUDED.telepon, fax=EXCLUDED.fax, email=EXCLUDED.email,
                       perpanjangan_terakhir_sertifikat=EXCLUDED.perpanjangan_terakhir_sertifikat,
                       status_operasi=EXCLUDED.status_operasi,
                       detail_url=EXCLUDED.detail_url, scraped_at=now()""",
                (
                    kode, kategori, nama, telepon_listing,
                    detail.get("Nama Perusahaan"),
                    detail.get("Doing Business as (Dba. Name)"),
                    detail.get("Alamat Perusahaan"),
                    detail.get("Nomor Telepon"),
                    detail.get("Fax"),
                    detail.get("Alamat Email"),
                    detail.get("Perpanjangan Terakhir Sertifikat"),
                    detail.get("Status Operasi"),
                    detail_url,
                ),
            )
        saved += 1

    return saved


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kategori", choices=["negeri", "asing", "semua"], default="semua",
                     help="default: semua (negeri + asing)")
    ap.add_argument("--max-page", type=int, default=None,
                     help="override halaman terakhir (default per kategori: negeri=11, asing=6)")
    args = ap.parse_args()

    with pg_cursor() as cur:
        cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

    kategoris = ["negeri", "asing"] if args.kategori == "semua" else [args.kategori]
    total_saved = 0
    for kat in kategoris:
        max_page = args.max_page if args.max_page is not None else KATEGORI[kat][2]
        total_saved += _scrape_kategori(kat, max_page)

    print(f"\nSelesai: {total_saved} maskapai di-upsert ke maskapai_organisasi.")


if __name__ == "__main__":
    main()
