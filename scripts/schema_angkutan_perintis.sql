-- Daftar trayek/lintas angkutan perintis nasional (docs/New/5. DARAT/
-- Daftar Angkutan Perintis Darat Tahun 2026.xlsx, 5 sheet -- Barang
-- Perintis, Perkotaan BTS, Penyeberangan Perintis, KSPN, Jalan
-- Perintis). Lampiran Keputusan Direktur Jenderal Perhubungan Darat
-- (KP-DRJD) per jenis layanan. Tabel referensi non-spasial (TIDAK ADA
-- koordinat sama sekali di sumbernya, cuma nama titik awal-akhir
-- sebagai teks) -- satu tabel gabungan (bukan 5 tabel terpisah) karena
-- strukturnya mirip, dibedakan lewat kolom `jenis`.
--
-- Diisi scripts/import_angkutan_perintis.py. Lihat
-- docs/kajian_data_baru_docs_new.md §7.1. TIDAK terkait usulan_inpres/IJD.

CREATE TABLE IF NOT EXISTS angkutan_perintis (
  id                BIGSERIAL PRIMARY KEY,
  jenis             TEXT NOT NULL,   -- BARANG_PERINTIS | PERKOTAAN_BTS | PENYEBERANGAN_PERINTIS | KSPN | JALAN_PERINTIS
  no_urut           INTEGER,
  provinsi          TEXT,
  wilayah           TEXT,   -- kabupaten/kota, WILAYAH metropolitan, atau kawasan strategis (beda makna per jenis)
  no_koridor_trayek TEXT,
  nama_trayek       TEXT NOT NULL,
  jarak             NUMERIC(10, 2),
  satuan_jarak      TEXT,   -- 'KM' | 'MIL' | 'KM PP'
  target_trip_2026  INTEGER,
  imported_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_angkutan_perintis_jenis ON angkutan_perintis (jenis);
