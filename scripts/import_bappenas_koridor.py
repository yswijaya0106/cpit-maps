# -*- coding: utf-8 -*-
"""Import Daftar Koridor Bappenas Admin (docs/docs/Daftar_Koridor_Bappenas_
Admin_20260721141822.xlsx, sheet "Worksheet") -> MySQL, tabel
bappenas_koridor.

Granularitas KORIDOR (bukan ruas/usulan) -- lihat scripts/schema_bappenas_
koridor.sql utk dokumentasi kolom & kenapa kolom level-ruas di file sumber
(selalu "---") tidak diimpor. kode_kab dicari via pencocokan (provinsi,
kabupaten_kota) thd wilayah_mapping. Idempoten: REPLACE INTO per id_koridor.

Usage (venv aktif):
    python scripts/import_bappenas_koridor.py
    python scripts/import_bappenas_koridor.py path/ke/file.xlsx
"""

import os
import sys
from pathlib import Path

import openpyxl
import psycopg

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_XLSX = BASE_DIR / "docs" / "docs" / "Daftar_Koridor_Bappenas_Admin_20260721141822.xlsx"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_bappenas_koridor.sql"

DB_HOST = os.environ.get("PG_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("PG_PORT", "5432"))
DB_USER = os.environ.get("PG_USER", "postgres")
DB_PASS = os.environ.get("PG_PASS", "")
DB_NAME = os.environ.get("PG_DB", "route_gis")


def connect():
    return psycopg.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS, dbname=DB_NAME,
    )


