-- Indeks Penanaman dari raster resmi Dit. SDA (Maps/IP2019-2024/*.tif) --
-- SUMBER PRIMER yg dirujuk sheet Kumpulan Data baris 31 ("SHP Indeks
-- Penanaman", ternyata dikirim sbg GeoTIFF raster, bukan format SHP spt
-- tertulis -- pola yg sama dgn temuan mismatch dokumen sebelumnya).
-- Diisi scripts/import_indeks_penanaman_raster.py (zonal statistics modus
-- piksel per kabupaten/kota, poligon dibangun dgn dissolve BATAS
-- KECAMATAN). BEDA dari bps_kabupaten_indeks_penanaman (Kertas Kerja.xlsx,
-- sumber SEKUNDER, persentase kontinu) -- tabel ini sumber resmi tapi cuma
-- 3 kelas kasar (1x/2x/3x tanam per tahun), lihat docstring importer utk
-- pemetaan ke ambang Tabel 4.

USE route_gis;

CREATE TABLE IF NOT EXISTS bps_kabupaten_indeks_penanaman_raster (
  kode_kab        CHAR(4)     NOT NULL,
  tahun           SMALLINT    NOT NULL,
  kelas_tanam     TINYINT     NOT NULL,   -- 1/2/3 = tanam 1x/2x/3x per tahun (piksel modus)
  bucket_ip       VARCHAR(10) NOT NULL,   -- '100-150' / '150-199' / 'GT300' -- lihat KELAS_TO_BUCKET
  n_piksel_valid  INT UNSIGNED NOT NULL,  -- jumlah piksel non-nol dlm poligon (indikasi keyakinan)
  PRIMARY KEY (kode_kab, tahun)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
