-- Jumlah penumpang kereta api nasional per kategori/sistem, 2020-2025
-- (docs/New/5. DARAT/Rekap Data Daerah.xlsx, sheet "(KEN TITIP 3)") --
-- satu-satunya bagian dari file "Rekap Data Daerah.xlsx" yang cukup
-- bersih & nasional untuk diimpor; sheet lain di file yang sama
-- ('2020 - 2025', 'LKJ 2025', 'BRT & KA', 'Sheet1', '(KEN TITIP 1)',
-- '(KEN TITIP 2)') SENGAJA dilewati -- strukturnya multi-section
-- (kota BTS dikelola Kemenhub vs. BRT dikelola daerah dicampur dalam
-- satu sheet, placeholder '-'/'?'/'N/A' berbeda arti tergantung
-- konteks) dan cakupannya kota-per-kota (bukan nasional), nilai
-- tambahnya tidak sebanding dengan usaha parsing yang dibutuhkan --
-- lihat docs/kajian_data_baru_docs_new.md §7.3.
--
-- Format long/tidy (uraian x tahun) -- 26 kategori: KA Antarkota,
-- Kereta Cepat Whoosh, KA Perkotaan, KRL (+ rincian Jabodetabek/
-- Yogyakarta), KA Bandara (+ rincian per bandara), KA Perintis, dll.
--
-- Diisi scripts/import_rekap_penumpang_ka_nasional.py. TIDAK terkait
-- usulan_inpres/IJD.

CREATE TABLE IF NOT EXISTS rekap_penumpang_ka_nasional (
  uraian            TEXT NOT NULL,
  tahun             TEXT NOT NULL,   -- '2020'..'2024' atau label apa adanya spt '2025*'
  jumlah_penumpang  BIGINT,
  imported_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (uraian, tahun)
);
