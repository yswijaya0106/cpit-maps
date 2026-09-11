-- Daftar Jalur Perlintasan Langsung (JPL, perlintasan sebidang) KA yang
-- diprioritaskan DJKA untuk peningkatan keselamatan, per 12 Mei 2026
-- (docs/New/11092026/.../(REV) JPL_Prioritas_DJKA_v3.xlsx), 7 sheet
-- regional per wilayah kerja BTP (Balai Teknik Perkeretaapian) digabung
-- jadi satu tabel + kolom btp_wilayah_kerja. Domain keselamatan KA yang
-- sebelumnya sama sekali tidak ada di database (lihat
-- docs/kajian_data_baru_11092026.md §3) -- beda dari anev_laka_lantas_*
-- (itu kecelakaan lalu lintas jalan raya, bukan insiden di perlintasan KA).
--
-- Tidak ada koordinat di sumber (cuma lokasi KM+HM tekstual) -- tabel
-- referensi murni, bukan layer peta. frekuensi_ka/headway_ka disimpan
-- TEXT apa adanya (format campur angka+satuan spt "149 KA/hari"/"5 menit"
-- di sumbernya, tidak seragam antar sheet). justifikasi (sheet Bandung/
-- Surabaya) dan jumlah_kecelakaan (sheet Palembang) adalah kolom
-- tambahan yang cuma ada di sebagian sheet -- NULL di sheet lain, bukan
-- data hilang.
--
-- Diisi scripts/import_jpl_prioritas_djka.py. TIDAK terkait
-- usulan_inpres/IJD.

CREATE TABLE IF NOT EXISTS jpl_prioritas_djka (
  id                   BIGSERIAL PRIMARY KEY,
  btp_wilayah_kerja    TEXT NOT NULL,   -- nama sheet asal: Jakarta/Bandung/Semarang/Surabaya/Medan/Padang/Palembang
  no                   INTEGER,
  petak_stasiun        TEXT,
  no_jpl               TEXT,            -- campur angka/kode (mis. "150 B"), disimpan teks
  lokasi_km_hm         TEXT,
  kota_kab             TEXT,
  status_penjagaan     TEXT,            -- Tidak Dijaga | Dijaga Swadaya | Dijaga BTP | Dijaga Pemda | Resmi Dijaga Swadaya | dst
  provinsi             TEXT,
  kategori_jalan       TEXT,            -- Nasional | Provinsi | Kabupaten/Kota | Desa | dst
  lebar_jalan_m        NUMERIC(6, 2),
  jenis_jalur_ka       TEXT,
  frekuensi_ka         TEXT,
  headway_ka           TEXT,
  nama_jalan           TEXT,
  daop_divre           TEXT,
  justifikasi          TEXT,            -- hanya diisi di sheet Bandung/Surabaya
  jumlah_kecelakaan    INTEGER,         -- hanya diisi di sheet Palembang
  imported_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_jpl_prioritas_djka_wilayah ON jpl_prioritas_djka (btp_wilayah_kerja);
CREATE INDEX IF NOT EXISTS idx_jpl_prioritas_djka_provinsi ON jpl_prioritas_djka (provinsi);
