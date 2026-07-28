-- Kaidah skoring "Prioritisasi Teknokratik" IJD versi 14 Juli 2026, dari
-- docs/docs/F. Parameter Penilaian IJD [FULL] 14072026.pdf (Tabel 1-6).
-- Menambah baris tahun_berlaku=2026 ke tabel ijd_scoring_rules yang dibuat
-- scripts/schema_ijd_scoring.sql (rules 2025 dibiarkan utuh sebagai histori).
-- Idempoten: aman dijalankan ulang (ON DUPLICATE KEY UPDATE).
--
-- Perubahan vs kaidah 2025 (BF/SD):
--   * Tabel 1: bobot C (Kemanfaatan) 20 -> 25, D (Koridor) 15 -> 20,
--     F (Readiness Criteria) DIHAPUS dari penilaian, E (Penuntasan IJD 2025)
--     masuk resmi dengan bobot 10. Total tetap 100.
--   * Parameter A kini eksplisit A = A1(40%) + A2(30%) + A3(20%) + A4(10%).
--     Kolom `nilai` di bawah DISIMPAN SUDAH TERTIMBANG ke skala 0-100
--     parameter A (mis. A1 "Pertanian" 100 x 40% = 40.0), karena satu usulan
--     SITIA hanya membawa satu string tematik_kawasan_pemda — A3 (tematik
--     tambahan) & A4 (data dukung) butuh data gdrive yang belum diimpor
--     (gap G2/G18). Ini beda dengan seed 2025 yang menyimpan nilai mentah
--     0-100 dan memperlakukan satu tematik sebagai seluruh parameter A.
--   * Nilai A1 banyak naik: Perkebunan/Perikanan/Peternakan 60 -> 100,
--     Energi Terbarukan & BBM Satu Harga 75 -> 100, Transmigrasi 50 -> 75.
--   * "Kawasan Strategis Daerah" tidak ada lagi di daftar A1 2026 (hanya di
--     A3, nilai 50 bobot 20%) — tetap di-seed sebagai pendekatan 50 x 20% =
--     10.0 supaya usulan SITIA berkategori itu tidak jatuh ke "tidak dikenali".
--   * D (Tabel 5) kini 3 tingkat: teridentifikasi 100, koridor lainnya 50,
--     bukan/tidak ada informasi koridor 0. Proksi kode_koridor hanya bisa
--     membedakan terisi/kosong, jadi kosong dipetakan ke tingkat terbawah (0).
--
-- C (Kemanfaatan, bobot 25) di-seed di bawah untuk sub-parameter A1
-- (kepadatan penduduk kecamatan, bobot internal 35%) — dihitung
-- _ijd_score_kemanfaatan() dari kecamatan_data_turunan via
-- usulan_inpres.kode_kecamatan. Sub A2 (produktivitas, 35%) dan A3 (lalu
-- lintas, 30%) menunggu data (gap G4/G5). E (Penuntasan) di-seed di bawah
-- dan dihitung _ijd_score_penuntasan() dari flag resmi SITIA / pencocokan
-- scripts/import_dpp_ijd_2025.py.

USE route_gis;

