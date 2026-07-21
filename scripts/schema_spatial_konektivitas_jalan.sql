-- Validasi spasial "Konektivitas Jaringan Jalan" per USULAN (bukan proksi
-- administratif "kabupaten punya data jalan" di konektivitas_jaringan_jalan)
-- -- jarak jalur usulan (usulan_inpres.geom_geojson) ke ruas Jalan
-- Nasional/Provinsi/Tol terdekat. Diisi scripts/spatial_konektivitas_jalan.py.
-- Request eksplisit user, docs/spec/laporan prioritas.md.

USE route_gis;

CREATE TABLE IF NOT EXISTS usulan_konektivitas_jalan (
  usulan_id          INT UNSIGNED NOT NULL PRIMARY KEY,
  kode_kecamatan     INT UNSIGNED NULL,
  terhubung_nasional TINYINT(1) NOT NULL DEFAULT 0,
  jarak_nasional_m   DECIMAL(8,1) NULL,
  terhubung_provinsi TINYINT(1) NOT NULL DEFAULT 0,
  jarak_provinsi_m   DECIMAL(8,1) NULL,
  terhubung_tol      TINYINT(1) NOT NULL DEFAULT 0,
  jarak_tol_m        DECIMAL(8,1) NULL,
  terhubung          TINYINT(1) NOT NULL DEFAULT 0,  -- OR dari ketiga di atas
  ambang_m           DECIMAL(6,1) NOT NULL,
  KEY idx_kode_kecamatan (kode_kecamatan)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
