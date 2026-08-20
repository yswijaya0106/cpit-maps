-- Kinerja tahunan per pelabuhan dari BPS Statistik Transportasi Laut
-- (docs/New/2. LAUT/(DATA) KINERJA PELABUHAN - STATISTIK TRANSPORTASI
-- LAUT BPS.xlsx, sheet "Data") -- kunjungan kapal DN/LN, arus penumpang
-- DN/LN, arus barang (ton, peti kemas & non-peti kemas). Tabel referensi
-- non-spasial, TIDAK terkait usulan_inpres/IJD.
--
-- Kolom 18 ke atas pada sumber xlsx adalah artefak pivot-table Excel
-- yang nyasar ke baris pertama sheet (nilai "Avg Muat"/"Avg Berangkat"
-- cuma muncul 1 baris, semua baris lain kosong) -- SENGAJA tidak
-- diimpor, lihat scripts/import_bps_kinerja_pelabuhan.py.
--
-- Diisi scripts/import_bps_kinerja_pelabuhan.py. Lihat
-- docs/kajian_data_baru_docs_new.md §4.1.

CREATE TABLE IF NOT EXISTS bps_kinerja_pelabuhan (
  pelabuhan               TEXT NOT NULL,
  provinsi                TEXT NOT NULL,
  tahun                    SMALLINT NOT NULL,
  unit_dn                  INTEGER,
  gt_dn                     BIGINT,
  avg_gt_dn                 NUMERIC(14, 4),
  unit_ln                  INTEGER,
  gt_ln                     BIGINT,
  avg_gt_ln                 NUMERIC(14, 4),
  penumpang_datang_dn       INTEGER,
  penumpang_berangkat_dn    INTEGER,
  penumpang_datang_ln       INTEGER,
  penumpang_berangkat_ln    INTEGER,
  bongkar_dn_ton            NUMERIC(16, 2),
  muat_dn_ton               NUMERIC(16, 2),
  bongkar_ln_ton            NUMERIC(16, 2),
  muat_ln_ton               NUMERIC(16, 2),
  keterangan                TEXT,
  imported_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (pelabuhan, provinsi, tahun)
);
