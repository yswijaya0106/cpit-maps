-- Kemantapan jalan daerah per provinsi & kabupaten/kota + rasio kapasitas
-- fiskal, dari docs/docs/5_IJD 2026 - DATA (Kemantapan Jalan per Kab-Kota).xlsx
-- (sheet IJD-26, sumber PFID via Kumpulan Data file 2 baris "Kemantapan
-- Jalan (IJD)"). Basis parameter G8.A2 "Panjang Jalan Tidak Mantap" (bobot
-- 30, komponen pagu provinsi terbesar yang sebelumnya kosong) — lihat
-- _pagu_provinsi() di app.py.
--
-- Satu baris "Adm='Prov'" per provinsi (kode wilayah xx00, mencakup jalan
-- KEWENANGAN PROVINSI) + banyak baris "Adm='Kab.'/'Kota'" per kabupaten/kota
-- (jalan KEWENANGAN kab/kota). "Jalan daerah" per definisi Tabel 1 = jumlah
-- keduanya per provinsi (jalan provinsi + jalan kab/kota) — _pagu_provinsi()
-- menjumlahkan seluruh baris ber-kode_provinsi yang sama.
-- RASIO KFD & kategori fiskal per provinsi (baris Prov) adalah sumber PMK
-- yang lebih otoritatif dibanding kapasitas_fiskal usulan (deklarasi
-- Gubernur di SITIA) — belum dipakai menggantikan A4, disimpan sebagai
-- referensi/validasi.

USE route_gis;

CREATE TABLE IF NOT EXISTS kemantapan_ijd_2026 (
  id                 INT AUTO_INCREMENT PRIMARY KEY,
  kode_provinsi      SMALLINT UNSIGNED NOT NULL,
  kode_wilayah       MEDIUMINT UNSIGNED NOT NULL,   -- xx00 utk baris Prov, kode kab 4 digit utk baris Kab/Kota
  provinsi           VARCHAR(80) NOT NULL,
  kabupaten_kota     VARCHAR(80) NOT NULL,          -- "Provinsi <nama>" utk baris Prov
  jenis_adm          VARCHAR(10) NOT NULL,          -- Prov / Kab. / Kota
  panjang_km         DECIMAL(10,3) NULL,
  mantap_km          DECIMAL(10,3) NULL,
  mantap_pct         DECIMAL(6,3) NULL,
  tidak_mantap_km    DECIMAL(10,3) NULL,
  tidak_mantap_pct   DECIMAL(6,3) NULL,
  status_pkrms       VARCHAR(20) NULL,
  rasio_kfd          DECIMAL(8,4) NULL,
  kategori_fiskal    VARCHAR(20) NULL,              -- Sangat Rendah..Sangat Tinggi (baris Prov)
  UNIQUE KEY uq_kemantapan (kode_provinsi, kode_wilayah, jenis_adm)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
