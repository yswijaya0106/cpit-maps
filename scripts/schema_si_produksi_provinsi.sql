-- Produksi Padi&Jagung dan Perikanan Tangkap level PROVINSI dari BPS
-- "Statistik Indonesia 2026" (docs/docs/00 Statistik Indonesia 2026.pdf,
-- Tabel 5.1.2/5.1.4/5.6.1) -- fallback PROKSI provinsi utk NPR
-- PADI_JAGUNG/PERIKANAN (_npr_skor_intensitas di app.py) saat kabupaten
-- usulan tidak punya baris di bps_kecamatan_potensi_tematik (Dalam Angka
-- kabupaten belum diimpor/parsernya gagal utk tabel itu) -- BUKAN
-- pengganti data kabupaten, cuma dipakai kalau data kabupaten kosong,
-- selalu ditandai "PROKSI provinsi" di keterangan skor (pola sama dgn
-- proksi C.A1 kabupaten, lihat docs/MEMORY.md).
--
-- PETERNAKAN provinsi SENGAJA belum ditambahkan -- tabel sumbernya
-- (5.5.4-5.5.11) terpecah per jenis ternak/produk lintas beberapa halaman
-- (sebagian ada halaman "Lanjutan Tabel") dan makna "total produksi
-- peternakan" perlu keputusan metodologi (daging saja vs +telur+susu,
-- karkas vs daging murni) sebelum diekstrak -- lihat percakapan 24 Jul
-- 2026 (tanya user dulu kalau mau lanjutkan).
--
-- Ditulis native PostgreSQL (bukan hasil migrasi MySQL) -- tabel baru,
-- dibuat oleh scripts/extract_statistik_indonesia.py sendiri (run_schema()),
-- bukan lewat scripts/migrate_pg_01_schema.py.

CREATE TABLE IF NOT EXISTS si_padi_jagung_provinsi (
  kode_provinsi SMALLINT     NOT NULL,  -- 0 = Indonesia (total)
  provinsi      VARCHAR(60)  NOT NULL,
  tahun         SMALLINT     NOT NULL,  -- tahun kolom terakhir tabel (2025)
  padi_ton      DECIMAL(14,2) NULL,     -- Tabel 5.1.2 "Produksi Padi"
  jagung_ton    DECIMAL(14,2) NULL,     -- Tabel 5.1.4 "Produksi JPK KA 28%"
  total_ton     DECIMAL(14,2) NULL,     -- padi_ton + jagung_ton (NULL kalau keduanya NULL)
  PRIMARY KEY (kode_provinsi, tahun)
);

CREATE TABLE IF NOT EXISTS si_perikanan_tangkap_provinsi (
  kode_provinsi   SMALLINT     NOT NULL,
  provinsi        VARCHAR(60)  NOT NULL,
  tahun           SMALLINT     NOT NULL,
  volume_ton      DECIMAL(14,2) NULL,   -- Tabel 5.6.1 kolom "Jumlah/Total Volume (ton)"
                                          -- (Perikanan Tangkap Laut + Perairan Darat,
                                          -- SAMA cakupan dgn label NPR "Tangkap Darat & Laut")
  nilai_ribu_rp   DECIMAL(16,2) NULL,    -- kolom "Jumlah/Total Nilai (000 Rp)", referensi saja
  PRIMARY KEY (kode_provinsi, tahun)
);
