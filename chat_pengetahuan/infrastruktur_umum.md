---
judul: Infrastruktur umum (pasar, SDA, listrik, air minum)
kata_kunci: [pasar, bendungan, irigasi, sabo, pengaman pantai, gardu induk, listrik, pembangkit, pltd, plts, spam, air minum, rusunawa, tpa, iplt, terminal bbm, lpg, kilang, pelabuhan perikanan, alur pelayaran, rencana umum jalan]
---
- Hanya ada sebagai layer peta (tabel map_layers, kabupaten = '', nama di attrs->>'Nama'), sumber SHP Infrastruktur 2026. Bucket (kolom `provinsi`) dan `layer`:
  - 'LOGISTIK & EKONOMI': 'Pasar', 'Pelabuhan Perikanan', 'Terminal BBM', 'Terminal LPG', 'Kilang Minyak', 'Alur Pelayaran Laut'.
  - 'SUMBER DAYA AIR': 'Bendungan Eksisting', 'Bendungan Rencana', 'Daerah Irigasi Rawa - Fungsional'/'- Potensial'/'- Baku', 'Daerah Irigasi Tambak - Fungsional'/'- Potensial', 'Sabo DAM', 'Pengaman Pantai'.
  - 'ENERGI & KELISTRIKAN': 'Gardu Induk', 'Jaringan Transmisi Listrik', 'Pembangkit Listrik (ESDM)', 'Pembangkit Off-grid APBN'.
  - 'PERMUKIMAN & LAYANAN DASAR': 'SPAM (Air Minum)', 'Rusunawa', 'TPA (Sampah)', 'IPLT (Lumpur Tinja)'.
  - 'JALAN NASIONAL': 'Rencana Umum Jalan Nasional Non-Tol (SK 367/2023)' (attrs 'Nama ruas', 'Jenis penanganan' PEMBANGUNAN/PENINGKATAN; trase indikatif).
- Hitung per wilayah dgn `wilayah_provinsi` (array nama provinsi, mis. `'Jawa Timur' = ANY(wilayah_provinsi)`) atau spasial thd poligon BATAS KABUPATEN. Data titik ini tidak lengkap per daerah (mis. Pasar hanya 625 titik nasional) -> jangan simpulkan "tidak ada pasar" dari ketiadaan titik.
- Jarak dari rute usulan: endpoint/tool analisa spasial, atau panel detail usulan blok "Infrastruktur di Sekitar Ruas".
