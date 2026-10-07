---
judul: Bandara & penerbangan
kata_kunci: [bandara, bandar udara, airport, penerbangan, pesawat, udara, iata, penumpang*, tersibuk, terminal, runway]
---
- Bandara: tabel bps_data_bandara (nama_bandara, provinsi, kabupaten, kelas, hirarki, lat, lon, kapasitas_eksisting_valid, kapasitas_eksisting_estimasi, catatan_data; kode wilayah: pakai kode_kabupaten_bps/kode_provinsi_bps, BUKAN kode_kabupaten/kode_provinsi yg salah urut utk Papua). demand_pax satuannya TIDAK seragam antarbandara -- jangan dijumlah/dibandingkan.
- Bandara tersibuk / jumlah penumpang aktual: bandara_kemenhub.lalu_lintas_penumpang (+ lalu_lintas_tahun), BUKAN bps_data_bandara (join bps_data_bandara.bandara_kemenhub_id = bandara_kemenhub.bandara_id).
- Titik di map_layers provinsi='BANDARA KEMENHUB' layer='Bandara Kemenhub' (attrs Name, IATA, Kelas, Hierarki, Provinsi); rute penerbangan layer='Rute Penerbangan (Kemenhub)'.
