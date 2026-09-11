-- Kolom precompute untuk skor "Urgensitas Penanganan Pelabuhan"
-- (docs/kajian_implementasi_skor_urgensi_pelabuhan_laut.md,
-- docs/checklist_implementasi_skor_urgensi_pelabuhan.md, sumber
-- "Kerangka berpikir lAUT (1).pptx"). Lingkup Fase 1 tahap 1a: parameter
-- #3 "Kedekatan dengan Pelabuhan Lain" saja -- kolom untuk parameter
-- lain ditambah di tahap berikutnya (1b dst.), bukan sekaligus, supaya
-- migrasi tetap kecil per tahap.
--
-- hirarki_kode diturunkan dari hirarki_pelabuhan (teks bebas seperti
-- "Laut - Pelabuhan Pengumpan Lokal (PL)") via kode 2 huruf di akhir
-- string -- HANYA PP/PR/PL yang ada di data saat ini (tidak ada PU,
-- lihat checklist §"Temuan tambahan"), kategori non-"Laut -" (Sungai/
-- Danau, Penyeberangan, Tidak ada) sengaja dibiarkan NULL karena di luar
-- cakupan kerangka ini.
--
-- Diisi scripts/spatial_join_pelabuhan_urgensi.py.

ALTER TABLE pelabuhan_daerah ADD COLUMN IF NOT EXISTS hirarki_kode TEXT;
ALTER TABLE pelabuhan_daerah ADD COLUMN IF NOT EXISTS pelabuhan_sehirarki_terdekat_id BIGINT;
ALTER TABLE pelabuhan_daerah ADD COLUMN IF NOT EXISTS pelabuhan_sehirarki_terdekat_nama TEXT;
ALTER TABLE pelabuhan_daerah ADD COLUMN IF NOT EXISTS jarak_sehirarki_terdekat_km NUMERIC(10, 3);

CREATE INDEX IF NOT EXISTS idx_pelabuhan_daerah_hirarki_kode ON pelabuhan_daerah (hirarki_kode);

-- Tahap 1b: parameter #6 "Jumlah Penduduk" dalam radius (per hirarki --
-- radius PP=93km memakai unit KABUPATEN, radius PR=60km/PL=40km memakai
-- unit KECAMATAN, sesuai slide 5 pptx sumber). Radius sengaja TIDAK
-- disimpan sbg kolom (diturunkan dari hirarki_kode di kode scorer),
-- kolom di bawah cuma HASIL agregasinya.
--
-- penduduk_radius_wilayah_json: daftar {kode, nama, penduduk} unit
-- wilayah (kabupaten utk PP, kecamatan utk PR/PL) yang polygon-nya
-- (map_layers "BATAS KABUPATEN"/"BATAS KECAMATAN") dalam radius dari
-- titik pelabuhan -- disimpan mentah (bukan cuma total) supaya export
-- bisa menunjukkan wilayah mana saja yg ikut dihitung (kajian §6, kolom
-- "Wilayah Tercakup").
ALTER TABLE pelabuhan_daerah ADD COLUMN IF NOT EXISTS penduduk_radius_total INTEGER;
ALTER TABLE pelabuhan_daerah ADD COLUMN IF NOT EXISTS penduduk_radius_wilayah_json JSONB;

-- Tahap 1c: parameter #4 "Klasifikasi Wilayah 3TP", versi kategorikal
-- (bukan versi jarak 0-7+0-3 penuh -- itu butuh geometri wilayah 3T/
-- perbatasan yang belum ada, lihat Fase 2). Kabupaten pelabuhan dicocokkan
-- ke list_lokpri_kawasan (kategori='3TP' saja, kategori='Pertum' di luar
-- cakupan parameter ini). ASUMSI pemetaan status->tingkatan (BELUM
-- dikonfirmasi ke pemilik kaidah): status mengandung "Perbatasan" -> tier
-- perbatasan, status mengandung "Tertinggal" -> tier 3T, kabupaten dengan
-- KEDUA jenis status -> tier 3TP gabungan (nilai tertinggi). Lihat
-- scripts/spatial_join_pelabuhan_urgensi.py fungsi _isi_klasifikasi_3tp().
ALTER TABLE pelabuhan_daerah ADD COLUMN IF NOT EXISTS klasifikasi_3tp_kategori TEXT;
ALTER TABLE pelabuhan_daerah ADD COLUMN IF NOT EXISTS klasifikasi_3tp_program_json JSONB;

-- Tahap 1e: parameter #7 "Kemudahan Akses" (kemantapan + lebar jalan),
-- versi cakupan-terbatas -- HANYA menjangkau ruas usulan_inpres (program
-- IJD) yang kebetulan ada dalam radius yang sama dgn tahap 1b (PP 93km/
-- PR 60km/PL 40km). Kondisi & lebar jalan seluruh jaringan (bukan cuma
-- usulan IJD) adalah item Fase 2 terpisah. ruas_ijd_terdekat_id NULL
-- berarti tidak ada usulan IJD manapun dalam radius pelabuhan itu (bukan
-- error) -- scorer harus melapor tersedia:false utk baris begitu, BUKAN
-- fallback diam-diam ke kabupaten (itu keputusan scorer, bukan di sini).
ALTER TABLE pelabuhan_daerah ADD COLUMN IF NOT EXISTS ruas_ijd_terdekat_id INTEGER;
ALTER TABLE pelabuhan_daerah ADD COLUMN IF NOT EXISTS ruas_ijd_terdekat_nama TEXT;
ALTER TABLE pelabuhan_daerah ADD COLUMN IF NOT EXISTS ruas_ijd_terdekat_jarak_km NUMERIC(10, 3);
ALTER TABLE pelabuhan_daerah ADD COLUMN IF NOT EXISTS ruas_ijd_kondisi_baik_km NUMERIC(10, 3);
ALTER TABLE pelabuhan_daerah ADD COLUMN IF NOT EXISTS ruas_ijd_kondisi_sedang_km NUMERIC(10, 3);
ALTER TABLE pelabuhan_daerah ADD COLUMN IF NOT EXISTS ruas_ijd_kondisi_ringan_km NUMERIC(10, 3);
ALTER TABLE pelabuhan_daerah ADD COLUMN IF NOT EXISTS ruas_ijd_kondisi_berat_km NUMERIC(10, 3);
ALTER TABLE pelabuhan_daerah ADD COLUMN IF NOT EXISTS ruas_ijd_lebar_jalan_m NUMERIC(6, 2);
