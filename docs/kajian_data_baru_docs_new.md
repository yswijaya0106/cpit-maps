# Kajian Data Baru `docs/New/` dan Strategi Implementasi Bertahap

Kajian ini membahas dataset baru yang ditempatkan di `docs/New/` (dump
Google Drive multi-moda transportasi, 9 kategori: DATA SHP, JALAN, LAUT,
UDARA, KERETA (KA), DARAT, BASARNAS, KESELAMATAN, DATA LAINNYA), memisahkan
mana yang tumpang tindih dengan data yang sudah ada di aplikasi vs. mana
yang benar-benar baru, dan mengusulkan urutan implementasi.

**Catatan penting: kajian ini TIDAK ADA KAITANNYA SAMA SEKALI dengan IJD**
(Inpres Jalan Daerah — `usulan_inpres`, skoring A-E, NPR, Laporan Prioritas,
Aspek A/B, dsb). Semua yang dibahas di sini adalah **layer overlay peta
umum** untuk fitur reference-map (`/api/maps/*`, `map_layers`/
`map_layer_meta`) yang berdiri sendiri — sama kelasnya dengan layer
BANDARA/PETA KORIDOR/BATAS KECAMATAN yang sudah ada, dipakai untuk
visualisasi/analitik peta secara umum (identify, overlay, layer picker),
bukan input ke proses usulan atau skoring IJD apa pun. Jangan hubungkan
rekomendasi di dokumen ini ke `_IJD_SCORERS`, `ijd_scoring_rules`,
`usulan_inpres`, atau narasi Aspek A/B.

## 1. Ringkasan per kategori

### 1.1 Overlap / sekadar pembaruan (prioritas rendah)

| Kategori | Isi | Status vs. data existing |
|---|---|---|
| Bandara (SHP) | ~87 titik bandara nasional | Sudah ada `Maps/BANDARA` → `map_layers`. xlsx UDARA (251 bandara, detail di §5) punya atribut jauh lebih kaya (runway length/width, apron area, terminal m², demand pax, critical aircraft, kode wilayah `KP`/`KD` resmi) — nilai tambahnya di **pengayaan atribut**, bukan layer baru |
| Pelabuhan (RIPN/PT) | Titik pelabuhan nasional | Sudah ada layer pelabuhan/pelabuhan penyeberangan |
| Kemantapan Jalan Nasional/Daerah | xlsx kondisi ruas 2025-2027 | Sepadan dengan `import_kemantapan_ijd2026.py` — kemungkinan pembaruan tahun data, bukan sumber baru |
| BPS Dalam Angka Provinsi 2026 | 34 PDF | Cocok dengan fitur "Dalam Angka" yang sudah ada (`dalam_angka_publikasi`) — pelengkap tahun terbaru |

### 1.2 Data benar-benar baru (kandidat kontribusi)

**BASARNAS** — domain lengkap, belum ada sama sekali di aplikasi:
- Titik Kantor SAR & Pos SAR (KML/SHP/GPKG + metadata XML)
- Polygon "Wilayah Tanggung Jawab Kantor Pencarian dan Pertolongan" (nasional)
- Data Ops SAR 2021-2025 per kejadian: lat/lon, jenis kejadian (pesawat/
  kapal/bencana), timeline waktu kejadian→selesai, korban selamat/meninggal
- Sarpras (ALUT SAR udara/darat/laut: kendaraan, kapal, pesawat)
- Data rescuer/potensi, rekap pendidikan & pelatihan (peserta/tenaga
  pendidik) 2021-2025

**Keselamatan Jalan** — kategori baru:
- Blackspot Bina Marga Jalan Nasional 2020-2024 (titik lat/lon rawan
  kecelakaan per ruas jalan nasional — overlay langsung ke layer JALAN
  NASIONAL yang sudah ada)
- LHR (Lalu Lintas Harian Rata-rata) 2024
- ANEV Laka Lantas 2020-2025, KEP Data Laka (7 tahun PDF), RUNK 2021-2025
- PSC 119 (survei layanan call-center darurat per kab/kota — data
  operasional, belum geo-ready)

**Kereta Api / LRT** — moda absen total dari aplikasi saat ini:
- Jaringan rel nasional (SHP), plus shapefile jalur aktif Jawa/Sumatera
- OD (origin-destination) penumpang LRT Jabodebek 2025 (matriks antar 18
  stasiun)

**Transjakarta & Angkutan Perintis**
- Rute + halte Transjakarta (SHP)
- Angkutan Perintis Darat 2026, ANGKUTAN PERINTIS (multimoda)
- Rekap ridership BRT/KA 10 kota metro 2020-2025 (LKJ 2025)

**RTRW-Perda**
- Baru 2 kabupaten (Bandung, Kebumen) — PDF regulasi tata ruang, bukan
  data spasial siap pakai; relevan sebagai referensi kebijakan, bukan
  layer peta

**Pelabuhan TERSUS/TUKS**
- Dermaga khusus/untuk kepentingan sendiri, koordinat + atribut
  penyelenggara/bidang kegiatan — jenis pelabuhan yang belum punya layer
  di aplikasi. Detail lengkap di §4.4 — koordinat lat/lon tersedia
  langsung di xlsx (~1979 titik nasional), import paling sederhana di
  seluruh dataset.

## 2. Pola integrasi yang konsisten dengan arsitektur saat ini

Semua data spasial baru mengikuti pola yang sudah mapan di aplikasi:

- **Layer overlay baru** → tabel generik `map_layers`/`map_layer_meta`
  (bukan tabel per layer), lewat script `scripts/import_<nama>_to_postgis.py`
  baru — sama seperti `import_peta_koridor_to_postgis.py` atau
  `import_batas_administrasi_kecamatan.py`. Endpoint `/api/maps/*` yang
  sudah generic (`maps_provinces`/`maps_kabupaten`/`maps_layers`/
  `maps_layer`) **tidak perlu diubah** — cukup tambah entri di
  `MAP_LAYER_LABELS` (`map_layer_labels.py`) untuk label tampilan.
