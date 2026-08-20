-- Daftar lengkap Bandar Udara dari situs resmi Ditjen Perhubungan Udara
-- Kemenhub (https://hubud.kemenhub.go.id/daftar-bandara, 597 bandara,
-- 60 halaman @ 10 baris) + halaman detail tiap bandara
-- (https://hubud.kemenhub.go.id/bandara/{id}, 8 tab: Data Umum, Bandar
-- Udara Terdekat, Rute Domestik, Rute Internasional, Fasilitas Udara,
-- Fasilitas Darat, Transportasi, Galeri). Sumber web, live scraping
-- (server-rendered HTML, semua tab ada dalam satu response, ditoggle
-- CSS/JS client-side -- bukan AJAX per-tab).
--
-- BEDA dari bps_data_bandara (atribut xlsx statis 251 bandara,
-- Attributes_ Data Bandara.xlsx) -- ini sumber LIVE dari situs resmi,
-- cakupan lebih luas (597, termasuk bandara kecil/tidak aktif), dan
-- host layer titik BANDARA (SHP) yang sudah ada di map_layers.
-- SENGAJA tabel terpisah (bukan menimpa bps_data_bandara) supaya kedua
-- sumber tetap bisa dibandingkan/cross-check.
--
-- lat/lon dari link "Buka di Google Maps" pada halaman detail (koordinat
-- desimal bersih, bukan hasil parsing teks DMS "Lokasi (ARP)" yang
-- encoding derajatnya rusak di sumbernya sendiri -- disimpan apa adanya
-- di lokasi_arp_text sebagai referensi mentah, TIDAK dipakai untuk
-- lat/lon).
--
-- Diisi scripts/scrape_bandara_kemenhub.py. TIDAK terkait
-- usulan_inpres/IJD.

