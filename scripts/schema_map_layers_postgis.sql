-- Layer peta referensi Maps/ (SHP RBI per provinsi/kabupaten + layer
-- nasional JALAN PROVINSI/JALAN TOL/BATAS KECAMATAN dst.), sebelumnya dibaca
-- langsung dari disk per-request (gpd.read_file) oleh /api/maps/* di
-- app.py. Skema generik (bukan satu tabel per layer) karena tiap file .shp
-- RBI punya kolom atribut berbeda-beda tergantung jenisnya (AR/LN/PT) --
-- app.py sendiri juga tidak pernah bergantung pada nama kolom spesifik,
-- cuma serialize apa adanya ke GeoJSON (lihat _map_layer_label,
-- maps_layer()). Jadi atribut asli disimpan sebagai JSONB, bukan kolom.
--
-- map_layer_meta dipakai untuk daftar provinsi/kabupaten/layer (dulu
-- Path.iterdir()/glob() atas folder Maps/) supaya endpoint listing tidak
-- perlu SELECT DISTINCT dari tabel geometri yang besar tiap request.
--
-- Diisi scripts/import_maps_to_postgis.py.

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS map_layer_meta (
  provinsi       TEXT NOT NULL,
  kabupaten      TEXT NOT NULL DEFAULT '',   -- '' = folder provinsi tanpa sub-folder kabupaten (mis. JALAN TOL)
  layer          TEXT NOT NULL,              -- stem file .shp, mis. 'ADMINISTRASI_AR_25K'
  label          TEXT,
  feature_count  INTEGER,
  size_mb        NUMERIC(10, 2),             -- ukuran .shp sumber (setara shp.stat().st_size lama)
  source_shp     TEXT,                       -- path relatif thd Maps/, utk penelusuran/debug
  imported_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (provinsi, kabupaten, layer)
);

CREATE TABLE IF NOT EXISTS map_layers (
  id         BIGSERIAL PRIMARY KEY,
  provinsi   TEXT NOT NULL,
  kabupaten  TEXT NOT NULL DEFAULT '',
  layer      TEXT NOT NULL,
  attrs      JSONB NOT NULL DEFAULT '{}',
  geom       geometry(Geometry, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_map_layers_pkl ON map_layers (provinsi, kabupaten, layer);
CREATE INDEX IF NOT EXISTS idx_map_layers_geom ON map_layers USING GIST (geom);

-- Layer BATAS KECAMATAN (provinsi='BATAS KECAMATAN', diisi
-- scripts/import_batas_administrasi_kecamatan.py dari Maps/BATAS_ADMINISTRASI.gdb)
-- menyimpan provinsi/kabupaten ASLI langsung di kolom kabupaten/layer --
-- sudah tercakup idx_map_layers_pkl di atas, tidak perlu index nama terpisah
-- lagi (versi lama yang dicari lewat attrs->>'KECAMATAN' sudah tidak dipakai).
