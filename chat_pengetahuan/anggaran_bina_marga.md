---
judul: Anggaran Bina Marga (Paket LS & SBSN)
kata_kunci: [sbsn, sukuk, paket ls, dipa, anggaran bina marga, satker, pagu bina marga, apbn bina marga, long segment]
---
- Isinya anggaran JALAN NASIONAL Ditjen Bina Marga (satker PJN), BUKAN usulan/program IJD. Tidak ada lokasi ruas/kab: hanya `kode_provinsi` (+ nama ruas di dalam nama paket).
- `paket_ls_bina_marga`: alokasi DIPA akhir TA 2021-2025 per paket x output, rupiah. Total = `jumlah_rp`; per sumber dana `rpm_rp`, `pdp_rp`, `rpln_rp`, `phln_rp`, `local_cost_rmp_rp`, `sbsn_rp` (NULL bila tahun itu tak punya kolom tsb). `jalan_daerah = true` = RO "Dukungan Penanganan Jalan/Jembatan Daerah" (porsi IJD di DIPA, mulai 2023: Rp15,59 T / 3,62 T / 7,12 T utk 2023/2024/2025). Total per tahun: 2021 Rp66,37 T, 2022 58,15 T, 2023 88,99 T, 2024 76,83 T, 2025 50,66 T.
- `sbsn_kegiatan_djbm`: paket berpendanaan SBSN TA 2015-2026 (pagu, nilai kontrak, realisasi, rupiah). `pagu_rp` = pagu SBSN tahun itu (arti per tahun di `jenis_pagu`; 2025-2026 dari Rp ribu, sudah dikali 1000). `nilai_kontrak_rp` = nilai kontrak PENUH (MYC multi-tahun) -> JANGAN dijumlah lintas tahun. `myc` = kontrak tahun jamak. Untuk 2021-2025, SUM(pagu_rp) per tahun dan per provinsi = SUM(sbsn_rp) di paket_ls_bina_marga (sudah dicek cocok persis).
- Provinsi Tanah Papua: sebelum 2023 tercatat di provinsi induk (Papua/Papua Barat, lihat `catatan_data`).
