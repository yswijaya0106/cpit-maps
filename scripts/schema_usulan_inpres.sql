-- Skema untuk data Usulan Inpres No. 11 Tahun 2025 (Bina Marga SITIA)
-- Sumber: docs/usulan_inpres_20260706114127.xlsx (139 kolom asli) +
-- kolom tambahan tarikan 15 Juli 2026 (jalur verifikasi Kompetensi yang
-- mulai terisi, status koridor balai, penuntasan IJD — lihat
-- OPTIONAL_COLUMN_MAP di scripts/import_usulan_inpres.py; importer
-- menambahkannya via ALTER TABLE bila tabel dibuat dari schema lama).
-- Kolom yang tetap kosong/konstan (Bilateral Bappenas/PU, Verifikasi PFID,
-- MYP/MYC, Diprogramkan, Indikasi Prioritas Kemenko/Bappenas/Aspirasi)
-- sengaja tidak dibawa masuk supaya tabel tidak jadi sangat sparse.
-- Tambahkan lagi kalau suatu saat kolom itu mulai terisi di ekspor
-- berikutnya.

CREATE DATABASE IF NOT EXISTS route_gis
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE route_gis;

CREATE TABLE IF NOT EXISTS usulan_inpres (
  id                          BIGINT UNSIGNED PRIMARY KEY,        -- kolom 'ID' sumber (ID unik SITIA, bukan 'No.' urutan baris)
  tahun_usulan                SMALLINT UNSIGNED NOT NULL DEFAULT 2026,

  -- Pengusul & administratif
  pemda_status                VARCHAR(20),                        -- Submit / Simpan
  nama_pengusul                VARCHAR(255),
  provinsi                    VARCHAR(100),
  kabupaten_kota               VARCHAR(100),
  nama_kegiatan                VARCHAR(500),
  prioritas                   SMALLINT UNSIGNED,
  surat_dukungan               VARCHAR(50),
  pemberi_dukungan             VARCHAR(255),
  tgl_pengusulan               DATE,
  no_surat                    VARCHAR(100),
  tgl_surat                   DATE,
  perihal                     VARCHAR(500),

  -- Koridor & ruas (identitas geografis jalan)
  kode_koridor                 VARCHAR(50),
  nama_koridor                 VARCHAR(255),
  panjang_koridor_km            DECIMAL(10,3),
  kode_ruas                   VARCHAR(50),
  nama_ruas                   VARCHAR(255),
  panjang_ruas_km               DECIMAL(10,3),
  status_ruas                 VARCHAR(50),                        -- Kabupaten/Kota, Provinsi, Nasional, Non Status, ...
  lebar_jalan_m                DECIMAL(6,2),
  kesesuaian_lebar_jalan_balai    VARCHAR(20),

  -- Jembatan (opsional, hanya sebagian usulan berupa jembatan)
  no_jembatan                 VARCHAR(50),
  nama_jembatan                VARCHAR(255),
  panjang_jembatan_m            DECIMAL(10,2),
  kondisi_jembatan              VARCHAR(150),

  -- Jenis penanganan & komponen pekerjaan
  jenis_penanganan              VARCHAR(100),                       -- Peningkatan Jalan, Pembangunan Jembatan Baru, ...
  komponen_balai                VARCHAR(255),
  komponen_kompetensi            VARCHAR(255),
  panjang_penanganan_pemda        DECIMAL(10,3),
  panjang_penanganan_balai        DECIMAL(10,3),
  panjang_penanganan_kompetensi    DECIMAL(10,3),
  satuan                     VARCHAR(10),                        -- KM / M

  -- Anggaran
  alokasi_usulan_pemda           BIGINT UNSIGNED,
  alokasi_usulan_balai            BIGINT UNSIGNED,
  alokasi_usulan_kompetensi        BIGINT UNSIGNED,
  kapasitas_fiskal              VARCHAR(20),                        -- Sangat Rendah..Sangat Tinggi

  -- Tematik kawasan
  tematik_kawasan_pemda           VARCHAR(255),
  tematik_kawasan_balai           VARCHAR(255),
  tematik_kawasan_kompetensi       VARCHAR(255),

  -- Kondisi ruas jalan eksisting (km per kategori kerusakan)
  kondisi_baik_km               DECIMAL(10,3),
  kondisi_sedang_km             DECIMAL(10,3),
  kondisi_ringan_km             DECIMAL(10,3),
  kondisi_berat_km              DECIMAL(10,3),

  -- Seleksi & verifikasi
  seleksi_sistem                VARCHAR(20),                        -- LULUS / TIDAK LULUS
  kelengkapan_input_data          VARCHAR(20),
  verifikasi_balai              VARCHAR(20),                        -- SIMPAN / TERIMA / TOLAK
  verifikasi_balai_oleh           VARCHAR(255),
  catatan_pembahasan_balai         TEXT,
  alasan_tolak_terima_balai        TEXT,
  verifikasi_kompetensi           VARCHAR(20),
  dir_pengampu_verifikasi_balai      VARCHAR(100),
  prioritas_balai                SMALLINT UNSIGNED,
  prioritas_kompetensi            SMALLINT UNSIGNED,

  -- Jalur verifikasi Kompetensi + prioritisasi (terisi mulai tarikan 15 Juli)
  prioritas_dpr                 SMALLINT UNSIGNED,
  indikasi_prioritas_pu           VARCHAR(10),                        -- YA
  indikasi_prioritas_bappenas      VARCHAR(10),                        -- komponen 10% skor prioritas nasional
  indikasi_prioritas_kemenko       VARCHAR(10),                        -- komponen 10% skor prioritas nasional
  verifikasi_kompetensi_oleh       VARCHAR(255),
  catatan_pembahasan_kompetensi     TEXT,
  alasan_tolak_terima_kompetensi    TEXT,
  dir_pengampu_verifikasi_kompetensi VARCHAR(100),
  rc_ded_kompetensi              VARCHAR(20),
  catatan_rc_ded_kompetensi        TEXT,
  rc_fs_kompetensi               VARCHAR(20),
  catatan_rc_fs_kompetensi         TEXT,
  rc_lahan_kompetensi             VARCHAR(20),
  catatan_rc_lahan_kompetensi       TEXT,
  rc_dokling_kompetensi           VARCHAR(20),
  catatan_rc_dokling_kompetensi     TEXT,
  rab_kompetensi                 VARCHAR(20),
  catatan_rab_kompetensi           TEXT,
  jenis_rc_dokling_balai           VARCHAR(40),                        -- SPPL / UKL-UPL / DELH-DPLH / TIDAK ADA
  status_koridor_balai            VARCHAR(20),                        -- SESUAI / TIDAK SESUAI (parameter D 2026)
  jenis_data_dukung_tematik_kompetensi VARCHAR(60),                    -- KP2B/LP2B dkk (calon A4)
  penuntasan_ijd_kompetensi        VARCHAR(10),                        -- YA = flag resmi parameter E

  -- Readiness criteria (RC) - Pemda vs Balai, SIAP/TIDAK SIAP/TIDAK PERLU
  rc_ded_pemda                 VARCHAR(20),
  rc_ded_balai                 VARCHAR(20),
  catatan_rc_ded_balai            TEXT,
  rc_fs_pemda                  VARCHAR(20),
  rc_fs_balai                  VARCHAR(20),
  catatan_rc_fs_balai             TEXT,
  rc_lahan_pemda                VARCHAR(20),
  rc_lahan_balai                VARCHAR(20),
  catatan_rc_lahan_balai           TEXT,
  rc_dokling_pemda               VARCHAR(20),
  rc_dokling_balai               VARCHAR(20),
  catatan_rc_dokling_balai         TEXT,
  rab_pemda                   VARCHAR(20),
  rab_balai                   VARCHAR(20),
  catatan_rab_balai              TEXT,

  keterangan                  TEXT,
  catatan                    TEXT,

  -- Geometri (link KML sumber SITIA, geometri hasil parsing di-cache di sini
  -- supaya endpoint peta tidak perlu fetch KML berulang kali)
  kml_original_url              VARCHAR(500),
  kml_ijd_url                  VARCHAR(500),
  geom_geojson                 JSON,                              -- hasil parse KML -> GeoJSON LineString/MultiLineString, diisi belakangan oleh job caching
  geom_fetched_at               DATETIME,

  created_at                  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at                  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  INDEX idx_provinsi (provinsi),
  INDEX idx_kabkota (kabupaten_kota),
  INDEX idx_kode_ruas (kode_ruas),
  INDEX idx_jenis_penanganan (jenis_penanganan),
  INDEX idx_prioritas (prioritas),
  INDEX idx_seleksi_sistem (seleksi_sistem),
  INDEX idx_verifikasi_balai (verifikasi_balai),
  INDEX idx_tahun (tahun_usulan),
  FULLTEXT INDEX ftx_nama (nama_ruas, nama_kegiatan, nama_koridor)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Link dokumen pendukung (surat, RC, RAB, project digest, dst). Dinormalisasi
-- jadi baris per dokumen alih-alih puluhan kolom URL yang sebagian besar NULL.
CREATE TABLE IF NOT EXISTS usulan_dokumen (
  id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  usulan_id      BIGINT UNSIGNED NOT NULL,
  jenis_dokumen   VARCHAR(50) NOT NULL,
  url           VARCHAR(500) NOT NULL,
  UNIQUE KEY uq_usulan_jenis (usulan_id, jenis_dokumen),
  CONSTRAINT fk_usulan_dokumen_usulan
    FOREIGN KEY (usulan_id) REFERENCES usulan_inpres(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
