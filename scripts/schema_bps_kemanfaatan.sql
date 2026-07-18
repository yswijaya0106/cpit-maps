-- Data BPS "Dalam Angka 2026" untuk Parameter C (Kemanfaatan) skoring IJD —
-- sumber data yang di scripts/schema_ijd_scoring.sql masih ditandai "belum
-- tersedia". Diisi oleh scripts/extract_dalam_angka.py --load, yang membaca
-- SEMUA folder provinsi di dalam_angka/ ("data gdrive" pada kerangka CPIT;
-- saat ini baru 36 Banten — tambahkan folder provinsi lain lalu jalankan
-- ulang script untuk memperluas cakupan).
--
-- Pemetaan ke sub-parameter C (docs/BF. Parameter Penilaian IJD [FULL].pdf):
--   C.A1 (35%) kepadatan penduduk kecamatan -> bps_kecamatan_demografi.
--        kepadatan_per_km2 (>1000=100; 500-1000=75; 100-500=50; <100=25)
--   C.A2 (35%) produktivitas -> bps_kabupaten_padi. BPS 2026 tidak lagi
--        memublikasikan padi per kecamatan (data KSA hanya per kabupaten).
--        produktivitas_ku_ha dalam kuintal/ha; ambang BF dalam ton/ha
--        (ton/ha = ku/ha / 10). Indeks Penanaman tidak dipublikasikan BPS.
--   C.A3 (30%) kepemilikan kendaraan -> bps_kecamatan_demografi.
--        total_kendaraan (hanya Pandeglang & Kota Serang yang merilis per
--        kecamatan); fallback rasio kabupaten dari bps_kabupaten_kendaraan
--        sesuai catatan BF ("dapat menggunakan rasio per kabupaten").

USE route_gis;

CREATE TABLE IF NOT EXISTS bps_kecamatan_demografi (
  kode_kab            CHAR(4)      NOT NULL,   -- kode BPS kab/kota (3601..3674)
  nama_kab            VARCHAR(60)  NOT NULL,   -- mis. "Kabupaten Kepulauan Siau Tagulandang Biaro" (42 char)
  kecamatan           VARCHAR(60)  NOT NULL,   -- nama sesuai buku Dalam Angka
  tahun               SMALLINT     NOT NULL,
  jumlah_penduduk     INT          NULL,
  laju_pertumbuhan_pct DECIMAL(6,2) NULL,      -- NULL utk Kab. Serang (tidak dipublikasikan)
  persentase_penduduk DECIMAL(6,2) NULL,
  kepadatan_per_km2   DECIMAL(10,2) NULL,      -- dasar skor C.A1
  rasio_jenis_kelamin DECIMAL(6,2) NULL,
  luas_km2_derived    DECIMAL(10,2) NULL,      -- turunan: penduduk/kepadatan
  total_kendaraan     INT          NULL,       -- dasar skor C.A3 (bila tersedia)
  PRIMARY KEY (kode_kab, kecamatan, tahun)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS bps_kabupaten_padi (
  kode_kab            CHAR(4)      NOT NULL,
  nama_kab            VARCHAR(60)  NOT NULL,   -- mis. "Kabupaten Kepulauan Siau Tagulandang Biaro" (42 char)
  tahun               SMALLINT     NOT NULL,
  luas_panen_ha       DECIMAL(12,2) NULL,      -- NULL = "-" di sumber (Tangsel)
  produktivitas_ku_ha DECIMAL(8,2) NULL,       -- kuintal/ha (GKG)
  produksi_ton        DECIMAL(14,2) NULL,
  PRIMARY KEY (kode_kab, tahun)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS bps_kabupaten_kendaraan (
  kode_kab        CHAR(4)     NOT NULL,
  nama_kab        VARCHAR(40) NOT NULL,
  tahun           SMALLINT    NOT NULL,        -- 2023-2025 (2025 = angka sementara*)
  mobil_penumpang INT NULL,
  bus             INT NULL,
  mobil_barang    INT NULL,
  sepeda_motor    INT NULL,
  jumlah          INT NULL,
  PRIMARY KEY (kode_kab, tahun)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