- **Analitik spasial umum** (mis. "titik SAR/blackspot terdekat dari
  suatu lokasi/rute yang sedang dilihat di peta") → memakai pola yang
  sama dengan tool chat `analisa_spasial_usulan`/`daftar_layer_peta_
  overlay` (query PostGIS `ST_DWithin`/KNN langsung terhadap `map_layers`),
  bukan tabel precompute yang terikat ke `usulan_inpres` — karena layer
  ini dipakai lintas konteks peta, bukan hanya konteks usulan IJD.
- **Tidak berkaitan dengan** `_IJD_SCORERS`/`ijd_scoring_rules`/
  `usulan_inpres` — murni layer overlay peta baru untuk fitur reference-map
  umum.

## 3. Strategi implementasi bertahap

### Fase 1 — BASARNAS (dampak tinggi, data paling siap — detail di §8)
1. Import titik Kantor SAR (47) + Pos SAR (85) sebagai layer `map_layers`
   (`layer="KANTOR SAR"` / `"POS SAR"`) — sumber GPKG sudah EPSG:4326,
   pola sama seperti `import_batas_administrasi_kecamatan.py` tapi untuk
   titik, tanpa perlu reprojection.
2. Import polygon "Wilayah Tanggung Jawab" (43 wilayah) sebagai layer
   terpisah (`layer="WILAYAH TANGGUNG JAWAB SAR"`) — **wajib pakai
   `engine="pyogrio"`** saat baca SHP-nya (fiona gagal dengan error
   `create_collection`, bug shapely/numpy MultiPolygon-from-dict yang
   sama seperti `Maps/BATAS_ADMINISTRASI.gdb`).
3. (Opsional, prioritas tinggi juga — lihat §8.4) Import data Ops SAR
   2021-2025 (~12.000 insiden, koordinat + linimasa respons per kejadian)
   sebagai layer "riwayat insiden SAR" atau agregat statistik per
   kecamatan/kabupaten/tahun — nilai analitiknya tinggi (response-time,
   sebaran jenis kecelakaan) tapi volume besar, perlu keputusan agregasi
   vs. per-titik (lihat §9). Murni untuk visualisasi/analitik peta umum
   (mis. tool chat spasial generik), tidak terikat ke `usulan_inpres`
   atau IJD.
4. (Opsional, lanjutan) ALUT (§8.2) dan Rescuer/Potensi (§8.3) sebagai
   atribut identify-popup pada titik Kantor SAR — perlu normalisasi
   kolom `Kondisi Saat Ini` (nilai bebas: S/US/Baik/Rusak Ringan/dll.)
   sebelum dipakai untuk agregasi kesiapan alat.

### Fase 2 — Blackspot & Keselamatan Jalan (detail terverifikasi di §9)
1. Import titik blackspot Bina Marga (§9.2, 840 dari 955 baris valid —
   **filter baris dengan `LTG`/`BJR` kosong/tak-terparse dulu**, ~12%
   baris cacat) sebagai layer overlay pada JALAN NASIONAL yang sudah ada
   (`layer="BLACKSPOT KECELAKAAN"`) — layer peta umum, lepas dari
   konteks usulan IJD mana pun.
2. LHR per-ruas (§9.3, 3.310 baris, AADT + VCR per ruas) — **prioritas
   naik**: bukan sekadar pelengkap, VCR adalah indikator kemacetan siap
   pakai yang belum ada di aplikasi. Cocok sebagai atribut pengayaan
   identify-popup JALAN NASIONAL (join via `Linkid`/`Linkname`, perlu
   dicek kecocokan penamaan ruas) atau tabel referensi terpisah.
3. ANEV Laka Lantas (§9.1, xlsx per-Polda) sebagai tabel referensi
   statistik keselamatan per provinsi — **lebih diprioritaskan daripada
   PDF KEP DATA LAKA** (§9.6) yang kualitas ekstraksinya buruk (4 dari
   7 tahun full-scan, butuh OCR) padahal mencakup rentang tahun yang
   sama; PDF cukup jadi rujukan legal.
4. LRK 2026 (§9.5) sebagai layer titik tambahan kecil (129 titik,
   koordinat tertanam di teks — regex, mirip §7.4 Terminal Tipe A) —
   prioritas rendah dibanding Blackspot yang cakupannya jauh lebih
   besar (5 tahun vs. 1 tahun).
5. PSC 119 (§9.4): **redaksi kolom kontak personal (nama, WA, email)
   sebelum diimpor** jika data substantifnya (kapasitas layanan gawat
   darurat per kab/kota) mau dipakai — data self-reported, bukan layer
   peta (tanpa koordinat).

### Fase 3 — Kereta Api / LRT
1. Import jaringan rel nasional (SHP) sebagai layer `map_layers`
   (`layer="JALUR KERETA API"`) — satu-satunya bagian kategori KERETA
   yang menghasilkan data spasial siap pakai (lihat §6, sumbernya folder
   "0. DATA SHP", bukan "4. KERETA (KA)").
2. OD penumpang LRT Jabodebek & peta skematik Jawa/Sumatera (folder "4.
   KERETA (KA)", detail §6): nilai analitiknya spesifik Jabodebek (bukan
   nasional) dan tidak punya koordinat siap pakai — **prioritas rendah**,
   cukup sebagai referensi tanpa integrasi DB kecuali ada kebutuhan
   spesifik analitik transit perkotaan Jabodetabek.

### Fase 4 — Terminal Tipe A, Pelabuhan Penyeberangan, TERSUS/TUKS, Transjakarta
1. **Terminal Tipe A** (§7.4, sumber PDF `KM_109_Tahun_2019`): layer titik
   baru `layer="TERMINAL TIPE A"`, 126 titik nasional — usaha impor
   rendah (ekstraksi teks PDF + regex koordinat desimal, tanpa
   geopandas), **prioritas naik** bersama TERSUS/TUKS.
2. Pelabuhan TERSUS/TUKS: import sebagai layer tambahan pada kategori
   pelabuhan yang sudah ada (`layer="PELABUHAN TERSUS/TUKS"`) — **prioritas
   naik**, lihat §4.4: sumbernya xlsx dengan lat/lon langsung, jauh lebih
   sederhana diimpor daripada layer SHP lain (tidak perlu geopandas/parsing
   shapefile).
3. **Pelabuhan Penyeberangan Operasi** (§7.2): upgrade/tambahan atribut
   pada layer pelabuhan penyeberangan existing — granularitas kecamatan,
   status operasi eksplisit, dan pengelola (PemProv/BPTD).
4. Halte + rute Transjakarta sebagai layer opsional (konteks perkotaan
   Jabodetabek, di luar fokus utama IJD nasional) — prioritas rendah
   kecuali ada permintaan spesifik.
5. Angkutan Perintis (darat/multimoda, §7.1) dan Rekap Ridership BRT/KA
   (§7.3): tidak punya koordinat sama sekali — cukup referensi
   dokumen/kebijakan, bukan layer peta.

### Fase 5 — RTRW-Perda & referensi kebijakan
1. Simpan sebagai dokumen referensi (link/PDF), belum berupa data spasial.
2. Kumpulkan lebih banyak kabupaten sebelum dipertimbangkan sebagai basis
   "kesesuaian RTRW" — 2 kabupaten belum representatif untuk fitur
   nasional.

### Checklist implementasi per fase

Status `[ ]` = belum dikerjakan. Update checkbox ini seiring progres
(pola sama seperti `docs/checklist_implementasi_cpit.md`) — dokumen ini
murni layer overlay peta umum, **tidak menyentuh** `_IJD_SCORERS`/
`ijd_scoring_rules`/`usulan_inpres` di manapun dalam checklist berikut.

**Fase 1 — BASARNAS**
- [x] Baca 3 dataset spasial dari GPKG (`Kantor SAR`, `Pos SAR`, `Wilayah
      Tanggung Jawab`) — polygon wajib `engine="pyogrio"` (fiona gagal,
      bug shapely/numpy `create_collection` yang sama dengan
      `BATAS_ADMINISTRASI.gdb`); dipakai untuk ketiganya demi konsistensi.
- [x] `scripts/import_basarnas_to_postgis.py` dibuat & dijalankan: 47
      Kantor SAR + 85 Pos SAR + 43 Wilayah Tanggung Jawab masuk
      `map_layers` (bucket flat `provinsi="BASARNAS"`, `kabupaten=""`,
      pola sama dengan JALAN PROVINSI/JALAN TOL), idempotent
      (skip kecuali `--force`).
- [x] Entri label ditambahkan di `map_layer_labels.py`.
- [x] **Temuan tambahan saat verifikasi**: `MAP_LAYER_CATEGORIES` di
      `static/js/maps-overlay.js` punya catatan eksplisit bahwa bucket
      provinsi flat baru WAJIB didaftarkan di sana atau diam-diam jatuh
      ke kategori catch-all "Jalan" (persis bug yang pernah kejadian di
      BATAS KABUPATEN/PROVINSI). Ditambahkan kategori baru "Pencarian &
      Pertolongan (SAR)" (`id: "sar"`, ikon `bi-life-preserver`) khusus
      untuk bucket `BASARNAS` — sekaligus menjawab diskusi pengelompokan
      sektor di dropdown Overlay Peta sebelumnya.
- [x] Diuji end-to-end lewat server aktif (bukan cuma query DB langsung):
      `GET /api/maps/provinces` menampilkan `BASARNAS`, `GET
      /api/maps/kabupaten?provinsi=BASARNAS` mengembalikan bucket flat
      (`kabupaten=""`, `layer_count=3`), `GET /api/maps/layers` & `GET
      /api/maps/layer` mengembalikan GeoJSON dengan atribut
      (`nama_kantor`, `call_sign`, `tipe_kelas`, dst.) dengan benar.
- [ ] **Catatan untuk nanti** (opsional, belum dikerjakan):
  - Import data Ops SAR 2021-2025 — putuskan dulu: per-titik mentah vs.
    agregat kecamatan/kabupaten/tahun (lihat §9 catatan volume) sebelum
    menulis scriptnya.
  - Normalisasi kolom `Kondisi Saat Ini` ALUT (S/US/lainnya) lalu simpan
    sebagai tabel atribut terpisah, join manual di identify-popup Kantor
    SAR (bukan kolom `map_layers.attrs`, karena datanya banyak-ke-satu
    per kantor).

**Fase 2 — Blackspot & Keselamatan Jalan**
- [x] Parsing Blackspot Bina Marga: konversi `LTG`/`BJR` teks→float +
      validasi rentang lat/lon Indonesia, buang baris kosong/tak-terparse
      (116/955 dibuang, 839 titik valid — sedikit lebih tinggi dari
      estimasi awal ~115 karena validasi rentang juga menangkap sisa
      anomali yang lolos parsing float).
- [x] `scripts/import_blackspot_to_postgis.py` dibuat & dijalankan →
      839 titik masuk `map_layers` sebagai `layer="BLACKSPOT
      KECELAKAAN"`, ditumpangkan pada bucket `JALAN NASIONAL` yang sudah
      ada (bukan bucket baru) supaya muncul sejajar dengan layer garis
      jalan nasional — sesuai maksud "overlay pada JALAN NASIONAL"; tidak
      perlu registrasi kategori baru di `maps-overlay.js` karena bucket
      ini sudah tercakup kategori catch-all "Jalan".
- [x] Cek kecocokan `Linkid` LHR terhadap `attrs->>'LINKID'` layer JALAN
      NASIONAL existing: **3306/3306 LINKID di DB ditemukan persis** di
      3307 baris LHR (hanya 1 baris LHR tanpa pasangan) — match hampir
      sempurna, tanpa perlu fuzzy-match nama ruas.
- [x] **Keputusan skema LHR: tabel terpisah** `bps_lhr_ruas_nasional`
      (bukan menyuntik ke `attrs` JSONB layer JALAN NASIONAL) — supaya
      reimport layer JALAN NASIONAL dan reimport LHR independen satu sama
      lain, tidak saling mengunci proses. `scripts/schema_bps_lhr_ruas_
      nasional.sql` + `scripts/import_lhr_ruas_nasional.py` dibuat &
      dijalankan (3307 baris, UPSERT per `linkid`), didaftarkan di
      `DATA_TABLES`.
- [x] Import ANEV Laka Lantas sebagai 2 tabel `Data` viewer baru
      (`DATA_TABLES` whitelist): `anev_laka_lantas_nasional` (sheet
      REKAP, format long/tidy — sumbernya 25 kategori hierarkis dengan
      URAIAN/SATUAN berbeda-beda per kategori, jadi tidak dipaksa jadi
      tabel rectangular; 1.641 baris) dan `anev_laka_lantas_polda`
      (sheet POLDA, rectangular per polda×tahun; 216 baris = 36 polda ×
      6 tahun). `scripts/schema_anev_laka_lantas.sql` +
      `scripts/import_anev_laka_lantas.py` dibuat & dijalankan, nilai
      dicek sampel manual (Aceh 2020/nasional 2020 cocok persis dengan
      angka mentah di xlsx). PDF KEP DATA LAKA tetap dilewati sesuai
      rencana (kualitas ekstraksi buruk, xlsx ini sudah mencakup rentang
      tahun yang sama dengan struktur rapi).
- [x] Diverifikasi end-to-end lewat server terisolasi (port lain, supaya
      tidak mengganggu server dev yang mungkin sedang berjalan di
      port 8000): `GET /api/data/tables` menampilkan ketiga tabel baru
      dengan jumlah baris yang cocok, `GET /api/maps/layers?provinsi=
      JALAN%20NASIONAL` menampilkan `BLACKSPOT KECELAKAAN` sejajar
      dengan layer jalan lain.
- [ ] **Catatan untuk nanti** (opsional, belum dikerjakan — didaftarkan
      di sini supaya tidak hilang, prioritas menyusul):
  - Ekstrak `LRK 2026` via regex koordinat dari teks ruas → layer titik
    kecil (129 titik/1 tahun, jauh lebih kecil cakupannya dari Blackspot
    yang 5 tahun/839 titik).
  - PSC 119: kalau suatu saat dipakai, wajib redaksi kolom kontak
    personal (nama, WA, email) sebelum data masuk tahap impor apa pun —
    data self-reported, non-spasial, granularitas kab/kota.

**Fase 3 — Kereta Api**
- [x] `scripts/import_kereta_api_to_postgis.py` dibuat & dijalankan, 2
      layer di bucket flat nasional `JALUR KERETA API` (pola sama dengan
      BASARNAS): `layer="JALUR KERETA API"` dari `Rel KA_2022.shp`
      (1.460 ruas nasional, atribut minim) dan `layer="JALUR KERETA API
      AKTIF (BTP)"` dari 7 file per-BTP (Jakarta/Semarang/Surabaya/
      Bandung/Medan/Padang/Palembang, 668 fitur total, atribut jauh
      lebih kaya — KM_START/END, DAOPDIVREI, LINTASID, PETAK1/PETAK2,
      STATUS aktif/tidak). **Ditemukan saat implementasi** (tidak
      tercatat di kajian awal): sumbernya bukan cuma "Rel KA_2022.shp"
      tunggal — ada 2 file zip `Jalan_Rel_Aktif_BTP` per pulau yang jauh
      lebih detail operasionalnya, walau cakupannya cuma 7 wilayah kerja
      BTP (bukan nasional penuh) — diimpor sebagai layer kedua, bukan
      pengganti, supaya cakupan nasional dari `Rel KA_2022` tidak hilang.
      File Jawa berproyeksi EPSG:32748 (UTM 48S), direproyeksi otomatis;
      file Sumatera sudah EPSG:4326.
- [x] Kategori baru "Kereta Api" (`id: "kereta-api"`, ikon
      `bi-train-front`) didaftarkan di `MAP_LAYER_CATEGORIES`
      (`maps-overlay.js`) — bucket flat baru wajib didaftarkan di sana
      atau jatuh ke catch-all "Jalan" (gotcha yang sama seperti BASARNAS
      di Fase 1).
- [x] Diverifikasi lewat server terisolasi: `GET /api/maps/kabupaten`,
      `.../layers`, `.../layer` mengembalikan kedua layer dengan
      geometri LineString/atribut yang benar.
- [ ] OD LRT Jabodebek & peta skematik: tunda, tidak ada aksi kecuali ada
      permintaan spesifik transit perkotaan.

**Fase 4 — Terminal Tipe A, TERSUS/TUKS, Pelabuhan Penyeberangan**
- [x] `scripts/import_terminal_tipe_a_to_postgis.py` dibuat & dijalankan:
      ekstrak lampiran PDF `KM_109_Tahun_2019` via PyMuPDF, split per
      entri dengan regex nomor urut, regex pasangan desimal setelah `/`
      (fallback ke DMS→desimal untuk entri yang formatnya rusak),
      validasi rentang lat -11..6/lon 95..141. **125/126 titik berhasil**
      (120 lewat desimal, 5 lewat fallback DMS); persis 1 gagal total
      sesuai prediksi kajian (No. 120 "Terminal Bolaang Mongondow",
      `"125°59'54.89.1°E"` — dua desimal bertumpuk, tidak
      direkonstruksi otomatis, dicatat & dilewati) → `layer="TERMINAL
      TIPE A"`.
- [x] `scripts/import_pelabuhan_tersus_tuks_to_postgis.py` dibuat &
      dijalankan: 1.978 dari 1.978 titik valid (0 dibuang) → `layer=
      "PELABUHAN TERSUS/TUKS"`.
- [x] `scripts/import_pelabuhan_penyeberangan_operasi_to_postgis.py`
      dibuat & dijalankan: parser DMS lebih rumit dari dugaan awal —
      **ditemukan variasi format** (sebagian pakai N/S/E/W, sebagian
      notasi Indonesia LU/LS/BT/BB, satu baris pakai koma sbg pemisah
      desimal) yang butuh regex lebih longgar dari perkiraan; setelah
      disesuaikan, **235/235 titik berhasil diparse** (0 dibuang),
      baris header romawi provinsi dilewati otomatis → layer baru
      `layer="PELABUHAN PENYEBERANGAN OPERASI"` (ejaan benar, terpisah
      dari bucket lama `PELABUHAN PENYEBRANGAN` yang sumbernya SHP RBI
      — bukan menimpa, supaya sumber data lama & baru tidak tercampur).
- [x] Entri label ditambahkan di `map_layer_labels.py` untuk ketiga
      layer, dan ketiganya didaftarkan ke kategori existing "Simpul
      Transportasi" di `maps-overlay.js` (bukan kategori baru — secara
      konseptual sejenis BANDARA/PELABUHAN yang sudah ada di sana).
