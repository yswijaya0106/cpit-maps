-- Log setiap pertanyaan ke asisten chat (/api/chat): siapa bertanya, provider
-- & model yang menjawab, apakah itu model cadangan (provider di depannya
-- gagal) dan kenapa, durasi, token, tool & SQL yang dijalankan. Bahan ukur
-- kualitas/biaya & log audit -- Tahap 1 kajian agentic workflow
-- (docs/kajian_agentic_workflow_fitur_ai.md §7). Dibuat otomatis oleh app.py
-- (_catat_chat_log) saat pertama dipakai; baris > 180 hari dihapus saat
-- server start. TIDAK menyimpan isi jawaban, hanya metadata + pertanyaan.

CREATE TABLE IF NOT EXISTS chat_log (
  id                BIGSERIAL PRIMARY KEY,
  waktu             TIMESTAMPTZ NOT NULL DEFAULT now(),
  pengguna          TEXT,
  peran             TEXT,
  pertanyaan        TEXT,
  provider          TEXT,          -- NULL bila semua provider gagal (lihat galat)
  model             TEXT,
  cadangan          BOOLEAN,       -- true = provider di depannya gagal
  gagal_sebelumnya  JSONB,         -- [{provider, model, alasan}]
  durasi_detik      REAL,
  token_masuk       INTEGER,
  token_keluar      INTEGER,
  tools             TEXT[],        -- nama tool yg dipanggil, berurutan
  sql_dijalankan    TEXT[],
  dataset_ids       TEXT[],
  galat             TEXT
);

CREATE INDEX IF NOT EXISTS idx_chat_log_waktu ON chat_log (waktu);
