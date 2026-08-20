-- Daftar kabupaten "Lokasi Prioritas" (Lokpri) lintas program nasional
-- (docs/New/2. LAUT/Dukungan Kawasan_R Pelabuhan Sandingan RPJMN-RKP-SBPI.xlsx,
-- sheet "List Lokpri") -- data referensi lintas-sektor, BUKAN spesifik
-- pelabuhan walau sumbernya ada di folder LAUT. Satu kabupaten bisa
-- muncul berkali-kali dengan status/kategori program berbeda (mis.
-- "Perbatasan Prioritas", "Kawasan Transmigrasi", "Food Estate", "Wisata",
-- dst., dikelompokkan ke kategori "3TP" atau "Pertum") -- karena itu
-- tidak ada primary key alami selain surrogate id.
--
-- Diisi scripts/import_list_lokpri_kawasan.py. Lihat
-- docs/kajian_data_baru_docs_new.md §4.2. TIDAK terkait usulan_inpres/IJD.

CREATE TABLE IF NOT EXISTS list_lokpri_kawasan (
  id           BIGSERIAL PRIMARY KEY,
  no_urut      INTEGER,
  kabupaten_lengkap TEXT,   -- mis. "Kab. Nias Utara" (apa adanya sumber)
  kabupaten    TEXT NOT NULL,   -- nama bersih, mis. "Nias Utara"
  status       TEXT,   -- mis. "Tertinggal", "Perbatasan Prioritas", "Food Estate"
  kategori     TEXT,   -- "3TP" | "Pertum"
  imported_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_list_lokpri_kawasan_kabupaten ON list_lokpri_kawasan (kabupaten);
