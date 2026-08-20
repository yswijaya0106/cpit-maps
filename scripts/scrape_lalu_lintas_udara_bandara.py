# -*- coding: utf-8 -*-
"""Scrape statistik lalu lintas udara bulanan per bandara (pesawat/
penumpang/kargo/bagasi/pos, Datang & Berangkat) dari situs resmi Ditjen
Perhubungan Udara Kemenhub
(https://hubud.kemenhub.go.id/lalu-lintas?bandara=<kode>&period=<YYYY-MM>
&category=domestik|internasional) untuk SEMUA bandara di dropdown situs,
simpan ke tabel lalu_lintas_udara_bandara. Lihat
scripts/schema_lalu_lintas_udara_bandara.sql. TIDAK terkait
usulan_inpres/IJD.

Bukan file lokal (xlsx/PDF) spt import_*.py lain -- ini live scraping,
server-rendered HTML, diparsing dgn BeautifulSoup. Sopan ke server: 1
request per REQUEST_DELAY detik, User-Agent jelas.

Skala default (semua bandara x Jan-Agu 2026 x domestik+internasional)
besar (~240 bandara x 8 bulan x 2 kategori = ~3.840 request) -- perkiraan
puluhan menit jalan. Idempotent: UPSERT per (kode_bandara, periode,
kategori), aman dijalankan ulang/parsial (mis. --bandara utk 1 bandara
saja, atau --bulan-mulai/--bulan-akhir utk rentang lebih sempit).

Usage (venv aktif):
    python scripts/scrape_lalu_lintas_udara_bandara.py                       # semua bandara, Jan-Agu 2026, kedua kategori
    python scripts/scrape_lalu_lintas_udara_bandara.py --bandara MLG,CGK
    python scripts/scrape_lalu_lintas_udara_bandara.py --tahun 2026 --bulan-mulai 1 --bulan-akhir 8
    python scripts/scrape_lalu_lintas_udara_bandara.py --kategori domestik  # cuma 1 kategori
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

BASE_URL = "https://hubud.kemenhub.go.id/lalu-lintas"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; analytic-maps/1.0; data referensi Ditjen Hubud)"}
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_lalu_lintas_udara_bandara.sql"
REQUEST_DELAY = 0.4
REQUEST_TIMEOUT = 20

ROW_LABEL_TO_COL = {
    "Pesawat": "pesawat",
    "Penumpang": "penumpang",
    "Penumpang Transit": "penumpang_transit",
    "Kargo (kg)": "kargo_kg",
    "Bagasi (kg)": "bagasi_kg",
    "Pos (kg)": "pos_kg",
}


def _fetch(params):
    resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def _parse_airport_list(html):
    soup = BeautifulSoup(html, "html.parser")
    select = soup.find("select", attrs={"name": "bandara"})
    if not select:
        return []
    out = []
    for opt in select.find_all("option"):
        kode = (opt.get("value") or "").strip()
        if not kode:
            continue
        label = opt.get_text(strip=True)
        nama = label.split(" - ", 1)[1].strip() if " - " in label else label
        out.append((kode, nama))
    return out


def _num(text):
    text = (text or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _parse_traffic_table(html):
    soup = BeautifulSoup(html, "html.parser")
    target = None
    for table in soup.find_all("table"):
        ths = [th.get_text(strip=True) for th in table.select("thead th")]
        if "Datang" in ths and "Berangkat" in ths:
            target = table
            break
    if not target:
        return None
    data = {}
    for tr in target.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue
        label = tds[0].get_text(strip=True)
        col = ROW_LABEL_TO_COL.get(label)
        if not col:
            continue
        data[f"{col}_datang"] = _num(tds[1].get_text())
        data[f"{col}_berangkat"] = _num(tds[2].get_text())
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bandara", help="daftar kode bandara dipisah koma (default: semua dari dropdown situs)")
    ap.add_argument("--tahun", type=int, default=2026)
    ap.add_argument("--bulan-mulai", type=int, default=1)
    ap.add_argument("--bulan-akhir", type=int, default=8)
    ap.add_argument("--kategori", choices=["domestik", "internasional", "semua"], default="semua")
    args = ap.parse_args()

    with pg_cursor() as cur:
        cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

    print("Mengambil daftar bandara dari dropdown situs...")
    html = _fetch({"bandara": "CGK", "period": f"{args.tahun}-01", "category": "domestik"})
    airports = _parse_airport_list(html)
    time.sleep(REQUEST_DELAY)
    if args.bandara:
        wanted = {k.strip().upper() for k in args.bandara.split(",")}
        airports = [(k, n) for k, n in airports if k in wanted]
    print(f"{len(airports)} bandara akan di-scrape.\n")

    kategoris = ["domestik", "internasional"] if args.kategori == "semua" else [args.kategori]
    bulan_list = list(range(args.bulan_mulai, args.bulan_akhir + 1))
    total_jobs = len(airports) * len(bulan_list) * len(kategoris)
    print(f"Total {total_jobs} kombinasi (bandara x bulan x kategori) akan diambil.\n")

    saved = 0
    job_i = 0
    for kode, nama in airports:
        for bulan in bulan_list:
            periode = f"{args.tahun}-{bulan:02d}"
            for kategori in kategoris:
                job_i += 1
                if job_i % 20 == 0 or job_i == 1:
                    print(f"[{job_i}/{total_jobs}] {kode} {periode} {kategori}...")
                try:
                    html = _fetch({"bandara": kode, "period": periode, "category": kategori})
                    data = _parse_traffic_table(html)
                except requests.RequestException as e:
                    print(f"  GAGAL {kode} {periode} {kategori}: {e}")
                    data = None
                time.sleep(REQUEST_DELAY)

                if not data:
                    continue

                with pg_cursor() as cur:
                    cur.execute(
                        """INSERT INTO lalu_lintas_udara_bandara
                               (kode_bandara, nama_bandara, periode, kategori,
                                pesawat_datang, pesawat_berangkat,
                                penumpang_datang, penumpang_berangkat,
                                penumpang_transit_datang, penumpang_transit_berangkat,
                                kargo_kg_datang, kargo_kg_berangkat,
                                bagasi_kg_datang, bagasi_kg_berangkat,
                                pos_kg_datang, pos_kg_berangkat)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                           ON CONFLICT (kode_bandara, periode, kategori) DO UPDATE SET
                               nama_bandara=EXCLUDED.nama_bandara,
                               pesawat_datang=EXCLUDED.pesawat_datang,
                               pesawat_berangkat=EXCLUDED.pesawat_berangkat,
                               penumpang_datang=EXCLUDED.penumpang_datang,
                               penumpang_berangkat=EXCLUDED.penumpang_berangkat,
                               penumpang_transit_datang=EXCLUDED.penumpang_transit_datang,
                               penumpang_transit_berangkat=EXCLUDED.penumpang_transit_berangkat,
                               kargo_kg_datang=EXCLUDED.kargo_kg_datang,
                               kargo_kg_berangkat=EXCLUDED.kargo_kg_berangkat,
                               bagasi_kg_datang=EXCLUDED.bagasi_kg_datang,
                               bagasi_kg_berangkat=EXCLUDED.bagasi_kg_berangkat,
                               pos_kg_datang=EXCLUDED.pos_kg_datang,
                               pos_kg_berangkat=EXCLUDED.pos_kg_berangkat,
                               scraped_at=now()""",
                        (
                            kode, nama, f"{periode}-01", kategori,
                            data.get("pesawat_datang"), data.get("pesawat_berangkat"),
                            data.get("penumpang_datang"), data.get("penumpang_berangkat"),
                            data.get("penumpang_transit_datang"), data.get("penumpang_transit_berangkat"),
                            data.get("kargo_kg_datang"), data.get("kargo_kg_berangkat"),
                            data.get("bagasi_kg_datang"), data.get("bagasi_kg_berangkat"),
                            data.get("pos_kg_datang"), data.get("pos_kg_berangkat"),
                        ),
                    )
                saved += 1

    print(f"\nSelesai: {saved}/{total_jobs} baris di-upsert ke lalu_lintas_udara_bandara.")


if __name__ == "__main__":
    main()
