-- Statistik lalu lintas udara bulanan per bandara (pesawat/penumpang/
-- kargo/bagasi/pos, datang & berangkat) dari situs resmi Ditjen
-- Perhubungan Udara Kemenhub (https://hubud.kemenhub.go.id/lalu-lintas
-- ?bandara=<kode>&period=<YYYY-MM>&category=domestik|internasional).
-- Sumber web, bukan xlsx/PDF -- diisi lewat scraping, bukan import file
-- lokal. TIDAK terkait usulan_inpres/IJD.
--
-- Halaman sumbernya juga punya tabel ringkasan tahunan NASIONAL (total
-- semua bandara per tahun, bukan per bandara) -- SENGAJA tidak diambil,
-- cuma tabel detail per-bandara/per-bulan/per-kategori (Datang/Berangkat)
-- yang relevan di sini.
--
-- Diisi scripts/scrape_lalu_lintas_udara_bandara.py.

CREATE TABLE IF NOT EXISTS lalu_lintas_udara_bandara (
  kode_bandara              TEXT NOT NULL,
  nama_bandara              TEXT,
  periode                   DATE NOT NULL,   -- tanggal 1 bulan ybs
  kategori                  TEXT NOT NULL,   -- domestik | internasional
  pesawat_datang            BIGINT,
  pesawat_berangkat         BIGINT,
  penumpang_datang          BIGINT,
  penumpang_berangkat       BIGINT,
  penumpang_transit_datang  BIGINT,
  penumpang_transit_berangkat BIGINT,
  kargo_kg_datang           BIGINT,
  kargo_kg_berangkat        BIGINT,
  bagasi_kg_datang          BIGINT,
  bagasi_kg_berangkat       BIGINT,
  pos_kg_datang             BIGINT,
  pos_kg_berangkat          BIGINT,
  scraped_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (kode_bandara, periode, kategori)
);

CREATE INDEX IF NOT EXISTS idx_lalu_lintas_udara_bandara_periode ON lalu_lintas_udara_bandara (periode);
