-- Kaidah skoring "Prioritisasi Teknokratik" usulan IJD (Inpres Jalan Daerah
-- No. 11/2025), diturunkan dari docs/BF. & SD. Parameter Penilaian IJD [FULL].pdf
-- (Tabel 1, 3, 6, dan Tabel A1/A2 tematik). Nilai bobot & skor per kondisi
-- disimpan sebagai data supaya bisa disesuaikan tanpa ubah kode saat kebijakan
-- IJD tahun berikutnya berubah — lihat _load_ijd_rules() / _compute_ijd_score()
-- di app.py untuk cara pakainya.
--
-- Catatan cakupan: dari 6 parameter Tabel 1 (A-F, total maks 100), yang bisa
-- dihitung otomatis dari data usulan_inpres yang sudah ada hanyalah A
-- (tematik — hanya sub-parameter A1/A2, karena A3/A4 butuh input tambahan
-- yang tidak diisi Pemda di SITIA), B (kemantapan eksisting), D (koridor,
-- pendekatan dari ada/tidaknya kode_koridor), dan F (kelengkapan RC).
-- C (Kemanfaatan: kepadatan penduduk/produktivitas/LHR) dan E (Keberlanjutan
-- usulan IJD tahun sebelumnya) belum ada sumber datanya — skor dilaporkan
-- sebagai "belum tersedia", bukan 0, supaya tidak keliru dibaca sebagai nilai
-- rendah.

USE route_gis;

