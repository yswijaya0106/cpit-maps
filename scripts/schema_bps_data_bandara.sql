-- Atribut detail 251 bandara nasional (docs/New/3. UDARA/Attributes_ Data
-- Bandara.xlsx, sheet "Sheet1") -- tabel referensi non-spasial, TIDAK
-- menggantikan/menimpa layer titik BANDARA (SHP) yang sudah ada di
-- map_layers. Atributnya jauh lebih kaya (runway/apron/terminal/
-- kapasitas) daripada layer SHP yang cuma titik+nama, dan sudah punya
-- kode wilayah resmi KP (kode provinsi)/KD (kode kabupaten) format sama
-- dengan wilayah_mapping/penduduk_kecamatan -- join langsung tanpa
-- fuzzy-match nama daerah.
--
-- kolom `taxiway` menggabungkan semua baris kelanjutan (bandara dengan
-- >1 taxiway punya baris tambahan tanpa nomor urut di sumber xlsx,
-- lihat scripts/import_bps_data_bandara.py) dipisah "; ".
-- `lat`/`lon` hasil parsing kolom "Titik Koordinat" (teks DMS, notasi
-- Indonesia LU/LS/BT/BB) -- disimpan di samping teks aslinya, bukan
-- pengganti.
--
-- Diisi scripts/import_bps_data_bandara.py. Lihat
-- docs/kajian_data_baru_docs_new.md §5 untuk hasil telaah datanya.
-- Tabel ini murni referensi umum, TIDAK terkait usulan_inpres/IJD.

CREATE TABLE IF NOT EXISTS bps_data_bandara (
  no                            SMALLINT PRIMARY KEY,
  nama_bandara                  TEXT NOT NULL,
  hirarki                       TEXT,
  kelas                         TEXT,
  provinsi                      TEXT,
  kabupaten                     TEXT,
  status                        TEXT,
  operator                      TEXT,
  runway_length_m               NUMERIC(10, 2),
  runway_width_m                NUMERIC(10, 2),
  apron_area_m2                 NUMERIC(14, 2),
  taxiway                       TEXT,
  terminal_penumpang_m2         NUMERIC(14, 2),
  demand_pax                    NUMERIC(14, 2),
  terminal_kargo                TEXT,
  critical_aircraft             TEXT,
  kapasitas_eksisting_valid     NUMERIC(14, 2),
  kapasitas_eksisting_estimasi  NUMERIC(14, 2),
  titik_koordinat_dms           TEXT,
  lat                           NUMERIC(10, 6),
  lon                           NUMERIC(10, 6),
  kode_provinsi                 SMALLINT,   -- KP
  kode_kabupaten                INTEGER,    -- KD
  imported_at                   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Referensi silang (name-match, bukan penggabungan/penimpaan) ke
-- bandara_kemenhub (hasil scrape hubud.kemenhub.go.id, 596 bandara,
-- lebih luas & live) -- dipakai panel detail bandara utk menampilkan
-- rute/fasilitas/foto/lalu-lintas dari sumber itu tanpa mengubah struktur
-- bps_data_bandara yang sudah dipakai skoring/wilayah lain (kode_provinsi/
-- kode_kabupaten resmi BPS TIDAK ada di bandara_kemenhub). Diisi
-- scripts/match_bps_data_bandara_kemenhub.py.
ALTER TABLE bps_data_bandara ADD COLUMN IF NOT EXISTS bandara_kemenhub_id INTEGER REFERENCES bandara_kemenhub (bandara_id);
ALTER TABLE bps_data_bandara ADD COLUMN IF NOT EXISTS match_skor NUMERIC(4, 3);   -- rasio kemiripan nama (difflib), 0-1 -- referensi konfiden match
