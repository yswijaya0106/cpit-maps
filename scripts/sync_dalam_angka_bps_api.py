# -*- coding: utf-8 -*-
"""Sinkronisasi katalog link publikasi "X Dalam Angka <tahun>" dari BPS Web
API (webapi.bps.go.id) -> tabel dalam_angka_publikasi (lihat
schema_dalam_angka_publikasi.sql).

Tujuan: server production/staging tidak perlu menyimpan 9GB PDF
dalam_angka/ -- cukup link ke halaman publikasi resmi BPS (permanen),
diambil live dari API BPS sendiri.

DINAMIS TIAP TAHUN by design: script ini tidak hardcode tahun mana pun --
tiap dijalankan, dia tanya API "publikasi apa saja utk wilayah X dengan
kata kunci 'Dalam Angka'" dan upsert semua yang ketemu (kunci unik
kode_wilayah+tahun). Begitu BPS terbitkan edisi tahun baru, run ulang
script ini otomatis menambah baris baru tanpa perlu ubah kode. Jadwalkan
via cron (mis. tiap awal tahun) atau jalankan manual kapan saja.

Butuh API key gratis dari https://webapi.bps.go.id (daftar sendiri,
1 akun 1 key) -- lewat env var BPS_API_KEY.

Usage (venv aktif):
    BPS_API_KEY=xxxxx python scripts/sync_dalam_angka_bps_api.py
    BPS_API_KEY=xxxxx python scripts/sync_dalam_angka_bps_api.py --kode-wilayah 1101
    BPS_API_KEY=xxxxx python scripts/sync_dalam_angka_bps_api.py --dry-run
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

import psycopg
import requests
from psycopg.rows import dict_row

SCHEMA_PATH = Path(__file__).resolve().parent / "schema_dalam_angka_publikasi.sql"

DB_HOST = os.environ.get("PG_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("PG_PORT", "5432"))
DB_USER = os.environ.get("PG_USER", "postgres")
DB_PASS = os.environ.get("PG_PASS", "")
DB_NAME = os.environ.get("PG_DB", "route_gis")

BPS_API_KEY = os.environ.get("BPS_API_KEY", "")
BPS_API_BASE = "https://webapi.bps.go.id/v1/api/list"

# Judul publikasi berpola "<Nama Wilayah> Dalam Angka <tahun>" -- kadang
# ada akhiran subjudul (mis. "... Dalam Angka 2026: Penyediaan Data ...")
# jadi cari tahun 4-digit setelah frasa "dalam angka", bukan akhir string.
# WAJIB diawali Kabupaten/Kota/Provinsi -- API juga mengembalikan seri
# "Kecamatan X Dalam Angka <tahun>" (level kecamatan, publikasi TERPISAH,
# bukan yg dicari) yang kalau lolos filter akan bentrok kunci unik
# (kode_wilayah, tahun) dgn kabupaten/kota induknya lewat ON CONFLICT --
# ditemukan 24 Jul 2026 saat pilot Kab. Simeulue (30 hasil, cuma 3 yang
# benar levelnya).
_RE_TAHUN = re.compile(
    r"^(?:Kabupaten|Kota|Provinsi)\s+.+\s+dalam angka\s+(\d{4})", re.IGNORECASE
)


def connect():
    return psycopg.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS,
        dbname=DB_NAME, row_factory=dict_row,
    )


def run_schema(conn):
    """Tabel BARU (bukan hasil migrasi MySQL) -- buat langsung native
    Postgres kalau belum ada, bukan lewat migrate_pg_01_schema.py."""
    sql_text = SCHEMA_PATH.read_text(encoding="utf-8")
    code = "\n".join(l for l in sql_text.splitlines() if not l.strip().startswith("--"))
    with conn.cursor() as cur:
        for stmt in [s.strip() for s in code.split(";") if s.strip()]:
            cur.execute(stmt)
    conn.commit()


def fetch_publikasi(domain_code: str, keyword: str = "dalam angka", page: int = 1):
    """Satu halaman hasil BPS Web API model=publication utk domain (kode
    wilayah BPS) tertentu. domain_code '0000' = nasional; kode provinsi 2
    digit atau kab/kota 4 digit utk wilayah spesifik. Response asli
    (dikonfirmasi 24 Jul 2026 dgn key aktif): data[0] = metadata paginasi
    (page/pages/per_page/count/total), data[1] = list publikasi dgn field
    pub_id/title/sch_date/rl_date/updt_date/cover/pdf/size/abstract --
    TIDAK ada field nama wilayah terpisah, judul saja."""
    params = {
        "model": "publication",
        "lang": "ind",
        "domain": domain_code,
        "keyword": keyword,
        "page": page,
        "key": BPS_API_KEY,
    }
    r = requests.get(BPS_API_BASE, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "OK":
        raise RuntimeError(f"BPS API error utk domain {domain_code}: {data}")
    payload = data.get("data", [])
    meta = payload[0] if payload else {}
    items = payload[1] if len(payload) > 1 else []
    return items, meta


def fetch_fresh_pdf_url(pub_id: str, domain_code: str) -> Optional[str]:
    """Regenerasi link download.php?f=<token> segar dari pub_id -- dipakai
    kalau url_publikasi tersimpan sudah kedaluwarsa (lihat catatan di
    schema_dalam_angka_publikasi.sql). Bisa dipanggil live dari endpoint
    app.py juga (bukan cuma dari script sync ini). domain WAJIB diisi --
    API menolak query by id tanpa domain ("Parameter Domain is Missing"),
    ditemukan 24 Jul 2026 saat verifikasi pilot."""
    params = {"model": "publication", "lang": "ind", "domain": domain_code,
              "id": pub_id, "key": BPS_API_KEY}
    r = requests.get(BPS_API_BASE, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    payload = data.get("data", [])
    items = payload[1] if len(payload) > 1 else []
    # "id" tidak benar-benar memfilter di sisi BPS -- balikannya listing
    # default domain tsb (terbaru dulu), jadi items[0] bisa jadi publikasi
    # lain sama sekali. Cocokkan eksplisit ke pub_id yang diminta.
    for item in items:
        if str(item.get("pub_id")) == str(pub_id):
            return item.get("pdf")
    return None


def parse_row(kode_wilayah: int, jenis: str, item: dict):
    judul = item.get("title", "")
    m = _RE_TAHUN.search(judul)
    if not m:
        return None  # bukan "X Dalam Angka <tahun>" (bisa publikasi lain yg kebetulan kena keyword)
    tahun = int(m.group(1))
    pub_id = str(item.get("pub_id") or "") or None
    # Tidak ada field nama-wilayah terpisah di response -- derive dari
    # judul dgn membuang ekor " Dalam Angka <tahun>..." (bukan pakai
    # m.start(), regex skrg diawali ^ jadi start selalu 0).
    nama_wilayah = re.split(r"\s+dalam angka\s+", judul, flags=re.IGNORECASE)[0].strip()
    return {
        "kode_wilayah": kode_wilayah,
        "jenis_wilayah": jenis,
        "nama_wilayah": nama_wilayah,
        "tahun": tahun,
        "pub_id": pub_id,
        "judul": judul,
        "url_publikasi": item.get("pdf") or "",
        "tanggal_terbit": item.get("rl_date") or item.get("sch_date") or None,
    }


# Publikasi tahunan baru biasanya nongol di halaman awal (diasumsikan
# terurut terbaru dulu) -- dibatasi MAX_PAGES supaya tidak menghabiskan
# rate limit API cuma utk menyisir ratusan publikasi tak relevan yang
# kebetulan kena keyword bebas "dalam angka" (tercatat 17 halaman/164
# hasil utk 1 kab/kota, mayoritas bukan publikasi tahunan yang dicari).
MAX_PAGES = 3


def sync_wilayah(conn, kode_wilayah: int, jenis: str, dry_run: bool):
    # Domain provinsi WAJIB 4 digit ("3600", bukan "36") -- endpoint
    # publication BPS API 404 kalau dikirim 2 digit (beda dari endpoint
    # var/data yang menerima 2 digit utk provinsi, ditemukan 24 Jul 2026).
    domain_code = f"{kode_wilayah:02d}00" if jenis == "PROVINSI" else f"{kode_wilayah:04d}"
    rows = []
    for page in range(1, MAX_PAGES + 1):
        items, meta = fetch_publikasi(domain_code, page=page)
        rows += [r for r in (parse_row(kode_wilayah, jenis, it) for it in items) if r]
        if page >= int(meta.get("pages", 1) or 1):
            break
    if dry_run:
        for r in rows:
            print(f"  [DRY-RUN] {kode_wilayah} {jenis}: {r['judul']} -> {r['url_publikasi']}")
        return len(rows)
    if rows:
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    "INSERT INTO dalam_angka_publikasi "
                    "(kode_wilayah, jenis_wilayah, nama_wilayah, tahun, pub_id, judul, "
                    "url_publikasi, tanggal_terbit) "
                    "VALUES (%(kode_wilayah)s, %(jenis_wilayah)s, %(nama_wilayah)s, %(tahun)s, "
                    "%(pub_id)s, %(judul)s, %(url_publikasi)s, %(tanggal_terbit)s) "
                    "ON CONFLICT (kode_wilayah, tahun) DO UPDATE SET "
                    "nama_wilayah=EXCLUDED.nama_wilayah, pub_id=EXCLUDED.pub_id, "
                    "judul=EXCLUDED.judul, url_publikasi=EXCLUDED.url_publikasi, "
                    "tanggal_terbit=EXCLUDED.tanggal_terbit, disinkron_at=now()",
                    r,
                )
        conn.commit()
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kode-wilayah", type=int, default=None,
                     help="hanya sinkron 1 kode wilayah (provinsi 2 digit / kab-kota 4 digit)")
    ap.add_argument("--dry-run", action="store_true", help="tampilkan hasil tanpa tulis ke DB")
    args = ap.parse_args()

    if not BPS_API_KEY:
        sys.exit("BPS_API_KEY belum diset -- daftar gratis di https://webapi.bps.go.id "
                  "lalu: BPS_API_KEY=xxxxx python scripts/sync_dalam_angka_bps_api.py")

    conn = connect()
    try:
        run_schema(conn)
        with conn.cursor() as cur:
            if args.kode_wilayah:
                jenis = "PROVINSI" if args.kode_wilayah < 100 else "KABUPATEN_KOTA"
                wilayah = [(args.kode_wilayah, jenis)]
            else:
                cur.execute(
                    "SELECT DISTINCT kode_provinsi AS kode, 'PROVINSI' AS jenis FROM penduduk_kecamatan "
                    "UNION SELECT DISTINCT kode_kabupaten AS kode, 'KABUPATEN_KOTA' AS jenis FROM penduduk_kecamatan "
                    "ORDER BY 1"
                )
                # row_factory=dict_row (lihat connect()) -- fetchall() balikin
                # list of dict, BUKAN tuple. Bug ditemukan 24 Jul 2026: versi
                # lama unpack langsung "for k, j in wilayah" jadi keliru
                # unpack KEYS dict (string), bukan value -- semua 550+ wilayah
                # gagal diam-diam ("Unknown format code 'd' for object of
                # type 'str'") krn kode_wilayah jadi string nama kolom.
                wilayah = [(w["kode"], w["jenis"]) for w in cur.fetchall()]

        total = 0
        for kode_wilayah, jenis in wilayah:
            try:
                n = sync_wilayah(conn, kode_wilayah, jenis, args.dry_run)
                total += n
                print(f"{kode_wilayah} ({jenis}): {n} publikasi 'Dalam Angka' ditemukan")
            except Exception as e:
                print(f"  GAGAL {kode_wilayah}: {e}", file=sys.stderr)
            time.sleep(0.3)  # sopan ke rate limit API BPS

        print(f"\nTotal: {total} baris publikasi disinkron"
              f"{' (dry-run, tidak ditulis ke DB)' if args.dry_run else ''}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