def run_schema(conn):
    """Tabel sudah dibuat via scripts/migrate_pg_01_schema.py (lihat
    docs/migrasi_mysql_ke_postgresql.md) -- schema_bappenas_koridor.sql
    aslinya DDL MySQL, tidak bisa dieksekusi langsung ke PostgreSQL. Di
    sini cuma pastikan tabelnya benar-benar ada."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name='bappenas_koridor'"
        )
        if not cur.fetchone():
            raise RuntimeError(
                "Tabel bappenas_koridor belum ada di PostgreSQL -- jalankan "
                "scripts/migrate_pg_01_schema.py dulu."
            )


def _s(v):
    if v is None:
        return None
    v = str(v).strip()
    return v if v and v != "---" else None


def _num(v):
    if v is None or str(v).strip() in ("", "-", "---"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v):
    n = _num(v)
    return int(n) if n is not None else None


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_XLSX
    if not path.exists():
        sys.exit(f"File tidak ditemukan: {path}")

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["Worksheet"]
    rows = ws.iter_rows(values_only=True)
    header = next(rows)
    if not header or str(header[0]).strip() != "No.":
        sys.exit('Baris header "No." tidak ditemukan di baris pertama')

    out, skipped = [], 0
    for row in rows:
        if not row or row[1] is None:
            continue
        try:
            id_koridor = int(row[1])
        except (TypeError, ValueError):
            skipped += 1
            continue
        provinsi, kabkota = _s(row[2]), _s(row[3])
        out.append((
            id_koridor, provinsi, kabkota,
            _s(row[4]), _s(row[5]), _s(row[6]), _s(row[7]), _s(row[8]), _s(row[9]),
            _s(row[10]), _s(row[11]),
            _num(row[17]), _num(row[18]), _num(row[19]), _num(row[20]), _num(row[21]), _num(row[22]),
            _s(row[23]), _s(row[24]), _s(row[25]),
            _s(row[26]), _num(row[27]), _num(row[28]),
            _s(row[29]), _num(row[30]), _num(row[31]),
            _s(row[32]), _num(row[33]), _num(row[34]),
            _s(row[35]), _num(row[36]), _num(row[37]),
            _s(row[38]), _s(row[39]), _s(row[40]),
            _int(row[41]), _int(row[42]), _int(row[43]), _int(row[44]),
            _s(row[45]), _s(row[49]),
            _int(row[47]), _int(row[48]), _s(row[51]),
            _num(row[52]), _num(row[53]), _num(row[54]), _num(row[55]), _num(row[56]),
            _s(row[57]), _int(row[58]), _s(row[59]), _int(row[60]), _s(row[61]),
        ))

    conn = connect()
    try:
        run_schema(conn)
        with conn.cursor() as cur:
            # (provinsi,kabupaten_kota) -> kode_kabupaten, dipetakan sekali di
            # sini (bukan JOIN per-row) -- pola sama dgn ctx-batch di app.py
            cur.execute("SELECT provinsi_sitia, kabupaten_kota_sitia, kode_kabupaten FROM wilayah_mapping")
            kab_by_wilayah = {(r[0], r[1]): r[2] for r in cur.fetchall()}
            not_matched = set()
            rows_with_kode = []
            for r in out:
                kode_kab = kab_by_wilayah.get((r[1], r[2]))
                if kode_kab is None and r[1] and r[2]:
                    not_matched.add((r[1], r[2]))
                rows_with_kode.append(r[:3] + (f"{kode_kab:04d}" if kode_kab else None,) + r[3:])

            kolom = [
                "id_koridor", "provinsi", "kabupaten_kota", "kode_kab", "no_koridor", "nama_koridor",
                "rpjmn", "tematik", "kspp", "jenis_produksi", "status_pengajuan", "disetujui_ditolak_oleh",
                "panjang_km", "baik_km", "sedang_km", "rusak_ringan_km", "rusak_berat_km", "biaya_rp_miliar",
                "tematik_utama", "tematik_tambahan_1", "tematik_tambahan_2",
                "jenis_produksi_1", "luas_lahan_1_ha", "jumlah_produksi_1_ton",
                "jenis_produksi_2", "luas_lahan_2_ha", "jumlah_produksi_2_ton",
                "jenis_produksi_3", "luas_lahan_3_ha", "jumlah_produksi_3_ton",
                "jenis_produksi_4", "luas_lahan_4_ha", "jumlah_produksi_4_ton",
                "konektivitas_simpul_transportasi", "konektivitas_pusat_kegiatan", "konektivitas_koridor_lain",
                "fasilitas_pendidikan", "fasilitas_kesehatan", "fasilitas_pemerintahan", "fasilitas_sppg",
                "map_koridor", "map_awal_koridor", "prioritas_kabupaten_kota", "prioritas_provinsi", "koridor_awal",
                "panjang_kml_km", "baik_kml_km", "sedang_kml_km", "rusak_ringan_kml_km", "rusak_berat_kml_km",
                "beririsan_hari_jalan", "tahun_hari_jalan", "beririsan_diskresi_menteri", "tahun_diskresi_menteri",
                "beririsan_rujj",
            ]
            # PostgreSQL tidak punya REPLACE INTO (MySQL) -- INSERT ... ON
            # CONFLICT (id_koridor) DO UPDATE SET semua kolom selain PK,
            # setara delete+insert REPLACE INTO utk kasus ini (tidak ada
            # kolom lain yg bergantung ON DELETE CASCADE dari tabel ini).
            update_cols = ", ".join(f"{c}=EXCLUDED.{c}" for c in kolom if c != "id_koridor")
            cur.executemany(
                f"INSERT INTO bappenas_koridor ({', '.join(kolom)}) VALUES ("
                + ",".join(["%s"] * len(kolom)) + ") "
                f"ON CONFLICT (id_koridor) DO UPDATE SET {update_cols}",
                rows_with_kode,
            )
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM bappenas_koridor")
            total = cur.fetchone()[0]
    finally:
        conn.close()

    print(f"Import koridor Bappenas: {len(out)} baris diproses ({skipped} dilewati), total di DB: {total}")
    print(f"kode_kab tidak match wilayah_mapping: {len(not_matched)} pasangan provinsi/kab-kota unik")


if __name__ == "__main__":
    main()
