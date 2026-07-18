-- Potensi tematik per kecamatan dari BPS "Kab/Kota Dalam Angka" (Bab 5:
-- Pertanian, Perkebunan, Peternakan, Perikanan) -- dasar sub-parameter A3
-- "Tematik Tambahan" IJD 2026 untuk kategori yang selaras dengan produksi
-- sektoral (beda sumber dari kawasan_tematik/lokus Bappenas yang menutupi
-- Transmigrasi/KI Prioritas/PKPN, lihat scripts/schema_kawasan_tematik.sql).
--
-- Diisi oleh scripts/extract_dalam_angka.py --load. Flag *_ada = TRUE bila
-- kecamatan ybs. punya nilai > 0 di tabel BPS terkait pada tahun `tahun`
-- (Tabel 5.1.2/5.1.3 Padi Sawah/Ladang -> pertanian_ada; 5.3.1 Luas Areal
-- Perkebunan -> perkebunan_ada; 5.4.1 Populasi Ternak -> peternakan_ada;
-- 5.5.2/5.5.3 Prasarana Budidaya/Produksi Perikanan Laut -> perikanan_ada).
-- Kecamatan yang tidak muncul sama sekali di tabel terkait (kab/kota tidak
-- menerbitkan tabel itu, atau kecamatan memang tidak tercatat) disimpan
-- sebagai FALSE, bukan NULL -- ekstraksi ini binary "ada potensi/tidak",
-- bukan estimasi volume.
--
-- Kolom *_produksi_* (DECIMAL, NULL kalau tabel produksinya tidak
-- ditemukan/tidak dipublikasikan buku ybs.) menyimpan angka produksi tahun
-- berjalan (2025) utk tampilan, dari tabel BEDA dari yang dipakai flag *_ada
-- Perkebunan/Peternakan (yang dipakai flag itu tabel luas areal/populasi,
-- bukan produksi) -- lihat PRODUKSI_TABLES di scripts/extract_dalam_angka.py:
--   pertanian_produksi_ton           <- Tabel 5.1.2+5.1.3+5.1.7 (Padi Sawah/
--                                        Ladang + Jagung), kolom Produksi (Ton)
--   perkebunan_produksi_ton          <- Tabel 5.3.2 Produksi Perkebunan (ton) --
--                                        sudah mencakup semua jenis tanaman yg
--                                        dilaporkan per kecamatan, termasuk
--                                        kelapa sawit/kelapa/karet/tebu
--   peternakan_produksi_daging_kg    <- Tabel 5.4.4 Produksi Daging (kg) --
--                                        sudah mencakup sapi/kerbau/kambing/
--                                        domba/unggas (ayam/itik), satu kolom
--                                        gabungan, bukan per jenis ternak
--   peternakan_produksi_telur_kg     <- Tabel 5.4.3 Produksi Telur (kg)
--   perikanan_produksi_ton           <- Tabel 5.5.3 Perikanan Laut kolom Jumlah
--                                        Produksi (Ton), ATAU varian "Produksi
--                                        Ikan Menurut Tempat Penangkapan/
--                                        Budidaya" (pola provinsi lain, mis.
--                                        Kota Serang) yang gabungkan tangkap
--                                        laut + perairan umum (sungai/rawa) --
--                                        dua pola judul beda krn tidak semua
--                                        buku pakai numbering/struktur bab yang
--                                        sama, dicocokkan by teks judul bukan
--                                        nomor tabel

USE route_gis;

CREATE TABLE IF NOT EXISTS bps_kecamatan_potensi_tematik (
  kode_kab        CHAR(4)      NOT NULL,   -- kode BPS kab/kota
  nama_kab        VARCHAR(60)  NOT NULL,
  kecamatan       VARCHAR(60)  NOT NULL,   -- nama sesuai buku Dalam Angka
  tahun           SMALLINT     NOT NULL,
  kode_kecamatan  INT UNSIGNED NULL,       -- diisi build_kecamatan_turunan.py (matching thd penduduk_kecamatan);
                                            -- NULL kalau nama kecamatan Dalam Angka tak terpetakan ke master
                                            -- (lihat "tak terpetakan" saat build_kecamatan_turunan.py dijalankan)
  pertanian_ada   TINYINT(1)   NOT NULL DEFAULT 0,  -- Tabel 5.1.2/5.1.3 Padi Sawah/Ladang > 0
  perkebunan_ada  TINYINT(1)   NOT NULL DEFAULT 0,  -- Tabel 5.3.1 Luas Areal Tanaman Perkebunan > 0
  peternakan_ada  TINYINT(1)   NOT NULL DEFAULT 0,  -- Tabel 5.4.1 Populasi Ternak > 0
  perikanan_ada   TINYINT(1)   NOT NULL DEFAULT 0,  -- Tabel 5.5.2/5.5.3 Prasarana/Produksi Perikanan > 0
  pertanian_produksi_ton        DECIMAL(12,2) NULL,
  perkebunan_produksi_ton       DECIMAL(12,2) NULL,
  peternakan_produksi_daging_kg DECIMAL(12,2) NULL,
  peternakan_produksi_telur_kg  DECIMAL(12,2) NULL,
  perikanan_produksi_ton        DECIMAL(12,2) NULL,
  PRIMARY KEY (kode_kab, kecamatan, tahun),
  KEY idx_kode_kecamatan (kode_kecamatan)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
