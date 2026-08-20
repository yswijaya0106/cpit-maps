-- Komposisi tenaga (Rescuer/ABK/Operator Komunikasi/Medis) dan potensi
-- SAR (relawan Literasi/Terlatih/Kompeten) per satuan kerja BASARNAS,
-- Juli 2026 (docs/New/6. BASARNAS/3. Data Rescuer dan Potensi/
-- Komposisi_Rescuer_dan_Potensi_Juli_2026.xlsx). Tabel referensi
-- non-spasial, join ke titik Kantor SAR via kode_daerah/satuan_kerja
-- (dua baris "Kantor Pusat"/"Balai SDM PP" tidak punya kode_daerah --
-- bukan kantor regional).
--
-- Diisi scripts/import_basarnas_rescuer_potensi.py. Lihat
-- docs/kajian_data_baru_docs_new.md §8.3. TIDAK terkait usulan_inpres/IJD.

CREATE TABLE IF NOT EXISTS basarnas_rescuer_potensi (
  no                     INTEGER PRIMARY KEY,
  kode_daerah            TEXT,
  satuan_kerja           TEXT NOT NULL,
  tenaga_rescuer         INTEGER,
  tenaga_abk             INTEGER,
  tenaga_operator_komunikasi INTEGER,
  tenaga_medis           INTEGER,
  tenaga_total           INTEGER,
  potensi_literasi       INTEGER,
  potensi_terlatih       INTEGER,
  potensi_kompeten       INTEGER,
  potensi_total          INTEGER,
  grand_total            INTEGER,
  imported_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
