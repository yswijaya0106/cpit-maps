-- Lalu Lintas Harian Rata-Rata (LHR/AADT) per ruas Jalan Nasional 2024,
-- Bina Marga (docs/New/8. KESELAMATAN/Data Lalu Lintas Harian Rata-Rata
-- (LHR) Jalan Nasional Tahun 2024.xlsx, sheet "Per Ruas"). Tabel referensi
-- murni non-spasial -- linkid cocok 1:1 (3306/3306, diverifikasi saat
-- kajian) dengan attrs->>'LINKID' pada map_layers (provinsi='JALAN
-- NASIONAL', layer='Jalan Nasional'), tapi disimpan sebagai tabel
-- terpisah (bukan merge ke attrs JSONB layer peta) supaya reimport
-- layer JALAN NASIONAL dan reimport LHR tetap independen satu sama lain.
--
-- vcr (Volume-Capacity Ratio) adalah indikator kepadatan/kemacetan lalu
-- lintas siap pakai per ruas -- belum ada sumber lain di aplikasi ini.
--
-- Diisi scripts/import_lhr_ruas_nasional.py. Lihat
-- docs/kajian_data_baru_docs_new.md §9.3 untuk hasil telaah datanya.
-- Layer/tabel ini murni referensi umum, TIDAK terkait usulan_inpres/IJD.

CREATE TABLE IF NOT EXISTS bps_lhr_ruas_nasional (
  linkid        TEXT PRIMARY KEY,
  linkname      TEXT,
  lintas        TEXT,
  panjang_sk_km NUMERIC(10, 2),
  tahun_data    SMALLINT,
  aadt_total    INTEGER,
  aadt_veh1     INTEGER,
  aadt_veh2     INTEGER,
  aadt_veh3     INTEGER,
  aadt_veh4     INTEGER,
  aadt_veh5a    INTEGER,
  aadt_veh5b    INTEGER,
  aadt_veh6a    INTEGER,
  aadt_veh6b    INTEGER,
  aadt_veh7a    INTEGER,
  aadt_veh7b    INTEGER,
  aadt_veh7c    INTEGER,
  aadt_veh8     INTEGER,
  volume        NUMERIC(12, 3),
  capacity      NUMERIC(12, 3),
  vcr           NUMERIC(6, 3),
  imported_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- provinsi/kabupaten/kecamatan: hasil spatial join ad-hoc
-- (scripts/lhr_spatial_join.py) ruas ini terhadap BATAS KECAMATAN, ditulis
-- lebih dulu sbg kolom baru di sheet "Per Ruas" xlsx sumber, lalu diimpor
-- ke sini oleh import_lhr_ruas_nasional.py. Bisa berisi lebih dari satu
-- nilai per kolom (dipisah "; ") kalau satu ruas melintasi >1 wilayah --
-- ADD COLUMN IF NOT EXISTS supaya aman utk instalasi yang sudah punya
-- tabel ini dari sebelum kolom ini ada.
ALTER TABLE bps_lhr_ruas_nasional ADD COLUMN IF NOT EXISTS provinsi TEXT;
ALTER TABLE bps_lhr_ruas_nasional ADD COLUMN IF NOT EXISTS kabupaten TEXT;
ALTER TABLE bps_lhr_ruas_nasional ADD COLUMN IF NOT EXISTS kecamatan TEXT;
