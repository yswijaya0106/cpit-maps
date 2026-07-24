-- Produksi per KOMODITAS (bukan gabungan sektor) per kecamatan, dari BPS
-- "Kab/Kota Dalam Angka" Tabel 5.3.2 "Produksi Perkebunan Menurut
-- Kecamatan dan Jenis Tanaman" (dan varian "Produksi Tanaman Perkebunan").
-- Ekstraksi RINCI dari _extract_kecamatan_table_by_group() di
-- scripts/extract_dalam_angka.py -- BEDA dari
-- bps_kecamatan_potensi_tematik.perkebunan_produksi_ton (yang menjumlah
-- SEMUA komoditas jadi satu angka). jenis_tanaman disimpan APA ADANYA
-- label header PDF (mis. "Kelapa Sawit/Oil Palm", "Karet/Rubber") --
-- bukan dinormalisasi krn daftar komoditas TIDAK seragam antar kab/kota
-- (ikut apa yang diterbitkan buku ybs., lihat komentar PRODUKSI_TABLES).
--
-- kode_kecamatan diisi kemudian oleh build_kecamatan_turunan.py (matching
-- thd penduduk_kecamatan), sama pola dgn bps_kecamatan_potensi_tematik.

USE route_gis;

CREATE TABLE IF NOT EXISTS bps_kecamatan_produksi_komoditas (
  kode_kab        CHAR(4)      NOT NULL,
  nama_kab        VARCHAR(60)  NOT NULL,
  kecamatan       VARCHAR(60)  NOT NULL,
  tahun           SMALLINT     NOT NULL,
  kategori        VARCHAR(20)  NOT NULL,   -- PERKEBUNAN (baru satu kategori per 21 Jul 2026)
  jenis_tanaman   VARCHAR(60)  NOT NULL,   -- label apa adanya dari PDF, mis. "Kelapa Sawit/Oil Palm"
  kode_kecamatan  INT UNSIGNED NULL,
  produksi_ton    DECIMAL(12,2) NULL,
  PRIMARY KEY (kode_kab, kecamatan, tahun, kategori, jenis_tanaman),
  KEY idx_kode_kecamatan (kode_kecamatan)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
