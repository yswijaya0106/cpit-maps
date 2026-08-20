-- Kapasitas/realisasi trip/realisasi penumpang per LAYANAN kereta
-- perkotaan (KRL/LRT/MRT/KA Bandara/KA Commuter Line), 2020-2029
-- (docs/New/5. DARAT/Rekap Data Daerah.xlsx, sheet "(KEN TITIP 1)"
-- [2020-2024, realisasi] + "(KEN TITIP 2)" [2025-2029, 2025 realisasi
-- parsial + 2026-2029 target Gapeka]) -- lebih granular dari
-- rekap_penumpang_ka_nasional (yang cuma agregat nasional per kategori,
-- sheet "(KEN TITIP 3)" di file yang sama): 19 layanan disebut eksplisit
-- (KRL Jabodetabek, KRL Yogyakarta, LRT Sumsel, LRT Jakarta, LRT
-- Jabodebek, MRT Jakarta, Kereta Cepat Jakarta-Bandung, KA Merak, KA
-- Bandung Raya, 4 KA Bandara, 5 KA Commuter Line Surabaya/Garut/Walahar).
--
-- Sebelumnya SENGAJA dilewati (lihat komentar lama di
-- schema_rekap_penumpang_ka_nasional.sql) berdasarkan asumsi strukturnya
-- semirip sheet BRT ('2020 - 2025'/'LKJ 2025', kota Kemenhub vs Daerah
-- tercampur) -- ternyata KEN TITIP 1/2 strukturnya lebih sederhana
-- (satu baris per layanan, bukan per-kota-per-koridor) dan bersih,
-- diimpor ulang setelah ditinjau 20 Agu 2026.
--
-- Baris "Total"/"Total Realisasi Cap" di sumber SENGAJA tidak diimpor
-- (agregat turunan, hitung ulang via SUM bila perlu, hindari duplikasi
-- makna dengan baris per-layanan).
--
-- tahun 2026-2029 di "(KEN TITIP 2)" murni TARGET kapasitas Gapeka
-- (realisasi_trip/realisasi_penumpang kosong/nol, belum terjadi saat
-- sumber ditulis) -- kolom `sumber` membedakan asal sheet supaya UI bisa
-- melabeli tahun-tahun tsb sebagai target, bukan realisasi aktual.
--
-- Diisi scripts/import_ka_perkotaan_layanan.py. TIDAK terkait
-- usulan_inpres/IJD.

CREATE TABLE IF NOT EXISTS ka_perkotaan_layanan (
  nama_layanan          TEXT NOT NULL,
  tahun                 SMALLINT NOT NULL,
  kapasitas             INTEGER,
  realisasi_trip        INTEGER,
  realisasi_penumpang   BIGINT,
  sumber                TEXT NOT NULL,   -- 'KEN_TITIP_1' (2020-2024, realisasi) | 'KEN_TITIP_2' (2025-2029, 2025 realisasi/2026-2029 target)
  imported_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (nama_layanan, tahun)
);
