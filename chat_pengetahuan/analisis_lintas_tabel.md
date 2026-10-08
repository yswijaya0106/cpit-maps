---
judul: Analisis lintas tabel (join antar data)
kata_kunci: [join, gabung*, dibanding*, bandingkan, perbandingan, korelasi, hubungan, kaitan, rasio, per kapita, per penduduk, per 100, per km, per jiwa, lintas, silang, sekaligus, beserta, terhadap, vs, versus, kemantapan, fiskal, kapasitas fiskal, kendaraan, padi, sawit, komoditas, lokus, perbatasan, 3t, lokpri, vcr, lhr, iri]
---
KUNCI JOIN (semua INTEGER kode BPS, sudah diverifikasi ~100% cocok ke ref_wilayah):
- Kab/kota: `kode_kabupaten` ada di HAMPIR semua tabel berwilayah (usulan_inpres, usulan_inpres_riwayat, penduduk_kecamatan, kemantapan_ijd_2026, bps_kabupaten_jalan/kendaraan/padi/indeks_penanaman, bps_kecamatan_*, program_ijd_riwayat, cer_awp1_koridor, koridor_simpul_terdekat, bappenas_koridor, bappenas_lokus_a, kawasan_tematik, simpul_transportasi, bandara_kemenhub, psc119_layanan, jpl_prioritas_djka, bps_lhr_ruas_nasional, konektivitas_jaringan_jalan, bpsdm_*). Nama tampilan: ref_wilayah_kabupaten (nama_kabupaten_kota + jenis_kabupaten 'KABUPATEN'/'KOTA').
- PENGECUALIAN: pelabuhan_daerah -> pakai `kode_kabupaten_bps`/`kode_kecamatan_bps`/`kode_provinsi_bps` (kolom kode_* aslinya format sumber). bps_data_bandara -> `kode_kabupaten_bps`. JANGAN pakai `kode_kab` (CHAR) atau `kode_wilayah` (98xx/xx00) bila `kode_kabupaten` tersedia.
- Provinsi: `kode_provinsi` (= kode_kabupaten / 100). Tabel si_* (Statistik Indonesia) level provinsi; baris kode_provinsi=0 = Indonesia (keluarkan saat ranking).
- Kecamatan: `kode_kecamatan` (7 digit, /1000 = kab). Rute usulan -> kecamatan yg DILALUI: usulan_kecamatan_dilalui(usulan_id, kode_kecamatan).
- Usulan: usulan_inpres.id = usulan_kecamatan_dilalui.usulan_id = usulan_konektivitas_jalan.usulan_id = program_ijd_riwayat.usulan_inpres_id (hanya baris tahun 2026 yg diprogramkan) = dpp_ijd_2025.matched_usulan_id.
- Ruas jalan nasional: iri_ruas_nasional.linkid = bps_lhr_ruas_nasional.linkid (TEXT, 100%). LHR lintas >1 kab: kode_kabupaten NULL, daftar di kode_kabupaten_semua INTEGER[] -> `WHERE 3204 = ANY(kode_kabupaten_semua)`.
- Koridor: usulan_inpres.kode_koridor = cer_awp1_koridor.no_koridor = bappenas_koridor.no_koridor (no_koridor sama bisa di >1 kab -> tambah `AND u.kode_kabupaten = c.kode_kabupaten`).
- Bandara: bandara_kemenhub.bandara_id = bps_data_bandara.bandara_kemenhub_id = bandara_kemenhub_rute.bandara_id; lalu_lintas_udara_bandara.nama_bandara = bandara_kemenhub.nama_bandara.

