---
judul: Batas wilayah, penduduk & kecamatan
kata_kunci: [penduduk, populasi, jiwa, demografi, kecamatan, distrik, batas, poligon, kabupaten, kota, kab]
---
- Batas wilayah: map_layers provinsi='BATAS PROVINSI' (attrs PROVINSI) dan 'BATAS KABUPATEN' (attrs PROVINSI, KABUPATEN_KOTA, KODE_KABUPATEN).
- Penduduk & kecamatan: penduduk_kecamatan (satu baris = satu kecamatan; jumlah_penduduk). kabupaten_kota berisi nama TANPA awalan & KEMBAR utk Kab/Kota sama nama ('BANDUNG' = Kab. Bandung 3204 DAN Kota Bandung 3273) -> WAJIB filter kode_kabupaten; cari kodenya di ref_wilayah_kabupaten (nama_kabupaten_kota, jenis_kabupaten 'KABUPATEN'/'KOTA'). Utk profil satu kab/kota lebih baik pakai tool analisis_kabupaten.
