-- Statistik kecelakaan lalu lintas Korlantas POLRI 2020 - 30 Okt 2025
-- (docs/New/8. KESELAMATAN/ANEV LAKA LANTAS TAHUN 2020-2025 (BAPENAS
-- B-17549) 2.xlsx -- nama file menunjukkan ini juga hasil permohonan
-- data Bappenas, pola sama dengan surat BASARNAS di
-- docs/kajian_data_baru_docs_new.md §8.7).
--
-- Dua tabel referensi non-spasial, TIDAK terkait usulan_inpres/IJD:
--
-- anev_laka_lantas_nasional: sheet REKAP, format long/tidy -- sumbernya
-- laporan hierarkis 25 kategori (Berdasarkan Kecelakaan Lalu Lintas/
-- Tunggal/JOL/Tabrak Lari/Tabrak Beruntun/Fungsi Jalan/Status Jalan/
-- Objek Acuan/Kondisi Cuaca/dst.) dengan URAIAN & SATUAN berbeda-beda
-- per kategori -- long/tidy dipilih drpd rectangular per-kategori supaya
-- import tidak perlu hardcode skema per kategori (kategori baru di
-- laporan tahun berikutnya otomatis tertampung tanpa migrasi skema).
--
-- anev_laka_lantas_polda: sheet POLDA, rectangular murni per (polda,
-- tahun) -- struktur sumbernya memang genap 5 kolom (KEJADIAN/KORBAN
-- MD/LB/LR/RUMAT) per blok tahun, jadi TIDAK dibuat long/tidy spt REKAP.
--
-- Diisi scripts/import_anev_laka_lantas.py. Lihat
-- docs/kajian_data_baru_docs_new.md §9.1 untuk hasil telaah datanya.

CREATE TABLE IF NOT EXISTS anev_laka_lantas_nasional (
  kategori_no  SMALLINT,
  kategori     TEXT NOT NULL,
  uraian       TEXT NOT NULL,
  satuan       TEXT,
  tahun        TEXT NOT NULL,   -- '2020'..'2024' atau label apa adanya spt 'JAN - 30 OKT 2025'
  nilai        NUMERIC(18, 2),
  imported_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (kategori, uraian, tahun)
);

CREATE TABLE IF NOT EXISTS anev_laka_lantas_polda (
  polda            TEXT NOT NULL,
  tahun            TEXT NOT NULL,
  kejadian         INTEGER,
  korban_md        INTEGER,
  korban_lb        INTEGER,
  korban_lr        INTEGER,
  kerugian_materi  NUMERIC(18, 2),
  imported_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (polda, tahun)
);