- [x] Diverifikasi lewat server terisolasi: ketiga layer tampil dengan
      jumlah fitur yang cocok di `GET /api/maps/kabupaten`.
- [ ] Transjakarta, Angkutan Perintis, Rekap Ridership BRT/KA: tunda.

**Fase 5 — RTRW-Perda**
- [x] Diputuskan: **cukup referensi, tidak ada aksi impor**. Sumbernya
      cuma 2 PDF Perda (`docs/New/1. JALAN/DATA DUKUNG/2. RTRW-Perda/
      Perda Kabupaten Bandung.pdf` & `Perda Kabupaten Kebumen.pdf`) —
      2 kabupaten belum representatif untuk fitur nasional "kesesuaian
      RTRW", dan isinya regulasi tata ruang tekstual (bukan data spasial
      siap pakai). Ditinjau ulang kalau cakupan kabupaten bertambah di
      masa depan.

**Lintas-fase (dikerjakan sekali, bukan per fase)**
- [x] Pengelompokan sektor di dropdown "Overlay Peta" **diselesaikan
      langsung per-fase** (bukan migrasi skema tag terpisah di
      `map_layer_meta` seperti opsi awal): tiap bucket flat nasional baru
      didaftarkan ke `MAP_LAYER_CATEGORIES` (`maps-overlay.js`) saat
      layernya dibuat — kategori baru "Pencarian & Pertolongan (SAR)"
      (Fase 1), "Kereta Api" (Fase 3), dan 3 bucket Fase 4 diperluas ke
      kategori existing "Simpul Transportasi". Konsisten dengan gotcha
      yang sudah didokumentasikan di kode: bucket flat baru WAJIB
      didaftarkan di sana atau diam-diam jatuh ke catch-all "Jalan".

**Ringkasan status (setelah Fase 1-5)**: seluruh rencana implementasi
bertahap di dokumen ini SELESAI. 8 layer/tabel baru hidup di aplikasi —
3 layer BASARNAS, 1 layer Blackspot + 2 tabel referensi (LHR, ANEV Laka
Lantas), 2 layer Kereta Api, 3 layer Fase 4 (Terminal Tipe A, TERSUS/
TUKS, Pelabuhan Penyeberangan Operasi) — semuanya diverifikasi hidup
lewat server aktif (bukan cuma query DB), dan RTRW-Perda diputuskan
cukup referensi. Item opsional yang sengaja ditunda (Data Ops SAR,
LRK 2026, PSC 119, Transjakarta, Angkutan Perintis, Rekap Ridership
BRT/KA, OD LRT Jabodebek) tetap tercatat di checklist di atas untuk
pengerjaan lanjutan kapan pun dibutuhkan. Tidak ada satu pun perubahan
yang menyentuh `_IJD_SCORERS`, `ijd_scoring_rules`, `usulan_inpres`,
atau endpoint skoring IJD manapun.

### Susulan setelah Fase 1-5: 4 sumber tambahan diimplementasikan

Setelah kajian ulang lintas seluruh `docs/New/` (bukan cuma yang sudah
kena fase), ditemukan 1 **gap** (Pelabuhan Penumpang — sudah dianalisis
di §4.3 tapi tidak jadi masuk Fase 4) dan beberapa kandidat prioritas
sedang yang belum dikerjakan. Empat di antaranya diimplementasikan:

- [x] **Pelabuhan Penumpang** (§4.3, gap dari Fase 4): 546 dari 547
      titik valid (1 dibuang, koordinat di luar rentang Indonesia) →
      `scripts/import_pelabuhan_penumpang_to_postgis.py`, layer baru
      `layer="PELABUHAN PENUMPANG"` (bucket flat terpisah dari layer
      "PELABUHAN" SHP existing), didaftarkan ke kategori "Simpul
      Transportasi".
- [x] **Atribut Detail Bandara** (§5): `scripts/schema_bps_data_bandara.sql`
      + `scripts/import_bps_data_bandara.py` — tabel referensi 251
      bandara. **Ditemukan & diperbaiki saat implementasi**: asumsi
      index kolom awal (`COL_KAP_VALID`/`COL_KAP_ESTIMASI`/
      `COL_KOORDINAT`/`KP`/`KD`) meleset 1 kolom dari struktur sumber
      sebenarnya — diverifikasi ulang manual terhadap baris data mentah
      sebelum dikoreksi. Baris kelanjutan multi-taxiway berhasil
      digabung ke bandara induknya (contoh: Sultan Iskandar Muda,
      5 taxiway tergabung), nilai "Tidak Terdefinisi" pada Apron Area
      dikonversi jadi NULL (bukan dipaksa jadi angka), lat/lon berhasil
      diparse untuk 247/251 bandara (4 sisanya memang tidak punya
      koordinat di sumber, sesuai temuan awal kajian).