CREATE TABLE IF NOT EXISTS bandara_kemenhub (
  bandara_id                INTEGER PRIMARY KEY,   -- id dari URL /bandara/{id}
  icao                      TEXT,
  iata                      TEXT,
  nama_bandara               TEXT NOT NULL,
  provinsi                  TEXT,
  kabupaten                 TEXT,
  kecamatan                 TEXT,
  kelurahan_desa             TEXT,
  penggunaan                TEXT,   -- Internasional | Domestik (dari listing)
  kelas                     TEXT,   -- Non Kelas | Kelas I/II/III | Satpel BU dst (dari listing)
  pengelola                 TEXT,
  tkbn                      TEXT,   -- kolom "TKBN" di listing (Ya/Tidak)
  status_operasi             TEXT,
  hierarki                  TEXT,
  pkp_pk                    TEXT,
  klasifikasi                TEXT,
  critical_aircraft          TEXT,
  pesawat_beroperasi         TEXT,
  dokumen_pendukung          TEXT,
  airnav_info                TEXT,   -- teks gabungan kantor cabang/alamat/telepon Airnav (baris <br> sumber collapse jadi 1 teks, tak dipecah)
  alamat_bandara             TEXT,
  status_blu                TEXT,
  lokasi_arp_text            TEXT,   -- teks mentah "Lokasi (ARP)" DMS, encoding derajat rusak di sumber -- referensi saja
  lat                       DOUBLE PRECISION,   -- dari link "Buka di Google Maps"
  lon                       DOUBLE PRECISION,
  lalu_lintas_tahun          SMALLINT,   -- tahun data "Lalu Lintas Udara" di panel kanan (mis. 2025)
  lalu_lintas_pesawat        BIGINT,
  lalu_lintas_penumpang      BIGINT,
  lalu_lintas_kargo_kg       BIGINT,
  transportasi_darat         TEXT[],   -- tab "Transportasi": daftar moda (Bus, Taksi, dst) -- cuma nama, tanpa atribut lain di sumber
  galeri_urls                TEXT[],   -- tab "Galeri": url foto
  detail_url                 TEXT,
  scraped_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bandara_kemenhub_provinsi ON bandara_kemenhub (provinsi);
CREATE INDEX IF NOT EXISTS idx_bandara_kemenhub_kabupaten ON bandara_kemenhub (kabupaten);

-- Tab "Rute Domestik" + "Rute Internasional" digabung, dibedakan kolom tipe.
CREATE TABLE IF NOT EXISTS bandara_kemenhub_rute (
  id            BIGSERIAL PRIMARY KEY,
  bandara_id    INTEGER NOT NULL REFERENCES bandara_kemenhub (bandara_id) ON DELETE CASCADE,
  tipe          TEXT NOT NULL,   -- 'domestik' | 'internasional'
  tujuan        TEXT,
  maskapai      TEXT,
  pesawat       TEXT,
  frekuensi     TEXT
);
CREATE INDEX IF NOT EXISTS idx_bandara_kemenhub_rute_bandara ON bandara_kemenhub_rute (bandara_id);
-- Koordinat tujuan dari blok JS Highcharts.mapChart('mapRuteDom'/'mapRuteInt', ...)
-- (bukan DOM/li biasa -- lihat _parse_rute_koordinat di scrape_bandara_kemenhub.py).
-- ALTER terpisah (bukan di definisi CREATE TABLE di atas) krn tabelnya
-- sudah lebih dulu ada dari sebelum kolom ini ditambahkan -- CREATE TABLE
-- IF NOT EXISTS jadi no-op utk tabel yg sudah ada, kolom baru wajib lewat
-- ALTER eksplisit, sama pola dgn ALTER di bps_data_bandara/bandara_kemenhub
-- di atas.
ALTER TABLE bandara_kemenhub_rute ADD COLUMN IF NOT EXISTS tujuan_lat DOUBLE PRECISION;
ALTER TABLE bandara_kemenhub_rute ADD COLUMN IF NOT EXISTS tujuan_lon DOUBLE PRECISION;

-- Tab "Bandar Udara Terdekat".
CREATE TABLE IF NOT EXISTS bandara_kemenhub_terdekat (
  id                    BIGSERIAL PRIMARY KEY,
  bandara_id            INTEGER NOT NULL REFERENCES bandara_kemenhub (bandara_id) ON DELETE CASCADE,
  nama_terdekat          TEXT,
  jarak_km               NUMERIC(10, 2),
  bandara_terdekat_id    INTEGER   -- id bandara tujuan (dari href), TANPA FK -- bisa merujuk baris yg belum/tidak ikut ter-scrape
);
CREATE INDEX IF NOT EXISTS idx_bandara_kemenhub_terdekat_bandara ON bandara_kemenhub_terdekat (bandara_id);

-- Tab "Fasilitas Udara" + "Fasilitas Darat" digabung, dibedakan kolom
-- kategori. Atribut per item (Dimensi Terverifikasi/Terbangun,
-- Konstruksi, Daya Dukung, Luas, dst) bervariasi per jenis_fasilitas --
-- disimpan sebagai JSONB apa adanya, bukan dipecah jadi kolom tetap.
CREATE TABLE IF NOT EXISTS bandara_kemenhub_fasilitas (
  id                BIGSERIAL PRIMARY KEY,
  bandara_id        INTEGER NOT NULL REFERENCES bandara_kemenhub (bandara_id) ON DELETE CASCADE,
  kategori          TEXT NOT NULL,   -- 'udara' | 'darat'
  jenis_fasilitas    TEXT NOT NULL,   -- Runway | Taxiway | Apron | Gedung Terminal | Gedung Kargo | dst
  nama_item          TEXT,   -- label sub-item (bisa sama dgn jenis_fasilitas kalau cuma 1, atau "Runway 1"/"Runway 2" dst)
  atribut            JSONB
);
CREATE INDEX IF NOT EXISTS idx_bandara_kemenhub_fasilitas_bandara ON bandara_kemenhub_fasilitas (bandara_id);
