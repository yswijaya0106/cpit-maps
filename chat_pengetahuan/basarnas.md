---
judul: Basarnas / SAR
kata_kunci: [sar, basarnas, pencarian dan pertolongan, rescue*, respon, respons, pos sar, kantor sar, alut, darurat]
---
- Basarnas: map_layers provinsi='BASARNAS': layer='KANTOR SAR' (attrs nama_kantor, tipe_kelas, latitude, longitude), layer='POS SAR' (attrs 'Nama Pos SAR', 'Nama Kantor SAR'), layer='WILAYAH TANGGUNG JAWAB SAR' (poligon, attrs 'Nama Kantor Pencarian dan Pertolongan'). Data operasional: basarnas_alut, basarnas_ops_sar, basarnas_analisis_kantor.
- Waktu respon Kantor SAR: basarnas_analisis_kantor (lokasi, status 'Kantor SAR'/'Pos SAR', waktu_respon_rata_rata_menit -- NULL utk Pos SAR) atau hitung dari basarnas_ops_sar.
