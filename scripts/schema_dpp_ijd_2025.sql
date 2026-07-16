-- Daftar Proyek Prioritas (DPP) Tambahan IJD TA 2025, dari
-- docs/docs/DPP_IJD 2025.xlsx — basis parameter E "Kegiatan IJD Sebelumnya
-- (Penuntasan)" kaidah skoring 2026 (lihat scripts/schema_ijd_scoring_2026.sql).
--
-- Isi file sumber: sheet "LAMPIRAN BA" (534 kegiatan fisik, daftar berita
-- acara) + sheet "RINCIAN DPP VAL" (112 kegiatan DPP; punya ID SITIA siklus
-- 2025 di blok pivot kiri). Catatan: ID SITIA 2025 (234075-238785) TIDAK
-- beririsan dengan id usulan_inpres tarikan 2026 (238839+) — pencocokan
-- lanjutan/penuntasan dilakukan lewat normalisasi nama ruas + wilayah oleh
-- scripts/import_dpp_ijd_2025.py, hasilnya disimpan di matched_usulan_id
-- (tabel ini) dan usulan_inpres.lanjutan_ijd_2025 (ditambahkan importer).
-- Diisi/di-refresh oleh scripts/import_dpp_ijd_2025.py (upsert per
-- sumber+no_urut).

USE route_gis;

CREATE TABLE IF NOT EXISTS dpp_ijd_2025 (
  id                INT AUTO_INCREMENT PRIMARY KEY,
  sumber            VARCHAR(8) NOT NULL,      -- 'BA' (LAMPIRAN BA) / 'DPP' (RINCIAN DPP VAL)
  no_urut           INT NOT NULL,             -- kolom NO di sheet sumber
  id_sitia_2025     INT NULL,                 -- ID SITIA siklus 2025 (hanya DPP)
  nama_kegiatan     VARCHAR(300) NOT NULL,
  jenis_penanganan  VARCHAR(60),
  status_jalan      VARCHAR(4),               -- K = kabupaten/kota, P = provinsi
  provinsi          VARCHAR(80),
  kewenangan        VARCHAR(120),             -- "Kab. X" / "Kota Y" / "Provinsi Z"
  pjg_jalan_km      DECIMAL(10,3),
  pjg_jbt_m         DECIMAL(10,2),
  alokasi_rp        DECIMAL(20,2),
  alokasi_ta2025_rp DECIMAL(20,2),            -- hanya DPP
  alokasi_ta2026_rp DECIMAL(20,2),            -- hanya DPP
  keterangan        VARCHAR(120),             -- hanya BA ("Tahap 1"/"Tahap 2")
  tematik           VARCHAR(180),
  matched_usulan_id INT NULL,                 -- id usulan_inpres 2026 hasil pencocokan
  match_metode      VARCHAR(30) NULL,         -- 'PROV_KAB_RUAS' / 'PROV_RUAS'
  imported_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_dpp (sumber, no_urut),
  KEY idx_dpp_wilayah (provinsi, kewenangan),
  KEY idx_dpp_match (matched_usulan_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
