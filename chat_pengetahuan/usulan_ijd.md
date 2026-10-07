---
judul: Usulan Inpres / IJD
kata_kunci: [usulan, inpres, ijd, ruas, sitia, lulus, tidak lulus, seleksi, seleksi sistem, penanganan]
---
- Usulan Inpres/IJD: tabel usulan_inpres = usulan SITIA 2026 (tahun_usulan smallint; provinsi HURUF BESAR mis. 'MALUKU UTARA'; kabupaten_kota, nama_ruas, kode_koridor, panjang_ruas_km; geometri di geom_geojson TEKS GeoJSON -> ST_GeomFromGeoJSON(geom_geojson)).
- Status lulus seleksi = kolom `seleksi_sistem`, nilai 'LULUS'/'TIDAK LULUS'; TIDAK ADA kolom `status`. Contoh: `WHERE tahun_usulan=2026 AND provinsi='PAPUA SELATAN' AND seleksi_sistem='TIDAK LULUS'`.
- Riwayat lintas tahun 2023-2026: usulan_inpres_riwayat (kolom `tahun`, BUKAN tahun_usulan; provinsi HURUF BESAR; `seleksi_sistem` bisa NULL utk 2024; `diprogramkan`).
