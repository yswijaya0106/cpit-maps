# Update Staging — Layer & Tabel Baru dari `docs/New/`

Panduan ini untuk mem-push hasil kerja `docs/kajian_data_baru_docs_new.md`
(21 script import baru: layer overlay peta + tabel referensi dari BASARNAS,
Keselamatan, Laut, Udara, Darat, Kereta Api — lihat kajian untuk daftar
lengkap) ke server **staging** yang sudah berjalan, **bukan** panduan deploy
dari nol (untuk itu lihat `docs/deployment_production.md`).

Semua ini **layer overlay peta umum & tabel referensi lepas-IJD** — tidak
menyentuh `_IJD_SCORERS`, `ijd_scoring_rules`, `usulan_inpres`, atau
endpoint skoring IJD manapun. Aman diupdate independen dari alur kerja IJD
yang sedang berjalan di staging.

## 0. Status kode saat ini (cek sebelum mulai)

Sebagian pekerjaan sesi ini **sudah ter-commit & ter-push ke `origin/main`**
(commit `ccef070`, `08c3056`). Ada **4 file lagi masih berubah di working
tree lokal, belum di-commit** (per `git status` terakhir):
`static/css/style.css`, `static/index.html`, `static/js/state.js`,
`static/js/usulan-inpres.js` — ini bagian selector moda (IJD/Udara/Darat/
Laut) di panel "Lokasi Prioritas" dan "Jelajahi Usulan Inpres". **Commit &
push dulu perubahan ini sebelum lanjut ke langkah `git pull` di staging**,
kalau belum dilakukan.

## 1. Update kode di staging

```bash
cd /path/ke/analytic-maps   # working directory aplikasi di staging
git pull origin main
```

Tidak ada perubahan dependensi Python baru (semua script pakai
`openpyxl`/`geopandas`/`psycopg` yang sudah ada di `requirements.txt`) —
tidak perlu `pip install` ulang.

## 2. Siapkan sumber data `docs/New/`

**`docs/` (termasuk `docs/New/`) gitignored** — `git pull` di atas
**tidak** membawa file sumber xlsx/PDF/SHP-nya. Ada 2 opsi, sama seperti
pola `Maps/`/`dalam_angka/` di `docs/deployment_production.md`:

### Opsi A — jalankan import langsung di staging (kalau `docs/New/` sudah/bisa ada di sana)
Salin folder `docs/New/` (dari mesin dev/tempat kajian ini dikerjakan) ke
staging, path relatif yang sama persis (`docs/New/<kategori>-<timestamp>/...`
— tiap script punya path sumber hardcoded persis sesuai struktur folder
asli, lihat konstanta `XLSX_PATH`/`BASARNAS_DIR`/dst. di tiap script).
Lanjut ke §3.

### Opsi B — jalankan import di dev, pindahkan hasilnya lewat `pg_dump` (lebih dianjurkan)
Kalau staging tidak perlu/tidak boleh menyimpan `docs/New/` (mis. berisi
data yang belum final untuk didistribusikan), jalankan §3 di lingkungan
dev yang sudah punya `docs/New/` lokal, lalu dump HANYA tabel/baris baru
ke staging:

```bash
# di dev, setelah semua script §3 selesai:
pg_dump -h <host-dev> -U <user> -d route_gis -F c \
  -t map_layers -t map_layer_meta \
  -t basarnas_alut -t basarnas_diklat_rekap -t basarnas_ops_sar \
  -t basarnas_rescuer_potensi -t bps_data_bandara -t bps_kinerja_pelabuhan \
  -t bps_lhr_ruas_nasional -t anev_laka_lantas_nasional -t anev_laka_lantas_polda \
  -t angkutan_perintis -t list_lokpri_kawasan -t od_lrt_jabodebek \
  -t rekap_penumpang_ka_nasional -t psc119_layanan \
  -f layer_baru_dump.pgdump
```

**Catatan penting**: `map_layers`/`map_layer_meta` adalah tabel bersama
(dipakai SEMUA layer overlay peta, bukan cuma yang baru) — `pg_dump -t`
di atas men-dump SELURUH isi tabel itu, bukan cuma baris baru. Kalau
staging sudah punya isi `map_layers` sendiri yang beda dari dev (mis. ada
layer lain yang diimpor terpisah di staging), **jangan** `pg_restore`
kedua tabel itu dengan mode replace — pakai `pg_restore --data-only
--disable-triggers` ke tabel yang sudah di-`TRUNCATE` cuma untuk baris
`provinsi` yang relevan, atau lebih aman: jalankan ulang script import di
staging langsung (Opsi A) untuk tabel `map_layers`, dan `pg_dump -t` cukup
untuk tabel non-`map_layers` yang lain (semuanya idempotent/refresh-penuh
per tabel, aman di-restore langsung).

