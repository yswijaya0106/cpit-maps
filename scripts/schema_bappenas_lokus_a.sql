-- Lokus data pendukung "Aspek Prioritas dan Nilai Strategis (A)" penilaian
-- Bappenas -- dasar fitur "Draf Penilaian Bappenas (AI)" export bulk per
-- provinsi (docs/spec/Draf Penilaian Bappenas.md). BEDA dari kawasan_tematik
-- (yang dipakai skor IJD A3 "Tematik Tambahan") -- tabel terpisah supaya dua
-- fitur yang beda tujuan tidak saling bercampur walau sumber datanya
-- sebagian sama.
--
-- Sumber: sheet "Kumpulan Data" baris 3-18 (bagian "PENILAIAN LOKPRI") di
-- docs/docs/2_Analisis Prioritas untuk Bappenas dan Teknokratis 15.7.2026.xlsx.
-- Diisi oleh scripts/import_bappenas_lokus_a.py. kode_kabupaten/kode_kecamatan
-- dicocokkan ke master penduduk_kecamatan -- teknik sama dengan
-- import_kawasan_tematik.py.
--
-- kriteria = salah satu dari:
--   LOKPRI_RPJMN, PKSN, PERBATASAN, SR, SEKOLAH_GARUDA, KNMP, KDMP,
--   SWASEMBADA_PANGAN_RPJMN, BBM_1_HARGA (diimpor script ini)
--   PKPN, PERKEBUNAN, PERIKANAN, TRANSMIGRASI, KI_PRIORITAS (SUDAH ada di
--   kawasan_tematik dari import_kawasan_tematik.py -- TIDAK diduplikasi di
--   sini, scorer Aspek A membaca kawasan_tematik langsung utk kategori ini)
-- BBM_1_HARGA: sumber "Lokus IJD BBM 1 HARGA" cuma 5 baris nasional, teks
-- bebas + koordinat tanpa kolom kabupaten/kota bersih -- dicocokkan via
-- regex "Kab./Kec. <nama>" pada gabungan sel per baris (lihat
-- import_bbm_1_harga() di import_bappenas_lokus_a.py), diverifikasi manual
-- 5/5 baris. Baris yg menyebut >1 kabupaten (tanpa kecamatan spesifik)
-- menghasilkan beberapa baris keluaran level KABUPATEN, satu per kabupaten.

USE route_gis;

CREATE TABLE IF NOT EXISTS bappenas_lokus_a (
  id                INT AUTO_INCREMENT PRIMARY KEY,
  kriteria          VARCHAR(30)  NOT NULL,
  level             ENUM('PROVINSI','KABUPATEN','KECAMATAN') NOT NULL,
  provinsi_asli     VARCHAR(100) NULL,
  kabupaten_asli    VARCHAR(100) NULL,
  kecamatan_asli    VARCHAR(100) NULL,
  kode_provinsi     SMALLINT UNSIGNED NULL,
  kode_kabupaten    MEDIUMINT UNSIGNED NULL,
  kode_kecamatan    INT UNSIGNED NULL,
  keterangan        VARCHAR(255) NULL,
  sumber_file       VARCHAR(150) NULL,
  sumber_sheet      VARCHAR(60)  NULL,
  KEY idx_kriteria (kriteria),
  KEY idx_kab (kode_kabupaten),
  KEY idx_kec (kode_kecamatan),
  KEY idx_prov (kode_provinsi)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
