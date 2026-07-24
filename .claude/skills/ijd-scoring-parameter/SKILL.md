---
name: ijd-scoring-parameter
description: Use when adding, extending, or reweighting an IJD/CPIT scoring parameter (A1-A4, B, C, D, E, F) in the The Next - SiJalan repo (analytic-maps) — seeding pre-weighted rules into ijd_scoring_rules, writing or extending a _ijd_score_* function in app.py, registering it in _IJD_SCORERS, and verifying the endpoint. Triggers on requests like "tambah parameter skoring IJD", "ubah bobot kaidah 2026/2027", "hitung sub-parameter A3/A4/C.A1", "kaidah IJD tahun baru", or any change touching ijd_scoring_rules / _compute_ijd_score.
---

# Menambah / mengubah parameter skoring IJD

Resep ini dipakai berulang selama pengembangan CPIT/IJD di repo ini (A1
tematik+A4 data dukung, A2 koridor via Balai, C.A1 kepadatan, E penuntasan,
A3 tematik tambahan, A2 pagu provinsi). Ikuti urutan ini persis — jangan
menghitung bobot inline di Python (lihat `docs/ARCHITECTURE.md` §"Rules-as-
data").

## 1. Baca dokumen sumber, catat nilai & bobot persis

Nilai resmi ada di PDF kebijakan (`docs/docs/F. Parameter Penilaian IJD
[FULL] <tanggal>.pdf` atau versi terbaru). Ekstrak teks PDF dengan PyMuPDF
kalau perlu (`pdftoppm` tidak tersedia di environment ini — jangan pakai
Read tool langsung pada PDF gambar, pakai `fitz` via Bash/PowerShell).

## 2. Seed rules — nilai SUDAH TERTIMBANG, bukan mentah

Tambahkan `INSERT ... ON DUPLICATE KEY UPDATE` ke
`scripts/schema_ijd_scoring_<tahun>.sql` (buat baru kalau tahun kaidah
baru). Kolom `nilai` di `ijd_scoring_rules` untuk kaidah 2026+ menyimpan
hasil **nilai_tabel × bobot_sub_parameter%**, contoh:

```sql
-- A1 "Pertanian" nilai tabel 100, bobot sub A1 = 40% dari parameter A
(2026, 'A', 'Tematik dan Data Dukungnya', 30, 'A1_PERTANIAN', 'A1 ... (100 x 40%)', 40.0),
```

`sub_kode` adalah kunci pencocokan di kode Python — pilih yang deskriptif
dan konsisten prefiks (`A3_<KATEGORI>`, `A4_<STATUS>`, dst.) supaya scorer
bisa `any(k.startswith("A3_") for k in rule["subs"])` untuk mendeteksi
apakah sub-parameter ini sudah di-seed untuk tahun tsb.

Beri komentar SQL di atas blok INSERT: sumber data, sub-parameter apa yang
tercakup, dan **sub-parameter mana yang SENGAJA belum di-seed** (biar orang
lain tak menyangka itu kelalaian).

## 3. Tulis atau perluas fungsi `_ijd_score_<nama>()` di app.py

Bentuk wajib:

```python
def _ijd_score_x(row: dict, rules: dict) -> dict:
    rule = rules.get("X")
    if not rule:
        return {"tersedia": False, "keterangan": "Kaidah X belum diset di database."}
    # ambil data sumber dari row (kolom usulan_inpres) atau query tabel lain
    if <data tidak ada>:
        return {"tersedia": False, "keterangan": "<alasan spesifik, actionable>"}
    sub = rule["subs"]["<SUB_KODE>"]
    return {"tersedia": True, "nilai": sub["nilai"], "keterangan": f"{sub['label']} (sumber: ...)."}
```

Aturan tak boleh dilanggar (lihat `docs/ARCHITECTURE.md` §"belum tersedia,
bukan 0"):
- Tidak ada data → `tersedia: False` + alasan spesifik, **jangan** nilai 0.
- Kalau field punya hierarki Pemda→Balai→Kompetensi, pakai pola
  fallback-chain (lihat `_ijd_score_tematik` untuk contoh).
- Kalau butuh join ke tabel lain (mis. `kawasan_tematik`,
  `kecamatan_data_turunan`), pakai `with db_cursor() as cur:` di dalam
  fungsi scorer — jangan pre-fetch semua usulan sekaligus (scorer dipanggil
  per-usulan, bukan batch).

## 4. Daftarkan di `_IJD_SCORERS`

```python
_IJD_SCORERS = {"A": _ijd_score_tematik, ..., "X": _ijd_score_x}
```

Parameter yang **tidak** didaftarkan otomatis lewat jalur
`IJD_PENDING_PARAMETERS` (app.py) — tambahkan entrinya di situ dengan
`bobot_maks_per_tahun` per tahun kaidah dan `alasan` yang jujur, supaya
endpoint tetap melaporkan parameter itu sebagai "belum tersedia" alih-alih
menghilang begitu saja.

**Jangan** sentuh loop utama di `_compute_ijd_score()` — dia sudah memakai
`set(rules) | set(IJD_PENDING_PARAMETERS)` per tahun, jadi parameter baru
otomatis muncul begitu ada di salah satu dict, dan parameter yang dihapus
suatu tahun (seperti F di 2026) otomatis hilang tanpa perlu if/else tahun.

## 5. Kalau parameter ini juga komponen Pagu Provinsi (G8)

Pagu provinsi (`_pagu_provinsi()`) itu terpisah dari skor per-usulan —
komponennya (A1-A5 di level *provinsi*, bukan level usulan) punya bobot
sendiri (20/30/20/15/15) dan pola normalisasi pangsa-nasional sendiri.
Kalau menambah komponen di situ, ikuti pola A1/A2/A4 yang sudah ada:
hitung skor per provinsi → jumlahkan sebagai pangsa nasional (harus 100%
kalau bobot komponen itu tersedia untuk semua provinsi) → masukkan ke
`bobot`/`nilai` accumulator sebelum `skor = nilai / bobot`.

## 6. Jalankan seed & verifikasi end-to-end

```powershell
.venv\Scripts\Activate.ps1
python -c "from app import db_cursor; sql=open('scripts/schema_ijd_scoring_2026.sql',encoding='utf-8').read(); sql='\n'.join(l for l in sql.splitlines() if not l.strip().startswith('--'));
exec('with db_cursor() as cur:\n ' + chr(10).join(f' cur.execute({s!r})' for s in sql.split(';') if s.strip()))"
```

(atau lebih mudah: tulis script kecil di scratchpad yang membuka
`db_cursor()`, loop `stmt.split(';')`, `cur.execute(stmt)`.)

Lalu verifikasi via `TestClient` (bukan browser) — bandingkan 2-3 usulan
riil dengan kondisi berbeda (tersedia vs tidak tersedia vs nilai tertinggi/
terendah) terhadap perhitungan manual:

```python
from fastapi.testclient import TestClient
from app import app
c = TestClient(app)
d = c.get(f"/api/usulan-inpres/{uid}/ijd-score").json()
k = next(x for x in d["komponen"] if x["kode"] == "X")
assert k["nilai"] == <hitung manual>
```

Cek juga `bobot_tersedia` di respons naik sesuai bobot parameter baru, dan
kaidah tahun lain (mis. `?tahun=2025`) tidak ikut berubah kalau memang tidak
seharusnya.

## 7. Dokumentasikan

- Tandai gap terkait selesai di `checklist_implementasi_cpit.md` (fase yang
  sesuai), sebutkan cakupan riil (berapa usulan yang terhitung, bukan cuma
  "selesai").
- Kalau ada gotcha baru (format data sumber aneh, bug library), tambahkan
  ke `docs/MEMORY.md`, bukan ke komentar kode yang tersebar.
