-- Jarak terdekat tiap koridor (layer PETA KORIDOR, per NO_KORIDOR x kabupaten)
-- ke simpul transportasi bandara, pelabuhan laut & pelabuhan penyeberangan. Diisi
-- scripts/build_koridor_simpul_terdekat.py (DELETE + reinsert, idempotent).
-- Jarak = jarak geodesik (geography) dari titik terdekat pada jalur koridor
-- ke titik simpul, dalam km -- garis lurus, bukan jarak tempuh jalan.
CREATE TABLE IF NOT EXISTS koridor_simpul_terdekat (
  no_koridor          TEXT NOT NULL,
  nama_koridor        TEXT,
  pulau               TEXT,
  provinsi            TEXT,
  kode_provinsi       INTEGER,
  kabupaten_kota      TEXT,
  kode_kab            INTEGER,
  jumlah_ruas         INTEGER,
  panjang_km          NUMERIC(10, 2),
  bandara_terdekat    TEXT,
  kelas_bandara       TEXT,
  jarak_bandara_km    NUMERIC(10, 2),
  pelabuhan_terdekat  TEXT,
  hierarki_pelabuhan  TEXT,
  jarak_pelabuhan_km  NUMERIC(10, 2),
  penyeberangan_terdekat  TEXT,
  lintas_penyeberangan    TEXT,
  jarak_penyeberangan_km  NUMERIC(10, 2),
  bandara_kelas1_terdekat  TEXT,
  kelas_bandara_kelas1     TEXT,
  jarak_bandara_kelas1_km  NUMERIC(10, 2),
  pelabuhan_utama_terdekat TEXT,
  jarak_pelabuhan_utama_km NUMERIC(10, 2),
  PRIMARY KEY (no_koridor, kabupaten_kota)
);
-- tabel yg sudah terlanjur dibuat sebelum kolom penyeberangan ditambah
ALTER TABLE koridor_simpul_terdekat ADD COLUMN IF NOT EXISTS penyeberangan_terdekat TEXT;
ALTER TABLE koridor_simpul_terdekat ADD COLUMN IF NOT EXISTS lintas_penyeberangan TEXT;
ALTER TABLE koridor_simpul_terdekat ADD COLUMN IF NOT EXISTS jarak_penyeberangan_km NUMERIC(10, 2);
ALTER TABLE koridor_simpul_terdekat ADD COLUMN IF NOT EXISTS bandara_kelas1_terdekat TEXT;
ALTER TABLE koridor_simpul_terdekat ADD COLUMN IF NOT EXISTS kelas_bandara_kelas1 TEXT;
ALTER TABLE koridor_simpul_terdekat ADD COLUMN IF NOT EXISTS jarak_bandara_kelas1_km NUMERIC(10, 2);
ALTER TABLE koridor_simpul_terdekat ADD COLUMN IF NOT EXISTS pelabuhan_utama_terdekat TEXT;
ALTER TABLE koridor_simpul_terdekat ADD COLUMN IF NOT EXISTS jarak_pelabuhan_utama_km NUMERIC(10, 2);
