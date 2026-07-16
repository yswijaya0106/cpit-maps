-- Tabel turunan per kecamatan untuk skoring Kemanfaatan (parameter C) —
-- gap G3 (C.A1 kepadatan) + G13 (disagregasi rasio kabupaten->kecamatan)
-- analisa_gap_cpit.md. Dibangun scripts/build_kecamatan_turunan.py dari:
--   - penduduk_kecamatan          : kerangka nasional (7.288 kecamatan)
--   - bps_kecamatan_demografi     : kepadatan/luas/kendaraan per kecamatan
--                                   (baru provinsi yang ada di dalam_angka/)
--   - bps_kabupaten_kendaraan     : kendaraan per kabupaten -> disagregasi
--                                   proporsional penduduk, DITANDAI estimasi=1
-- Nilai langsung dari publikasi BPS diberi flag estimasi=0; hasil bagi
-- proporsional (kunci alokasi = pangsa penduduk kecamatan) diberi flag
-- estimasi=1 dan tidak boleh disajikan tanpa penanda itu.

USE route_gis;

CREATE TABLE IF NOT EXISTS kecamatan_data_turunan (
  kode_kecamatan       INT UNSIGNED NOT NULL,   -- kode BPS 7 digit (master penduduk_kecamatan)
  tahun                SMALLINT NOT NULL,
  kode_kabupaten       MEDIUMINT UNSIGNED NOT NULL,
  kecamatan            VARCHAR(80) NOT NULL,
  jumlah_penduduk      INT UNSIGNED NULL,
  kepadatan_per_km2    DECIMAL(10,2) NULL,      -- dasar skor C.A1 (dari Dalam Angka)
  luas_km2             DECIMAL(10,2) NULL,      -- turunan penduduk/kepadatan
  kendaraan_total      INT UNSIGNED NULL,       -- dasar fallback C.A3
  kendaraan_estimasi   TINYINT NULL,            -- 0=angka BPS per kecamatan, 1=disagregasi dari kabupaten
  built_at             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                       ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (kode_kecamatan, tahun),
  KEY idx_kab (kode_kabupaten)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
