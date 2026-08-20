# Database dump untuk staging

`route_gis_20260820.dump` — pg_dump format custom (`-Fc`), database `route_gis`
PostgreSQL/PostGIS, diambil 2026-08-20 setelah import gap docs/New/ (angkutan
perintis geometri, pelabuhan_daerah, basarnas_puslat_fasilitas).

Berisi semua 52 tabel + PostGIS extension reference, ~1.09 GiB terkompresi
(map_layers sendiri ~1.5 GB tanpa kompresi, tabel terbesar — semua layer SHP
RBI nasional).

## Restore di server staging

Server staging harus sudah punya PostgreSQL + ekstensi PostGIS terpasang
(`CREATE EXTENSION postgis;` di database kosong sebelum restore, atau biarkan
pg_restore yang membuatnya — dump ini menyertakan definisi ekstensinya).

```bash
# 1. Buat database kosong (kalau belum ada)
createdb -h <host> -U <user> route_gis

# 2. Restore (paralel 4 job mempercepat restore tabel besar spt map_layers)
pg_restore -h <host> -U <user> -d route_gis --clean --if-exists -j 4 route_gis_20260820.dump
```

`--clean --if-exists` aman dipakai berulang (drop objek yang ada sebelum
recreate) — cocok untuk refresh staging dari dump baru tanpa drop database
manual dulu.

Update `.env` staging (`PG_HOST/PORT/USER/PASS/DB=route_gis`) supaya app.py
menunjuk ke database yang baru di-restore ini.

File dump tidak di-commit ke git (lihat `.gitignore` — `backups/*.dump`,
ukurannya ratusan MB-GB, tidak cocok utk version control). Pindahkan file
ini ke staging lewat scp/rsync/upload manual.