-- A. Tematik dan Data Dukungnya (bobot 30) — Tabel 2 dokumen 14072026.
-- sub_kode = string kolom tematik_kawasan_pemda SITIA apa adanya (termasuk
-- typo "Pekerbunan" yang memang begitu di data SITIA).
-- nilai = skor tabel x bobot sub-parameter (A1 40% / A2 30% / A3 20%).
INSERT INTO ijd_scoring_rules (tahun_berlaku, parameter_kode, parameter_label, bobot_maks, sub_kode, kondisi_label, nilai) VALUES
(2026, 'A', 'Tematik dan Data Dukungnya', 30, 'Swasembada Pangan - Pertanian', 'A1 Swasembada Pangan - Pertanian (100 x 40%)', 40.0),
(2026, 'A', 'Tematik dan Data Dukungnya', 30, 'Swasembada Pangan - Perkebunan', 'A1 Swasembada Pangan - Perkebunan (100 x 40%)', 40.0),
(2026, 'A', 'Tematik dan Data Dukungnya', 30, 'Swasembada Pangan - Perikanan', 'A1 Swasembada Pangan - Perikanan (100 x 40%)', 40.0),
(2026, 'A', 'Tematik dan Data Dukungnya', 30, 'Swasembada Pangan - Peternakan', 'A1 Swasembada Pangan - Peternakan (100 x 40%)', 40.0),
(2026, 'A', 'Tematik dan Data Dukungnya', 30, 'Swasembada Pangan - Kawasan Mendukung Program MBG', 'A1 Swasembada Pangan - Kawasan Mendukung Program MBG (75 x 40%)', 30.0),
(2026, 'A', 'Tematik dan Data Dukungnya', 30, 'Distribusi Energi - Pekerbunan yang mendukung Energi Terbarukan', 'A1 Distribusi Energi - Perkebunan mendukung Energi Terbarukan (100 x 40%)', 40.0),
(2026, 'A', 'Tematik dan Data Dukungnya', 30, 'Distribusi Energi - Mendukung Distribusi BBM satu harga', 'A1 Distribusi Energi - Mendukung Distribusi BBM Satu Harga (100 x 40%)', 40.0),
(2026, 'A', 'Tematik dan Data Dukungnya', 30, 'Kawasan Produktif Lainnya - Kawasan Transmigrasi', 'A1 Kawasan Produktif Lainnya - Kawasan Transmigrasi (75 x 40%)', 30.0),
(2026, 'A', 'Tematik dan Data Dukungnya', 30, 'Kawasan Produktif Lainnya - Kawasan Industri Prioritas', 'A1 Kawasan Produktif Lainnya - Kawasan Industri Prioritas RPJMN (50 x 40%)', 20.0),
(2026, 'A', 'Tematik dan Data Dukungnya', 30, 'Kawasan Produktif Lainnya - Kawasan Strategis Daerah', 'Pendekatan A3 Kawasan Strategis Daerah RTRW/RDTR (50 x 20%) — tidak ada di daftar A1 2026', 10.0),
(2026, 'A', 'Tematik dan Data Dukungnya', 30, 'Konektivitas - Terhubung Ke Status Lebih Tinggi (Jalan Nasional)', 'A2 Konektivitas - Terhubung ke Jalan Nasional (100 x 30%)', 30.0),
(2026, 'A', 'Tematik dan Data Dukungnya', 30, 'Konektivitas - Terhubung Ke Status Lebih Tinggi (Jalan Provinsi)', 'A2 Konektivitas - Terhubung ke Jalan Provinsi (75 x 30%)', 22.5),
(2026, 'A', 'Tematik dan Data Dukungnya', 30, 'Konektivitas - Terhubung Ke Simpul Transportasi', 'A2 Konektivitas - Terhubung ke Simpul Transportasi (75 x 30%)', 22.5)
ON DUPLICATE KEY UPDATE parameter_label=VALUES(parameter_label), bobot_maks=VALUES(bobot_maks), kondisi_label=VALUES(kondisi_label), nilai=VALUES(nilai);

-- A4. Data Dukung Tematik (bobot internal 10%) — Tabel 2 blok A4: data dukung
-- yang ada & relevan (KP2B/LP2B, surat BBM, perikanan/perkebunan) = 100.
-- Sumber: kolom SITIA "Jenis Data Dukung Tematik (Kompetensi)" (hasil
-- verifikasi kompetensi, terisi mulai tarikan 15 Juli). sub_kode berprefiks
-- "A4_" + status kolom apa adanya; dijumlahkan _ijd_score_tematik() ke nilai
-- A1/A2. NULL (belum dinilai kompetensi) tidak menambah nilai.
INSERT INTO ijd_scoring_rules (tahun_berlaku, parameter_kode, parameter_label, bobot_maks, sub_kode, kondisi_label, nilai) VALUES
(2026, 'A', 'Tematik dan Data Dukungnya', 30, 'A4_KP2B/LP2B', 'A4 Data dukung KP2B/LP2B — menjaga alih fungsi lahan (100 x 10%)', 10.0),
(2026, 'A', 'Tematik dan Data Dukungnya', 30, 'A4_SELAIN KP2B/LP2B', 'A4 Data dukung tematik selain KP2B/LP2B (100 x 10%)', 10.0),
(2026, 'A', 'Tematik dan Data Dukungnya', 30, 'A4_TIDAK ADA', 'A4 Tidak ada data dukung tematik (0 x 10%)', 0.0)
ON DUPLICATE KEY UPDATE parameter_label=VALUES(parameter_label), bobot_maks=VALUES(bobot_maks), kondisi_label=VALUES(kondisi_label), nilai=VALUES(nilai);

