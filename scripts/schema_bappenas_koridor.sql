-- Daftar Koridor Bappenas Admin (docs/docs/Daftar_Koridor_Bappenas_Admin_
-- 20260721141822.xlsx, sheet "Worksheet") -- master data KORIDOR (bukan
-- ruas/usulan) dari SITIA + anotasi Bappenas: klasifikasi tematik, produksi
-- komoditas per koridor (s.d. 4 komoditas), status konektivitas, jumlah
-- fasilitas umum dilewati, dan peringkat prioritas kab/kota & provinsi.
-- id_koridor = ID SITIA (lihat URL kolom Map Koridor
-- ".../koridor_utama/show_map/<id_koridor>/...") -- key alami, unik per
-- baris (2692 koridor pada snapshot 21 Jul 2026).
--
-- Granularitas KORIDOR, bukan ruas -- kolom "ID Ruas"/"No. Ruas Unique"/
-- "Nama Ruas"/"Status Jalan"/"Kecamatan"/"Map Ruas"/"Map Awal Ruas" pada
-- file sumber selalu "---" (placeholder template ruas-detail yang tidak
-- terisi di export level-koridor ini) -- sengaja TIDAK diimpor.
--
-- kode_kab dicari via pencocokan (provinsi, kabupaten_kota) thd
-- wilayah_mapping.(provinsi_sitia, kabupaten_kota_sitia) -- format sumber
-- sudah sama persis (mis. "ACEH" / "KABUPATEN ACEH BARAT"), tanpa perlu
-- normalisasi tambahan.
--
-- Diisi scripts/import_bappenas_koridor.py.

USE route_gis;

CREATE TABLE IF NOT EXISTS bappenas_koridor (
  id_koridor                INT           NOT NULL,
  provinsi                  VARCHAR(100)  NULL,
  kabupaten_kota             VARCHAR(80)   NULL,
  kode_kab                  CHAR(4)       NULL,       -- via wilayah_mapping, NULL kalau tidak match
  no_koridor                 VARCHAR(30)   NULL,
  nama_koridor               VARCHAR(255)  NULL,
  rpjmn                      VARCHAR(100)  NULL,       -- label klasifikasi lokus RPJMN/PHJD/RC, apa adanya dari sumber
  tematik                    VARCHAR(255)  NULL,
  kspp                       VARCHAR(255)  NULL,       -- Kawasan Sentra Produksi Pangan/kawasan strategis terkait, kalau ada
  jenis_produksi              VARCHAR(100)  NULL,
  status_pengajuan            VARCHAR(40)   NULL,       -- 'Menunggu Persetujuan SSPJJ' | 'Disetujui SSPJJ' | 'Ditolak'
  disetujui_ditolak_oleh      VARCHAR(120)  NULL,       -- nama Balai/Direktur SSPJJ, NULL kalau belum diputuskan
  panjang_km                  DECIMAL(10,3) NULL,
  baik_km                     DECIMAL(10,3) NULL,
  sedang_km                   DECIMAL(10,3) NULL,
  rusak_ringan_km              DECIMAL(10,3) NULL,
  rusak_berat_km               DECIMAL(10,3) NULL,
  biaya_rp_miliar              DECIMAL(14,3) NULL,
  tematik_utama                VARCHAR(255)  NULL,
  tematik_tambahan_1            VARCHAR(255)  NULL,
  tematik_tambahan_2            VARCHAR(255)  NULL,
  -- s.d. 4 slot komoditas/produksi per koridor (jenis + luas lahan + jumlah produksi/tahun)
  jenis_produksi_1              VARCHAR(100)  NULL,
  luas_lahan_1_ha                DECIMAL(12,2) NULL,
  jumlah_produksi_1_ton           DECIMAL(14,2) NULL,
  jenis_produksi_2              VARCHAR(100)  NULL,
  luas_lahan_2_ha                DECIMAL(12,2) NULL,
  jumlah_produksi_2_ton           DECIMAL(14,2) NULL,
  jenis_produksi_3              VARCHAR(100)  NULL,
  luas_lahan_3_ha                DECIMAL(12,2) NULL,
  jumlah_produksi_3_ton           DECIMAL(14,2) NULL,
  jenis_produksi_4              VARCHAR(100)  NULL,
  luas_lahan_4_ha                DECIMAL(12,2) NULL,
  jumlah_produksi_4_ton           DECIMAL(14,2) NULL,
  konektivitas_simpul_transportasi VARCHAR(10) NULL,     -- 'YA' | 'TIDAK'
  konektivitas_pusat_kegiatan       VARCHAR(10) NULL,     -- terhubung PKN/PKW
  konektivitas_koridor_lain          VARCHAR(10) NULL,     -- terhubung koridor utama lain
  fasilitas_pendidikan          SMALLINT      NULL,       -- jumlah fasilitas dilewati koridor
  fasilitas_kesehatan           SMALLINT      NULL,
  fasilitas_pemerintahan        SMALLINT      NULL,
  fasilitas_sppg                SMALLINT      NULL,
  map_koridor                  VARCHAR(255)  NULL,       -- URL SITIA show_map
  map_awal_koridor              VARCHAR(255)  NULL,
  prioritas_kabupaten_kota      SMALLINT      NULL,       -- peringkat prioritas dlm kab/kota ybs (1=tertinggi)
  prioritas_provinsi            SMALLINT      NULL,       -- peringkat prioritas dlm provinsi ybs, NULL kalau belum dinilai
  koridor_awal                 VARCHAR(5)    NULL,       -- 'YA' kalau koridor ini bagian dari daftar koridor awal, NULL kalau bukan
  panjang_kml_km                DECIMAL(10,3) NULL,       -- panjang hasil geometri KML/KMZ terupload (beda dari panjang_km administratif), NULL kalau belum ada
  baik_kml_km                  DECIMAL(10,3) NULL,
  sedang_kml_km                 DECIMAL(10,3) NULL,
  rusak_ringan_kml_km            DECIMAL(10,3) NULL,
  rusak_berat_kml_km             DECIMAL(10,3) NULL,
  beririsan_hari_jalan           VARCHAR(10)   NULL,       -- semua NULL di snapshot 21 Jul 2026, disimpan utk kalau diisi di update selanjutnya
  tahun_hari_jalan               SMALLINT      NULL,
  beririsan_diskresi_menteri      VARCHAR(10)   NULL,
  tahun_diskresi_menteri          SMALLINT      NULL,
  beririsan_rujj                VARCHAR(10)   NULL,       -- Rencana Umum Jaringan Jalan
  PRIMARY KEY (id_koridor),
  KEY idx_kode_kab (kode_kab),
  KEY idx_provinsi (provinsi)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
