-- Daftar maskapai (Air Operator Certificate) dari situs resmi Ditjen
-- Perhubungan Udara Kemenhub (https://hubud.kemenhub.go.id/maskapai-organisasi),
-- kategori "Maskapai Dalam Negeri" (kode organisasi 121-xxx). Sumber web,
-- bukan xlsx/PDF -- diisi lewat scraping, bukan import file lokal.
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