- [x] **ALUT SAR** (§8.2): `scripts/schema_basarnas_alut.sql` +
      `scripts/import_basarnas_alut.py` — 3.939 baris gabungan 3 matra
      (130 udara, 1.664 darat, 2.145 laut; lebih tinggi dari estimasi
      awal kajian karena baris "penanda kategori" & "Tidak Memiliki"
      ikut diimpor apa adanya, bukan cuma unit individual). Offset
      kolom header terdeteksi otomatis per file (sheet LAUT tidak
      punya kolom spacer kosong di depan seperti UDARA/DARAT — beda
      struktur yang baru ketahuan saat implementasi). `kondisi_kategori`
      dinormalisasi dari teks bebas sumber (SIAP/SIAP_TERBATAS/
      TIDAK_SIAP/LAINNYA) — hasil distribusi: 2.076 SIAP, 232
      TIDAK_SIAP, 4 SIAP_TERBATAS, 10 LAINNYA, 1.617 tanpa kondisi
      (baris kategori/tidak-memiliki).
- [x] **Rescuer & Potensi SAR** (§8.3): `scripts/schema_basarnas_rescuer_potensi.sql`
      + `scripts/import_basarnas_rescuer_potensi.py` — 47 satuan kerja
      (termasuk 2 baris non-regional "Kantor Pusat"/"Balai SDM PP" tanpa
      kode_daerah).
- [x] Ketiga tabel non-spasial (`bps_data_bandara`, `basarnas_alut`,
      `basarnas_rescuer_potensi`) didaftarkan di `DATA_TABLES`
      (app.py) dan diverifikasi tampil di "Data" viewer lewat server
      terisolasi bersama layer Pelabuhan Penumpang — total kini **11
      layer/tabel baru** hidup di aplikasi sejak kajian ini dimulai.

**Sisa kandidat yang masih tercatat, belum dikerjakan** (nilai lebih
rendah/butuh keputusan tambahan): Angkutan Perintis, Rekap Data Daerah
(ridership BRT/KA), OD LRT Jabodebek, LRK 2026, PSC 119 (perlu redaksi
privasi), Diklat SAR (tabel kecil 5 baris).

### Susulan kedua: 4 sumber lagi diimplementasikan (Kinerja Pelabuhan, List Lokpri, Data Ops SAR)

- [x] **Kinerja Pelabuhan BPS** (§4.1): `scripts/schema_bps_kinerja_pelabuhan.sql`
      + `scripts/import_bps_kinerja_pelabuhan.py` — 480 baris final
      (482 baris sumber, 2 pasang duplikat persis di Kepulauan Riau
      2020 collapse jadi 1 lewat UPSERT). Kolom 18+ pada sumber (artefak
      pivot-table Excel yang nyasar ke 1 baris) sengaja tidak diimpor.
- [x] **List Lokpri** (§4.2): `scripts/schema_list_lokpri_kawasan.sql`
      + `scripts/import_list_lokpri_kawasan.py` — 249 baris. **Ditemukan
      saat implementasi**: kolom "Status" jauh lebih beragam dari sampel
      awal kajian (yang cuma menunjukkan "Tertinggal") — nyatanya ada 10
      kategori program berbeda (Perbatasan Prioritas, Kawasan
      Transmigrasi, Food Estate, Wisata, dll.), dan 36 kabupaten muncul
      lebih dari sekali (program berbeda) — makanya tabel pakai
      surrogate id, bukan kabupaten sebagai primary key.
- [x] **Data Ops SAR 2021-2025** (§8.4, item bernilai tertinggi yang
      sempat ditunda): `scripts/schema_basarnas_ops_sar.sql` +
      `scripts/import_basarnas_ops_sar.py` — **diputuskan impor
      per-insiden mentah (tanpa agregasi)**, 12.216 dari 12.372 baris
      valid (156 dibuang, koordinat kosong/di luar rentang Indonesia).
      Cuma sheet `REKAPITULASI DETAIL` per tahun yang diimpor (5 sheet
      kategori lain tetap dilewati sesuai temuan awal — subset
      terfilter, bukan data tambahan).
      **Bug data kualitas ditemukan & diperbaiki saat verifikasi**:
      ~620 baris (terutama tahun sumber 2025) punya `waktu_tiba` korup
      persis `"0001-11-30 00:00:00"` (placeholder tahun 1 dari sumber)
      — kalau tidak difilter, ini menghasilkan rata-rata response-time
      negatif ekstrem (jutaan menit) saat dihitung
      `waktu_tiba - waktu_lapor`. Parser ditambah validasi rentang
      tahun wajar (2015-2030), timestamp di luar itu diperlakukan NULL.
      Setelah fix, response-time rata-rata per jenis kecelakaan masuk
      akal (mis. Kecelakaan Kapal ≈ 1.164 menit, Bencana ≈ 6.721 menit)
      — mengonfirmasi nilai analitik yang disebut di kajian awal
      (linimasa respons siap pakai per insiden) sungguh valid.
- [x] Keempatnya didaftarkan di `DATA_TABLES` dan diverifikasi tampil
      di "Data" viewer lewat server terisolasi — total kini **15
      layer/tabel baru** hidup di aplikasi sejak kajian ini dimulai
      (11 dari dua putaran sebelumnya + 4 dari putaran ini).

**Sisa kandidat yang masih tercatat, belum dikerjakan** (nilai lebih
rendah/butuh keputusan tambahan, tidak berubah dari putaran
sebelumnya): Angkutan Perintis, Rekap Data Daerah (ridership BRT/KA),
OD LRT Jabodebek, LRK 2026, PSC 119 (perlu redaksi privasi), Diklat
SAR (tabel kecil 5 baris).

### Susulan ketiga: seluruh sisa kandidat diimplementasikan

Semua item yang sempat tercatat "belum dikerjakan" di atas kini
diselesaikan (kecuali Rekap Data Daerah yang di-scope-ulang, lihat
bawah), menuntaskan seluruh inventaris `docs/New/`:

- [x] **LRK 2026** (§9.5): `scripts/import_lrk_2026_to_postgis.py` —
      **kualitas sumber jauh lebih buruk dari sampel awal kajian**
      (yang cuma melihat 4 baris rapi Aceh): format koordinat di teks
      "Nama Ruas" sangat tidak konsisten antar BPTD (desimal berkurung,
      desimal-koma notasi Indonesia, DMS, multi-titik per sel, dan
      banyak baris tanpa koordinat sama sekali). Parser 4-pola dicoba
      berurutan; hasil akhir **55 titik dari ~130 baris ruas** (81 baris
      tanpa koordinat yang bisa dikenali, bukan kegagalan parsing —
      memang tidak ada di sumber). Ditumpangkan ke bucket `JALAN
      NASIONAL` yang sudah ada, pola sama dengan Blackspot.
- [x] **Angkutan Perintis Darat** (§7.1): `scripts/schema_angkutan_perintis.sql`
      + `scripts/import_angkutan_perintis.py` — 632 baris gabungan 5
      jenis layanan (9 Barang Perintis, 11 Perkotaan BTS, 265
      Penyeberangan Perintis, 34 KSPN, 313 Jalan Perintis) dalam satu
      tabel dibedakan kolom `jenis`. Non-spasial (sesuai temuan awal —
      sumbernya memang tidak punya koordinat sama sekali).
- [x] **Diklat SAR** (§8.6): `scripts/schema_basarnas_diklat_rekap.sql`
      + `scripts/import_basarnas_diklat_rekap.py` — 2 sumber kecil
      (peserta diklat, tenaga pendidik) digabung jadi 1 tabel 5 baris
      (2021-2025) karena dimensi tahunnya sama.
- [x] **OD LRT Jabodebek** (§6.1): `scripts/schema_od_lrt_jabodebek.sql`
      + `scripts/import_od_lrt_jabodebek.py` — matriks OD 18x18 stasiun
      × 10 bulan (Jan-Okt 2025) disimpan format long/tidy, 3.240 baris.
      **Ditemukan saat implementasi**: sheet sumber punya 2 blok
      trailing SETELAH blok "Rata-Rata" yang BUKAN data ridership bulanan
      (satu daftar urutan stasiun tanpa data, satu lagi matriks JARAK
      ANTAR STASIUN dalam km — data statis, bukan jumlah penumpang) —
      keduanya sengaja dikecualikan, cuma 10 bulan Jan-Okt yang diimpor.
- [x] **Rekap Data Daerah — di-scope-ulang, bukan diimpor utuh**
      (§7.3): file sumbernya (7 sheet) jauh lebih berantakan dari
      dugaan — mayoritas sheet mencampur tabel "BTS dikelola Kemenhub"
      dan "BRT dikelola daerah" dalam satu sheet dengan sub-section
      berjenjang (header kota tanpa data, placeholder `-`/`?`/`N/A`
      dengan makna berbeda-beda) — usaha parsing robust tidak sebanding
      nilainya (cakupan kota-per-kota, bukan nasional). **Hanya sheet
      "(KEN TITIP 3)" yang diimpor** (`scripts/schema_rekap_penumpang_ka_nasional.sql`
      + `scripts/import_rekap_penumpang_ka_nasional.py`) — satu-satunya
      bagian yang bersih & nasional: rekap penumpang KA per sistem
      (KA Antarkota, Kereta Cepat Whoosh, KRL, KA Bandara, dst.)
      2020-2025, 144 baris (26 kategori × ~6 tahun, sebagian baris
      kolaps lewat UPSERT karena label kategori sedikit duplikat di
      sumber). Sheet lain (`2020 - 2025`, `LKJ 2025`, `BRT & KA`,
      `Sheet1`, `(KEN TITIP 1)`, `(KEN TITIP 2)`) **tetap tidak
      diimpor** — keputusan sadar, bukan terlewat.
- [x] **PSC 119 — dengan redaksi privasi wajib** (§9.4):
      `scripts/schema_psc119_layanan.sql` + `scripts/import_psc119_layanan.py`
      — 187 PSC. **Kolom data pribadi (nama penanggung jawab, nomor WA
      penanggung jawab & tim teknis) TIDAK PERNAH dibaca sama sekali**
      (bukan cuma di-null-kan setelah dibaca) — dideklarasikan eksplisit
      di docstring & komentar skema supaya tidak diam-diam ditambahkan
      lagi di masa depan. Diverifikasi ulang: tidak ada kolom
      nama/kontak personal di skema final. Data tetap self-reported
      (survei mandiri) — perlu disclaimer itu kalau ditampilkan di UI.