-- A3. Tematik Tambahan (bobot internal 20%) — Tabel 2 baris 14-23 dokumen
-- 14072026. PENTING: daftar resmi A3 mulai dari Perkebunan (item 14) —
-- "Pertanian" TIDAK ADA di A3 sama sekali (beda dari A1 yang punya
-- Pertanian sbg item 1). Sempat ditambahkan sub_kode A3_PERTANIAN by
-- ekstrapolasi (analogi ke A1) saat fitur potensi Dalam Angka dibangun,
-- lalu DIHAPUS setelah dicek ulang persis terhadap Tabel 2 PDF — supaya
-- kaidah aplikasi tidak menyimpang dari dokumen resmi. Kalau kelak memang
-- perlu dimasukkan, itu keputusan kebijakan (bukan bug baca dokumen),
-- konfirmasi ke pemilik kaidah dulu.
--
-- DUA sumber independen, dicocokkan sekaligus oleh _ijd_score_tematik()
-- (nilai tertinggi dipakai bila cocok >1 kategori DAN >1 sumber):
--   (a) tabel kawasan_tematik (scripts/import_kawasan_tematik.py, data lokus
--       Bappenas) -- cakupan Perkebunan/Perikanan/Transmigrasi/KI Prioritas/
--       PKPN, dicocokkan by kabupaten/kecamatan.
--   (b) kecamatan_data_turunan.potensi_* (scripts/extract_dalam_angka.py,
--       Tabel 5.3.1/5.4.1/5.5.x BPS Dalam Angka -- flag ada/tidak produksi
--       sektoral per kecamatan) -- cakupan Perkebunan/Peternakan/Perikanan,
--       PARSIAL (baru provinsi yang bukunya ada di dalam_angka/ DAN pola
--       tabelnya sudah dikenali ekstraktor). potensi_pertanian TETAP
--       diekstrak & disimpan (dipakai tampilan viewer "Data"), tapi
--       SENGAJA tidak dicocokkan ke skor A3 di sini.
-- sub_kode = "A3_<kategori>". Kategori MBG, ENERGI_TERBARUKAN, BBM_SATU_HARGA,
-- dan KAWASAN_STRATEGIS masih belum ada sumber datanya sama sekali (bukan
-- statistik BPS, bukan sheet lokus Bappenas yang tersedia).
INSERT INTO ijd_scoring_rules (tahun_berlaku, parameter_kode, parameter_label, bobot_maks, sub_kode, kondisi_label, nilai) VALUES
(2026, 'A', 'Tematik dan Data Dukungnya', 30, 'A3_PERKEBUNAN', 'A3 Swasembada Pangan - Perkebunan (100 x 20%)', 20.0),
(2026, 'A', 'Tematik dan Data Dukungnya', 30, 'A3_PETERNAKAN', 'A3 Swasembada Pangan - Peternakan (100 x 20%)', 20.0),
(2026, 'A', 'Tematik dan Data Dukungnya', 30, 'A3_PERIKANAN', 'A3 Swasembada Pangan - Perikanan (100 x 20%)', 20.0),
(2026, 'A', 'Tematik dan Data Dukungnya', 30, 'A3_TRANSMIGRASI', 'A3 Kawasan Produktif Lainnya - Kawasan Transmigrasi (75 x 20%)', 15.0),
(2026, 'A', 'Tematik dan Data Dukungnya', 30, 'A3_KI_PRIORITAS', 'A3 Kawasan Produktif Lainnya - Kawasan Industri Prioritas RPJMN (50 x 20%)', 10.0),
(2026, 'A', 'Tematik dan Data Dukungnya', 30, 'A3_PKPN', 'A3 Kawasan Produktif Lainnya - Kawasan Mendukung PKPN (25 x 20%)', 5.0)
ON DUPLICATE KEY UPDATE parameter_label=VALUES(parameter_label), bobot_maks=VALUES(bobot_maks), kondisi_label=VALUES(kondisi_label), nilai=VALUES(nilai);

-- B. Kondisi Kemantapan Eksisting Ruas (bobot 15) — Tabel 3, tidak berubah
-- dari 2025.
INSERT INTO ijd_scoring_rules (tahun_berlaku, parameter_kode, parameter_label, bobot_maks, sub_kode, kondisi_label, nilai) VALUES
(2026, 'B', 'Kondisi Kemantapan Eksisting Ruas', 15, 'TIDAK_MANTAP', 'Kemantapan ruas < 60% (mayoritas rusak)', 100),
(2026, 'B', 'Kondisi Kemantapan Eksisting Ruas', 15, 'MANTAP', 'Kemantapan ruas > 60%', 60),
(2026, 'B', 'Kondisi Kemantapan Eksisting Ruas', 15, 'PEMBANGUNAN', 'Pembangunan jalan/jembatan baru', 40)
ON DUPLICATE KEY UPDATE parameter_label=VALUES(parameter_label), bobot_maks=VALUES(bobot_maks), kondisi_label=VALUES(kondisi_label), nilai=VALUES(nilai);

