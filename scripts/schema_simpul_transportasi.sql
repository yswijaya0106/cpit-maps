-- Simpul transportasi (bandara/pelabuhan) pendukung "Konektivitas Simpul
-- Transportasi" (Aspek B Laporan Daerah Prioritas,
-- docs/docs/laporan-validator.md, dan A2 Tematik Konektivitas Tabel 2
-- dokumen 14072026). Sumber: folder publik
-- Maps/KONEKTIVITAS SIMPUL TRANSPORTASI/ (4 layer titik SHP, kualitas
-- atribut beda-beda -- lihat scripts/import_simpul_transportasi.py).
--
-- BARU 2 dari 4 layer diimpor di sini (21 Jul 2026) -- yang bisa dicocokkan
-- ke kabupaten TANPA spatial join (risiko rendah):
--   Pelabuhan Nasional  -> kolom KABUPATEN (nama teks) dicocokkan ke master
--   Pelabuhan Penyeberangan (PP.shp) -> kolom KD_KABKOT = kode BPS kabupaten
--                                        langsung ("11.72" -> 1172)
-- 2 layer sisanya (Bandara -- cuma provinsi, tanpa kabupaten; Pelabuhan
-- Laut/PELABUHAN_PT.shp -- tanpa atribut sama sekali) BELUM diimpor --
-- butuh spatial join titik->poligon kecamatan yang lebih rumit (resolusi
-- homonim nama kecamatan lintas kabupaten), disisakan sbg task terpisah.

USE route_gis;

CREATE TABLE IF NOT EXISTS simpul_transportasi (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  jenis           VARCHAR(30) NOT NULL,   -- PELABUHAN_NASIONAL / PELABUHAN_PENYEBERANGAN
  nama            VARCHAR(150),
  provinsi_asli   VARCHAR(100),
  kabupaten_asli  VARCHAR(100),
  kode_provinsi   SMALLINT UNSIGNED NULL,
  kode_kabupaten  MEDIUMINT UNSIGNED NULL,
  sumber_file     VARCHAR(150),
  KEY idx_kode_kabupaten (kode_kabupaten)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
