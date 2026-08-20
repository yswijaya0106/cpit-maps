-- Matriks Origin-Destination (OD) penumpang LRT Jabodebek 2025, per
-- bulan (docs/New/4. KERETA (KA)/OD LRT Jabodebek 2025.xlsx, sheet
-- "2025") -- disimpan format long/tidy (bulan x asal x tujuan), bukan
-- matriks 18x18 lebar, supaya query per-stasiun/per-bulan langsung
-- tanpa perlu unpivot manual.
--
-- Cakupan LOKAL (satu sistem LRT Jabodebek), bukan nasional -- nilai
-- analitiknya rendah untuk aplikasi berskala nasional ini (lihat
-- docs/kajian_data_baru_docs_new.md §6.1), tapi tetap diimpor sebagai
-- referensi jika suatu saat dibutuhkan analitik transit perkotaan
-- Jabodetabek. Hanya 10 bulan (Januari-Oktober) yang diimpor -- blok
-- "Rata-Rata" di sumber (rata-rata Jan-Okt) SENGAJA dilewati (redundan
-- dgn 10 bulan yang sudah ada), begitu juga 2 blok trailing di akhir
-- sheet sumber ("O/D" tanpa label bulan & "O/D (Jarak dalam km)") yang
-- ternyata BUKAN data ridership bulanan -- satu daftar stasiun urutan
-- beda tanpa data, satu lagi matriks JARAK ANTAR STASIUN (km statis,
-- bukan jumlah penumpang) -- keduanya di luar cakupan tabel ini.
--
-- Diisi scripts/import_od_lrt_jabodebek.py. TIDAK terkait
-- usulan_inpres/IJD.

CREATE TABLE IF NOT EXISTS od_lrt_jabodebek (
  id                BIGSERIAL PRIMARY KEY,
  tahun             SMALLINT NOT NULL,
  bulan             TEXT NOT NULL,
  stasiun_asal      TEXT NOT NULL,
  stasiun_tujuan    TEXT NOT NULL,
  jumlah_penumpang  NUMERIC(12, 2),
  imported_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tahun, bulan, stasiun_asal, stasiun_tujuan)
);
