-- Database pelabuhan lokal (docs/New/0. DATA SHP/Pelabuhan Laut/Database
-- Pelabuhan Daerah.xls, sheet "Masterr") -- form pendataan pelabuhan
-- kewenangan Pusat/Provinsi/Kab-Kota, 1008 baris. TIDAK terkait
-- usulan_inpres/IJD.
--
-- Beda dari bps_kinerja_pelabuhan (kinerja tahunan level pelabuhan
-- nasional/besar dari BPS Statistik Transportasi Laut) -- tabel ini
-- mencakup pelabuhan LOKAL/daerah yang tidak masuk cakupan BPS, dgn
-- koordinat sendiri.
--
-- Kolom lat/lon diparsing dari "Titik Koordinat Lokasi" (teks "lat, lon"
-- desimal, lebih bersih drpd kolom Y/X di sheet "Koordinat" yg skalanya
-- TIDAK konsisten antar baris -- lihat import_pelabuhan_daerah.py, sheet
-- "Koordinat" SENGAJA tidak dipakai).
--
-- Sumber xlsx adalah form pendataan mentah (bukan hasil olahan) -- kolom
-- "Penumpang/Barang <tahun>" kadang berisi angka dgn titik yg AMBIGU
-- (mis. "40.668" bisa berarti 40,668 gaya pemisah ribuan Indonesia, atau
-- literal 40.668) -- disimpan APA ADANYA (float persis dari sumber),
-- TIDAK ditafsirkan/dikalikan 1000, sama semangatnya dgn
-- IJD_OUTLIER_PRODUKSI_AMBANG di app.py yg menandai anomali drpd diam-diam
-- "membetulkan" tanpa konfirmasi. "Tidak input data" di sumber -> NULL.
--
-- Kolom rincian fasilitas (dermaga/terminal/gudang/dst, puluhan kolom
-- bernomor spt "Nama.1"/"Kondisi.3" hasil form berulang) disimpan sbg JSONB
-- detail_fasilitas, bukan kolom rigid satu-satu -- strukturnya repeated-
-- group per jenis fasilitas, tidak seragam menjadi kolom SQL yg berguna.
--
-- Diisi scripts/import_pelabuhan_daerah.py.

CREATE TABLE IF NOT EXISTS pelabuhan_daerah (
  id                    BIGSERIAL PRIMARY KEY,
  no                    INTEGER,
  wilayah               TEXT,     -- 'Provinsi' | 'Kab/Kota' (level kewenangan pendataan)
  kode_provinsi         SMALLINT,
  provinsi              TEXT,
  kode_kabupaten        INTEGER,
  kabupaten_kota        TEXT,
  kode_kecamatan        NUMERIC(10, 2),
  kecamatan             TEXT,
  ripn                  TEXT,     -- masuk Rencana Induk Pelabuhan Nasional? Ya/Tidak
  nama_pelabuhan        TEXT NOT NULL,
  kewenangan            TEXT,     -- Pusat | Provinsi | Kab/Kota
  aktifitas_pelabuhan   TEXT,
  unit_kerja            TEXT,
  jenis                 TEXT,
  alamat                TEXT,
  kondisi_pelabuhan     TEXT,
  hirarki_pelabuhan     TEXT,
  komoditas             TEXT,
  penumpang_2021        NUMERIC(14, 3),
  barang_2021           NUMERIC(14, 3),
  penumpang_2022        NUMERIC(14, 3),
  barang_2022           NUMERIC(14, 3),
  penumpang_2023        NUMERIC(14, 3),
  barang_2023           NUMERIC(14, 3),
  penumpang_2024        NUMERIC(14, 3),
  barang_2024           NUMERIC(14, 3),
  status_asset          TEXT,
  lat                   NUMERIC(10, 6),
  lon                   NUMERIC(10, 6),
  detail_fasilitas      JSONB,
  imported_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pelabuhan_daerah_provinsi ON pelabuhan_daerah (provinsi);
CREATE INDEX IF NOT EXISTS idx_pelabuhan_daerah_kabupaten ON pelabuhan_daerah (kabupaten_kota);
