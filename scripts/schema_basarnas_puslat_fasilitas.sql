-- Inventaris sarana/prasarana Pusat Pendidikan dan Pelatihan SDMPP BASARNAS
-- (docs/New/6. BASARNAS/6. Fasilitas Puslat SDMPP/Rekapitulasi Fasilitas
-- Pusat Pendidikan dan Pelatihan Pencarian dan Pertolongan.xlsx, 3 sheet:
-- SARANA DARAT/SARANA LAUT/PRASARANA LATIHAN) -- satu lokasi Puslat
-- (bukan per kantor SAR spt basarnas_alut), jadi tidak perlu kolom
-- kantor_sar. TIDAK terkait usulan_inpres/IJD.
--
-- Diisi scripts/import_basarnas_puslat_fasilitas.py.

CREATE TABLE IF NOT EXISTS basarnas_puslat_fasilitas (
  id           BIGSERIAL PRIMARY KEY,
  kategori     TEXT NOT NULL,   -- SARANA DARAT | SARANA LAUT | PRASARANA LATIHAN
  no_urut      INTEGER,
  nama         TEXT NOT NULL,
  nomor_plat   TEXT,            -- kosong utk PRASARANA LATIHAN
  merk_type    TEXT,
  tahun        TEXT,
  imported_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_basarnas_puslat_fasilitas_kategori ON basarnas_puslat_fasilitas (kategori);
