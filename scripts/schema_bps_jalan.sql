-- Panjang jalan per kab/kota dari BPS "Dalam Angka 2026" bab 8 Transportasi:
--   - Tabel 8.1.1 "Panjang Jalan Menurut Tingkat Kewenangan Pemerintahan"
--     (km; baris Negara/Provinsi/Kabupaten|Kota + Jumlah, kolom 2023-2025 --
--     diambil tahun terakhir) -> panjang_*_km
--   - Tabel 8.1.3 "Panjang Jalan (Kabupaten) Menurut Kondisi Jalan"
--     (baris Baik/Sedang/Rusak/Rusak Berat + Jumlah) -> kondisi_*_km.
--     CATATAN CAKUPAN: umumnya hanya jalan kewenangan kab/kota ybs.
--     (kondisi_total_km ~= panjang_kabkota_km), bukan seluruh jalan wilayah.
-- Diisi scripts/extract_dalam_angka.py --load (tabel juga di-CREATE dari
-- sana). Kegunaan: pembanding independen kemantapan_ijd_2026 (sheet
-- "Kumpulan Data" baris 39, file 2_Analisis Prioritas 15.7.2026.xlsx) dan
-- kandidat komponen A1 panjang jalan pada pagu indikatif provinsi.
-- Kemantapan versi BPS bisa diturunkan: (baik+sedang)/total.
--
-- tidak_mantap_pct_ijd -- kolom L "Tidak mantap (%)" sheet IJD-26 pada
-- docs/docs/5_IJD 2026 - DATA (Kemantapan Jalan per Kab-Kota).xlsx (sumber
-- resmi, beda dari kondisi_*_km di atas yang hasil ekstraksi PDF BPS) --
-- dititip di sini sbg pembanding independen, diisi oleh
-- scripts/import_kemantapan_ijd2026.py (baris jenis_adm Kab./Kota saja,
-- matched by kode_kab; skrip yang sama juga mengisi kemantapan_ijd_2026).

USE route_gis;

CREATE TABLE IF NOT EXISTS bps_kabupaten_jalan (
  kode_kab   CHAR(4)     NOT NULL,   -- kode BPS kab/kota
  nama_kab   VARCHAR(60) NOT NULL,
  tahun      SMALLINT    NOT NULL,   -- tahun kolom terakhir tabel (umumnya 2025)
  panjang_negara_km      DECIMAL(10,2) NULL,
  panjang_provinsi_km    DECIMAL(10,2) NULL,
  panjang_kabkota_km     DECIMAL(10,2) NULL,
  panjang_total_km       DECIMAL(10,2) NULL,
  kondisi_baik_km        DECIMAL(10,2) NULL,
  kondisi_sedang_km      DECIMAL(10,2) NULL,
  kondisi_rusak_km       DECIMAL(10,2) NULL,
  kondisi_rusak_berat_km DECIMAL(10,2) NULL,
  kondisi_total_km       DECIMAL(10,2) NULL,
  tidak_mantap_pct_ijd   DECIMAL(6,2) NULL,
  PRIMARY KEY (kode_kab, tahun)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
