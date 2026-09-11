-- Kelengkapan data per kolom yang diminta docs/Requierment/Analisis Basarnas
-- (1).xlsx sheet "Lembar1" (template kosong -- header 13 kolom, baris contoh
-- placeholder "xxxx"/"yyyy"/"zzzz"), dicek satu-satu terhadap data BASARNAS
-- yang sudah kita punya (docs/New/6. BASARNAS/, lihat scripts/import_basarnas_
-- *.py dan schema_basarnas_*.sql) lalu diagregasi per Kantor/Pos SAR di sini
-- SUPAYA GAP-NYA TERLIHAT LANGSUNG di viewer "Data", bukan cuma didiskusikan
-- di chat. Dibangun scripts/build_basarnas_analisis_kantor.py, TIDAK terkait
-- usulan_inpres/IJD.
--
-- Status per kolom xlsx (dicek 21 Agu 2026):
--   No.                                          -> tersedia (nomor urut)
--   Lokasi                                       -> tersedia (nama_kantor / nama_pos, KANTOR SAR + POS SAR map_layers)
--   Provinsi                                     -> tersedia SECARA TURUNAN, bukan kolom sumber asli --
--                                                    dihitung via point-in-polygon (ST_Contains) titik kantor/pos
--                                                    terhadap layer "BATAS PROVINSI" (37/38 provinsi, sumber gdb resmi)
--   Status (Kantor/Pos)                          -> tersedia (dari layer titik yang jadi sumber baris: KANTOR SAR vs POS SAR)
--   Luas Cakupan Wilayah Kerja                   -> tersedia UNTUK KANTOR SAJA (bukan Pos), via ST_Area(geography)
--                                                    layer "WILAYAH TANGGUNG JAWAB SAR", di-join lewat call_sign --
--                                                    43/47 kantor punya poligon (Kantor Pusat/Balai SDM PP/Banyuwangi/
--                                                    Surakarta belum ada poligon di sumber gpkg-nya)
--   Termasuk Wilayah Rawan Bencana                -> TIDAK TERSEDIA -- tidak ada dataset kebencanaan (BNPB/indeks
--                                                    risiko bencana per wilayah kerja SAR) di seluruh docs/New/ atau
--                                                    tabel lain di database ini. Kolom tetap dibuat (selalu NULL)
--                                                    supaya gapnya eksplisit terlihat di viewer, bukan dihilangkan diam-diam.
--   Waktu Respon Rata-Rata Operasi                -> tersedia UNTUK KANTOR SAJA, dihitung dari basarnas_ops_sar
--                                                    (waktu_lapor -> waktu_tiba, hanya baris yg 2 kolom waktu itu
--                                                    terisi & selisihnya >= 0 -- ~58% dari 12.216 insiden). Dihitung
--                                                    sebagai MEDIAN (bukan rata-rata aritmetik) -- sumbernya punya
--                                                    sesekali typo tahun di waktu_tiba (mis. 2030) yang membuat rata-
--                                                    rata melompat jadi ribuan menit, median tahan thd outlier ini.
--   Jenis Kejadian Terbanyak 5 Tahun Terakhir     -> tersedia UNTUK KANTOR SAJA (basarnas_ops_sar.jenis_kecelakaan,
--                                                    modus per kantor, data sudah persis mencakup 2021-2025)
--   Jumlah Korban 5 Tahun Terakhir (Selamat/MD/Hilang) -> tersedia UNTUK KANTOR SAJA (SUM basarnas_ops_sar.selamat/
--                                                    meninggal_dunia/dalam_pencarian_hilang, 2021-2025)
--   Rata-Rata Jumlah Operasi Per Tahun            -> tersedia UNTUK KANTOR SAJA (COUNT(*) / 5 tahun sumber)
--   Rata-Rata Rasio Keberhasilan Operasi          -> tersedia UNTUK KANTOR SAJA (SUM(selamat) / SUM(korban) x 100%)
--   Jarak Tempuh Terjauh                          -> tersedia UNTUK KANTOR SAJA, dihitung (bukan kolom sumber) --
--                                                    jarak terbesar (ST_Distance geography) dari titik Kantor SAR ke
--                                                    titik lokasi insiden basarnas_ops_sar miliknya (lat/lon terisi
--                                                    100% di basarnas_ops_sar)
--   Jumlah Tenaga Pencarian dan Pertolongan Aktif -> tersedia UNTUK KANTOR SAJA (basarnas_rescuer_potensi.tenaga_total,
--                                                    di-join by satuan_kerja == nama kota kantor, cocok 100% utk 47/47 kantor)
--
-- Baris Pos SAR (status = 'Pos Pencarian dan Pertolongan') SENGAJA tetap
-- disertakan (bukan dihilangkan) supaya cakupan tabel ini mengikuti struktur
-- xlsx yang minta baris Kantor MAUPUN Pos -- tapi kolom operasional (Waktu
-- Respon s/d Jumlah Tenaga Aktif) semuanya NULL utk Pos, karena SETIAP sumber
-- data operasional di atas (ops SAR, rescuer/potensi, wilayah tanggung jawab)
-- direkam di granularitas KANTOR, tidak per Pos -- bukan bug/kelalaian join,
-- memang tidak ada datanya di level itu.
CREATE TABLE IF NOT EXISTS basarnas_analisis_kantor (
  no                                  INTEGER PRIMARY KEY,
  lokasi                              TEXT NOT NULL,
  status                              TEXT NOT NULL,   -- 'Kantor Pencarian dan Pertolongan' | 'Pos Pencarian dan Pertolongan'
  kantor_induk                        TEXT,             -- diisi utk baris Pos: nama Kantor SAR induknya
  provinsi                            TEXT,             -- turunan spasial, lihat catatan di atas
  luas_cakupan_wilayah_kerja_km2      NUMERIC(12, 2),
  termasuk_wilayah_rawan_bencana      TEXT,             -- selalu NULL, lihat catatan di atas -- kolom sengaja dipertahankan
  waktu_respon_rata_rata_menit        NUMERIC(10, 1),
  jenis_kejadian_terbanyak_5_tahun    TEXT,
  korban_selamat_5_tahun              INTEGER,
  korban_meninggal_dunia_5_tahun      INTEGER,
  korban_hilang_5_tahun               INTEGER,
  rata_rata_operasi_per_tahun         NUMERIC(10, 1),
  rata_rata_rasio_keberhasilan_persen NUMERIC(5, 1),
  jarak_tempuh_terjauh_km             NUMERIC(10, 1),
  jumlah_tenaga_aktif                 INTEGER,
  dibangun_at                         TIMESTAMPTZ NOT NULL DEFAULT now()
);
