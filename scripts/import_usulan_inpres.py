"""Import docs/usulan_inpres_20260706114127.xlsx into MySQL (route_gis).

Usage (venv aktif):
    python scripts/import_usulan_inpres.py

Membaca skema dari scripts/schema_usulan_inpres.sql, lalu mengisi tabel
usulan_inpres + usulan_dokumen dari file xlsx sumber.
"""

import datetime
import os
from pathlib import Path

import openpyxl
import pymysql

BASE_DIR = Path(__file__).resolve().parent.parent
XLSX_PATH = BASE_DIR / "docs" / "usulan_inpres_20260706114127.xlsx"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema_usulan_inpres.sql"

DB_HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
DB_USER = os.environ.get("MYSQL_USER", "root")
DB_PASS = os.environ.get("MYSQL_PASS", "")
DB_NAME = os.environ.get("MYSQL_DB", "route_gis")

# Kolom sumber -> kolom tabel usulan_inpres. Kolom yang tidak disebut di sini
# (terutama seluruh "File ..." dan jalur Kompetensi yang nyaris kosong)
# sengaja tidak diimpor sebagai kolom tabel utama.
COLUMN_MAP = {
    "ID": "id",
    "Pemda Simpan/Submit": "pemda_status",
    "Nama Pengusul": "nama_pengusul",
    "Provinsi": "provinsi",
    "Kabupaten/Kota": "kabupaten_kota",
    "Nama Kegiatan": "nama_kegiatan",
    "Prioritas": "prioritas",
    "Surat Dukungan": "surat_dukungan",
    "Pemberi Dukungan": "pemberi_dukungan",
    "Tgl. Pengusulan": "tgl_pengusulan",
    "No. Surat": "no_surat",
    "Tgl. Surat": "tgl_surat",
    "Perihal": "perihal",
    "Kode Koridor": "kode_koridor",
    "Nama Koridor": "nama_koridor",
    "Panjang Koridor": "panjang_koridor_km",
    "Kode Ruas": "kode_ruas",
    "Nama Ruas": "nama_ruas",
    "Panjang Ruas (KM)": "panjang_ruas_km",
    "Status Ruas": "status_ruas",
    "Lebar Jalan (M)": "lebar_jalan_m",
    "Kesesuaian Lebar Jalan (Balai)": "kesesuaian_lebar_jalan_balai",
    "No. Jembatan": "no_jembatan",
    "Nama Jembatan": "nama_jembatan",
    "Panjang Jembatan (M)": "panjang_jembatan_m",
    "Kondisi Jembatan": "kondisi_jembatan",
    "Jenis Penanganan": "jenis_penanganan",
    "Komponen (Balai)": "komponen_balai",
    "Komponen (Kompetensi)": "komponen_kompetensi",
    "Panjang Penanganan (Pemda)": "panjang_penanganan_pemda",
    "Panjang Penanganan (Balai)": "panjang_penanganan_balai",
    "Panjang Penanganan (Kompetensi)": "panjang_penanganan_kompetensi",
    "Satuan": "satuan",
    "Alokasi Usulan (Pemda)": "alokasi_usulan_pemda",
    "Alokasi Usulan (Balai)": "alokasi_usulan_balai",
    "Alokasi Usulan (Kompetensi)": "alokasi_usulan_kompetensi",
    "Kapasitas Fiskal": "kapasitas_fiskal",
    "Tematik Kawasan (Pemda)": "tematik_kawasan_pemda",
    "Tematik Kawasan (Balai)": "tematik_kawasan_balai",
    "Tematik Kawasan (Kompetensi)": "tematik_kawasan_kompetensi",
    "Kondisi Ruas Jalan Baik (KM)": "kondisi_baik_km",
    "Kondisi Ruas Jalan Sedang (KM)": "kondisi_sedang_km",
    "Kondisi Ruas Jalan Ringan (KM)": "kondisi_ringan_km",
    "Kondisi Ruas Jalan Berat (KM)": "kondisi_berat_km",
    "Seleksi Sistem": "seleksi_sistem",
    "Kelengkapan Input Data": "kelengkapan_input_data",
    "Verifikasi Balai": "verifikasi_balai",
    "Verifikasi Balai Oleh": "verifikasi_balai_oleh",
    "Catatan Pembahasan Balai": "catatan_pembahasan_balai",
    "Alasan Tolak/Terima Verifikasi Balai": "alasan_tolak_terima_balai",
    "Verifikasi Kompetensi": "verifikasi_kompetensi",
    "Dir. Pengampu Verifikasi Balai": "dir_pengampu_verifikasi_balai",
    "Prioritas Balai": "prioritas_balai",
    "Prioritas Kompetensi": "prioritas_kompetensi",
    "RC DED Pemda": "rc_ded_pemda",
    "RC DED Balai": "rc_ded_balai",
    "Catatan RC DED Balai": "catatan_rc_ded_balai",
    "RC FS Pemda": "rc_fs_pemda",
    "RC FS Balai": "rc_fs_balai",
    "Catatan RC FS Balai": "catatan_rc_fs_balai",
    "RC Lahan Pemda": "rc_lahan_pemda",
    "RC Lahan Balai": "rc_lahan_balai",
    "Catatan RC Lahan Balai": "catatan_rc_lahan_balai",
    "RC Dokling Pemda": "rc_dokling_pemda",
    "RC Dokling Balai": "rc_dokling_balai",
    "Catatan RC Dokling Balai": "catatan_rc_dokling_balai",
    "RAB Pemda": "rab_pemda",
    "RAB Balai": "rab_balai",
    "Catatan RAB Balai": "catatan_rab_balai",
    "Keterangan": "keterangan",
    "Catatan": "catatan",
    "Map Ruas KML Original": "kml_original_url",
    "Map Ruas KML dengan Data IJD": "kml_ijd_url",
}

