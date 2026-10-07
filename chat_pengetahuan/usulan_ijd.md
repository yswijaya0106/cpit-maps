---
judul: Usulan Inpres / IJD
kata_kunci: [usulan, inpres, ijd, ruas, sitia, lulus, tidak lulus, seleksi, seleksi sistem, penanganan]
---
- Usulan Inpres/IJD: tabel usulan_inpres = usulan SITIA 2026 (tahun_usulan smallint; provinsi HURUF BESAR mis. 'MALUKU UTARA'; kabupaten_kota, nama_ruas, kode_koridor, panjang_ruas_km; geometri di geom_geojson TEKS GeoJSON -> ST_GeomFromGeoJSON(geom_geojson)).
- Status lulus seleksi = kolom `seleksi_sistem`, nilai 'LULUS'/'TIDAK LULUS'; TIDAK ADA kolom `status`. Contoh: `WHERE tahun_usulan=2026 AND provinsi='PAPUA SELATAN' AND seleksi_sistem='TIDAK LULUS'`.
- Panjang: `panjang_ruas_km` = panjang SELURUH ruas, `panjang_penanganan_pemda` = panjang yg diusulkan ditangani (jauh lebih kecil). Satu ruas (kode_ruas) bisa diusulkan >1 paket, jadi SUM(panjang_ruas_km) per wilayah menghitung ganda (Banten: Lebak 341,8 km vs 291,2 km ruas unik). Utk "panjang ruas" pakai ruas unik (MAX per kode_ruas lalu SUM); utk "panjang ditangani" SUM(panjang_penanganan_pemda). Sebut kolom mana yg dipakai.
- Riwayat lintas tahun 2023-2026: usulan_inpres_riwayat (kolom `tahun`, BUKAN tahun_usulan; provinsi HURUF BESAR; `seleksi_sistem` bisa NULL utk 2024; `diprogramkan`).
