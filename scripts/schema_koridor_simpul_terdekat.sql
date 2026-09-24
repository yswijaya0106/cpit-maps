-- Jarak terdekat tiap koridor (layer PETA KORIDOR, per NO_KORIDOR x kabupaten)
-- ke simpul transportasi bandara & pelabuhan laut. Diisi
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
  PRIMARY KEY (no_koridor, kabupaten_kota)
);
