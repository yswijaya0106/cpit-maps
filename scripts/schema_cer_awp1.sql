-- Analisis Skoring Jalan AWP-1: Cost Effectiveness Ratio (CER) per koridor.
-- Model EKSPERIMENTAL (deck "20261007 PENAMBAHAN PENYEMPURNAAN SIJALAN" slide
-- 5-22), terpisah dari skor IJD A-E dan NPR. Sumber input: sheet All file
-- docs/07102026/VfM-koridor-kirim bappenas.xlsx; rumus di cer_awp1.py.
-- Diisi scripts/import_cer_awp1.py (DELETE + INSERT, memvalidasi hasil
-- terhadap nilai tersimpan di Excel sebelum menulis).
-- Satu baris = satu koridor per kab/kota (id_koridor SITIA). no_koridor bisa
-- muncul di beberapa kab/kota (227 kode) -- jangan dijadikan kunci.

CREATE TABLE IF NOT EXISTS cer_awp1_koridor (
  id_koridor          INTEGER PRIMARY KEY,
  provinsi            TEXT,
  kabupaten_kota      TEXT,
  kode_provinsi       INTEGER,         -- dari nama (wilayah_cocok.PencocokKabupaten)
  kode_kabupaten      INTEGER,
  no_koridor          TEXT,
  nama_koridor        TEXT,
  status_pengajuan    TEXT,
  rpjmn               TEXT,
  tematik             TEXT,
  -- input kondisi & biaya
  panjang_km          DOUBLE PRECISION,
  baik_km             DOUBLE PRECISION,
  sedang_km           DOUBLE PRECISION,
  rusak_ringan_km     DOUBLE PRECISION,
  rusak_berat_km      DOUBLE PRECISION,
  biaya_pemda_m       DOUBLE PRECISION, -- ada di file, TIDAK dipakai skor (slide 17)
  biaya_std_m         DOUBLE PRECISION, -- B*0,06 + S*0,2 + RR*4 + RB*8 (Rp M)
  -- manfaat (komponen mentah)
  komoditas           TEXT,             -- daftar komoditas 1-3
  hpp_rp              DOUBLE PRECISION, -- nilai produksi Rp/tahun
  pfa                 DOUBLE PRECISION, -- jumlah fasilitas umum dilewati
  d_bok_rp_km         DOUBLE PRECISION,
  d_wt_jam            DOUBLE PRECISION,
  d_acc               DOUBLE PRECISION,
  d_grk               DOUBLE PRECISION,
  -- skor 0-10 & hasil
  skor_hpp            DOUBLE PRECISION,
  skor_bok            DOUBLE PRECISION,
  skor_pfa            DOUBLE PRECISION,
  skor_wt             DOUBLE PRECISION,
  skor_acc            DOUBLE PRECISION,
  skor_grk            DOUBLE PRECISION,
  tot_score           DOUBLE PRECISION, -- manfaat tertimbang
  c_score             DOUBLE PRECISION, -- biaya relatif
  cer_score           DOUBLE PRECISION, -- TOT / C
  peringkat_tot       INTEGER,          -- nasional, 1 = manfaat terbesar
  peringkat_cer       INTEGER,          -- nasional, 1 = paling efisien
  punya_geometri      BOOLEAN,          -- ID_KORIDOR ada di layer PETA KORIDOR
  catatan_data        TEXT,
  diimpor_pada        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cer_awp1_kab ON cer_awp1_koridor (kode_kabupaten);
CREATE INDEX IF NOT EXISTS idx_cer_awp1_no_koridor ON cer_awp1_koridor (no_koridor);
