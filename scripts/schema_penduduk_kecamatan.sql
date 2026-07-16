-- Master penyelarasan ID wilayah + jumlah penduduk per kecamatan/distrik
-- seluruh Indonesia, dari docs/docs/3_ID dan Jumlah Penduduk Indonesia Tahun
-- 2025.xlsx (sumber: Kabupaten/Kota Dalam Angka 2026, berbagai terbitan).
-- Kerangka CPIT (docs/docs/1_ KERANGKA PENGGUNAAN DATA UNTUK APLIKASI
-- CPIT.docx) memakai file ini sebagai acuan kode provinsi/kabupaten/kecamatan
-- sebelum analisis bobot Bappenas & Teknokratis, dan sebagai dasar skor
-- C.A1 Jumlah Penduduk (Kecamatan).
-- Diisi oleh scripts/import_penduduk_kecamatan.py (upsert per kode kecamatan).

USE route_gis;

CREATE TABLE IF NOT EXISTS penduduk_kecamatan (
  kode_provinsi  SMALLINT UNSIGNED NOT NULL,  -- kode BPS 2 digit
  provinsi       VARCHAR(60)  NOT NULL,
  kode_kabupaten MEDIUMINT UNSIGNED NOT NULL, -- kode BPS 4 digit
  kabupaten_kota VARCHAR(80)  NOT NULL,
  kode_kecamatan INT UNSIGNED NOT NULL,       -- kode BPS 7 digit
  kecamatan      VARCHAR(80)  NOT NULL,
  tahun          SMALLINT     NOT NULL DEFAULT 2025,
  jumlah_penduduk INT UNSIGNED NULL,
  keterangan     VARCHAR(255) NULL,           -- catatan sumber/estimasi dari file
  PRIMARY KEY (kode_kecamatan, tahun),
  KEY idx_kab (kode_kabupaten),
  KEY idx_prov (kode_provinsi)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
