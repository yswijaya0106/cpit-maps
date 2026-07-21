-- Konektivitas Jaringan Jalan (Aspek B Laporan Daerah Prioritas,
-- docs/spec/laporan prioritas.md) -- proksi "kabupaten/kota ini punya data
-- jaringan jalan terpetakan" (ada/tidak, BUKAN kualitas/kepadatan jaringan).
--
-- 2 sumber independen digabung (kabupaten dianggap terkoneksi kalau SALAH
-- SATU ada, lihat kolom `sumber` utk tahu yg mana):
--   DAERAH   - struktur folder Maps/<PROVINSI>/<Kabupaten X>/*.shp yang
--              SUDAH dipakai overlay peta topbar (skema atribut per-file
--              sangat beragam, dicocokkan lewat NAMA FOLDER bukan atribut
--              file). scripts/import_konektivitas_jalan.py.
--   NASIONAL - Maps/JALAN NASIONAL/Jalan Nasional.shp (3.306 ruas, kolom
--              CITY_ID = kode BPS kabupaten LANGSUNG, tanpa perlu
--              name-matching/spatial join). scripts/import_jalan_nasional.py.
-- Diisi scripts/import_konektivitas_jalan.py (DAERAH) dan
-- scripts/import_jalan_nasional.py (NASIONAL) -- keduanya UPSERT ke tabel
-- yang sama, tidak saling menimpa (lihat ON DUPLICATE KEY di masing-masing).

USE route_gis;

CREATE TABLE IF NOT EXISTS konektivitas_jaringan_jalan (
  kode_kabupaten   MEDIUMINT UNSIGNED NOT NULL PRIMARY KEY,
  ada_jalan_daerah   TINYINT(1) NOT NULL DEFAULT 0,
  ada_jalan_nasional TINYINT(1) NOT NULL DEFAULT 0,
  provinsi_folder  VARCHAR(100),
  kabupaten_folder VARCHAR(100),
  sumber_file      VARCHAR(150),
  n_ruas_nasional  INT UNSIGNED
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
