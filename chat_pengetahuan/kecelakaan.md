---
judul: Kecelakaan lalu lintas
kata_kunci: [kecelakaan, laka, polda, korban, fatalitas, meninggal, luka, kejadian, tren]
---
- Kecelakaan lalu lintas: anev_laka_lantas_polda (polda, tahun TEKS, kejadian, korban_md/lb/lr). Satu baris = satu polda per tahun; `kejadian` & `korban_*` sudah total agregat tahun itu, BUKAN per-insiden. Untuk total/tren pakai SUM(kejadian), BUKAN COUNT(kejadian).
- Nama polda SINGKATAN: 'JABAR', 'JATENG', 'JATIM', 'METRO JAYA' (DKI), 'DIY', 'BABEL', 'SUMUT', 'SULSEL', dst. -- cek SELECT DISTINCT polda.
- Tahun TEKS: '2020'..'2024' (setahun penuh) dan 'JAN - 30 OKT 2025' (parsial, Jan-30 Okt). Filter dgn `tahun IN ('2020',...)`, bukan BETWEEN angka; sertakan 2025 hanya bila diminta dan sebut parsial.