JEBAKAN DATA (terbukti):
- penduduk_kecamatan: 5 kab Papua Pegunungan (Tolikara, Nduga, Yalimo, Mamberamo Tengah, Lanny Jaya) jumlah_penduduk = 0 -> rasio per penduduk WAJIB `/ NULLIF(pend, 0)` dan sebutkan kab tanpa data.
- Ranking: selalu `ORDER BY x DESC NULLS LAST` (banyak kolom NULL: bps_kabupaten_kendaraan.jumlah, lalu_lintas_penumpang).
- bps_kabupaten_jalan.panjang_total_km (parser PDF BPS) kadang tak masuk akal (Situbondo 17 km). Untuk panjang/kemantapan jalan DAERAH per kab lebih andal kemantapan_ijd_2026 (panjang_km, mantap_pct; baris provinsi kode_kabupaten NULL).
- bps_lhr_ruas_nasional.vcr DIPOTONG maks 1,000 (363 ruas = 1) -> utk ranking kepadatan pakai volume / NULLIF(capacity,0).
- Agregasi usulan per kab dari GROUP BY usulan_inpres: hitung usulan = count(*); panjang ruas = per ruas unik (lihat catatan usulan_ijd), jangan SUM(panjang_ruas_km) polos.
- Bandara melayani kab tetangga (Soekarno-Hatta tercatat di Kota Tangerang) -> rasio penumpang/penduduk kab = indikatif, sebutkan.

RESEP (pola SQL yang sudah diuji):
1. Usulan vs kemantapan jalan per kab: `FROM kemantapan_ijd_2026 k LEFT JOIN usulan_inpres u ON u.kode_kabupaten = k.kode_kabupaten WHERE k.kode_kabupaten IS NOT NULL AND k.kode_provinsi = 32 GROUP BY k.kabupaten_kota, k.mantap_pct`.
2. Per 100 ribu penduduk: CTE `p AS (SELECT kode_kabupaten, sum(jumlah_penduduk) pend FROM penduduk_kecamatan GROUP BY 1)` lalu join ke agregat lain USING (kode_kabupaten), `n*100000.0/NULLIF(pend,0)`.
3. Kapasitas fiskal: kemantapan_ijd_2026.kategori_fiskal ('Sangat Rendah'..'Sangat Tinggi', rasio_kfd) join usulan_inpres lewat kode_kabupaten.
4. Lokus prioritas Bappenas: `u.kode_kabupaten IN (SELECT kode_kabupaten FROM bappenas_lokus_a WHERE kriteria = 'PERBATASAN')` -- kriteria: LOKPRI_RPJMN, PERBATASAN, PKSN, KDMP, KNMP, SR, SEKOLAH_GARUDA, BBM_1_HARGA, KPP_DESA, SWASEMBADA_PANGAN_*. Kawasan tematik: kawasan_tematik.kategori (PERKEBUNAN, PERIKANAN, TRANSMIGRASI, KI_PRIORITAS, PKPN). Di bappenas_lokus_a pakai kode_kabupaten (kode_provinsi LOKPRI bisa provinsi kawasan, bukan provinsi kab).
5. Komoditas kecamatan yg dilalui ruas usulan: `bps_kecamatan_produksi_komoditas (jenis_tanaman ILIKE '%sawit%', produksi_ton, kode_kecamatan)` JOIN usulan_kecamatan_dilalui USING (kode_kecamatan). Data 2025 saja; jenis_tanaman ditulis beragam ('Kelapa Sawit/Oil Palm', 'KelapaSawit1', ...) -> selalu ILIKE, dan agregasi dulu per kode_kecamatan (ada baris ganda) sebelum difilter ambang.
6. Kendaraan per km jalan: bps_kabupaten_kendaraan k JOIN bps_kabupaten_jalan j ON j.kode_kabupaten = k.kode_kabupaten AND j.tahun = k.tahun (tahun 2023-2025; tidak semua kab ada).
7. Ruas nasional padat + kondisi: bps_lhr_ruas_nasional l JOIN iri_ruas_nasional i USING (linkid) -> volume/capacity, i.total_mantap_pct, i.rata2_iri.
8. Pelabuhan & usulan per kab: CTE count(*) FROM pelabuhan_daerah GROUP BY kode_kabupaten_bps, LEFT JOIN dari ref_wilayah_kabupaten supaya kab tanpa pelabuhan tetap muncul (0).
9. Penumpang bandara per kab: lalu_lintas_udara_bandara JOIN bandara_kemenhub USING (nama_bandara) -> kode_kabupaten.
10. Program IJD (DPP final) vs usulan: program_ijd_riwayat(tahun, alokasi_rp, kode_kabupaten); kegiatan tingkat provinsi kode_kabupaten NULL -> agregasi per provinsi pakai kode_provinsi.
Sajikan: sebutkan kunci join & tahun data di "Catatan data"; rasio dibulatkan wajar.
