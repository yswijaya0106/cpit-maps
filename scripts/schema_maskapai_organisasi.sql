-- Daftar maskapai (Air Operator Certificate) dari situs resmi Ditjen
-- Perhubungan Udara Kemenhub (https://hubud.kemenhub.go.id/maskapai-organisasi),
-- kedua kategori di situs itu: "Maskapai Dalam Negeri" (kode 121-xxx/135-xxx/
-- AOC-xxx, param page_negeri) dan "Maskapai Asing" (kode 129-xxx, param
-- page_asing) -- dibedakan lewat kolom kategori. Sumber web, bukan
-- xlsx/PDF -- diisi lewat scraping, bukan import file lokal.
-- TIDAK terkait usulan_inpres/IJD.
--
-- Kolom telepon/fax/email dari halaman detail bisa berisi lebih dari satu
-- nilai (dipisah "; ") -- situsnya sendiri menampilkan beberapa nomor/alamat
-- per baris. telepon_listing adalah versi ringkas dari tabel daftar (bisa
-- beda format sedikit dari kolom telepon di halaman detail, disimpan
-- terpisah apa adanya, bukan dianggap duplikat).
--
-- Diisi scripts/scrape_maskapai_organisasi.py.

CREATE TABLE IF NOT EXISTS maskapai_organisasi (
  kode_organisasi                  TEXT PRIMARY KEY,
  kategori                         TEXT NOT NULL DEFAULT 'negeri',  -- 'negeri' | 'asing'
  nama_maskapai                    TEXT NOT NULL,
  telepon_listing                  TEXT,
  nama_perusahaan                  TEXT,
  dba_name                         TEXT,
  alamat_perusahaan                TEXT,
  telepon                          TEXT,
  fax                              TEXT,
  email                            TEXT,
  perpanjangan_terakhir_sertifikat TEXT,
  status_operasi                   TEXT,
  detail_url                       TEXT,
  scraped_at                       TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE maskapai_organisasi ADD COLUMN IF NOT EXISTS kategori TEXT NOT NULL DEFAULT 'negeri';

-- Lat/lon + provinsi/kabupaten/kecamatan hasil Google Maps Geocoding API
-- atas alamat_perusahaan (alamat kantor, bukan lokasi operasional
-- bandara maskapai) -- diisi scripts/geocode_maskapai_organisasi.py.
ALTER TABLE maskapai_organisasi ADD COLUMN IF NOT EXISTS lat DOUBLE PRECISION;
ALTER TABLE maskapai_organisasi ADD COLUMN IF NOT EXISTS lon DOUBLE PRECISION;
ALTER TABLE maskapai_organisasi ADD COLUMN IF NOT EXISTS geo_provinsi TEXT;
ALTER TABLE maskapai_organisasi ADD COLUMN IF NOT EXISTS geo_kabupaten TEXT;
ALTER TABLE maskapai_organisasi ADD COLUMN IF NOT EXISTS geo_kecamatan TEXT;
ALTER TABLE maskapai_organisasi ADD COLUMN IF NOT EXISTS geo_formatted_address TEXT;
ALTER TABLE maskapai_organisasi ADD COLUMN IF NOT EXISTS geo_status TEXT;
ALTER TABLE maskapai_organisasi ADD COLUMN IF NOT EXISTS geocoded_at TIMESTAMPTZ;
