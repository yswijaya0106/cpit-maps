-- Insiden operasi SAR nasional 2021-2025 (docs/New/6. BASARNAS/4. Data
-- Ops SAR/OPS <tahun>.xlsx, sheet "REKAPITULASI DETAIL" -- 5 sheet
-- kategori lain di file yang sama, PESAWAT/KAPAL/BENCANA/KMM/KPK, adalah
-- SUBSET TERFILTER dari REKAPITULASI DETAIL, diverifikasi baris identik
-- persis, sehingga TIDAK diimpor terpisah -- lihat
-- scripts/import_basarnas_ops_sar.py & docs/kajian_data_baru_docs_new.md
-- §8.4 untuk detail verifikasinya).
--
-- Dataset paling bernilai analitik di seluruh docs/New/: koordinat titik
-- kejadian presisi (bukan estimasi kecamatan) + linimasa respons lengkap
-- (kejadian->lapor->berangkat->tiba->selesai, bisa dihitung response-time)
-- + hasil (korban selamat/meninggal/dalam pencarian).
--
-- lat/lon disimpan sebagai kolom numerik biasa (BUKAN geometry
-- PostGIS/map_layers) -- tabel referensi murni untuk "Data" viewer &
-- analitik query, bukan layer toggle-on-map seperti titik BASARNAS
-- lainnya (Kantor SAR/Pos SAR/Wilayah Tanggung Jawab tetap di
-- map_layers terpisah, lihat scripts/import_basarnas_to_postgis.py).
--
-- Diisi scripts/import_basarnas_ops_sar.py. TIDAK terkait
-- usulan_inpres/IJD.

CREATE TABLE IF NOT EXISTS basarnas_ops_sar (
  id                       BIGSERIAL PRIMARY KEY,
  tahun_sumber             SMALLINT NOT NULL,
  no_urut                  INTEGER,
  kantor_sar               TEXT,
  jenis_kecelakaan         TEXT,
  sub_jenis_kecelakaan     TEXT,
  deskripsi                TEXT,
  lon                      NUMERIC(10, 6),
  lat                      NUMERIC(10, 6),
  waktu_kejadian           TIMESTAMP,
  waktu_lapor              TIMESTAMP,
  waktu_berangkat          TIMESTAMP,
  waktu_tiba               TIMESTAMP,
  waktu_selesai            TIMESTAMP,
  korban                   INTEGER,
  selamat                  INTEGER,
  meninggal_dunia          INTEGER,
  dalam_pencarian_hilang   INTEGER,
  imported_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_basarnas_ops_sar_tahun ON basarnas_ops_sar (tahun_sumber);
CREATE INDEX IF NOT EXISTS idx_basarnas_ops_sar_jenis ON basarnas_ops_sar (jenis_kecelakaan);
CREATE INDEX IF NOT EXISTS idx_basarnas_ops_sar_kantor ON basarnas_ops_sar (kantor_sar);