```bash
# di staging:
pg_restore -h <host> -U route_gis_app -d route_gis --no-owner --data-only layer_baru_dump.pgdump
```

## 3. Jalankan 21 script import (idempotent, aman diulang)

Semua script di bawah **aman dijalankan ulang** (skip yang sudah ada
kecuali `--force` untuk layer peta, atau UPSERT/refresh penuh untuk
tabel referensi) — urutan TIDAK saling bergantung, bisa paralel/acak,
tapi paling gampang dijalankan berurutan:

```bash
source .venv/bin/activate   # atau .venv\Scripts\Activate.ps1 di Windows

# --- Layer peta (map_layers/map_layer_meta) ---
python scripts/import_basarnas_to_postgis.py          # Kantor SAR, Pos SAR, Wilayah Tanggung Jawab
python scripts/import_blackspot_to_postgis.py          # Blackspot Kecelakaan (bucket JALAN NASIONAL)
python scripts/import_kereta_api_to_postgis.py          # Jalur KA nasional + BTP
python scripts/import_terminal_tipe_a_to_postgis.py     # Terminal Tipe A (ekstraksi PDF)
python scripts/import_pelabuhan_tersus_tuks_to_postgis.py
python scripts/import_pelabuhan_penyeberangan_operasi_to_postgis.py
python scripts/import_pelabuhan_penumpang_to_postgis.py
python scripts/import_lrk_2026_to_postgis.py            # bucket JALAN NASIONAL

# --- Tabel referensi non-spasial ---
python scripts/import_lhr_ruas_nasional.py
python scripts/import_anev_laka_lantas.py
python scripts/import_bps_data_bandara.py
python scripts/import_basarnas_alut.py
python scripts/import_basarnas_rescuer_potensi.py
python scripts/import_basarnas_ops_sar.py               # ~12.200 baris, paling besar, beberapa menit
python scripts/import_bps_kinerja_pelabuhan.py
python scripts/import_list_lokpri_kawasan.py
python scripts/import_angkutan_perintis.py
python scripts/import_basarnas_diklat_rekap.py
python scripts/import_od_lrt_jabodebek.py
python scripts/import_rekap_penumpang_ka_nasional.py
python scripts/import_psc119_layanan.py                 # data personal SUDAH diredaksi di level kode, aman
```

Kalau layer peta sebelumnya sudah pernah diimpor ke staging dan mau
diperbarui (mis. ada baris baru ditemukan di sumber), tambahkan `--force`
per script (menghapus layer lama lalu impor ulang):

```bash
python scripts/import_basarnas_to_postgis.py --force
```

Skema tabel (`CREATE TABLE IF NOT EXISTS ...`) otomatis dijalankan di
awal tiap script tabel referensi (baca file `schema_*.sql` pasangannya) —
**tidak perlu langkah `CREATE TABLE` manual terpisah**, beda dari
skema lama era MySQL yang sudah tidak dieksekusi kode manapun (lihat
`docs/deployment_production.md` §4).

## 4. Restart service aplikasi (WAJIB)

Perubahan `app.py` (dict `DATA_TABLES`, `DATA_TABLE_TEXT_PROVINSI`, param
`provinsi_text`) dan `map_layer_labels.py` (label layer baru) adalah kode
Python — **butuh restart proses uvicorn**, tidak otomatis kepakai tanpa
itu (beda dari data DB yang langsung kebaca live tiap request):

```bash
sudo systemctl restart analytic-maps   # Linux systemd, lihat docs/deployment_production.md §7
```

`static/index.html`/`.css`/`.js` **tidak butuh restart** — `NoCacheStaticFiles`
di `app.py` sudah bikin browser selalu ambil versi terbaru tiap load,
tapi restart tetap wajib untuk bagian `app.py`-nya.

## 5. Verifikasi

```bash
# 15 tabel baru harus muncul dengan total baris > 0:
curl -s https://staging.contoh-domain/api/data/tables | python3 -m json.tool | grep -A2 "bps_data_bandara\|basarnas_ops_sar\|angkutan_perintis"

# bucket layer peta baru harus muncul:
curl -s https://staging.contoh-domain/api/maps/provinces | grep -oE '"provinsi":"(BASARNAS|JALUR KERETA API|PELABUHAN[^"]*|TERMINAL TIPE A)"'
```

