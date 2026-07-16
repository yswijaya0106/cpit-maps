-- Kawasan tematik pendukung parameter A3 "Tematik Tambahan" (bobot internal
-- 20%, Tabel 2 baris 14-23 dokumen 14072026) — gap G2/G18 analisa_gap_cpit.md
-- bagian 7. Sumber: docs/docs/6_Usulan Lokus IJD 2026 Sektor Bappenas.xlsx
-- (5 sheet dipilih yang datanya bersih & sesuai daftar A3; sheet lain di
-- file itu — Swasembada Pangan flagship, BBM 1 Harga tanpa kolom kab/kota —
-- dilewati karena tak sesuai granularitas atau di luar daftar A3).
--
-- Pemetaan sheet -> kategori -> nilai A3 (Tabel 2):
--   Lokus Perkebunan              -> PERKEBUNAN            (100)
--   Lokus Kelautan dan Perikanan  -> PERIKANAN             (100)
--   Lokus Transmigrasi            -> TRANSMIGRASI          (75)
--   4 sheet Lokus PKPN KI *       -> KI_PRIORITAS          (50)
--   Lokus PKPN 3T (9.377 baris desa, diagregasi ke kecamatan) -> PKPN (25)
--
-- Diisi scripts/import_kawasan_tematik.py (upsert per kategori+kode wilayah).
-- kode_kabupaten dicari lewat pencocokan nama (provinsi+kabupaten) terhadap
-- master penduduk_kecamatan, teknik sama dengan build_wilayah_mapping.py.

USE route_gis;

CREATE TABLE IF NOT EXISTS kawasan_tematik (
  id                INT AUTO_INCREMENT PRIMARY KEY,
  kategori          VARCHAR(20) NOT NULL,    -- PERKEBUNAN/PERIKANAN/TRANSMIGRASI/KI_PRIORITAS/PKPN
  provinsi_asli     VARCHAR(100),
  kabupaten_asli    VARCHAR(100),
  kecamatan_asli    VARCHAR(200),            -- bisa multi-nilai dipisah koma (apa adanya sumber)
  kode_provinsi     SMALLINT UNSIGNED NULL,
  kode_kabupaten    MEDIUMINT UNSIGNED NULL,
  kode_kecamatan    INT UNSIGNED NULL,       -- NULL bila kecamatan tak tunggal/tak match
  keterangan        VARCHAR(300),
  sumber_sheet      VARCHAR(60) NOT NULL,
  UNIQUE KEY uq_kawasan (kategori, sumber_sheet, provinsi_asli, kabupaten_asli, kecamatan_asli),
  KEY idx_kode_kab (kode_kabupaten),
  KEY idx_kode_kec (kode_kecamatan)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