CREATE TABLE IF NOT EXISTS ijd_scoring_rules (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  tahun_berlaku    SMALLINT UNSIGNED NOT NULL DEFAULT 2025,
  parameter_kode   VARCHAR(5) NOT NULL,       -- A..F, sesuai Tabel 1 "Resume Parameter Penilaian"
  parameter_label  VARCHAR(120) NOT NULL,
  bobot_maks      DECIMAL(5,2) NOT NULL,      -- kontribusi maksimal parameter ini ke total skor 0-100
  sub_kode        VARCHAR(150) NOT NULL,      -- kondisi/kategori spesifik dalam parameter ini
  kondisi_label    VARCHAR(200) NOT NULL,
  nilai           DECIMAL(6,2) NOT NULL,      -- skor kondisi ini, skala 0-100 di dalam parameter
  UNIQUE KEY uq_rule (tahun_berlaku, parameter_kode, sub_kode)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- A. Tematik dan Data Dukungnya (bobot 30) — sub_kode = nilai kolom
-- tematik_kawasan_pemda apa adanya (dicocokkan persis). Nilai dari Tabel A1
-- (Tematik SITIA) & A2 (Tematik Konektivitas); kategori yang hanya muncul di
-- Tabel A3 (Kawasan Strategis Daerah) dipakai sebagai pendekatan bila belum
-- ada padanan di A1.
INSERT INTO ijd_scoring_rules (tahun_berlaku, parameter_kode, parameter_label, bobot_maks, sub_kode, kondisi_label, nilai) VALUES
(2025, 'A', 'Tematik dan Data Dukungnya', 30, 'Swasembada Pangan - Pertanian', 'Swasembada Pangan - Pertanian', 100),
(2025, 'A', 'Tematik dan Data Dukungnya', 30, 'Swasembada Pangan - Perkebunan', 'Swasembada Pangan - Perkebunan', 60),
(2025, 'A', 'Tematik dan Data Dukungnya', 30, 'Swasembada Pangan - Perikanan', 'Swasembada Pangan - Perikanan', 60),
(2025, 'A', 'Tematik dan Data Dukungnya', 30, 'Swasembada Pangan - Peternakan', 'Swasembada Pangan - Peternakan', 60),
(2025, 'A', 'Tematik dan Data Dukungnya', 30, 'Swasembada Pangan - Kawasan Mendukung Program MBG', 'Swasembada Pangan - Kawasan Mendukung Program MBG', 75),
(2025, 'A', 'Tematik dan Data Dukungnya', 30, 'Distribusi Energi - Pekerbunan yang mendukung Energi Terbarukan', 'Distribusi Energi - Perkebunan mendukung Energi Terbarukan', 75),
(2025, 'A', 'Tematik dan Data Dukungnya', 30, 'Distribusi Energi - Mendukung Distribusi BBM satu harga', 'Distribusi Energi - Mendukung Distribusi BBM Satu Harga', 75),
(2025, 'A', 'Tematik dan Data Dukungnya', 30, 'Kawasan Produktif Lainnya - Kawasan Transmigrasi', 'Kawasan Produktif Lainnya - Kawasan Transmigrasi', 50),
(2025, 'A', 'Tematik dan Data Dukungnya', 30, 'Kawasan Produktif Lainnya - Kawasan Industri Prioritas', 'Kawasan Produktif Lainnya - Kawasan Industri Prioritas (RPJMN)', 50),
(2025, 'A', 'Tematik dan Data Dukungnya', 30, 'Kawasan Produktif Lainnya - Kawasan Strategis Daerah', 'Kawasan Produktif Lainnya - Kawasan Strategis Daerah (RTRW/RDTR)', 50),
(2025, 'A', 'Tematik dan Data Dukungnya', 30, 'Konektivitas - Terhubung Ke Status Lebih Tinggi (Jalan Nasional)', 'Konektivitas - Terhubung ke Jalan Nasional', 100),
(2025, 'A', 'Tematik dan Data Dukungnya', 30, 'Konektivitas - Terhubung Ke Status Lebih Tinggi (Jalan Provinsi)', 'Konektivitas - Terhubung ke Jalan Provinsi', 50),
(2025, 'A', 'Tematik dan Data Dukungnya', 30, 'Konektivitas - Terhubung Ke Simpul Transportasi', 'Konektivitas - Terhubung ke Simpul Transportasi', 100);

-- B. Kondisi Kemantapan Eksisting Ruas (bobot 15) — Tabel 3.
INSERT INTO ijd_scoring_rules (tahun_berlaku, parameter_kode, parameter_label, bobot_maks, sub_kode, kondisi_label, nilai) VALUES
(2025, 'B', 'Kondisi Kemantapan Eksisting Ruas', 15, 'TIDAK_MANTAP', 'Kemantapan ruas < 60% (mayoritas rusak)', 100),
(2025, 'B', 'Kondisi Kemantapan Eksisting Ruas', 15, 'MANTAP', 'Kemantapan ruas > 60%', 60),
(2025, 'B', 'Kondisi Kemantapan Eksisting Ruas', 15, 'PEMBANGUNAN', 'Pembangunan jalan/jembatan baru', 40);

-- D. Koridor (bobot 15) — Tabel 3 (Keberlanjutan Usulan Kegiatan/koridor).
-- Pendekatan: ruas dengan kode_koridor terisi dianggap "bagian dari koridor
-- yang telah diidentifikasi"; ini proksi administratif, bukan pencocokan
-- terhadap daftar koridor resmi Bina Marga.
INSERT INTO ijd_scoring_rules (tahun_berlaku, parameter_kode, parameter_label, bobot_maks, sub_kode, kondisi_label, nilai) VALUES
(2025, 'D', 'Koridor', 15, 'TERIDENTIFIKASI', 'Bagian dari koridor yang telah diidentifikasi (kode_koridor terisi)', 75),
(2025, 'D', 'Koridor', 15, 'LAINNYA', 'Koridor lainnya / tidak terkait koridor', 25);

-- F. Kelengkapan Readiness Criteria — DED, RAB, Dokling, Lahan (bobot 10) —
-- Tabel 6. sub_kode = "<KOMPONEN>_<STATUS DB DINORMALISASI>"; status dari
-- rc_*_balai dipakai bila ada (sudah diverifikasi balai), fallback ke status
-- deklarasi rc_*_pemda bila balai belum menilai.
INSERT INTO ijd_scoring_rules (tahun_berlaku, parameter_kode, parameter_label, bobot_maks, sub_kode, kondisi_label, nilai) VALUES
(2025, 'F', 'Kelengkapan Readiness Criteria (RC)', 10, 'DED_SESUAI', 'DED sesuai', 100),
(2025, 'F', 'Kelengkapan Readiness Criteria (RC)', 10, 'DED_SIAP', 'DED siap (deklarasi Pemda)', 100),
(2025, 'F', 'Kelengkapan Readiness Criteria (RC)', 10, 'DED_DISIAPKAN_BALAI', 'DED sedang disiapkan Balai', 35),
(2025, 'F', 'Kelengkapan Readiness Criteria (RC)', 10, 'DED_TIDAK_SESUAI', 'DED tidak sesuai', 0),
(2025, 'F', 'Kelengkapan Readiness Criteria (RC)', 10, 'DED_TIDAK_SIAP', 'DED tidak siap', 0),
(2025, 'F', 'Kelengkapan Readiness Criteria (RC)', 10, 'DED_TIDAK_PERLU', 'DED tidak diperlukan', 100),
(2025, 'F', 'Kelengkapan Readiness Criteria (RC)', 10, 'RAB_SIAP', 'RAB siap', 100),
(2025, 'F', 'Kelengkapan Readiness Criteria (RC)', 10, 'RAB_PERLU_REVISI', 'RAB perlu revisi', 35),
(2025, 'F', 'Kelengkapan Readiness Criteria (RC)', 10, 'RAB_TIDAK_SIAP', 'RAB tidak siap', 0),
(2025, 'F', 'Kelengkapan Readiness Criteria (RC)', 10, 'DOKLING_SESUAI', 'Dokumen lingkungan sesuai', 100),
(2025, 'F', 'Kelengkapan Readiness Criteria (RC)', 10, 'DOKLING_SIAP', 'Dokumen lingkungan siap (deklarasi Pemda)', 100),
(2025, 'F', 'Kelengkapan Readiness Criteria (RC)', 10, 'DOKLING_AKAN_DISIAPKAN', 'Dokumen lingkungan akan disiapkan', 35),
(2025, 'F', 'Kelengkapan Readiness Criteria (RC)', 10, 'DOKLING_DISIAPKAN_BALAI', 'Dokumen lingkungan sedang disiapkan Balai', 35),
(2025, 'F', 'Kelengkapan Readiness Criteria (RC)', 10, 'DOKLING_TIDAK_SESUAI', 'Dokumen lingkungan tidak sesuai', 0),
(2025, 'F', 'Kelengkapan Readiness Criteria (RC)', 10, 'DOKLING_TIDAK_SIAP', 'Dokumen lingkungan tidak siap', 0),
(2025, 'F', 'Kelengkapan Readiness Criteria (RC)', 10, 'DOKLING_TIDAK_PERLU', 'Dokumen lingkungan tidak diperlukan', 70),
(2025, 'F', 'Kelengkapan Readiness Criteria (RC)', 10, 'LAHAN_SESUAI', 'Lahan sesuai/bebas', 100),
(2025, 'F', 'Kelengkapan Readiness Criteria (RC)', 10, 'LAHAN_SIAP', 'Lahan siap (deklarasi Pemda)', 100),
(2025, 'F', 'Kelengkapan Readiness Criteria (RC)', 10, 'LAHAN_DISIAPKAN_BALAI', 'Lahan sedang disiapkan Balai', 35),
(2025, 'F', 'Kelengkapan Readiness Criteria (RC)', 10, 'LAHAN_TIDAK_SESUAI', 'Lahan tidak sesuai', 0),
(2025, 'F', 'Kelengkapan Readiness Criteria (RC)', 10, 'LAHAN_TIDAK_SIAP', 'Lahan tidak siap', 0),
(2025, 'F', 'Kelengkapan Readiness Criteria (RC)', 10, 'LAHAN_TIDAK_PERLU', 'Lahan tidak diperlukan', 100);

-- C (Kemanfaatan) dan E (Keberlanjutan Usulan IJD Sebelumnya) sengaja tidak
-- diisi kaidahnya di sini — belum ada sumber data (kepadatan penduduk/LHR/
-- produktivitas lahan untuk C; riwayat usulan IJD tahun sebelumnya untuk E).
-- _compute_ijd_score() akan melaporkan kedua parameter ini sebagai
-- "belum tersedia" dan mengecualikannya dari skor, bukan menilainya 0.