Di browser: buka topbar **"Data"** — cek tabel baru ada di daftar dengan
jumlah baris masuk akal (lihat tabel ringkasan di bawah). Buka **"Overlay
Peta"** — kategori baru "Pencarian & Pertolongan (SAR)" dan "Kereta Api"
harus muncul, kategori "Simpul Transportasi" harus bertambah 3 layer
(Pelabuhan TERSUS/TUKS, Pelabuhan Penyeberangan Operasi, Pelabuhan
Penumpang, Terminal Tipe A). Buka tombol **"Lokasi Prioritas"** (dulu
"Laporan Prioritas") — pilih moda Udara/Darat/Laut, tabel referensi harus
tampil. Buka panel sidebar **"7. Jelajahi Usulan Inpres..."** — pilih moda
selain IJD, daftar harus beralih ke tabel referensi terkait.

### Jumlah baris yang diharapkan (referensi cepat)

| Tabel/Layer | Baris/Fitur |
|---|---|
| `map_layers` (BASARNAS: Kantor SAR/Pos SAR/Wilayah Tanggung Jawab) | 47 + 85 + 43 |
| `map_layers` (Blackspot Kecelakaan) | 839 |
| `map_layers` (Jalur KA nasional + BTP) | 1.460 + 668 |
| `map_layers` (Terminal Tipe A) | 125 |
| `map_layers` (Pelabuhan TERSUS/TUKS) | 1.978 |
| `map_layers` (Pelabuhan Penyeberangan Operasi) | 235 |
| `map_layers` (Pelabuhan Penumpang) | 546 |
| `map_layers` (LRK 2026) | 55 |
| `bps_lhr_ruas_nasional` | 3.307 |
| `anev_laka_lantas_nasional` / `_polda` | 1.641 / 216 |
| `bps_data_bandara` | 251 |
| `basarnas_alut` | 3.939 |
| `basarnas_rescuer_potensi` | 47 |
| `basarnas_ops_sar` | 12.216 |
| `bps_kinerja_pelabuhan` | 480 |
| `list_lokpri_kawasan` | 249 |
| `angkutan_perintis` | 632 |
| `basarnas_diklat_rekap` | 5 |
| `od_lrt_jabodebek` | 3.240 |
| `rekap_penumpang_ka_nasional` | 144 |
| `psc119_layanan` | 187 |

Kalau ada yang jauh berbeda dari angka ini (bukan cuma beda tipis karena
sumber data terupdate), cek log run script yang bersangkutan — tiap
script mencetak jumlah baris valid vs. dibuang beserta alasannya
(koordinat kosong/di luar rentang, dsb.), bukan gagal senyap.

## 6. Rollback kalau ada masalah

Semua tabel baru **berdiri sendiri** (tidak ada foreign key dari tabel
IJD manapun ke tabel-tabel ini) — kalau perlu mundur, cukup:

```sql
DROP TABLE IF EXISTS basarnas_alut, basarnas_diklat_rekap, basarnas_ops_sar,
  basarnas_rescuer_potensi, bps_data_bandara, bps_kinerja_pelabuhan,
  bps_lhr_ruas_nasional, anev_laka_lantas_nasional, anev_laka_lantas_polda,
  angkutan_perintis, list_lokpri_kawasan, od_lrt_jabodebek,
  rekap_penumpang_ka_nasional, psc119_layanan;

DELETE FROM map_layers WHERE provinsi IN
  ('BASARNAS', 'JALUR KERETA API', 'PELABUHAN TERSUS/TUKS',
   'PELABUHAN PENYEBERANGAN OPERASI', 'PELABUHAN PENUMPANG')
  OR (provinsi = 'JALAN NASIONAL' AND layer IN ('BLACKSPOT KECELAKAAN', 'LOKASI RAWAN KECELAKAAN 2026'));
DELETE FROM map_layer_meta WHERE provinsi IN
  ('BASARNAS', 'JALUR KERETA API', 'PELABUHAN TERSUS/TUKS',
   'PELABUHAN PENYEBERANGAN OPERASI', 'PELABUHAN PENUMPANG')
  OR (provinsi = 'JALAN NASIONAL' AND layer IN ('BLACKSPOT KECELAKAAN', 'LOKASI RAWAN KECELAKAAN 2026'));
```

Lalu `git revert`/checkout kode ke commit sebelum `ccef070`, restart
service. Tidak mempengaruhi `usulan_inpres`/skoring IJD sama sekali.