-- D. Koridor (bobot 20) — Tabel 5, EMPAT tingkat sejak 28 Jul 2026 (request
-- eksplisit user, promosi _ijd_score_koridor_v2 jadi resmi -- lihat
-- CLAUDE.md & docs/analisa_kerangka_penggunaan_data_cpit_270726.md §8).
-- Sumber utama TERIDENTIFIKASI/LAINNYA_BALAI/LAINNYA: kolom Status Koridor
-- Prioritas Balai (tarikan 15 Juli): SESUAI -> TERIDENTIFIKASI, TIDAK SESUAI
-- -> LAINNYA_BALAI (tingkat tengah "koridor lainnya" = 50). Usulan tanpa
-- penilaian Balai jatuh ke proksi kode_koridor: cocok ke bappenas_koridor
-- ATAU terisi -> TERIDENTIFIKASI, kosong -> LAINNYA (0).
-- TIDAK_LANGSUNG (75) BUKAN dari Tabel 5 PDF resmi (14072026) -- sumbernya
-- kerangka CPIT 27.7.26 sheet "D. KORIDOR" ("mendukung koridor tidak
-- langsung ... diambil dari shp koridor terhubung dengan radius <50m").
-- Dicek di _ijd_score_koridor_v2() via ST_DWithin thd map_layers layer
-- 'PETA KORIDOR' (scripts/import_peta_koridor_to_postgis.py), SETELAH match
-- langsung kode_koridor->bappenas_koridor dan SEBELUM fallback Balai/proksi.
INSERT INTO ijd_scoring_rules (tahun_berlaku, parameter_kode, parameter_label, bobot_maks, sub_kode, kondisi_label, nilai) VALUES
(2026, 'D', 'Koridor', 20, 'TERIDENTIFIKASI', 'Bagian dari koridor yang telah diidentifikasi', 100),
(2026, 'D', 'Koridor', 20, 'TIDAK_LANGSUNG', 'Koridor tidak langsung (radius <50m dari shp Peta Koridor)', 75),
(2026, 'D', 'Koridor', 20, 'LAINNYA_BALAI', 'Koridor lainnya (Balai: tidak sesuai koridor prioritas)', 50),
(2026, 'D', 'Koridor', 20, 'LAINNYA', 'Bukan / tidak ada informasi koridor', 0)
ON DUPLICATE KEY UPDATE parameter_label=VALUES(parameter_label), bobot_maks=VALUES(bobot_maks), kondisi_label=VALUES(kondisi_label), nilai=VALUES(nilai);

-- C. Kemanfaatan (bobot 25) — Tabel 4, baru sub-parameter A1 Jumlah Penduduk
-- Kecamatan (bobot internal 35%). Seperti parameter A, nilai DISIMPAN SUDAH
-- TERTIMBANG ke skala 0-100 parameter C (mis. kepadatan >1000/km2: 100 x 35%
-- = 35.0). Ambang kepadatan diterapkan _ijd_score_kemanfaatan() di app.py;
-- sub_kode di sini hanya kunci tingkatannya.
INSERT INTO ijd_scoring_rules (tahun_berlaku, parameter_kode, parameter_label, bobot_maks, sub_kode, kondisi_label, nilai) VALUES
(2026, 'C', 'Kemanfaatan', 25, 'A1_GT1000', 'Kepadatan > 1.000 jiwa/km2 — perkotaan padat (100 x 35%)', 35.0),
(2026, 'C', 'Kemanfaatan', 25, 'A1_500_1000', 'Kepadatan 500-1.000 jiwa/km2 — cukup padat (75 x 35%)', 26.25),
(2026, 'C', 'Kemanfaatan', 25, 'A1_100_500', 'Kepadatan 100-500 jiwa/km2 — transisi desa-kota (50 x 35%)', 17.5),
(2026, 'C', 'Kemanfaatan', 25, 'A1_LT100', 'Kepadatan < 100 jiwa/km2 — jarang penduduk (25 x 35%)', 8.75)
ON DUPLICATE KEY UPDATE parameter_label=VALUES(parameter_label), bobot_maks=VALUES(bobot_maks), kondisi_label=VALUES(kondisi_label), nilai=VALUES(nilai);

-- C.A2 Produktivitas (Ton/Ha), sub dari "A2. Produktivitas Bobot=35%" (Tabel 4:
-- Indeks Penanaman 11% + Produktivitas(Ton/Ha) 12% + Luas Lahan 12%). Hanya
-- sub "Produktivitas (Ton/Ha)" yang diseed di sini — proksi dari produksi
-- padi kabupaten (bps_kabupaten_padi.produktivitas_ku_ha, scripts/
-- extract_dalam_angka.py, level KABUPATEN bukan kecamatan, hanya komoditas
-- padi bukan "produktivitas" umum). Luas Lahan (12%, butuh Kertas Kerja LBS
-- 2024 Dit. PP — datanya level kabupaten, skala tak cocok ambang resmi
-- yang jelas dirancang utk skala kecil, lihat schema_kertas_kerja.sql)
-- SENGAJA belum diseed. Nilai DISIMPAN SUDAH TERTIMBANG ke skala 0-100
-- parameter C (mis. >6 ton/ha: 100 x 12% = 12.0). Ambang produktivitas
-- (ku/ha, 1 ton = 10 ku) diterapkan di _ijd_score_kemanfaatan() app.py.
INSERT INTO ijd_scoring_rules (tahun_berlaku, parameter_kode, parameter_label, bobot_maks, sub_kode, kondisi_label, nilai) VALUES
(2026, 'C', 'Kemanfaatan', 25, 'A2_GT6', 'Produktivitas padi > 6 ton/ha (100 x 12%)', 12.0),
(2026, 'C', 'Kemanfaatan', 25, 'A2_5_6', 'Produktivitas padi 5-6 ton/ha (80 x 12%)', 9.6),
(2026, 'C', 'Kemanfaatan', 25, 'A2_4_5', 'Produktivitas padi 4-4,9 ton/ha (60 x 12%)', 7.2),
(2026, 'C', 'Kemanfaatan', 25, 'A2_3_4', 'Produktivitas padi 3-3,9 ton/ha (40 x 12%)', 4.8),
(2026, 'C', 'Kemanfaatan', 25, 'A2_LT3', 'Produktivitas padi < 3 ton/ha (20 x 12%)', 2.4)
ON DUPLICATE KEY UPDATE parameter_label=VALUES(parameter_label), bobot_maks=VALUES(bobot_maks), kondisi_label=VALUES(kondisi_label), nilai=VALUES(nilai);

-- C.A2 Indeks Penanaman (IP, 11% dari 35% A2) — Tabel 4 dokumen 14072026
-- hal.3: ">100-199%"(40) tumpang-tindih dgn ">150-199%"(60) & ">200-299%"
-- (80), jelas TYPO di dokumen sumber (kategori sumber Kertas Kerja.xlsx
-- sendiri pakai bucket tak-tumpang-tindih "IP<100"/"IP100-150"/dst) —
-- di sini bucket 40% DIBACA ">100-150%" (bukan ">100-199%" apa adanya)
-- supaya lima tingkat tidak overlap. Sumber: docs/docs/Kertas Kerja.xlsx
-- sheet "Kertas Kerja" kolom "Indeks Penanaman" (level KABUPATEN, diimpor
-- scripts/import_kertas_kerja.py -> bps_kabupaten_indeks_penanaman).
-- Nilai DISIMPAN SUDAH TERTIMBANG (mis. >300%: 100 x 11% = 11.0). Ambang
-- diterapkan _ijd_score_kemanfaatan() app.py.
INSERT INTO ijd_scoring_rules (tahun_berlaku, parameter_kode, parameter_label, bobot_maks, sub_kode, kondisi_label, nilai) VALUES
(2026, 'C', 'Kemanfaatan', 25, 'A2IP_GT300', 'Indeks Penanaman > 300% — tanam >=3x/tahun (100 x 11%)', 11.0),
(2026, 'C', 'Kemanfaatan', 25, 'A2IP_200_300', 'Indeks Penanaman 200-299% — tanam 2-3x/tahun (80 x 11%)', 8.8),
(2026, 'C', 'Kemanfaatan', 25, 'A2IP_150_200', 'Indeks Penanaman 150-199% — tanam 1,5-2x/tahun (60 x 11%)', 6.6),
(2026, 'C', 'Kemanfaatan', 25, 'A2IP_100_150', 'Indeks Penanaman 100-149% — tanam 1x/tahun (40 x 11%)', 4.4),
(2026, 'C', 'Kemanfaatan', 25, 'A2IP_LT100', 'Indeks Penanaman < 100% — belum tanam optimal (20 x 11%)', 2.2)
ON DUPLICATE KEY UPDATE parameter_label=VALUES(parameter_label), bobot_maks=VALUES(bobot_maks), kondisi_label=VALUES(kondisi_label), nilai=VALUES(nilai);

-- C.A3 Lalu Lintas (bobot 30%, Tabel 4 dokumen 14072026 halaman 4) — dua opsi
-- ukur: LHR (diutamakan dokumen, tapi "sedang diminta"/G5, belum ada sumber
-- nasional) dan Kepemilikan Kendaraan per km jalan (dokumen: "*Apabila
-- tidak didapatkan data kepemilikan kendaraan maka dapat menggunakan rasio
-- dari data kepemilikan kendaraan per kabupaten" — jadi rasio KABUPATEN
-- resmi jadi fallback, bukan proksi liar). Hanya Kepemilikan Kendaraan yang
-- diseed di sini, memakai SELURUH bobot A3 (30%) sebagai substitusi
-- sementara LHR (pola sama dgn CPIT "Kumpulan Data" baris 60: "untuk saat
-- ini menggunakan data kepemilikan kendaraan dengan bobot 100"). Kendaraan
-- per km = bps_kabupaten_kendaraan.jumlah ÷ bps_kabupaten_jalan.panjang_total_km
-- (keduanya dari scripts/extract_dalam_angka.py, level KABUPATEN). LHR asli
-- SENGAJA belum diseed — tidak ada sumber data nasional. Nilai DISIMPAN
-- SUDAH TERTIMBANG ke skala 0-100 parameter C (mis. >1.000/km: 100 x 30% =
-- 30.0). Ambang diterapkan di _ijd_score_kemanfaatan() app.py.
INSERT INTO ijd_scoring_rules (tahun_berlaku, parameter_kode, parameter_label, bobot_maks, sub_kode, kondisi_label, nilai) VALUES
(2026, 'C', 'Kemanfaatan', 25, 'A3_GT1000', 'Kepemilikan kendaraan > 1.000/km — potensi kemacetan berat (100 x 30%)', 30.0),
(2026, 'C', 'Kemanfaatan', 25, 'A3_600_1000', 'Kepemilikan kendaraan 600-1.000/km — butuh peningkatan kapasitas (80 x 30%)', 24.0),
(2026, 'C', 'Kemanfaatan', 25, 'A3_300_600', 'Kepemilikan kendaraan 300-600/km — mulai padat (60 x 30%)', 18.0),
(2026, 'C', 'Kemanfaatan', 25, 'A3_100_300', 'Kepemilikan kendaraan 100-300/km — kondisi normal (40 x 30%)', 12.0),
(2026, 'C', 'Kemanfaatan', 25, 'A3_LT100', 'Kepemilikan kendaraan < 100/km — jalan sangat longgar (20 x 30%)', 6.0)
ON DUPLICATE KEY UPDATE parameter_label=VALUES(parameter_label), bobot_maks=VALUES(bobot_maks), kondisi_label=VALUES(kondisi_label), nilai=VALUES(nilai);

-- E. Kegiatan IJD Sebelumnya / Penuntasan (bobot 10) — Tabel 6. Basis per
-- ruas: cocok dengan kegiatan DPP IJD TA 2025 (tabel dpp_ijd_2025) = lanjutan.
INSERT INTO ijd_scoring_rules (tahun_berlaku, parameter_kode, parameter_label, bobot_maks, sub_kode, kondisi_label, nilai) VALUES
(2026, 'E', 'Kegiatan IJD Sebelumnya (Penuntasan)', 10, 'LANJUTAN', 'Lanjutan / Penuntasan IJD TA 2025', 100),
(2026, 'E', 'Kegiatan IJD Sebelumnya (Penuntasan)', 10, 'BARU', 'Usulan baru', 0)
ON DUPLICATE KEY UPDATE parameter_label=VALUES(parameter_label), bobot_maks=VALUES(bobot_maks), kondisi_label=VALUES(kondisi_label), nilai=VALUES(nilai);

-- F sengaja TIDAK di-seed untuk 2026 — dihapus dari penilaian per dokumen
-- 14072026. _compute_ijd_score() menampilkan parameter mengikuti kaidah tahun
-- terpilih, jadi F otomatis hilang dari hasil skor 2026.
