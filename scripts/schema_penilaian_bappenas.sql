-- Narasi "Output Penilaian" Bappenas per usulan, DIHASILKAN AI (gap G11
-- analisa_gap_cpit.md). Format mengikuti sheet `Output Penilaian` di
-- docs/docs/2_Analisis Prioritas untuk Bappenas dan Teknokratis 15.7.2026.xlsx:
--   - Aspek Prioritas & Nilai Strategis (A)  : poin 0/1/2 + narasi
--   - Daya Ungkit Ekonomi & Kinerja Sektoral (B): poin 0/1/2 + narasi
--   - Kesimpulan Penilaian
-- Diisi endpoint POST /api/usulan-inpres/{id}/penilaian-bappenas (app.py) —
-- hasil di-cache di sini supaya tidak digenerate ulang. Ini DRAF AI, bukan
-- penilaian resmi Bappenas; selalu ditampilkan dengan label tsb.

USE route_gis;

CREATE TABLE IF NOT EXISTS penilaian_bappenas_ai (
  usulan_id      BIGINT UNSIGNED PRIMARY KEY,
  aspek_a_poin   TINYINT NULL,      -- 0/1/2 -- SEKARANG deterministik dari aspek_a_total_kriteria
                                     -- (bukan LLM lagi, lihat _bappenas_aspek_a_lokus() di app.py)
  aspek_a_checklist TINYINT(1) NULL,     -- ada >=1 kriteria lokus yang cocok?
  aspek_a_total_kriteria TINYINT UNSIGNED NULL, -- jumlah kriteria lokus yang cocok (dari 11 yg diimplementasi)
  aspek_a_narasi TEXT NULL,         -- rule-based: daftar kriteria cocok + potensi tematik (bps_kecamatan_potensi_tematik)
  aspek_b_poin   TINYINT NULL,      -- 0/1/2 -- SEKARANG deterministik dari aspek_b_total_indikator
                                     -- (bukan LLM lagi, lihat _bappenas_aspek_b_ekonomi() di app.py)
  aspek_b_checklist TINYINT(1) NULL,      -- ada >=1 indikator daya ungkit ekonomi yang didukung data?
  aspek_b_total_indikator TINYINT UNSIGNED NULL, -- jumlah indikator yang didukung data (dari 12 yg diimplementasi)
  aspek_b_narasi TEXT NULL,         -- rule-based: daftar indikator ada + jumlah penduduk/kendaraan
  aspek_b_narasi_ai TEXT NULL,      -- narasi naratif/persuasif hasil AI, PELENGKAP aspek_b_narasi
                                     -- (rule-based) -- bukan pengganti, tidak boleh mengarang fakta baru
  total_poin     TINYINT NULL,      -- A + B (0-4)
  kesimpulan     TEXT NULL,
  provider       VARCHAR(20) NULL,  -- Groq/Grok/OpenAI/Claude/Gemini
  model          VARCHAR(80) NULL,
  generated_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                 ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_penilaian_usulan FOREIGN KEY (usulan_id)
    REFERENCES usulan_inpres(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