- [x] Seluruhnya didaftarkan di `DATA_TABLES` dan diverifikasi tampil di
      "Data" viewer + layer LRK 2026 tampil di Overlay Peta, lewat
      server terisolasi — total kini **20 layer/tabel baru** hidup di
      aplikasi sejak kajian ini dimulai.

**Status akhir**: seluruh isi `docs/New/` yang punya nilai analitik
sudah dikaji dan (kecuali yang sengaja diputuskan cukup referensi —
RTRW-Perda, sheet Rekap Data Daerah non-KEN-TITIP-3, PDF KEP DATA LAKA
scan-only, Laporan RUNK, peta skematik KA) sudah diimplementasikan ke
database. Tidak ada satu pun dari 20 layer/tabel baru yang menyentuh
`_IJD_SCORERS`, `ijd_scoring_rules`, `usulan_inpres`, atau endpoint
skoring IJD manapun.

## 4. Pendalaman kategori LAUT (`docs/New/2. LAUT`)

Telaah detail per file/sheet (4 xlsx, semua nasional):

### 4.1 `(DATA) KINERJA PELABUHAN - STATISTIK TRANSPORTASI LAUT BPS.xlsx`
- Sheet `Data` (487 baris): performa tahunan per pelabuhan dari BPS
  Statistik Transportasi Laut — kunjungan kapal DN/LN (unit, GT), arus
  penumpang DN/LN (datang/berangkat), arus barang (ton, bongkar/muat,
  peti kemas & non-peti kemas). Granularitas Pelabuhan × Provinsi × Tahun.
  **Non-spasial** — hanya nama pelabuhan/provinsi teks, tidak ada
  koordinat.
- Sheet `Sheet1`: contoh pivot table Excel untuk satu pelabuhan (Teluk
  Bayur) — artefak, bukan sumber data tambahan.
- Kontribusi: kandidat tabel baru di "Data" viewer (`DATA_TABLES`), murni
  statistik kinerja pelabuhan lintas tahun — tidak berkaitan jalan/IJD.

### 4.2 `Dukungan Kawasan_R Pelabuhan Sandingan RPJMN-RKP-SBPI.xlsx`
- Sheet `Sandingan SBPI dan RPJMN` (124 baris): crosswalk teks judul
  proyek antar nomenklatur program RKP/SBPI/RPJMN 2025-2029 per proyek
  pelabuhan — dokumentasi administratif, sulit distrukturkan jadi data
  peta (isinya judul proyek, bukan koordinat/angka konsisten).
- Sheet `RIPN` (1985 baris): kebutuhan anggaran & alokasi (Rp Juta)
  pembangunan pelabuhan per tahun 2020-2023, per pelabuhan (kode, kab/kota,
  provinsi, hierarki, dukungan kawasan). **Catatan kualitas data**: header
  kolom B berisi artefak `#REF!` (formula rusak dari sumber) — perlu
  dibersihkan sebelum diimpor; header juga 2-baris merge (tahun di atas,
  Penanganan/Alokasi di bawah).
- Sheet `List Lokpri` (~1000 baris: No, Kabupaten, Status, kategori
  "3TP"): daftar kabupaten prioritas nasional (status "Tertinggal",
  kategori 3TP = Tertinggal-Terdepan-Terluar-Perbatasan). **Data referensi
  lintas-sektor**, bukan spesifik pelabuhan — berpotensi jadi
  layer/atribut umum "kabupaten prioritas nasional" di peta, independen
  dari pelabuhan maupun IJD.

### 4.3 `Koordinat_Data Pelabuhan Penumpang.xlsx`
- Sheet `Data Dashboard` (585 baris): titik pelabuhan penumpang nasional
  dengan **koordinat lat/lon presisi langsung di xlsx** (kolom `lat`/`lon`),
  kode pelabuhan, hierarki (`PP`/`PL`/`PR`/`PU` = Pengumpul/Pengumpan
  Lokal/Regional, Pelabuhan Utama), unit pengawasan (KSOP/UPP), operator
  (Pelindo, dll.), status aktif/tidak. **Kandidat kuat sebagai upgrade
  layer pelabuhan** yang sudah ada — atribut jauh lebih kaya (hierarki
  resmi, status operasional, operator) dan tidak perlu parsing shapefile.
- Sheet `RIPN` (1985 baris): RIPN (Rencana Induk Pelabuhan Nasional) per
  pelabuhan — hierarki, dukungan kawasan, rencana penanganan & alokasi
  anggaran per tahun **2020-2029** (10 tahun, lebih panjang dari sheet
  RIPN di §4.2). Cocok jadi atribut pengayaan pada identify-popup titik
  pelabuhan (rencana pembangunan multi-tahun), bukan layer terpisah.

### 4.4 `Koordinat_Data Pelabuhan TERSUS TUKS.xlsx`
- Sheet `Tersus` (1979 baris): titik TERSUS (Terminal Khusus)/TUKS
  (Terminal Untuk Kepentingan Sendiri) — dermaga privat milik
  industri (migas, semen, pupuk, dll.), **koordinat lat/lon langsung**,
  provinsi/kab + kode wilayah, unit pengawas (KSOP), nama penyelenggara,
  bidang kegiatan usaha, jenis TERSUS/TUKS. Volume besar (~1979 titik) dan
  granularitas sangat detail (per fasilitas industri, bukan per pelabuhan
  umum) — layer yang benar-benar berbeda dari pelabuhan publik, mengungkap
  infrastruktur logistik industri privat nasional.

**Implikasi untuk strategi**: dua sheet dengan koordinat langsung (§4.3
Data Dashboard, §4.4 Tersus) adalah kandidat import layer titik yang
**paling mudah** di seluruh dataset `docs/New/` — tidak perlu geopandas/
parsing shapefile, cukup baca xlsx dan insert langsung ke `map_layers`
sebagai geometri `Point`. Data non-spasial (kinerja pelabuhan BPS, RIPN
anggaran, sandingan RKP/RPJMN) lebih cocok sebagai tabel "Data" viewer
baru atau atribut identify-popup, bukan layer peta.

## 5. Pendalaman kategori UDARA (`docs/New/3. UDARA`)

Hanya 1 file: `Attributes_ Data Bandara.xlsx`, sheet `Sheet1`
(A1:U517, header 2-baris merge). Setelah dibersihkan dari baris kosong/
separator (nilai non-breaking-space `\xa0`), berisi **251 bandara
nasional** bernomor urut rapi (`NO` 1-251, tanpa duplikat/reset).

Kolom: Nama Bandara, Hirarki (`P`/`PS`/`PT`/`PP` — 218/15/10/8 bandara),
Kelas (mis. `4E`, `3C`, `1B` — skala ICAO/Kemenhub), Provinsi, Kabupaten,
Status (`Domestik` 233 / `Internasional` 16 / 2 kosong), Operator (PT
Angkasa Pura I/II, UPT Ditjen Hubud, UPT Daerah/Pemda, Swasta, BUMN,
Misionaris), **Runway Length (m)**, **Runway Width (m)**, **Apron Area
(m²)**, Taxiway (dimensi teks, mis. `"175 x 23"` — beberapa bandara punya
lebih dari satu taxiway sehingga baris tambahan tanpa `NO` adalah baris
lanjutan/merge, bukan bandara baru — perlu ditangani saat parsing),
**Terminal Penumpang (m²)**, **Demand Pax**, Terminal Kargo, Critical
Aircraft (tipe pesawat kritis, teks bebas), Kapasitas Eksisting
Penumpang/tahun (data valid & estimasi), **Titik Koordinat** (format DMS
teks, mis. `05° 31' 12.9" LU 095° 25' 15.54" BT` — perlu diparsing ke
desimal, bukan format lat/lon siap pakai), serta dua kolom kode wilayah
resmi **`KP`** (kode provinsi 2-digit, mis. `11`=Aceh) dan **`KD`** (kode
kabupaten/kota 4-digit, mis. `1108`=Aceh Besar — format sama dengan kode
BPS/Kemendagri yang dipakai `wilayah_mapping`/`penduduk_kecamatan`).

**Kualitas data**: sangat rapi — cuma 4 dari 251 bandara tanpa koordinat,
3 tanpa runway length. Kode `KP`/`KD` yang sudah baku membuat join ke
tabel wilayah existing (mis. `penduduk_kecamatan`, `bps_kabupaten_jalan`)
langsung bisa dilakukan tanpa fuzzy-match nama daerah — nilai lebih
dibanding SHP `Maps/BANDARA` yang cuma titik+nama.

**Kontribusi ke aplikasi**: bukan layer baru (bandara sudah ada sebagai
layer `map_layers`), tapi **pengayaan atribut** — dua opsi:
1. Perkaya `attrs` JSONB pada layer BANDARA existing lewat re-import
   (join by nama+KP/KD) dengan kolom runway/apron/terminal/kapasitas, agar
   identify-popup peta menampilkan detail teknis bandara.
2. Atau simpan sebagai tabel referensi terpisah di "Data" viewer
   (`DATA_TABLES`) untuk analitik non-spasial (mis. bandingkan kapasitas
   vs. demand pax antar bandara) tanpa mengubah layer peta yang sudah ada.
Opsi 1 lebih bernilai untuk fitur peta/identify; opsi 2 lebih sederhana
diimplementasikan dan tidak berisiko terhadap layer existing.

## 6. Pendalaman kategori KERETA (KA) (`docs/New/4. KERETA (KA)`)

3 file, semua **spesifik Jabodebek/Jawa-Sumatera** (bukan cakupan
nasional penuh seperti LAUT/UDARA):

