---
judul: Bandara & penerbangan
kata_kunci: [bandara, bandar udara, airport, penerbangan, pesawat, udara, iata, penumpang*, tersibuk, terminal, runway, kemenhub, lalu lintas penumpang]
---
- Bandara: tabel bps_data_bandara (nama_bandara, provinsi, kabupaten, kelas, hirarki, lat, lon, kapasitas_eksisting_valid/estimasi, catatan_data; kode wilayah: pakai kode_kabupaten_bps/kode_provinsi_bps, BUKAN kode_kabupaten/kode_provinsi utk Papua). demand_pax satuannya TIDAK seragam -- jangan dijumlah/dibandingkan.
- Bandara tersibuk / penumpang aktual: bandara_kemenhub (bandara_id, nama_bandara, lalu_lintas_tahun, lalu_lintas_penumpang), BUKAN bps_data_bandara (join bandara_kemenhub_id = bandara_id). TIDAK ada kolom `tahun`.
- Jebakan: `lalu_lintas_penumpang` banyak NULL. `ORDER BY ... DESC` polos menaruh NULL paling atas, bandara tanpa data tampak terbesar. Selalu `WHERE lalu_lintas_penumpang IS NOT NULL` dan `ORDER BY ... DESC NULLS LAST`.
- Titik di map_layers provinsi='BANDARA KEMENHUB' layer='Bandara Kemenhub' (attrs Name, IATA, Kelas, Hierarki, Provinsi); rute layer='Rute Penerbangan (Kemenhub)'.
