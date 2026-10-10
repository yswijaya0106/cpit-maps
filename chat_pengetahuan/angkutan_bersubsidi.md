---
judul: Angkutan bersubsidi & skema tahun jamak (MYC)
kata_kunci: [bersubsidi, subsidi*, tahun jamak, myc, tier myc, terlayani, tidak terlayani, potensi integrasi]
---
- Tabel `angkutan_bersubsidi_2026`: latihan (draf) Bappenas Dit. Konektivitas, 514 kab/kota x `sektor` ('penumpang'|'barang') = 1.028 baris. Kunci wilayah `kode_kabupaten`/`kode_provinsi` (BPS); `provinsi_sumber` bisa salah, pakai `provinsi`.
- `status_layanan` 'Terlayani'/'Tidak Terlayani' = dilayani angkutan BERSUBSIDI (perintis), bukan angkutan umum komersial. Penumpang 336 terlayani, barang 147. `status_mentah` = versi sebelum perubahan definisi (barang mentah 79: penyeberangan baru dihitung sbg moda barang di data bersih).
- `urgensi` Tinggi/Sedang/Rendah = penilaian NARATIF penyusun (bukan skor); 59 wilayah Tinggi, sama di kedua sektor.
- `tier_myc` (Tier 1-4, 59 wilayah urgensi Tinggi, Kep. Seribu dikeluarkan) per wilayah, terisi sama di kedua baris sektor -> hitung dgn `WHERE sektor='penumpang'` supaya tidak ganda. Tier = KANDIDAT skema kontrak tahun jamak, belum diuji gerbang riwayat gangguan layanan; sebutkan itu.
- Peta: bucket overlay `ANGKUTAN BERSUBSIDI`, layer "Angkutan Bersubsidi Penumpang 2026", "Angkutan Bersubsidi Barang 2026", "Kandidat Skema Tahun Jamak (MYC) 2026" (kabupaten '' = nasional, atau nama provinsi).
