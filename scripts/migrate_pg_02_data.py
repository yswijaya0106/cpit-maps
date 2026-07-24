# -*- coding: utf-8 -*-
"""Fase 2 migrasi MySQL -> PostgreSQL: salin DATA (skema sudah dibuat oleh
scripts/migrate_pg_01_schema.py). Baca dari MySQL per tabel (streaming,
tidak load semua ke memori sekaligus utk tabel besar), tulis ke Postgres
pakai COPY (jauh lebih cepat drpd INSERT satu-satu).

Konversi nilai per baris:
  - kolom BOOLEAN (asalnya tinyint(1)) -> Python bool
  - kolom JSONB -> string JSON apa adanya (psycopg terima str utk jsonb)
  - Decimal/None -> apa adanya (psycopg tangani otomatis)

Setelah COPY, sequence identity (utk tabel yg py auto-increment) di-reset
ke MAX(id)+1 supaya INSERT berikutnya (dari aplikasi, pasca-migrasi) tidak
tabrakan dgn id yg baru disalin.

Pemakaian:
    python scripts/migrate_pg_02_data.py --only ref_province,wilayah_mapping
    python scripts/migrate_pg_02_data.py                      # semua tabel
    python scripts/migrate_pg_02_data.py --verify-only         # cuma bandingkan row count, tanpa copy
"""
import argparse
import json
import os
import sys
from decimal import Decimal

import psycopg
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import db_cursor  # noqa: E402

load_dotenv()

PG_DSN = dict(
    host=os.getenv("PG_HOST"), port=int(os.getenv("PG_PORT", 5432)),
    user=os.getenv("PG_USER"), password=os.getenv("PG_PASS"),
    dbname=os.getenv("PG_DB"),
)

# Urutan dependency-safe (kasar): tabel referensi/kecil dulu, tabel besar &
# yang mereferensikan usulan_inpres belakangan -- bukan foreign key formal
# (app.py tidak pakai FK constraint), tapi urutan ini bikin verifikasi
# bertahap lebih masuk akal (tabel besar terakhir, gagalnya lebih cepat
# ketauan di tabel kecil dulu).
TABLE_ORDER = [
    "ref_province", "ijd_scoring_rules", "wilayah_mapping",
    "si_kendaraan_provinsi", "si_lahan_sawah_provinsi", "si_panjang_jalan_provinsi",
    "bps_kabupaten_indeks_penanaman", "bps_kabupaten_indeks_penanaman_raster",
    "bps_kabupaten_jalan", "bps_kabupaten_kendaraan", "bps_kabupaten_padi",
    "kemantapan_ijd_2026", "konektivitas_jaringan_jalan", "dpp_ijd_2025",
    "kawasan_tematik", "bappenas_koridor", "bappenas_lokus_a",
    "penduduk_kecamatan", "bps_kecamatan_demografi",
    "kecamatan_data_turunan", "bps_kecamatan_potensi_tematik",
    "simpul_transportasi", "simpul_transportasi_kecamatan_radius",
    "usulan_inpres", "usulan_dokumen", "usulan_kecamatan_dilalui",
    "usulan_konektivitas_jalan", "penilaian_bappenas_ai",
    "bps_kecamatan_produksi_komoditas",
]


def _get_pg_column_types(pg_conn, table: str) -> dict:
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
            (table,),
        )
        return {r[0]: r[1] for r in cur.fetchall()}


def _get_identity_col(pg_conn, table: str) -> str | None:
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s AND is_identity='YES'",
            (table,),
        )
        r = cur.fetchone()
        return r[0] if r else None


def _convert_row(row: dict, columns: list, pg_types: dict) -> list:
    out = []
    for col in columns:
        v = row.get(col)
        pg_t = pg_types.get(col)
        if v is None:
            out.append(None)
        elif pg_t == "boolean":
            out.append(bool(v))
        elif pg_t == "jsonb":
            out.append(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
        elif isinstance(v, Decimal):
            out.append(v)
        else:
            out.append(v)
    return out


def migrate_table(table: str, batch_size: int = 5000) -> tuple:
    pg_conn = psycopg.connect(**PG_DSN, autocommit=False)
    try:
        pg_types = _get_pg_column_types(pg_conn, table)
        columns = list(pg_types.keys())
        col_list_sql = ", ".join(f'"{c}"' for c in columns)

        with pg_conn.cursor() as cur:
            cur.execute(f'TRUNCATE TABLE "{table}" CASCADE')  # idempoten -- aman dijalankan ulang per tabel

        total = 0
        with db_cursor() as mysql_cur:
            mysql_cur.execute(f"SELECT {', '.join(f'`{c}`' for c in columns)} FROM `{table}`")
            with pg_conn.cursor() as pg_cur:
                with pg_cur.copy(f'COPY "{table}" ({col_list_sql}) FROM STDIN') as copy:
                    while True:
                        rows = mysql_cur.fetchmany(batch_size)
                        if not rows:
                            break
                        for row in rows:
                            copy.write_row(_convert_row(row, columns, pg_types))
                        total += len(rows)

        identity_col = _get_identity_col(pg_conn, table)
        if identity_col:
            with pg_conn.cursor() as cur:
                cur.execute(
                    f'SELECT setval(pg_get_serial_sequence(%s, %s), '
                    f'COALESCE((SELECT MAX("{identity_col}") FROM "{table}"), 1), '
                    f'(SELECT MAX("{identity_col}") FROM "{table}") IS NOT NULL)',
                    (table, identity_col),
                )
        pg_conn.commit()
        return total, None
    except Exception as e:
        pg_conn.rollback()
        return 0, str(e)
    finally:
        pg_conn.close()


def row_counts(table: str) -> tuple:
    with db_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS n FROM `{table}`")
        mysql_n = cur.fetchone()["n"]
    pg_conn = psycopg.connect(**PG_DSN)
    with pg_conn.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) FROM "{table}"')
        pg_n = cur.fetchone()[0]
    pg_conn.close()
    return mysql_n, pg_n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="daftar tabel dipisah koma")
    ap.add_argument("--verify-only", action="store_true", help="cuma bandingkan row count, tanpa copy data")
    args = ap.parse_args()

    tables = TABLE_ORDER
    if args.only:
        wanted = set(args.only.split(","))
        tables = [t for t in tables if t in wanted]

    if args.verify_only:
        print(f"{'Tabel':45s} {'MySQL':>10s} {'Postgres':>10s} {'Status':>8s}")
        for t in tables:
            m, p = row_counts(t)
            status = "OK" if m == p else "BEDA"
            print(f"{t:45s} {m:10d} {p:10d} {status:>8s}")
        return

    print(f"Migrasi {len(tables)} tabel...", file=sys.stderr)
    results = []
    for t in tables:
        n, err = migrate_table(t)
        if err:
            print(f"  FAIL  {t}: {err}", file=sys.stderr)
            results.append((t, 0, err))
            continue
        mysql_n, pg_n = row_counts(t)
        status = "OK" if mysql_n == pg_n else "MISMATCH"
        print(f"  {status:8s} {t}: {n} baris disalin, MySQL={mysql_n} Postgres={pg_n}", file=sys.stderr)
        results.append((t, n, None if mysql_n == pg_n else f"row count MySQL={mysql_n} != Postgres={pg_n}"))

    failed = [r for r in results if r[2]]
    print(f"\nSelesai: {len(results) - len(failed)}/{len(results)} tabel cocok.", file=sys.stderr)
    if failed:
        print("Bermasalah:", failed, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