### 6.1 `OD LRT Jabodebek 2025.xlsx`
- Sheet `Summary` (61 baris) + sheet `2025` (270 baris): matriks
  Origin-Destination penumpang antar **18 stasiun LRT Jabodebek**
  (Bekasi Barat, Cawang, Cikoko, Cikunir 1/2, Ciliwung, Ciracas, Dukuh
  Atas, Halim, Harjamukti, Jatibening Baru, Jatimulya, Kampung
  Rambutan, Kuningan, Pancoran, Rasuna Said, Setiabudi, TMII).
- Sheet `2025` menumpuk matriks 18×18 **per bulan** (~22 baris per blok:
  header + 18 stasiun + baris Total + baris kosong, berulang
  Januari-Oktober 2025); `Summary` adalah rata-rata Januari-Oktober.
- **Cakupan sangat lokal** (satu sistem LRT di Jabodebek), tidak
  berkaitan dengan cakupan nasional aplikasi — nilai analitiknya sebagai
  data ridership transit perkotaan, bukan infrastruktur jalan/pelabuhan/
  bandara nasional. Kontribusi: hanya relevan bila aplikasi diperluas ke
  analitik transit perkotaan Jabodetabek secara khusus; untuk lingkup
  nasional saat ini nilainya rendah.

### 6.2 `Peta KA Pulau Jawa dan Madura (291222).pdf` & `Peta KA Pulau Sumatera (271222).pdf`
- PDF skematik ukuran besar (~6236×4819 pt / ~5102×6236 pt), masing-masing
  1 halaman, **698 dan 276 gambar** (ikon/simbol peta) — bukan dokumen
  tabel bergaya BPS.
- **Temuan penting**: teks nama stasiun + posisi kilometer (`"148+125
  MERAK"`, `"104+508 WALANTAKA"`, dst.) tersimpan sebagai **teks vektor
  asli**, bukan gambar raster — bisa diekstrak dengan PyMuPDF
  (`page.get_text()`) sama seperti extractor BPS yang sudah ada. Namun
  tata letaknya adalah diagram skematik bebas (bukan tabel baris/kolom
  beraturan), jadi posisi teks di halaman **tidak berkorespondensi
  langsung ke koordinat geografis** — hanya nama stasiun + jarak-km
  sepanjang jalur, perlu dicocokkan manual/sistematis ke geometri jalur
  rel nyata (mis. shapefile "Rel KA_2022"/jalur aktif Jawa-Sumatera di
  `docs/New/0. DATA SHP/Kereta Api/`, lihat kajian sebelumnya) untuk jadi
  data spasial siap pakai.
- Kontribusi: referensi nama-stasiun-per-km-jalur untuk pengayaan atribut
  layer jalur KA (jika/ketika diimpor dari SHP), **bukan** sumber
  ekstraksi otomatis prioritas tinggi — usaha ekstraksi tidak sebanding
  dengan nilai dibanding sumber SHP yang sudah punya geometri asli.