INT_COLUMNS = {
    "prioritas", "prioritas_balai", "prioritas_kompetensi",
    "alokasi_usulan_pemda", "alokasi_usulan_balai", "alokasi_usulan_kompetensi",
}
DATE_COLUMNS = {"tgl_pengusulan", "tgl_surat"}
DECIMAL_COLUMNS = {
    "panjang_koridor_km", "panjang_ruas_km", "lebar_jalan_m",
    "panjang_jembatan_m", "panjang_penanganan_pemda", "panjang_penanganan_balai",
    "panjang_penanganan_kompetensi", "kondisi_baik_km", "kondisi_sedang_km",
    "kondisi_ringan_km", "kondisi_berat_km",
}

# Kolom sumber "File ..." -> jenis_dokumen di usulan_dokumen
DOCUMENT_COLUMN_MAP = {
    "File Surat Resmi": "surat_resmi",
    "File Surat Dukungan": "surat_dukungan",
    "File Data Dukung Tematik": "data_dukung_tematik",
    "File Data Dukung Ruas Non-Status": "data_dukung_ruas_non_status",
    "File RC DED Pemda": "rc_ded_pemda",
    "File RC DED Balai": "rc_ded_balai",
    "File RC FS Pemda": "rc_fs_pemda",
    "File RC FS Balai": "rc_fs_balai",
    "File RC Lahan Pemda": "rc_lahan_pemda",
    "File RC Lahan Balai": "rc_lahan_balai",
    "File RC Dokling Pemda": "rc_dokling_pemda",
    "File RC Dokling Balai": "rc_dokling_balai",
    "File RAB Pemda": "rab_pemda",
    "File RAB Balai": "rab_balai",
    "File Project Digest Pemda": "project_digest_pemda",
    "File Project Digest Balai": "project_digest_balai",
    "File Telaah Balai": "telaah_balai",
    "File Berita Acara Balai": "berita_acara_balai",
    "File Surat Pernyataan Kesiapan Menerima Hibah": "pernyataan_hibah",
    "File Surat Pernyataan Terbebas dari Tuntutan Pihak Ketiga": "pernyataan_bebas_tuntutan",
    "File BAST dan/atau Surat Pertanyaan Kesiapan Menerima Aset dan Komitmen Menyediakan Anggaran Pemeliharaan": "bast_aset",
}


def clean_value(col, value):
    if value == "" or value is None:
        return None
    if col in INT_COLUMNS:
        try:
            return int(value)
        except (ValueError, TypeError):
            return None
    if col in DECIMAL_COLUMNS:
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    if col in DATE_COLUMNS:
        if isinstance(value, datetime.datetime):
            return value.date()
        if isinstance(value, datetime.date):
            return value
        try:
            return datetime.datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    if isinstance(value, str):
        return value.strip() or None
    return value


def run_schema(conn):
    sql_text = SCHEMA_PATH.read_text(encoding="utf-8")
    code_lines = [
        line for line in sql_text.splitlines()
        if not line.strip().startswith("--")
    ]
    statements = [s.strip() for s in "\n".join(code_lines).split(";") if s.strip()]
    with conn.cursor() as cur:
        for stmt in statements:
            cur.execute(stmt)
    conn.commit()


def main():
    wb = openpyxl.load_workbook(XLSX_PATH, read_only=True, data_only=True)
    ws = wb["Worksheet"]
    rows = ws.iter_rows(values_only=True)
    header = next(rows)
    header_idx = {name: i for i, name in enumerate(header)}

    conn = pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS,
        charset="utf8mb4", autocommit=False,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE DATABASE IF NOT EXISTS %s CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                % DB_NAME
            )
        conn.select_db(DB_NAME)
        run_schema(conn)

        usulan_cols = list(COLUMN_MAP.values())
        insert_sql = (
            f"INSERT INTO usulan_inpres ({', '.join(usulan_cols)}) "
            f"VALUES ({', '.join(['%s'] * len(usulan_cols))}) "
            f"ON DUPLICATE KEY UPDATE " +
            ", ".join(f"{c}=VALUES({c})" for c in usulan_cols if c != "id")
        )
        doc_insert_sql = (
            "INSERT INTO usulan_dokumen (usulan_id, jenis_dokumen, url) VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE url=VALUES(url)"
        )

        usulan_batch = []
        doc_batch = []
        total = 0
        with conn.cursor() as cur:
            for row in rows:
                record = {}
                for src_name, dest_col in COLUMN_MAP.items():
                    raw = row[header_idx[src_name]]
                    record[dest_col] = clean_value(dest_col, raw)
                usulan_batch.append(tuple(record[c] for c in usulan_cols))

                usulan_id = record["id"]
                for src_name, jenis in DOCUMENT_COLUMN_MAP.items():
                    url = row[header_idx[src_name]]
                    if url:
                        doc_batch.append((usulan_id, jenis, url))

                total += 1
                if len(usulan_batch) >= 500:
                    cur.executemany(insert_sql, usulan_batch)
                    usulan_batch.clear()
                    if doc_batch:
                        cur.executemany(doc_insert_sql, doc_batch)
                        doc_batch.clear()

            if usulan_batch:
                cur.executemany(insert_sql, usulan_batch)
            if doc_batch:
                cur.executemany(doc_insert_sql, doc_batch)

        conn.commit()
        print(f"Selesai import {total} baris usulan_inpres.")

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM usulan_inpres")
            print("Total usulan_inpres:", cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM usulan_dokumen")
            print("Total usulan_dokumen:", cur.fetchone()[0])
    finally:
        conn.close()


if __name__ == "__main__":
    main()
