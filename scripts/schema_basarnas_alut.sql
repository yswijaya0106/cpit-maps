-- Inventaris Alat Utama (ALUT) SAR per Kantor SAR -- udara, darat, laut
-- (docs/New/6. BASARNAS/2. Data Sarana dan Prasarana/, 3 file REKAP
-- terpisah per matra, skema kolom identik). Tabel referensi non-spasial,
-- join ke titik Kantor SAR (map_layers, layer="KANTOR SAR") via
-- kode_daerah/kantor_sar -- BUKAN kolom attrs JSONB di map_layers,
-- karena datanya banyak-ke-satu per kantor (satu kantor bisa punya
-- puluhan unit alat).
--
-- Baris sumber TIDAK seragam maknanya per baris -- ada baris "penanda
-- kategori" (Kendaraan='RESCUE TRUCK TIPE I' tanpa detail plat/merek)
-- dan baris "tidak memiliki" (Kendaraan='Tidak Memiliki') selain baris
-- unit individual sungguhan -- SEMUA diimpor apa adanya (bukan
-- difilter/diinterpretasi) supaya tidak diam-diam menghilangkan
-- informasi; `kondisi_kategori` adalah satu-satunya kolom yang
-- dinormalisasi (dari `kondisi_saat_ini_raw` yang penulisannya bebas:
-- S/US/Baik/Rusak Ringan/dll, lihat scripts/import_basarnas_alut.py).
--
-- Diisi scripts/import_basarnas_alut.py. Lihat
-- docs/kajian_data_baru_docs_new.md §8.2 untuk hasil telaah datanya.
-- TIDAK terkait usulan_inpres/IJD.

CREATE TABLE IF NOT EXISTS basarnas_alut (
  id                    BIGSERIAL PRIMARY KEY,
  matra                 TEXT NOT NULL,   -- 'UDARA' | 'DARAT' | 'LAUT'
  no_urut               INTEGER,
  kode_daerah           TEXT,
  kantor_sar            TEXT,
  kendaraan             TEXT,
  plat_lambung          TEXT,
  merk_type             TEXT,
  tempat                TEXT,
  tahun                 TEXT,
  no_mesin              TEXT,
  no_rangka             TEXT,
  kondisi_saat_ini_raw  TEXT,
  kondisi_kategori      TEXT,   -- 'SIAP' | 'SIAP_TERBATAS' | 'TIDAK_SIAP' | 'LAINNYA' | NULL
  keterangan            TEXT,
  imported_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_basarnas_alut_kode_daerah ON basarnas_alut (kode_daerah);