**Ringkasan kategori KERETA**: dari 3 file, tidak ada yang langsung
menghasilkan data spasial baru siap pakai — jaringan rel nasional (SHP)
sudah dibahas di kajian data baru §1.2 Fase 3 (data dari kategori "0.
DATA SHP", bukan folder ini). Folder "4. KERETA (KA)" ini isinya
pelengkap non-spasial (OD ridership LRT, peta skematik) dengan nilai
tambah terbatas untuk cakupan nasional — prioritas implementasi rendah
dibanding BASARNAS/Blackspot/TERSUS-TUKS.

## 7. Pendalaman kategori DARAT (`docs/New/5. DARAT`)

4 file, semua nasional. Yang paling bernilai justru sebuah **PDF decree**,
bukan xlsx.

### 7.1 `Daftar Angkutan Perintis Darat Tahun 2026.xlsx`
5 sheet, semuanya lampiran Keputusan Direktur Jenderal Perhubungan Darat
(KP-DRJD), berisi **daftar trayek/lintas** (nama titik awal-akhir sebagai
teks, jarak km/mil, kadang target trip) — **tidak ada koordinat sama
sekali** di sheet manapun (`Angkutan Barang Perintis`,
`Angkutan Perkotaan BTS`, `Angkutan Penyeberangan Perintis`,
`Angkutan KSPN`, `Angkutan Jalan Perintis`). Konsisten dengan dugaan
sebelumnya — daftar trayek administratif, bukan data spasial siap pakai.
Nilainya lebih ke referensi kebijakan (payung hukum KP-DRJD per jenis
layanan) daripada layer peta.

### 7.2 `Pelabuhan Penyeberangan Operasi.xlsx`
Sheet `Sheet1` (274 baris, dikelompokkan per provinsi dengan baris header
romawi seperti `I ACEH`): pelabuhan penyeberangan **yang benar-benar
beroperasi** — granularitas kecamatan (`KABUPATEN/KOTA`, `KECAMATAN`,
`NAMA PELABUHAN`), **koordinat DMS lengkap** (`4°12' 34.409"N 96°2'18.512"E`),
kolom `STATUS PENCAPAIAN REAL/REVIU` (mis. "Operasi") dan `PENGELOLA`
(PemProv/BPTD/dll.). Ini **upgrade nyata** dibanding data pelabuhan
penyeberangan yang sudah ada — resolusinya kecamatan (bukan kabupaten),
statusnya eksplisit "sedang beroperasi" (bukan sekadar terdaftar), dan
mencantumkan pengelola. Kandidat kuat sebagai layer titik baru atau
pembaruan atribut layer pelabuhan penyeberangan existing.

### 7.3 `Rekap Data Daerah.xlsx`
7 sheet (`2020 - 2025`, `LKJ 2025`, `BRT & KA`, `Sheet1`, `(KEN TITIP
1/2/3)`): seluruhnya data **ridership transportasi umum perkotaan**
(BRT/Trans-metro 10 kota metropolitan, KRL Jabodetabek/Yogyakarta,
LRT Sumsel, Kereta Cepat Whoosh, KA antarkota) per tahun/triwulan —
kapasitas vs. realisasi trip vs. realisasi penumpang, dipakai untuk
pelaporan kinerja (LKJ). **Sepenuhnya non-spasial** (nama kota/sistem
sebagai teks, tanpa koordinat) dan granularitasnya kota metropolitan,
bukan nasional merata. Nilai kontribusinya rendah untuk aplikasi ini,
sama seperti OD LRT Jabodebek di §6.1.

### 7.4 `KM_109_Tahun_2019_Penlok Terminal Tipe A.pdf` — **temuan paling bernilai di kategori ini**
Keputusan Menteri Perhubungan No. KM 109/2019, 15 halaman, lampiran
berisi **126 Terminal Penumpang Tipe A** (kelas terminal bus terbesar)
di seluruh Indonesia: No, Provinsi, Nama Terminal, Kabupaten/Kota,
Lokasi (alamat teks), dan **Titik Koordinat dalam dua format sekaligus**
— DMS *dan* **desimal langsung** (mis. `4.497648, 97.967850`) yang
ditulis setelah tanda `/`. Ini artinya **tidak perlu parsing DMS→desimal**
seperti kasus UDARA (§5) — cukup regex pasangan angka desimal setelah
`/` pada tiap entri.
- **Catatan kualitas ekstraksi**: teks PDF hasil OCR/scan lama punya
  sejumlah entri yang korup (mis. entri #3 Meulaboh: `"9 e o0 T 3 7 .7
  nE"`, entri #17 Bangkinang: `"lO rO l^ .r'E"`, entri #120 Bolaang
  Mongondow: hanya format DMS tanpa desimal) — perlu validasi rentang
  nilai (lat -11..6, lon 95..141 untuk wilayah Indonesia) dan fallback
  parsing DMS untuk baris yang gagal regex desimal, pola yang sama
  dengan pendekatan "best-effort, log yang gagal" di extractor BPS
  (`extract_dalam_angka.py`) yang sudah ada.
- Kontribusi: **layer titik baru** `layer="TERMINAL TIPE A"` — granularitas
  nasional per kabupaten/kota, sumber hukum resmi (SK Menteri), dan
  tergolong mudah diimpor (ekstraksi teks PDF + regex, tanpa geopandas/
  shapefile) — sepadan dengan kemudahan TERSUS/TUKS di §4.4.

**Ringkasan kategori DARAT**: satu file layak jadi layer baru dengan
usaha rendah (Terminal Tipe A, §7.4), satu file layak jadi
upgrade/tambahan atribut pelabuhan penyeberangan (§7.2), dua file
(Angkutan Perintis, Rekap Ridership) nilainya rendah untuk peta —
lebih cocok sebagai referensi dokumen/kebijakan.

## 8. Pendalaman kategori BASARNAS (`docs/New/6. BASARNAS`)

Kategori paling kaya di seluruh `docs/New/` — 8 subfolder, kombinasi data
spasial (SHP/KML/GPKG) dan xlsx operasional. Semua diverifikasi langsung
dengan `geopandas`/`openpyxl`/`PyMuPDF`, bukan dari nama folder saja.

### 8.1 Data spasial: Kantor SAR, Pos SAR, Wilayah Tanggung Jawab
Tiga dataset di subfolder "1. Titik koordinat...", masing-masing tersedia
dalam **3 format sekaligus** (SHP, KML, GPKG) + metadata XML — jadi bisa
dipilih format yang paling mudah dibaca (GPKG paling langsung untuk
`geopandas`, tidak perlu urus sidecar file `.dbf/.shx/.prj`).
- **Kantor SAR** (titik, 47 lokasi, EPSG:4326): kolom `no`, `nama_kanto`,
  `tipe_kelas` (A/B), `call_sign` (mis. `SAR-301`), `latitude`,
  `longitude`. Titik koordinat presisi, tanpa nilai kosong pada sampel.
- **Pos SAR** (titik, 85 lokasi): kolom `No`, `Nama Pos S`, `Nama Kanto`
  (kantor SAR induk — kolom relasi siap pakai untuk hierarki Kantor→Pos),
  `Latitude`, `Longitude`.
- **Wilayah Tanggung Jawab** (polygon/multipolygon, 43 wilayah): kolom
  `Nama Kanto`, `Call Sign`, `Tipe Kelas`. **Catatan teknis**: SHP-nya
  gagal dibaca dengan engine default `fiona` (error
  `TypeError: ufunc 'create_collection' not supported...`) — persis bug
  shapely/numpy MultiPolygon-from-dict yang sudah didokumentasikan di
  CLAUDE.md untuk `Maps/BATAS_ADMINISTRASI.gdb`; solusinya sama: baca
  dengan `engine="pyogrio"`. 43 wilayah vs. 47 Kantor SAR — sebagian
  kantor tidak (atau belum) punya polygon tanggung jawab sendiri di
  sumber ini.
- Ketiganya **siap impor langsung** ke `map_layers` dengan pola yang
  identik ke `import_batas_administrasi_kecamatan.py`/
  `import_peta_koridor_to_postgis.py` — sudah EPSG:4326, tidak perlu
  reprojection.

### 8.2 Sarana dan Prasarana (ALUT — Alat Utama)
3 file per matra (Udara/Darat/Laut), masing-masing sheet `REKAP` (ringkas)
plus sheet detail per jenis alat (mis. `RESCUE TRUCK TYPE I/II/III`,
`KAPAL KELAS I-V`, `JETSKY`, `HOVERCRAFT`, dst.). Baris data riil (bukan
`max_row` mentah yang penuh baris kosong): **124 aset udara, 1.524 aset
darat, 2.103 aset laut** — total >3.700 unit alat SAR terdaftar nasional.
- Kolom umum: `Kode Daerah`, `Kantor SAR`/`KANSAR`, `Kendaraan` (jenis),
  `Nomor Plat/No. Lambung`, `Merk/Type`, `Tempat` (lokasi pool/kantor),
  `Tahun` (tahun pengadaan), `No Mesin`, `No Rangka`, `Kondisi Saat Ini`,
  `Keterangan`.
- **Non-spasial** — tidak ada koordinat sendiri, tapi `Kode Daerah`/
  `KANSAR` bisa langsung di-join ke titik Kantor SAR (§8.1) untuk
  menampilkan jumlah/jenis alat sebagai atribut identify-popup.
- **Kualitas data "Kondisi Saat Ini" perlu dibersihkan sebelum
  dianalisis**: dari sampel darat, nilai didominasi `S` (Siap, 1116) dan
  `US` (Tidak Siap, 28), tapi ada variasi penulisan bebas — `Baik`(29),
  `Rusak Ringan`(3), `S Terbatas`(3), huruf kecil `s`(3), bahkan satu
  entri korup `US-YAMA0047A323` (tercampur dengan kolom lain) dan simbol
  `−` (2). Perlu normalisasi kategori (S/US/lainnya) sebelum dipakai
  untuk agregasi kesiapan alat per kantor.

### 8.3 Data Rescuer dan Potensi
`Komposisi_Rescuer_dan_Potensi_Juli_2026.xlsx`, 1 sheet: rekap tenaga per
Kantor SAR (`Kode Daerah`, `Satuan Kerja`) — kolom Tenaga (Rescuer, ABK,
Operator Komunikasi, Medis, Total) dan Potensi (Literasi, Terlatih,
Kompeten, Total — kemungkinan relawan/komunitas SAR terdaftar, bukan
pegawai). Termasuk baris non-regional (`Kantor Pusat`, `Balai SDM PP`)
tanpa `Kode Daerah`. Non-spasial, join via `Kode Daerah`/nama kantor.

### 8.4 Data Ops SAR 2021-2025 — dataset insiden paling bernilai
5 file (satu per tahun), masing-masing 6 sheet: `REKAPITULASI DETAIL`
(master, semua insiden) + 5 sheet kategori (`PESAWAT`, `KAPAL`,
`BENCANA`, `KMM`, `KPK`). **Penting**: diverifikasi baris-per-baris —
kelima sheet kategori adalah **subset terfilter dari REKAPITULASI
DETAIL** (baris identik persis, hanya dikelompokkan ulang per jenis
kecelakaan), bukan data tambahan — jangan menjumlahkannya bersama
`REKAPITULASI DETAIL` atau akan double-count.
- Volume per tahun (baris `REKAPITULASI DETAIL`, meningkat tiap tahun):
  2021 ≈ 2.268, 2022 ≈ 2.351, 2023 ≈ 2.418, 2024 ≈ 2.560, 2025 (s.d. akhir
  tahun berjalan) ≈ 2.765 insiden — **≈12.000 insiden SAR nasional dalam
  5 tahun**.
- Kolom sangat lengkap: `KANTOR SAR`, `JENIS KECELAKAAN` (Kondisi
  Membahayakan Manusia, Kecelakaan Pesawat Udara, Kecelakaan Kapal,
  Bencana, Kecelakaan Penanganan Khusus, dll.), `SUB JENIS KECELAKAAN`,
  narasi kejadian bebas, **`LONGITUDE`/`LATITUDE` per insiden** (titik
  asli, presisi tinggi — bukan estimasi kecamatan), lini masa lengkap
  (`WAKTU KEJADIAN` → `WAKTU LAPOR` → `WAKTU BERANGKAT` → `WAKTU TIBA` →
  `WAKTU SELESAI` — bisa dihitung *response time*), dan hasil operasi
  (`KORBAN` total, `S`=selamat, `MD`=meninggal dunia, `DP/H`=dalam
  pencarian/hilang).
- **Ini satu-satunya dataset di seluruh `docs/New/` dengan koordinat titik
  kejadian presisi + linimasa respons** — nilai analitik jauh melebihi
  BASARNAS lain: bisa jadi heatmap kejadian darurat nasional, analisis
  response-time per Kantor SAR, atau filter per jenis kecelakaan
  (banjir, kapal, kecelakaan lalu lintas berat, dll.) yang tumpang
  tindih dengan Blackspot Kecelakaan (§7 kategori DARAT/KESELAMATAN yang
  akan dikaji terpisah).

### 8.5 Fasilitas Puslat SDMPP
`Rekapitulasi Fasilitas Pusat Pendidikan dan Pelatihan...xlsx`, 3 sheet
(`SARANA DARAT`, `SARANA LAUT`, `PRASARANA LATIHAN`): inventaris
kendaraan dan fasilitas latihan (Tower Rapeling, Gedung Simulator Urban
SAR, Gedung K9, dll.) — **milik satu lokasi tunggal** (Pusat Diklat SAR),
bukan tersebar nasional. Non-spasial (kecuali lokasi Puslat itu sendiri,
yang tidak dicantumkan koordinatnya di file ini). Nilai kontribusi
rendah untuk peta — lebih ke referensi kapasitas pelatihan nasional.

### 8.6 Peserta & Tenaga Pendidik Diklat SAR 2021-2025
Dua file kecil, masing-masing hanya rekap **agregat nasional per tahun**
(bukan per kantor/wilayah): jumlah kegiatan diklat + peserta (mis. 2021:
30 kegiatan/1.073 peserta), dan jumlah tenaga pendidik per tahun (mis.
2021: 27 pendidik). 5 baris data saja per file. Nilai kontribusi rendah
untuk peta — cocok sebagai catatan kapasitas kelembagaan di dokumentasi,
bukan layer atau tabel analitik.

### 8.7 `B-17070 Surat Permohonan Data dashboard Basarnas_previewR1.pdf`
**Bukan sumber data**, melainkan surat resmi Bappenas (Direktorat
Konektivitas dan Infrastruktur Logistik) ke BASARNAS yang meminta data
ini — memberi konteks/provenance bahwa seluruh isi folder "6. BASARNAS"
memang dikumpulkan untuk kebutuhan dashboard data konektivitas &
logistik nasional, bukan untuk laporan lain. Poin permintaan dalam surat
(titik Kantor/Pos SAR, sarpras, tenaga & potensi SAR) cocok persis
dengan apa yang benar-benar ada di folder — konfirmasi bahwa dataset ini
lengkap sesuai permintaan, tidak ada bagian yang "hilang di tengah
jalan".

**Ringkasan kategori BASARNAS**: kandidat implementasi terbaik di
seluruh `docs/New/` sejauh ini —
1. **§8.1** (Kantor SAR, Pos SAR, Wilayah Tanggung Jawab): 3 layer titik/
   polygon siap impor langsung, format GPKG/EPSG:4326 bersih.
2. **§8.4** (Data Ops SAR): ~12.000 titik insiden 5 tahun dengan
   koordinat + linimasa — nilai analitik tertinggi, tapi volume besar
   sehingga perlu keputusan agregasi (lihat §9 catatan implementasi).
3. **§8.2/8.3** (ALUT, Rescuer): atribut pengayaan non-spasial untuk
   identify-popup titik Kantor SAR, perlu pembersihan kategori kondisi
   alat dulu.
4. **§8.5/8.6** (Puslat, Diklat): nilai kontribusi peta rendah, cukup
   referensi dokumentasi.

## 9. Pendalaman kategori KESELAMATAN (`docs/New/8. KESELAMATAN`)

12 file (5 xlsx + 7 PDF), semua nasional. Kategori ini sudah dibahas
sepintas di kajian awal (blackspot langsung overlay JALAN NASIONAL);
telaah mendalam berikut membedah tiap sheet/PDF.

### 9.1 `ANEV LAKA LANTAS TAHUN 2020-2025 (BAPENAS B-17549) 2.xlsx`
Dokumen dari Korlantas POLRI, judul file menunjukkan ini juga hasil
permohonan data Bappenas (pola sama dengan surat BASARNAS §8.7).
- Sheet `REKAP`: statistik kecelakaan **nasional** per tahun (2020 s.d.
  30 Okt 2025), dipecah per kategori (`Berdasarkan Kecelakaan Lalu
  Lintas`, `Berdasarkan Kecelakaan Tunggal`, dst.) — jumlah kejadian,
  korban MD/LB/LR (Meninggal Dunia/Luka Berat/Luka Ringan), kerugian
  materi (Rupiah). Header 2-baris merge (baris 8 nomor kolom, baris 11
  ulang nomor 1-12 sebagai index kedua — artefak formulir sumber, perlu
  di-skip saat parsing).
- Sheet `POLDA`: pecahan yang sama **per Polda (34 provinsi)** per tahun
  — kejadian, korban MD/LB/LR, kerugian materi (`RUMAT`) per tahun.
  **Non-spasial** (granularitas provinsi via nama Polda, tanpa
  koordinat) — kandidat tabel referensi "Data" viewer untuk konteks
  statistik keselamatan per provinsi, terpisah dari layer peta manapun.
- Sheet `Sheet1`/`Sheet2`: belum diverifikasi detail, kemungkinan
  turunan/draf dari REKAP.

### 9.2 `Blackspot Bina Marga Jalan Nasional 2020-2024.xlsx`
955 baris titik blackspot nasional (kolom `LTG`/`BJR` = Lintang/Bujur,
`PROV`, `Nama Ruas`) — **catatan kualitas data penting**: koordinat
disimpan sebagai teks, dan **115 dari 955 baris (~12%) punya
lintang/bujur kosong atau tidak bisa di-parse ke angka** — perlu
validasi & filter saat impor, bukan diasumsikan semua baris valid.
Selebihnya (≈840 titik) siap jadi layer titik `map_layers`
(`layer="BLACKSPOT KECELAKAAN"`) yang overlay langsung ke JALAN NASIONAL
existing, seperti sudah disebut di kajian sebelumnya.

### 9.3 `Data Lalu Lintas Harian Rata-Rata (LHR) Jalan Nasional Tahun 2024.xlsx`
Sheet `Per Ruas`, **3.310 baris** — jauh lebih detail dari dugaan awal
"data pelengkap". Per ruas jalan nasional: `Linkid`, `Linkname`,
`Lintas` (nama koridor lintas pulau), `Panjang SK (KM)`, `Tahun` data,
lalu **AADT (Average Annual Daily Traffic) terpecah per 12 golongan
kendaraan** (Veh1-Veh8 dengan sub-golongan a/b/c — motor, mobil
penumpang, bus, truk ringan/berat, dst.), serta **`Volume`, `Capacity`,
dan `VCR` (Volume-Capacity Ratio)** — indikator kemacetan siap pakai
per ruas. Tidak ada koordinat langsung, tapi `Linkid`/`Linkname`
berpotensi di-join ke layer JALAN NASIONAL existing via nama ruas
(perlu dicek kecocokan penamaan). **Nilai kontribusi tinggi** sebagai
atribut pengayaan identify-popup JALAN NASIONAL — data VCR per ruas
adalah indikator objektif kepadatan lalu lintas yang belum ada di
aplikasi sama sekali.

### 9.4 `Data layanan PSC 119 2025 survey.xlsx`
Hasil survei Google Form ke 184 PSC 119 (Public Safety Center — layanan
gawat darurat kesehatan) kab/kota. **Catatan privasi penting**: kolom
mentah memuat **data pribadi** (nama penanggung jawab, nomor WhatsApp,
email resmi) — bukan sekadar data institusi. Kalau bagian manapun dari
file ini akan diimpor/ditampilkan, kolom kontak personal harus
di-strip/redaksi, bukan diteruskan mentah ke database atau UI publik.
Data substantifnya (jumlah kasus per kategori — ibu/bayi/anak/
kecelakaan/jantung-stroke, waktu respons, jumlah ambulans, kendala,
kebutuhan anggaran) sepenuhnya **non-spasial** (tanpa koordinat), dan
bersifat self-reported (bukan data resmi terverifikasi) — cocok sebagai
referensi kapasitas layanan darurat per kab/kota, bukan layer peta,
dan dengan disclaimer "data survei mandiri" bila ditampilkan.

### 9.5 `REKAP LRK - Tahun 2025 dan 2026.xlsx`
7 sheet, program "Lokasi Rawan Kecelakaan" (LRK) Bina Marga — **berbeda**
dari dataset Blackspot §9.2 (LRK ini sepertinya daftar lokasi yang
sudah/akan **ditangani/dibangun** penanganannya, bukan sekadar catatan
lokasi rawan).
- `LOKASI RAWAN KECELAKAAN`: rekap jumlah LRK per tahun (2023: 216,
  2024: 287, 2025: 260, 2026: 129) — akumulatif, agregat nasional saja.
- `RELAKSASI TAHAP 1/2/3 2025`: daftar ruas per BPTD yang direlaksasi
  (nama ruas + panjang km) — **tanpa koordinat**.
- **`LRK 2026`** (temuan penting): daftar lokasi LRK per provinsi dengan
  **koordinat desimal tertanam langsung di teks nama ruas**, mis. `"RUAS
  009 (4) LHOKSUKON - BTS. ACEH UTARA/ ACEH TIMUR (PANTON LABU) - (LRK
  1) (5.1281734, 97.3909868)"` — pola yang sama seperti Terminal Tipe A
  (§7.4 kategori DARAT): perlu regex untuk mengeluarkan pasangan
  desimal di akhir teks, bukan kolom terpisah.
- `DIAGRAM`/`Anggaran`: target-vs-realisasi kinerja & anggaran program,
  administratif, tidak relevan untuk peta.
- Kontribusi: `LRK 2026` bisa jadi layer titik baru (`layer="LOKASI
  RAWAN KECELAKAAN 2026"`) dengan usaha ekstraksi rendah (regex, mirip
  §7.4), tapi cakupannya cuma satu tahun program (129 titik) — jauh
  lebih kecil dari Blackspot §9.2 (955 titik, 5 tahun).

### 9.6 `KEP DATA LAKA TAHUN 2019-2025.pdf` (7 file, Keputusan Kakorlantas POLRI)
**Kualitas ekstraksi teks sangat tidak konsisten antar tahun** —
diverifikasi per halaman dengan PyMuPDF:
- **2019, 2020, 2021, 2023**: PDF hasil scan murni (0 karakter teks
  per halaman di seluruh dokumen) — perlu OCR untuk diekstrak, tidak
  bisa dipakai extractor teks biasa (`page.get_text()`).
- **2022, 2024, 2025**: PDF punya teks vektor asli (>1000 karakter per
  halaman) — bisa diekstrak langsung, kemungkinan berisi tabel data
  laka lantas per Polda/tahun (belum diverifikasi struktur tabel
  detailnya, tapi metodologinya sama dengan `extract_dalam_angka.py`).
- Jika ke depan dataset laka lantas dari sumber ini mau dijadikan basis
  data terstruktur, urutan kerjanya: OCR dulu untuk 4 tahun yang
  scan-only, baru gabung dengan ekstraksi teks langsung untuk 3 tahun
  sisanya — usaha yang jauh lebih besar dibanding xlsx `ANEV LAKA
  LANTAS` (§9.1) yang sudah terstruktur rapi dan mencakup rentang tahun
  yang sama. **Rekomendasi: pakai §9.1 sebagai sumber utama, PDF ini
  cukup sebagai dokumen legal/rujukan**, bukan sumber ekstraksi.

### 9.7 `Laporan Akhir - Evaluasi Implementasi RUNK 2021-2025 - lampiran data.pdf`
Laporan evaluasi kebijakan (RUNK LLAJ = Rencana Umum Nasional
Keselamatan Lalu Lintas dan Angkutan Jalan 2021-2025), disusun konsultan
KIAT/DT Global didukung Pemerintah Australia, Februari 2026. Berisi
narasi evaluasi + daftar isi terstruktur (bukan tabel data mentah) —
**dokumen kebijakan/referensi**, bukan sumber data spasial atau
tabular. Nomor halaman internal dokumen ("Page 4 of 285") tidak cocok
dengan jumlah halaman file aktual (74) — kemungkinan ini kutipan/lampiran
parsial dari laporan lengkap 285 halaman, bukan dokumen utuh.

**Ringkasan kategori KESELAMATAN**: dua sumber bernilai tinggi dengan
usaha impor rendah — **Blackspot §9.2** (840 titik valid dari 955) dan
**LHR per-ruas §9.3** (3.310 baris, VCR sebagai indikator kemacetan).
`ANEV Laka Lantas §9.1` bagus sebagai tabel referensi statistik
(bukan layer). `LRK 2026 §9.5` layer tambahan kecil. PSC 119 §9.4 perlu
penanganan privasi sebelum dipakai. PDF KEP DATA LAKA (§9.6) dan RUNK
(§9.7) lebih tepat sebagai dokumen rujukan, bukan sumber ekstraksi data.

## 10. Catatan implementasi

- Setiap script import baru harus **idempotent** (skip yang sudah ada di
  `map_layer_meta` kecuali `--force`) — pola yang konsisten di seluruh
  `scripts/import_*_to_postgis.py`.
- `_map_layer_geojson_cache` di app.py bersifat in-process — restart
  server diperlukan setelah import baru agar layer baru terlihat tanpa
  cache basi, sama seperti layer lain.
- Volume data Ops SAR (5 tahun, per-kejadian) dan Rekap Ridership BRT/KA
  berpotensi besar — pertimbangkan agregasi (per kecamatan/kabupaten/
  tahun) alih-alih raw per-baris jika hanya dipakai untuk insight
  kontekstual, bukan visualisasi titik individual.
- Sekali lagi: tidak ada satu pun rekomendasi di dokumen ini yang
  menyentuh `_IJD_SCORERS`, `ijd_scoring_rules`, `usulan_inpres`, NPR,
  Laporan Prioritas, atau narasi Aspek A/B — seluruhnya adalah layer
  `map_layers` baru untuk fitur reference-map/overlay peta umum, berdiri
  sendiri di luar domain IJD.
