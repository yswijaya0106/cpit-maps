-- Indeks Penanaman (IP) per kabupaten/kota — sub-parameter C.A2 (11% dari
-- bobot A2, Tabel 4 dokumen 14072026 hal.3) yang sebelumnya belum ada
-- sumber data ("Indeks Penanaman tidak dipublikasikan BPS" —
-- schema_bps_kemanfaatan.sql). Ditemukan di docs/docs/Kertas Kerja.xlsx
-- sheet "Kertas Kerja" (BUKAN sheet "Master Data"/"3. Master Data" yang
-- disebut sheet Kumpulan Data (2_Analisis Prioritas...15.7.2026.xlsx, baris
-- 30, "Luas Lahan Baku Sawah (LBS) 2024 ... Kolom V ... Sheet Master Data").
-- Diverifikasi ulang 19 Jul 2026: nama SHEET di Kumpulan Data salah catat
-- (kolom "LBS" di sheet " Master Data" ada di kolom M, isinya 0/kosong di
-- semua 553 baris — bukan kolom V; kolom V di sheet itu ternyata "IRIGASI
-- PU", flag lain sama sekali). Tapi KOLOM-nya (V) benar kalau merujuk ke
-- sheet "Kertas Kerja" yang berbeda — di situ kolom V (indeks 21, 0-based)
-- persis "Lahan Baku Sawah (2024)" dgn nilai riil non-nol. Jadi tabel ini
-- bersumber sheet "Kertas Kerja" kolom V, BUKAN sheet "Master Data" seperti
-- tertulis di Kumpulan Data (kombinasi kolom-benar/sheet-salah, bukan
-- kolom-salah) — pelajaran: rujukan sheet/kolom di Kumpulan Data perlu
-- diverifikasi manual per kasus, jangan dipercaya apa adanya (sama dgn
-- temuan BBM 1 Harga yang nama sheetnya juga meleset).
-- Kolom C-KD (indeks 3) = kode kabupaten BPS; kolom "Indeks Penanaman"
-- (indeks 22, nilai numerik %) + kategori (indeks 23, mis. "IP 100-150");
-- baris kode berakhiran 00 = total provinsi, DILEWATI saat impor.
--
-- lahan_baku_sawah_ha (kolom "Lahan Baku Sawah (2024)", indeks 21 = kolom V)
-- DISIMPAN utk referensi tapi SENGAJA TIDAK dipakai skoring C.A2 "Luas
-- Lahan (12%)": nilainya level KABUPATEN (ratusan-ribuan ha), sementara
-- ambang resmi Tabel 4 (>500ha=100 ... <=25ha=20) jelas dirancang utk skala
-- jauh lebih kecil (per-usulan/kecamatan) — kalau dipaksa pakai skala
-- kabupaten, hampir semua kabupaten otomatis kena >500ha=100, tidak
-- diskriminatif. Sumber datanya sendiri (kolom "Sumber"=Dit. PP di
-- Kumpulan Data, header sheet tag "LP2B") = kompilasi Perda LP2B (Lahan
-- Pertanian Pangan Berkelanjutan) per kabupaten/kota tahun 2024 — penetapan
-- level kabupaten memang begitu adanya di Perda-nya, bukan keterbatasan
-- ekstraksi kita.
-- Diisi scripts/import_kertas_kerja.py.

USE route_gis;

CREATE TABLE IF NOT EXISTS bps_kabupaten_indeks_penanaman (
  kode_kab              CHAR(4)      NOT NULL,
  nama_kab              VARCHAR(60)  NOT NULL,
  tahun                 SMALLINT     NOT NULL,   -- tahun tersirat dari label "LBS 2024" berdampingan (sumber tak eksplisit sebut tahun IP)
  indeks_penanaman_pct  DECIMAL(7,2) NULL,        -- persen, mis. 148.51 = 148,51%
  kategori_sumber       VARCHAR(20)  NULL,        -- label kategori dari sumber (mis. "IP 100-150"), disimpan APA ADANYA, bukan dasar skoring (skoring pakai ambang Tabel 4 sendiri)
  lahan_baku_sawah_ha   DECIMAL(12,2) NULL,       -- referensi saja, TIDAK dipakai skoring (lihat catatan di atas)
  PRIMARY KEY (kode_kab, tahun)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
