---
judul: Pelabuhan
kata_kunci: [pelabuhan, dermaga*, kapal, laut, penyeberangan, maritim, port]
---
- Pelabuhan: tabel pelabuhan_daerah (nama_pelabuhan, provinsi berformat 'Provinsi Maluku Utara', kabupaten_kota 'Kab. ...'/'Kota ...', hirarki_pelabuhan, hirarki_kode PP/PR/PL, lat, lon, penumpang_2024, barang_2024). Titik pelabuhan nasional juga di map_layers provinsi='PELABUHAN' layer='Pelabuhan Nasional' (attrs Name, Provinsi, hierarki).
- Daftar resmi RIPN (Kemenhub, ver 22-09-2026): tabel pelabuhan_ripn (id_ripn = kunci; tipe 'Umum' 636 dgn hierarki PU/PP/PR/PL + hierarki_2017/2022/2027/2037, tipe 'Khusus' 1.978 TERSUS/TUKS; lat, lon, kode_provinsi/kode_kabupaten BPS dari titik). Kode pelabuhan SEL/SAI/PJA dipakai 2 pelabuhan -> join pakai id_ripn.
- Kinerja per pelabuhan umum 2021-2024 (BPS): pelabuhan_kinerja (id_ripn, tahun, unit_dn/ln, bongkar/muat dn/ln ton, penumpang datang/berangkat, total_ton_bersih). Hanya ~345 pelabuhan/tahun yang punya data (`keterangan LIKE 'BPS%'`); sisanya '-' = tidak ada data, BUKAN nol. Angka apa adanya dari sumber, ada yg janggal (mis. Pangkal Balam 2024 82,8 juta ton) -> sebut sbg data sumber. Rincian dermaga/gudang/lapangan: pelabuhan_fasilitas_komponen.
- Peta: bucket `PELABUHAN RIPN`, layer "Pelabuhan Umum (RIPN)" dan "Terminal Khusus TERSUS-TUKS (RIPN)".
