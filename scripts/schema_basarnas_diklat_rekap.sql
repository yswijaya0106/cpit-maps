-- Rekap tahunan kapasitas diklat SAR nasional 2021-2025 -- gabungan 2
-- sumber kecil (docs/New/6. BASARNAS/7. Peserta Pendidikan dan
-- Pelatihan SAR/Rekapitulasi Pelatihan 2021-2025.xlsx dan
-- 8. Tenaga Pendidik.../..2021-2025.xlsx, masing-masing cuma 5 baris
-- agregat nasional per tahun, tanpa dimensi kabupaten/kantor SAR) ke
-- satu tabel (bukan dua) karena dimensi tahunnya sama & keduanya
-- sama-sama menggambarkan kapasitas kelembagaan diklat.
--
-- Diisi scripts/import_basarnas_diklat_rekap.py. Lihat
-- docs/kajian_data_baru_docs_new.md §8.6. TIDAK terkait usulan_inpres/IJD.

CREATE TABLE IF NOT EXISTS basarnas_diklat_rekap (
  tahun                  SMALLINT PRIMARY KEY,
  jumlah_kegiatan        INTEGER,
  jumlah_peserta         INTEGER,
  jumlah_tenaga_pendidik INTEGER,
  imported_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
