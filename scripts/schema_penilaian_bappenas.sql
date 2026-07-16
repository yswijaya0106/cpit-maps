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
  aspek_a_poin   TINYINT NULL,      -- 0/1/2
  aspek_a_narasi TEXT NULL,
  aspek_b_poin   TINYINT NULL,      -- 0/1/2
  aspek_b_narasi TEXT NULL,
  total_poin     TINYINT NULL,      -- A + B (0-4)
  kesimpulan     TEXT NULL,
  provider       VARCHAR(20) NULL,  -- Groq/Grok/OpenAI/Claude/Gemini
  model          VARCHAR(80) NULL,
  generated_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                 ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_penilaian_usulan FOREIGN KEY (usulan_id)
    REFERENCES usulan_inpres(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
