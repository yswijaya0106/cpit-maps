-- Data level provinsi dari BPS "Statistik Indonesia 2026"
-- (docs/docs/00 Statistik Indonesia 2026.pdf) — menutup sebagian gap CPIT
-- (lihat docs/analisa_gap_cpit.md bagian 6):
--   - Tabel 10.1.1 panjang jalan per kewenangan -> komponen A1 Pagu Provinsi
--   - Tabel 10.1.2 kendaraan bermotor           -> rasio C.A3 level provinsi
--   - Tabel 5.1.6  luas wilayah & lahan baku sawah -> Indeks Penanaman C.A2
-- Diisi oleh scripts/extract_statistik_indonesia.py --load.
-- kode_provinsi = kode BPS 2 digit; baris "Indonesia" disimpan dengan kode 0.

USE route_gis;

CREATE TABLE IF NOT EXISTS si_panjang_jalan_provinsi (
  kode_provinsi SMALLINT UNSIGNED NOT NULL,   -- 0 = Indonesia (total)
  provinsi      VARCHAR(60) NOT NULL,
  tahun         SMALLINT    NOT NULL,          -- 2023-2025 (2025 = sementara*)
  nasional_km   DECIMAL(12,1) NULL,
  provinsi_km   DECIMAL(12,1) NULL,
  kabkota_km    DECIMAL(12,1) NULL,
  jumlah_km     DECIMAL(12,1) NULL,            -- jalan daerah = provinsi_km + kabkota_km
  PRIMARY KEY (kode_provinsi, tahun)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS si_kendaraan_provinsi (
  kode_provinsi   SMALLINT UNSIGNED NOT NULL,
  provinsi        VARCHAR(60) NOT NULL,
  tahun           SMALLINT NOT NULL,
  mobil_penumpang BIGINT UNSIGNED NULL,
  bus             BIGINT UNSIGNED NULL,
  mobil_barang    BIGINT UNSIGNED NULL,
  sepeda_motor    BIGINT UNSIGNED NULL,
  jumlah          BIGINT UNSIGNED NULL,
  PRIMARY KEY (kode_provinsi, tahun)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS si_lahan_sawah_provinsi (
  kode_provinsi        SMALLINT UNSIGNED NOT NULL,
  provinsi             VARCHAR(60) NOT NULL,
  luas_wilayah_km2     DECIMAL(14,2) NULL,     -- Kepmendagri 100.1.1-6117/2022
  lahan_sawah_2019_km2 DECIMAL(12,2) NULL,     -- SK ATR/BPN 686/2019
  lahan_sawah_2024_km2 DECIMAL(12,2) NULL,     -- SK ATR/BPN 446.1/2024
  persen_2019          DECIMAL(6,2) NULL,
  persen_2024          DECIMAL(6,2) NULL,
  PRIMARY KEY (kode_provinsi)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
