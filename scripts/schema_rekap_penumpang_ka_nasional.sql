-- Jumlah penumpang kereta api nasional per kategori/sistem, 2020-2025
-- (docs/New/5. DARAT/Rekap Data Daerah.xlsx, sheet "(KEN TITIP 3)").
-- Sheet BRT ('2020 - 2025', 'LKJ 2025', 'BRT & KA', 'Sheet1') di file
-- yang sama SENGAJA masih dilewati -- strukturnya multi-section (kota
-- BTS dikelola Kemenhub vs. BRT dikelola daerah dicampur dalam satu
-- sheet, placeholder '-'/'?'/'N/A' berbeda arti tergantung konteks) dan
-- cakupannya kota-per-kota (bukan nasional) -- lihat
-- docs/kajian_data_baru_docs_new.md §7.3. "(KEN TITIP 1)"/"(KEN TITIP 2)"
-- SEBELUMNYA juga dilewati dengan alasan yang sama, tapi setelah
-- ditinjau ulang 20 Agu 2026 ternyata strukturnya jauh lebih sederhana
-- (satu baris per layanan KA perkotaan, bukan per-kota-per-koridor) --
-- diimpor terpisah ke ka_perkotaan_layanan
-- (schema_ka_perkotaan_layanan.sql).
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
