-- Akun login aplikasi, 3 role: admin (akses penuh, termasuk import xlsx
-- usulan IJD), user (view-only, tidak bisa import), dan umum (4 Okt 2026:
-- view-only tanpa hasil penilaian IJD -- hanya mode Sikon, lihat
-- _PATH_PENILAIAN di app.py). Tanpa CHECK constraint, jadi role baru tidak
-- butuh migrasi. Menggantikan
-- APP_USERNAME/APP_PASSWORD tunggal di .env -- nilainya cuma dipakai SEKALI
-- sbg seed akun admin pertama (lihat _seed_initial_admin_user() di app.py),
-- setelahnya kredensial login dikelola lewat tabel ini.
--
-- Password di-hash (auth.py, pbkdf2_hmac stdlib), TIDAK PERNAH disimpan
-- plaintext. Kelola akun lewat scripts/manage_users.py (tidak ada UI
-- manajemen user, sengaja -- di luar cakupan permintaan awal).
--
-- Dibuat & di-seed otomatis saat app.py startup (_seed_initial_admin_user).

CREATE TABLE IF NOT EXISTS users (
  username      TEXT PRIMARY KEY,
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL DEFAULT 'user',  -- 'admin' | 'user' | 'umum'
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
