-- Pemetaan nama wilayah SITIA (usulan_inpres.provinsi/kabupaten_kota, teks
-- bebas huruf besar) -> kode wilayah BPS (master penduduk_kecamatan, dari
-- docs/docs/3_ID dan Jumlah Penduduk Indonesia Tahun 2025.xlsx).
-- Gap G15 analisa_gap_cpit.md — prasyarat skor Kemanfaatan (C) dan
-- disagregasi rasio kabupaten->kecamatan.
--
-- Diisi scripts/build_wilayah_mapping.py: matcher otomatis (metode AUTO)
-- + baris koreksi manual (metode MANUAL — tidak ditimpa saat matcher
-- dijalankan ulang; isi kode_provinsi/kode_kabupaten lalu set metode='MANUAL'
-- untuk pasangan yang gagal match otomatis).

USE route_gis;

CREATE TABLE IF NOT EXISTS wilayah_mapping (
  id                    INT AUTO_INCREMENT PRIMARY KEY,
  provinsi_sitia        VARCHAR(100) NOT NULL,
  kabupaten_kota_sitia  VARCHAR(100) NOT NULL,
  kode_provinsi         SMALLINT UNSIGNED NULL,   -- kode BPS 2 digit (NULL = belum terpetakan)
  kode_kabupaten        INT UNSIGNED NULL,        -- kode BPS 4 digit (NULL = belum terpetakan)
  kabupaten_kota_bps    VARCHAR(100) NULL,        -- nama master BPS (tanpa prefiks KAB/KOTA)
  metode                VARCHAR(10) NOT NULL DEFAULT 'AUTO',  -- AUTO / MANUAL
  catatan               VARCHAR(255) NULL,
  updated_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_wilayah_sitia (provinsi_sitia, kabupaten_kota_sitia),
  KEY idx_kode_kabupaten (kode_kabupaten)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
