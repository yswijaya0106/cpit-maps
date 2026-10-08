"""Asisten chat The Next - SiJalan -- provider LLM (Groq/Grok/OpenAI/Claude/Gemini),
tool-calling read-only ke database usulan Inpres, dan pemilihan provider
(dicoba berurutan lewat _call_chat sampai satu berhasil).

Diekstrak dari app.py (lihat strategi refactor bertahap di riwayat percakapan)
-- endpoint POST /api/chat tetap di app.py, modul ini cuma logikanya.

Fungsi tool (_tool_cari_usulan_inpres dkk.) butuh helper CRUD usulan_inpres
yang didefinisikan di app.py (usulan_inpres_list/usulan_inpres_detail/
_fetch_usulan_geometry). Diimpor LAZY (di dalam fungsi, bukan di top-level)
supaya tidak circular import -- app.py mengimpor modul ini di top-level utk
endpoint /api/chat, jadi modul ini tidak boleh mengimpor app.py di top-level.
"""
import contextvars
import json
import os
import re
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import List, Optional

import anthropic
import requests
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from pyproj import Geod

import chat_dataset
from db import db_cursor  # aman diimpor top-level -- db.py tidak bergantung pada app.py/modul ini

_GEOD = Geod(ellps="WGS84")

# Beberapa provider LLM opsional untuk chat assistant — semua dicek dari .env
# dan dicoba berurutan (lihat _call_chat) sampai salah satu berhasil, supaya
# tidak bergantung pada satu provider yang bisa kehabisan kuota harian.
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

GROK_MODEL = os.getenv("GROK_MODEL", "grok-3-mini")
GROK_API_URL = "https://api.x.ai/v1/chat/completions"

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5")

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")

# DeepSeek (api-docs.deepseek.com): Chat Completions kompatibel OpenAI, jadi
# memakai _call_openai_compatible apa adanya. Model per Okt 2026:
# deepseek-flash (V4.1-Flash, murah) dan deepseek-v4-pro (lebih kuat utk
# alur multi-langkah). Mode thinking aktif secara bawaan dan pesan asisten
# membawa reasoning_content; loop tool sudah mengirim balik pesan itu utuh.
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"

CHAT_SYSTEM_PROMPT = """Anda adalah asisten analisis rute di aplikasi The Next - SiJalan, sebuah alat perencanaan rute \
dan analisis GIS untuk jalan di Indonesia. Jawab dalam Bahasa Indonesia, singkat dan langsung ke inti.
Anda diberi data ringkas tentang rute yang sedang dilihat pengguna (jarak, durasi, wilayah administratif yang \
dilalui, perkiraan klasifikasi jalan dari OpenStreetMap, dan usulan Inpres Jalan/Jembatan di sekitar rute). \
Gunakan data ini untuk menjawab. Bila pengguna bertanya tentang usulan Inpres di luar rute yang sedang dilihat \
(wilayah lain, pencarian umum, atau detail satu usulan tertentu), gunakan fungsi cari_usulan_inpres atau \
detail_usulan_inpres untuk mengambil data terbaru dari database — jangan mengarang data. Saat memanggil \
cari_usulan_inpres berdasarkan nama, JANGAN isi provinsi/kabupaten_kota kecuali pengguna sendiri menyebutkan \
wilayahnya — kalau hasil pencarian nama-saja kosong, katakan usulan tidak ditemukan apa adanya, JANGAN \
menyebutkan provinsi/kabupaten/lokasi tertentu dalam jawaban kecuali itu benar-benar berasal dari hasil \
tool, bukan tebakan Anda sendiri. Bila pengguna bertanya \
soal geometri KML riil suatu usulan (panjang aktual, jumlah segmen, apakah cocok dengan data atribut \
panjang_ruas_km), gunakan fungsi analisa_geometri_kml_usulan. \
Untuk pertanyaan analitis/lintas tabel yang tidak tercakup fungsi-fungsi di atas (data BPS, kawasan tematik, \
agregasi/perbandingan antar wilayah, dsb.), Anda punya akses BACA-SAJA ke SELURUH tabel database lewat fungsi \
jalankan_query_sql (SELECT SQL bebas, hasil lengkap disimpan sbg dataset) — panggil daftar_tabel_database dulu kalau \
belum yakin nama tabel/kolom yang tepat, jangan menebak nama kolom. Hanya query baca yang bisa dijalankan \
(sistem menolak INSERT/UPDATE/DELETE/DDL apa pun bentuknya) — kalau pengguna minta mengubah data, jelaskan \
itu tidak bisa dilakukan lewat chat ini. \
KHUSUS skor IJD/Prioritisasi Teknokratik (parameter A-E): skor ini TIDAK tersimpan di tabel manapun (dihitung \
ulang tiap kali dari rumus berbobot resmi lintas banyak tabel) — WAJIB pakai fungsi hitung_skor_ijd_usulan \
untuk pertanyaan soal skor usulan tertentu, JANGAN coba hitung sendiri lewat jalankan_query_sql, hasilnya \
tidak akan sesuai kaidah resmi. \
Bila pengguna minta MENAMPILKAN/MENYALAKAN layer batas kecamatan/kabupaten/provinsi di peta untuk suatu usulan \
(bukan sekadar bertanya datanya), pakai fungsi tampilkan_layer_batas_administratif_usulan (id usulan + level) — \
fungsi ini otomatis mencari layer yang tepat dari lokasi usulan, JANGAN coba rakit sendiri lewat \
daftar_layer_peta_overlay untuk maksud menampilkan (fungsi itu cuma untuk cari data provinsi/kabupaten/layer \
sebelum analisa_spasial_usulan, bukan untuk menyalakan tampilan). \
Klasifikasi jalan OSM adalah perkiraan, bukan data resmi PUPR.

MODE ANALITIK (untuk permintaan analisis/laporan lintas data):
1. Pahami dulu datanya: panggil daftar_tabel_database (tanpa argumen = katalog tabel + kelompok layer peta) lalu daftar_tabel_database(tabel=...) untuk kolom tabel yang akan dipakai. Jangan menebak nama tabel/kolom.
2. Layer peta tersimpan di tabel map_layers(provinsi, kabupaten, layer, attrs JSONB, geom geometry 4326). "provinsi" di tabel ini adalah KELOMPOK layer (mis. 'KERETA API', 'BASARNAS', 'BANDARA', 'PELABUHAN', 'PETA KORIDOR', 'JALAN NASIONAL', 'KAPASITAS LINTAS KA', atau nama provinsi utk layer RBI per kabupaten); atribut fitur ada di attrs (akses attrs->>'NAMA KOLOM'). Analisis spasial dikerjakan LANGSUNG dengan PostGIS di jalankan_query_sql: jarak meter pakai geom::geography (ST_Distance, ST_DWithin), terdekat pakai ORDER BY a.geom <-> b.geom LIMIT n (LATERAL JOIN), cakupan pakai ST_Intersects/ST_Contains. Sertakan ST_AsGeoJSON(geom) AS geojson (atau kolom lat/lon) SEJAK QUERY PERTAMA bila pengguna menyebut peta/lokasi, supaya dataset yang sama bisa langsung ditampilkan di peta.
3. Setiap jalankan_query_sql menyimpan hasil LENGKAP sebagai dataset (dataset_id) di server; Anda hanya menerima pratinjau. Untuk hasil utama yang disajikan ke pengguna, WAJIB panggil tampilkan_tabel(dataset_id) supaya pengguna bisa melihat & mengunduh (Excel/CSV/GeoJSON). Pakai buat_grafik untuk perbandingan/tren, tampilkan_di_peta untuk hasil berlokasi, dan buat_laporan bila pengguna minta laporan/dokumen Word.
4. Jawaban akhir dalam MARKDOWN: judul singkat (##), ringkasan temuan utama berupa poin, tabel markdown ringkas (maks ~10 baris; tabel lengkap lewat tampilkan_tabel), lalu bagian "Catatan data" berisi keterbatasan/asumsi. Semua angka HARUS berasal dari hasil tool — jangan mengarang.
5. Batas kemampuan saat ini: TIDAK ada data lalu lintas/kemacetan real-time Google Maps dan TIDAK ada mesin rute jalan (rute/alternatif jalan). Bila diminta, katakan terus terang, lalu tawarkan pendekatan dari data yang ADA: jarak garis lurus (PostGIS), VCR/LHR ruas nasional (bps_lhr_ruas_nasional), kondisi IRI (iri_ruas_nasional), utilisasi kapasitas lintas KA (layer 'KAPASITAS LINTAS KA'), wilayah tanggung jawab Kantor SAR (layer 'WILAYAH TANGGUNG JAWAB SAR' di kelompok 'BASARNAS'), koridor terdekat simpul (koridor_simpul_terdekat).
6. Query berat: batasi dengan filter wilayah bila memungkinkan; hasil disimpan maks 20.000 baris.
7. Filter nama wilayah/objek: pakai ILIKE '%kata%', bukan '=' -- penulisan di data beragam (mis. provinsi \
'Provinsi Maluku Utara', kabupaten 'Kab. Halmahera Utara'). Kalau hasil 0 baris, periksa dulu nilai yang ada \
(SELECT DISTINCT kolom ... ILIKE ...) lalu ulangi query -- jangan langsung menyimpulkan data tidak ada.
8. Tabel, grafik, peta, dan tombol unduh dari tool tampil OTOMATIS sebagai kartu di bawah jawaban -- JANGAN \
menulis gambar markdown, tautan, atau URL untuk grafik/peta/unduhan (tautan buatan sendiri pasti rusak).
9. DILARANG KERAS membuat tabel/angka contoh atau placeholder (mis. "Pelabuhan 1", "Lokasi 1", "Jarak 1 km"). \
Kalau data gagal diambil, katakan apa adanya tanpa tabel. Sistem memeriksa isi tabel jawaban terhadap hasil \
tool dan menandai tabel yang isinya tidak ditemukan di data.

PERCAKAPAN & KONTEKS:
- Jawaban Anda sebelumnya di riwayat bisa diakhiri blok <memori>...</memori>, berisi ringkasan langkah yang \
Anda jalankan saat itu (tool, SQL, jumlah baris, beberapa baris hasil). Itu hasil tool ASLI dari giliran itu: \
pakai untuk pertanyaan lanjutan ("yang nomor 3 tadi", "kenapa angkanya begitu", "filter hasil tadi") -- \
lanjutkan dari SQL/hasil itu, jangan mulai dari nol, dan jalankan query baru bila butuh baris di luar \
cuplikan. JANGAN pernah menulis blok <memori> sendiri di jawaban.
- Bila pertanyaan baru jelas berganti topik dari riwayat, jawab topik baru saja; jangan bawa wilayah/filter \
lama kecuali pengguna merujuknya.
- "Konteks aplikasi saat ini" (rute, usulan yang sedang dibuka, layer peta aktif) adalah apa yang sedang \
dilihat pengguna di layar. Pakai bila pertanyaannya merujuk ke sana ("rute ini", "usulan ini", "layer yang \
aktif", "di sini"); abaikan bila pertanyaannya tidak terkait.
"""

CHAT_SEARCH_AVAILABLE_NOTE = (
    " Anda memiliki akses pencarian web untuk pertanyaan yang BENAR-BENAR di luar data aplikasi maupun "
    "database (mis. berita terkini, harga terbaru, cuaca, konteks umum non-infrastruktur) — gunakan "
    "pencarian web untuk itu, dan sebutkan bahwa jawabannya berasal dari hasil pencarian internet, bukan "
    "data resmi aplikasi ini. JANGAN pakai pencarian web untuk hal yang sebenarnya ADA di database (jumlah "
    "penduduk, data BPS, skor IJD, dsb.) — itu jawabannya lewat jalankan_query_sql/hitung_skor_ijd_usulan, "
    "BUKAN web search."
)
CHAT_SEARCH_UNAVAILABLE_NOTE = (
    " Anda TIDAK punya akses pencarian internet saat ini — bila pengguna bertanya hal yang BENAR-BENAR di "
    "luar data aplikasi maupun database (mis. berita terkini, harga terbaru, cuaca, konteks umum non-"
    "infrastruktur), katakan terus terang data itu tidak tersedia, jangan mengarang jawaban. TAPI jangan "
    "buru-buru bilang \"tidak tersedia\" untuk hal yang sebenarnya ADA di database (jumlah penduduk, data "
    "BPS, skor IJD, dsb.) — coba dulu daftar_tabel_database/jalankan_query_sql/hitung_skor_ijd_usulan "
    "sebelum menyimpulkan datanya tidak ada."
)

# Fungsi yang boleh dipanggil model (tool calling gaya OpenAI, dipakai Groq) —
# dibatasi ke query baca-saja lewat helper yang sudah ada (parameterized query,
# tidak ada SQL bebas dari model) supaya tidak ada risiko injeksi atau akses
# tulis ke database.
CHAT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "cari_usulan_inpres",
            "description": (
                "Mencari usulan Inpres Jalan/Jembatan di database berdasarkan provinsi, "
                "kabupaten/kota, dan/atau kata kunci nama ruas/kegiatan/kode ruas. Gunakan "
                "ini untuk pertanyaan di luar rute yang sedang dilihat pengguna. PENTING: "
                "provinsi dan kabupaten_kota HANYA diisi kalau pengguna sendiri menyebutkan "
                "wilayahnya secara eksplisit di pesannya — JANGAN pernah menebak provinsi/"
                "kabupaten dari nama ruas/kegiatan (mis. nama kecamatan di nama ruas tidak "
                "menjamin itu kabupatennya). Semua filter di sini digabung dgn AND, jadi "
                "menebak wilayah yang salah akan membuat usulan yang sebenarnya ada jadi "
                "tidak ketemu. Kalau ragu, panggil HANYA dengan q (kata kunci nama), biarkan "
                "provinsi/kabupaten_kota kosong."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "provinsi": {"type": "string", "description": "Nama provinsi persis, contoh: JAWA BARAT — isi HANYA kalau disebutkan eksplisit oleh pengguna, jangan menebak"},
                    "kabupaten_kota": {"type": "string", "description": "Nama kabupaten/kota (pencocokan sebagian) — isi HANYA kalau disebutkan eksplisit oleh pengguna, jangan menebak"},
                    "q": {"type": "string", "description": "Kata kunci nama ruas, nama kegiatan, atau kode ruas"},
                    "limit": {"type": "integer", "description": "Jumlah maksimum hasil, default 10, maksimum 20"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detail_usulan_inpres",
            "description": "Mengambil detail lengkap satu usulan Inpres Jalan/Jembatan berdasarkan id-nya.",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "integer", "description": "ID usulan"}},
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analisa_geometri_kml_usulan",
            "description": (
                "Menghitung statistik geometri KML riil suatu usulan: panjang aktual hasil "
                "ukur geodesik (bisa berbeda dari field atribut panjang_ruas_km yang diinput "
                "manual), jumlah segmen garis, bounding box, serta titik awal/akhir jalur."
            ),
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "integer", "description": "ID usulan"}},
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "daftar_tabel_database",
            "description": (
                "Melihat skema database: tanpa argumen, mengembalikan KATALOG semua tabel (nama, label "
                "bahasa Indonesia, perkiraan jumlah baris) plus daftar KELOMPOK layer peta di tabel map_layers "
                "(nama kelompok + jumlah layer + contoh nama layer). Dengan argumen 'tabel', mengembalikan daftar "
                "kolom (nama + tipe data) tabel itu; dengan 'kelompok_layer', daftar layer di kelompok itu "
                "beserta contoh kunci attrs-nya. "
                "WAJIB dipanggil dulu (kalau belum tahu nama tabel/kolom yang tepat) sebelum "
                "jalankan_query_sql, supaya query yang disusun memakai nama tabel/kolom yang benar-benar ada."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tabel": {"type": "string", "description": "Nama tabel spesifik (opsional) untuk melihat daftar kolomnya"},
                    "kelompok_layer": {"type": "string", "description": "Nama kelompok layer di map_layers (kolom provinsi), mis. 'BASARNAS' (opsional)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "jalankan_query_sql",
            "description": (
                "Menjalankan SATU query SQL baca-saja (SELECT, boleh dgn CTE/WITH, JOIN, agregasi "
                "GROUP BY/COUNT/SUM/AVG dst.) langsung ke database PostgreSQL — dipakai untuk pertanyaan "
                "analitis lintas tabel yang tidak tercakup fungsi lain (mis. \"berapa total penduduk "
                "kecamatan yang dilintasi usulan provinsi X\", \"kabupaten mana yang kepadatannya "
                "tertinggi\"). Panggil daftar_tabel_database dulu kalau belum yakin nama tabel/kolomnya. "
                "PENTING: skor IJD/Prioritisasi Teknokratik TIDAK tersimpan di tabel manapun (dihitung "
                "on-the-fly dari banyak tabel lewat rumus berbobot) — JANGAN coba menghitungnya sendiri "
                "lewat query, pakai fungsi hitung_skor_ijd_usulan. HANYA SELECT yang diizinkan "
                "(INSERT/UPDATE/DELETE/DDL akan ditolak sistem). Hasil LENGKAP (maks 20.000 baris) disimpan "
                "sebagai dataset dgn dataset_id; Anda menerima pratinjau 40 baris + jumlah baris total. Pakai "
                "dataset_id itu di tampilkan_tabel/buat_grafik/tampilkan_di_peta/buat_laporan."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "Satu statement SQL SELECT (boleh diawali WITH)"},
                    "judul": {"type": "string", "description": "Judul singkat hasil ini (dipakai di tabel/unduhan), mis. 'Pelabuhan & Kantor SAR terdekat'"},
                },
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hitung_skor_ijd_usulan",
            "description": (
                "Menghitung Skor Prioritisasi Teknokratik IJD (parameter A-E sesuai kaidah tahun "
                "berjalan) untuk satu usulan — panjang/detail per parameter, skor tertimbang, dan skor "
                "ternormalisasi 0-100. Skor ini TIDAK tersimpan di database (dihitung ulang tiap kali "
                "lewat rumus resmi), jadi WAJIB pakai fungsi ini, JANGAN coba hitung sendiri lewat "
                "jalankan_query_sql — hasilnya tidak akan sesuai kaidah resmi."
            ),
            "parameters": {
                "type": "object",
                "properties": {
    "id": {"type": "integer", "description": "ID usulan"},
                    "tahun": {"type": "integer", "description": "Tahun kaidah skoring, default 2026 (2025 juga tersedia)"},
                },
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "daftar_layer_peta_overlay",
            "description": (
                "Menjelajahi daftar layer overlay peta yang tersedia (batas kecamatan/kabupaten/provinsi, "
                "jalan nasional/provinsi/tol, bandara/pelabuhan, dst.) — dipakai utk mencari nilai "
                "provinsi/kabupaten/layer yang PERSIS sebelum panggil analisa_spasial_usulan. Tanpa "
                "argumen: daftar bucket/kategori teratas. Isi 'provinsi' saja (jangan isi 'kabupaten' "
                "sama sekali): daftar sub-wilayahnya. Isi 'provinsi' + 'kabupaten' dgn nilai PERSIS dari "
                "langkah sebelumnya (untuk bucket nasional flat spt BANDARA/JALAN NASIONAL/BATAS "
                "PROVINSI, nilai 'kabupaten' persisnya memang string KOSONG \"\" — tetap kirim \"\" "
                "sebagai argumen, JANGAN dihilangkan): daftar layer di dalamnya."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "provinsi": {"type": "string", "description": "Nama bucket/provinsi persis dari hasil panggilan tanpa argumen"},
                    "kabupaten": {"type": "string", "description": "Nama sub-wilayah persis dari hasil panggilan dgn provinsi saja -- boleh string kosong \"\" untuk bucket nasional flat, tapi harus tetap dikirim (jangan dihilangkan) begitu sudah tahu nilainya"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analisa_spasial_usulan",
            "description": (
                "Menganalisa hubungan spasial rute satu usulan terhadap fitur-fitur di satu layer peta "
                "overlay — jarak (km) ke tiap fitur terdekat (maks 10, terurut terdekat dulu) dan apakah "
                "rute berpotongan langsung dgn fitur itu. Contoh pakai: \"seberapa dekat usulan X ke "
                "bandara terdekat\", \"apakah usulan Y melintasi kabupaten Z\". WAJIB panggil "
                "daftar_layer_peta_overlay dulu utk dapat nilai provinsi/kabupaten/layer yang persis — "
                "jangan menebak."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "ID usulan"},
                    "provinsi": {"type": "string", "description": "Nilai 'provinsi' persis dari daftar_layer_peta_overlay"},
                    "kabupaten": {"type": "string", "description": "Nilai 'kabupaten' persis dari daftar_layer_peta_overlay (kosongkan string kalau layer nasional flat)"},
                    "layer": {"type": "string", "description": "Nilai 'layer' persis dari daftar_layer_peta_overlay"},
                },
                "required": ["id", "provinsi", "layer"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tampilkan_usulan_di_peta",
            "description": (
                "Menampilkan rute satu usulan Inpres di peta pada aplikasi ini (menggambar jalurnya & "
                "membuka panel detail atributnya) — pakai ini kalau pengguna secara eksplisit minta "
                "'tunjukkan/tampilkan/bukakan di peta', bukan sekadar bertanya datanya dalam teks."
            ),
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "integer", "description": "ID usulan yang mau ditampilkan"}},
                "required": ["id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tampilkan_layer_batas_administratif_usulan",
            "description": (
                "Menyalakan (menampilkan) layer overlay batas kecamatan/kabupaten/provinsi DI PETA "
                "untuk wilayah tempat satu usulan berada — pakai ini kalau pengguna minta 'tampilkan/"
                "tunjukkan/nyalakan layer kecamatan/kabupaten/provinsi' untuk suatu usulan. Otomatis "
                "mencari layer yang tepat dari lokasi usulan itu sendiri — TIDAK perlu panggil "
                "daftar_layer_peta_overlay dulu untuk kasus ini."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "ID usulan yang jadi acuan wilayah"},
                    "level": {"type": "string", "enum": ["kecamatan", "kabupaten", "provinsi"], "description": "Level batas administratif yang mau ditampilkan"},
                },
                "required": ["id", "level"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analisis_kabupaten",
            "description": (
                "Analisis lengkap SATU kabupaten/kota (deck 20261007 slide 3: 'Analisis Kabupaten X'). Pakai ini "
                "kalau pengguna minta 'analisis/profil/kondisi kabupaten X' atau 'analisa wilayah X'. Satu panggilan "
                "mengembalikan profil wilayah (penduduk, luas, kecamatan), indikator jaringan jalan (kemantapan, "
                "kepadatan, kerapatan + indeks nasional), ringkasan usulan IJD 2026, konektivitas spasial (bandara, "
                "pelabuhan, ruas koridor di dalam wilayah), riwayat Program IJD, dan skor CER AWP-1 -- SEKALIGUS "
                "menyalakan overlay awal di peta (batas kecamatan, jalan nasional, jalan kab/kota, peta koridor, "
                "ruas usulan IJD) dan zoom ke wilayah itu. Tidak perlu daftar_layer_peta_overlay atau SQL dulu. "
                "Susun analisis dari hasilnya; sebut keterbatasan data yang dilaporkan di 'catatan'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nama": {"type": "string", "description": "Nama kabupaten/kota, mis. 'Kabupaten Bandung', 'Kota Bandung', 'Merauke'"},
                    "provinsi": {"type": "string", "description": "Opsional, utk membedakan nama yang sama di provinsi lain"},
                },
                "required": ["nama"],
            },
        },
    },
]

# Tool yang PANGGILANNYA diteruskan MENTAH ke frontend utk dieksekusi di UI,
# BUKAN dijalankan/di-dispatch di server (lihat _run_tool_call) -- lapisan
# pertama fitur "AI bisa bertindak, bukan cuma menjawab" (27 Jul 2026).
CHAT_TOOLS += [
    {
        "type": "function",
        "function": {
            "name": "tampilkan_tabel",
            "description": (
                "Menampilkan dataset hasil jalankan_query_sql sebagai kartu tabel di chat, lengkap dgn tombol "
                "unduh Excel/CSV (dan GeoJSON bila berlokasi). Panggil untuk setiap hasil utama yang disajikan."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "judul": {"type": "string", "description": "Judul kartu tabel"},
                },
                "required": ["dataset_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buat_grafik",
            "description": (
                "Membuat grafik dari dataset (bar/line/pie/scatter) yang tampil di chat. kolom_label = kolom "
                "kategori/sumbu X; kolom_nilai = satu atau beberapa kolom angka. Idealnya dataset sudah "
                "diagregasi & diurutkan (maks ~30 kategori agar terbaca)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "jenis": {"type": "string", "enum": ["bar", "line", "pie", "scatter"]},
                    "kolom_label": {"type": "string"},
                    "kolom_nilai": {"type": "array", "items": {"type": "string"}},
                    "judul": {"type": "string"},
                    "urutan": {"type": "string", "enum": ["desc", "asc", "asli"],
                               "description": "Urutkan menurut kolom_nilai pertama sebelum dipotong (desc = terbesar dulu)"},
                    "maks_kategori": {"type": "integer", "description": "Batas jumlah kategori, mis. 10 utk 'top 10'"},
                },
                "required": ["dataset_id", "jenis", "kolom_label", "kolom_nilai"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tampilkan_di_peta",
            "description": (
                "Menampilkan dataset berlokasi sebagai layer di peta utama aplikasi. Dataset harus punya kolom "
                "GeoJSON (ST_AsGeoJSON(geom)) ATAU kolom lintang/bujur (otomatis dideteksi bila tidak diisi). "
                "kolom_label = kolom nama fitur utk label/popup; kolom_warna = kolom kategori utk pewarnaan (opsional)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "judul": {"type": "string"},
                    "kolom_geometri": {"type": "string"},
                    "kolom_lat": {"type": "string"},
                    "kolom_lon": {"type": "string"},
                    "kolom_label": {"type": "string"},
                    "kolom_warna": {"type": "string"},
                },
                "required": ["dataset_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buat_laporan",
            "description": (
                "Menyusun laporan Word (.docx) siap unduh: isi_markdown = isi laporan dlm markdown (judul, "
                "ringkasan, temuan, tabel markdown, catatan data), dataset_ids = dataset yang dilampirkan "
                "sebagai tabel lampiran. Panggil bila pengguna minta laporan/dokumen/ekspor Word."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "judul": {"type": "string"},
                    "isi_markdown": {"type": "string"},
                    "dataset_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["judul", "isi_markdown"],
            },
        },
    },
]

CLIENT_ACTION_TOOLS = {"tampilkan_usulan_di_peta"}

# Tool "hibrida": TETAP di-dispatch normal lewat CHAT_TOOL_DISPATCH (jalan di
# server dulu -- resolve nama layer yang benar dari lokasi usulan), TAPI
# fungsinya juga menerima param `actions` dan menambahkan aksi klien sendiri
# di akhir (lihat _tool_tampilkan_layer_batas_administratif_usulan) --
# ARGUMEN aksi yang dikirim ke frontend jadi SUDAH pasti valid (provinsi/
# kabupaten/layer persis dari map_layer_meta), bukan ditebak model spt kalau
# modelnya sendiri yang disuruh panggil daftar_layer_peta_overlay dulu.
_TOOLS_NEED_ACTIONS_PARAM = {
    "tampilkan_layer_batas_administratif_usulan", "jalankan_query_sql",
    "tampilkan_tabel", "buat_grafik", "tampilkan_di_peta", "buat_laporan", "analisis_kabupaten",
}

# Pengguna yg sedang chat (dicatat di dataset/laporan). ContextVar, bukan
# global biasa: FastAPI melayani beberapa /api/chat bersamaan di thread berbeda.
_PENGGUNA = contextvars.ContextVar("chat_pengguna", default=None)
# Teks hasil semua tool dlm satu request /api/chat -> dicocokkan dgn isi tabel
# di jawaban akhir (_periksa_tabel_karangan). ContextVar: per request/thread.
_HASIL_TOOL = contextvars.ContextVar("chat_hasil_tool", default=None)
# Role pengguna (app.py ROLE_TANPA_PENILAIAN): akun 'umum' tidak boleh melihat
# hasil penilaian IJD lewat chat -- tool skor ditolak, tabel penilaian diblokir.
_PERAN = contextvars.ContextVar("chat_peran", default=None)
# Jejak satu request /api/chat utk meta jawaban & chat_log (Tahap 1 kajian
# agentic workflow): token, nama tool yg dipanggil, SQL yg dijalankan.
# ContextVar: per request/thread, sama alasannya dgn _HASIL_TOOL.
_JEJAK = contextvars.ContextVar("chat_jejak", default=None)
# Catatan topik terpilih utk request ini (Tahap 4a, _pilih_catatan), disisipkan
# _chat_system_text. Dipilih sekali di _call_chat, dipakai ulang saat revisi.
_CATATAN = contextvars.ContextVar("chat_catatan", default="")

# Tahap 4a kajian agentic workflow: "PETA DATA" (sumber yg benar per topik) dulu
# ditempel utuh di system prompt & terkirim ulang di tiap putaran tool. Kini tiap
# topik satu file chat_pengetahuan/*.md dgn kata_kunci; hanya yg cocok dgn
# pertanyaan yg disisipkan (lihat chat_pengetahuan/README.md).
_DIR_PENGETAHUAN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_pengetahuan")
_MAKS_CATATAN = 3
# Nama catatan yg disisipkan / dibaca model di request ini -> meta & chat_log (Tahap 4b).
_CATATAN_NAMA = contextvars.ContextVar("chat_catatan_nama", default=())


def _muat_pengetahuan() -> list:
    """Hanya file *.md di tingkat atas folder. Draf hasil scripts/belajar_catatan_chat.py
    ada di subfolder _usulan/ (tidak terbaca di sini) dan baru berlaku setelah
    dipindah ke atas oleh manusia; `status:` selain 'aktif' juga dilewati."""
    catatan = []
    if not os.path.isdir(_DIR_PENGETAHUAN):
        return catatan
    for nama in sorted(os.listdir(_DIR_PENGETAHUAN)):
        if not nama.endswith(".md") or nama.lower() == "readme.md":
            continue
        teks = open(os.path.join(_DIR_PENGETAHUAN, nama), encoding="utf-8").read()
        m = re.match(r"---\s*\n(.*?)\n---\s*\n(.*)", teks, re.S)
        if not m:
            continue
        kepala = dict(re.findall(r"^(\w+):\s*(.+)$", m.group(1), re.M))
        if kepala.get("status", "aktif").strip().lower() != "aktif":
            continue
        kunci = [k.strip().lower() for k in kepala.get("kata_kunci", "").strip("[] ").split(",") if k.strip()]
        pola = [re.compile(r"\b" + re.escape(k[:-1]) if k.endswith("*") else r"\b" + re.escape(k) + r"\b") for k in kunci]
        catatan.append({"nama": nama[:-3], "judul": kepala.get("judul", nama[:-3]), "pola": pola,
                        "isi": m.group(2).strip()})
    return catatan


_PENGETAHUAN = _muat_pengetahuan()
_PENGETAHUAN_STEMPEL = None


def _pengetahuan() -> list:
    """Catatan terkini: dimuat ulang bila ada file di folder yg berubah/bertambah,
    supaya catatan yg baru diterima langsung berlaku tanpa restart server."""
    global _PENGETAHUAN, _PENGETAHUAN_STEMPEL
    try:
        stempel = tuple(sorted((e.name, e.stat().st_mtime) for e in os.scandir(_DIR_PENGETAHUAN)
                               if e.is_file() and e.name.endswith(".md")))
    except OSError:
        return _PENGETAHUAN
    if stempel != _PENGETAHUAN_STEMPEL:
        _PENGETAHUAN, _PENGETAHUAN_STEMPEL = _muat_pengetahuan(), stempel
    return _PENGETAHUAN


def _pilih_catatan(pertanyaan_terakhir: str, sebelumnya: str = "") -> str:
    """Catatan topik yg kata kuncinya muncul di pertanyaan (maks _MAKS_CATATAN,
    paling banyak cocok dulu). Pertanyaan sebelumnya ikut dihitung dgn bobot
    kecil supaya tindak lanjut ("buat grafiknya") tetap dapat catatan topiknya.
    Tak ada yg cocok -> hanya daftar judul+nama, supaya model tahu topik apa saja
    yg punya catatan & bisa membacanya sendiri lewat baca_catatan_pengetahuan
    (Tahap 4b: kata kunci tak pernah lengkap, model yg memutuskan)."""
    semua = _pengetahuan()
    baru, lama = (pertanyaan_terakhir or "").lower(), (sebelumnya or "").lower()
    skor = []
    for c in semua:
        s = 2 * sum(1 for p in c["pola"] if p.search(baru)) + sum(1 for p in c["pola"] if p.search(lama))
        if s:
            skor.append((s, c))
    skor.sort(key=lambda x: -x[0])
    pilih = [c for _, c in skor[:_MAKS_CATATAN]]
    _CATATAN_NAMA.set(tuple(c["nama"] for c in pilih))
    if not semua:
        return ""
    daftar = "; ".join(f"{c['judul']} [{c['nama']}]" for c in semua if c not in pilih)
    if not pilih:
        return ("\n\nCATATAN SUMBER DATA tersedia utk topik: " + daftar
                + ". (Tidak disisipkan krn pertanyaan tidak menyebutnya. Bila pertanyaan menyangkut salah satu "
                  "topik itu, panggil baca_catatan_pengetahuan(nama) dulu; selain itu periksa nama tabel/kolom "
                  "lewat daftar_tabel_database sebelum query.)")
    return ("\n\nCATATAN SUMBER DATA (sumber yang benar utk topik pertanyaan ini -- pakai ini, jangan menebak):\n"
            + "\n".join(c["isi"] for c in pilih)
            + (f"\nCatatan topik lain (baca lewat baca_catatan_pengetahuan bila perlu): {daftar}" if daftar else ""))


def _tool_baca_catatan_pengetahuan(nama=None) -> dict:
    """Isi satu catatan chat_pengetahuan/ (nama file tanpa .md, atau judulnya)."""
    semua = _pengetahuan()
    kunci = re.sub(r"\.md$", "", str(nama or "").strip().lower())
    c = next((c for c in semua if kunci in (c["nama"].lower(), c["judul"].lower())), None)
    if c is None:
        return {"error": f"Catatan '{nama}' tidak ada.",
                "catatan_tersedia": [{"nama": x["nama"], "judul": x["judul"]} for x in semua]}
    jejak = _JEJAK.get()
    if jejak is not None and c["nama"] not in jejak["catatan_dibaca"]:
        jejak["catatan_dibaca"].append(c["nama"])
    return {"nama": c["nama"], "judul": c["judul"], "isi": c["isi"]}


def _jejak_baru() -> dict:
    return {"token_masuk": 0, "token_keluar": 0, "tools": [], "sql": [], "hasil": [], "catatan_dibaca": [],
            "langkah": []}


# Memori antar-giliran: dulu model hanya melihat teks jawabannya sendiri di
# riwayat, SQL & hasil tool giliran sebelumnya hilang -> pertanyaan lanjutan
# ("yang nomor 3 tadi") ditebak atau di-query ulang dari nol. Ringkasan ini
# dikirim ke frontend (meta.memori), disimpan pada pesan, lalu ikut dikirim
# balik di riwayat sebagai blok <memori> (lihat chatHistoryPayload di chat.js).
_TOOLS_TANPA_MEMORI = {"daftar_tabel_database", "baca_catatan_pengetahuan", "tampilkan_tabel", "buat_grafik",
                       "tampilkan_di_peta", "buat_laporan", "daftar_layer_peta_overlay"}
_MAKS_MEMORI = 4000
_POLA_MEMORI = re.compile(r"<memori>(.*?)</memori>", re.DOTALL)


def _langkah_ringkas(name: str, args: dict, hasil) -> Optional[str]:
    if name in _TOOLS_TANPA_MEMORI:
        return None
    args = args or {}
    masukan = (" ".join(str(args["sql"]).split())[:800] if args.get("sql")
               else json.dumps(args, ensure_ascii=False, default=str)[:200])
    if not isinstance(hasil, dict):
        keluaran = json.dumps(jsonable_encoder(hasil), ensure_ascii=False, default=str)[:600]
    elif hasil.get("error"):
        keluaran = "galat: " + str(hasil["error"])[:300]
    elif "pratinjau_baris" in hasil:
        n = hasil.get("jumlah_baris")
        ds = f", dataset {hasil['dataset_id']}" if hasil.get("dataset_id") else ""
        cuplik = json.dumps(jsonable_encoder((hasil.get("pratinjau_baris") or [])[:5]), ensure_ascii=False,
                            default=str)[:1200]
        keluaran = f"{n} baris{ds}; 5 baris pertama: {cuplik}"
    else:
        keluaran = json.dumps(jsonable_encoder(hasil), ensure_ascii=False, default=str)[:800]
    return f"- {name}({masukan}) -> {keluaran}"


def _memori_jawaban(jejak: dict) -> str:
    teks = "\n".join(jejak.get("langkah") or [])
    return teks if len(teks) <= _MAKS_MEMORI else teks[:_MAKS_MEMORI] + "\n- …(dipotong)"


def _catat_token(masuk, keluar):
    j = _JEJAK.get()
    if j is not None:
        j["token_masuk"] += int(masuk or 0)
        j["token_keluar"] += int(keluar or 0)
_TOOLS_PENILAIAN = {"hitung_skor_ijd_usulan"}
_TABEL_PENILAIAN = re.compile(r"\bpenilaian_bappenas_ai\b", re.IGNORECASE)


def _tanpa_penilaian() -> bool:
    return _PERAN.get() == "umum"

_USULAN_TOOL_FIELDS = (
    "id", "nama_kegiatan", "nama_ruas", "kabupaten_kota", "provinsi", "jenis_penanganan",
    "panjang_ruas_km", "prioritas", "seleksi_sistem", "alokasi_usulan_pemda", "has_geometry",
)


def _tool_cari_usulan_inpres(provinsi=None, kabupaten_kota=None, q=None, limit=10) -> dict:
    from app import usulan_inpres_list  # lazy: hindari circular import (lihat docstring modul)
    limit = max(1, min(int(limit or 10), 20))
    result = usulan_inpres_list(provinsi=provinsi, kabupaten_kota=kabupaten_kota, q=q, limit=limit, offset=0)
    return {
        "total_ditemukan": result["total"],
        "usulan": [{k: u.get(k) for k in _USULAN_TOOL_FIELDS} for u in result["usulan"]],
    }


def _tool_detail_usulan_inpres(id=None) -> dict:
    from app import usulan_inpres_detail  # lazy: hindari circular import
    if id is None:
        return {"error": "id usulan diperlukan"}
    try:
        return usulan_inpres_detail(int(id))
    except HTTPException as e:
        return {"error": e.detail}


def _tool_hitung_skor_ijd_usulan(id=None, tahun=2026) -> dict:
    # Panggil endpoint yang sudah ada (usulan_inpres_ijd_score -> _compute_ijd_score)
    # langsung, BUKAN direplikasi lewat SQL -- skor berbobot A-E dgn normalisasi
    # bobot_tersedia ini tidak realistis ditulis ulang benar oleh model via query.
    from app import usulan_inpres_ijd_score  # lazy: hindari circular import
    if id is None:
        return {"error": "id usulan diperlukan"}
    try:
        return usulan_inpres_ijd_score(int(id), int(tahun or 2026))
    except HTTPException as e:
        return {"error": e.detail}


def _tool_daftar_layer_peta_overlay(provinsi=None, kabupaten=None) -> dict:
    # Reuse endpoint /api/maps/* yang sudah ada apa adanya (fungsi FastAPI
    # tetap bisa dipanggil langsung sbg fungsi Python biasa, dekorator tidak
    # mengubah calling convention-nya) -- BUKAN query map_layers manual di sini,
    # supaya konsisten dgn hierarki yang sama dipakai UI topbar "Overlay Peta".
    from app import maps_provinces, maps_kabupaten, maps_layers  # lazy: hindari circular import
    if not provinsi:
        return {"provinsi_atau_kategori": maps_provinces()}
    # "kabupaten" is None (kosong dari model = belum dipilih) BEDA dgn ""
    # (nilai VALID utk bucket nasional flat spt BANDARA/JALAN NASIONAL/BATAS
    # PROVINSI, lihat maps_kabupaten() di app.py) -- pakai `is None`, BUKAN
    # falsy check, supaya kabupaten="" yg disalin model dari hasil panggilan
    # sebelumnya benar2 lanjut ke daftar layer, bukan diam2 tersangkut
    # mengulang daftar sub-wilayah (bug ditemukan 27 Jul 2026 lewat tes
    # pertanyaan "bandara terdekat" yg gagal nemu layer BANDARA).
    if kabupaten is None:
        try:
            return {"kabupaten_atau_sub_wilayah": maps_kabupaten(provinsi)}
        except HTTPException as e:
            return {"error": e.detail}
    try:
        return {"layer": maps_layers(provinsi, kabupaten)}
    except HTTPException as e:
        return {"error": e.detail}


def _tool_analisa_spasial_usulan(id=None, provinsi=None, layer=None, kabupaten="") -> dict:
    if id is None or not provinsi or not layer:
        return {"error": "id usulan, provinsi, dan layer diperlukan -- panggil daftar_layer_peta_overlay dulu utk nilai yg persis"}
    with db_cursor() as cur:
        cur.execute("SELECT geom_geojson FROM usulan_inpres WHERE id=%s", (int(id),))
        row = cur.fetchone()
        if not row:
            return {"error": "usulan tidak ditemukan"}
        if not row["geom_geojson"]:
            return {"error": "usulan ini belum punya data geometri rute (geom_geojson kosong)"}
        try:
            # Cross join thd 1 baris target: ST_GeomFromGeoJSON dihitung SEKALI,
            # bukan per-baris map_layers -- geometri usulan tetap teks JSON di
            # kolom sumbernya (lihat CLAUDE.md), di-cast murni di sisi SQL
            # (ST_GeomFromGeoJSON), tidak lewat shapely Python sama sekali jadi
            # tidak kena bug shapely/numpy yang didokumentasikan di tempat lain.
            # "geom <-> target" (KNN operator) memakai idx_map_layers_geom
            # supaya tidak full-scan layer besar.
            cur.execute(
                """
                SELECT ml.attrs AS attrs,
                       ST_Distance(ml.geom::geography, t.target::geography) AS jarak_m,
                       ST_Intersects(ml.geom, t.target) AS berpotongan
                FROM map_layers ml,
                     (SELECT ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326) AS target) t
                WHERE ml.provinsi = %s AND ml.kabupaten = %s AND ml.layer = %s
                ORDER BY ml.geom <-> t.target
                LIMIT 10
                """,
                (row["geom_geojson"], provinsi, kabupaten, layer),
            )
            hits = cur.fetchall()
        except Exception as e:
            return {"error": f"Gagal analisa spasial (cek nama provinsi/kabupaten/layer via daftar_layer_peta_overlay): {e}"}
    if not hits:
        return {"error": "Tidak ada fitur di layer itu (cek nama provinsi/kabupaten/layer)"}
    return {
        "fitur_terdekat": [
            {
                "jarak_km": round(h["jarak_m"] / 1000, 3),
                "berpotongan_dengan_rute": bool(h["berpotongan"]),
                **jsonable_encoder(h["attrs"] or {}),
            }
            for h in hits
        ],
    }


_LEVEL_KE_BUCKET_LAYER = {
    "kecamatan": "BATAS KECAMATAN",
    "kabupaten": "BATAS KABUPATEN",
    "provinsi": "BATAS PROVINSI",
}


def _tool_tampilkan_layer_batas_administratif_usulan(id=None, level=None, actions=None) -> dict:
    """Resolve (provinsi, kabupaten, layer) map_layers YANG BENAR dari lokasi
    usulan itu sendiri -- lihat _TOOLS_NEED_ACTIONS_PARAM di atas kenapa ini
    tidak sesederhana CLIENT_ACTION_TOOLS biasa (model tidak disuruh menebak
    nama layer, ditemukan lewat query ILIKE ke map_layer_meta)."""
    bucket = _LEVEL_KE_BUCKET_LAYER.get(str(level or "").strip().lower())
    if id is None or bucket is None:
        return {"error": "id usulan dan level (kecamatan/kabupaten/provinsi) diperlukan"}

    with db_cursor() as cur:
        cur.execute("SELECT provinsi, kabupaten_kota FROM usulan_inpres WHERE id=%s", (int(id),))
        row = cur.fetchone()
        if not row:
            return {"error": "usulan tidak ditemukan"}

        if bucket == "BATAS PROVINSI":
            # bucket nasional flat, satu layer -- tidak perlu resolve apa pun.
            layer_provinsi, layer_kabupaten, layer_layer = bucket, "", "Provinsi"
        else:
            # kolom "kabupaten" di bucket ini = PROVINSI ASLI (lihat catatan
            # arsitektur di CLAUDE.md) -- cocokkan ke provinsi usulan.
            cur.execute(
                "SELECT DISTINCT kabupaten FROM map_layer_meta WHERE provinsi=%s AND kabupaten ILIKE %s LIMIT 1",
                (bucket, row["provinsi"]),
            )
            prov_row = cur.fetchone()
            if not prov_row:
                return {"error": f"Tidak ada layer {bucket} untuk provinsi '{row['provinsi']}'"}
            layer_provinsi, layer_kabupaten = bucket, prov_row["kabupaten"]

            if bucket == "BATAS KABUPATEN":
                # satu layer tunggal per provinsi ("Kabupaten/Kota"), tidak perlu cocokkan lebih lanjut.
                cur.execute(
                    "SELECT layer FROM map_layer_meta WHERE provinsi=%s AND kabupaten=%s LIMIT 1",
                    (bucket, layer_kabupaten),
                )
                layer_layer = cur.fetchone()["layer"]
            else:  # BATAS KECAMATAN: "layer" = nama kabupaten/kota usulan, cocokkan longgar
                nama_kabkota = re.sub(r"^(KABUPATEN|KOTA)\s+", "", str(row["kabupaten_kota"] or "").strip(), flags=re.IGNORECASE)
                cur.execute(
                    "SELECT layer FROM map_layer_meta WHERE provinsi=%s AND kabupaten=%s AND layer ILIKE %s LIMIT 1",
                    (bucket, layer_kabupaten, f"%{nama_kabkota}%"),
                )
                kab_row = cur.fetchone()
                if not kab_row:
                    return {"error": f"Tidak ada layer kecamatan yang cocok untuk '{row['kabupaten_kota']}'"}
                layer_layer = kab_row["layer"]

    if actions is not None:
        actions.append({
            "nama": "tampilkan_layer_peta_overlay",
            "argumen": {"provinsi": layer_provinsi, "kabupaten": layer_kabupaten, "layer": layer_layer},
        })
    return {"status": "diteruskan_ke_frontend_untuk_dieksekusi", "layer_ditemukan": layer_layer}


def _tool_analisa_geometri_kml_usulan(id=None) -> dict:
    from app import _fetch_usulan_geometry  # lazy: hindari circular import
    if id is None:
        return {"error": "id usulan diperlukan"}
    try:
        geojson = _fetch_usulan_geometry(int(id))
    except HTTPException as e:
        return {"error": e.detail}

    segments = geojson["coordinates"] if geojson["type"] == "MultiLineString" else [geojson["coordinates"]]

    total_m = 0.0
    all_lngs, all_lats = [], []
    for seg in segments:
        lngs = [pt[0] for pt in seg]
        lats = [pt[1] for pt in seg]
        total_m += _GEOD.line_length(lngs, lats)
        all_lngs.extend(lngs)
        all_lats.extend(lats)

    start, end = segments[0][0], segments[-1][-1]
    return {
        "jumlah_segmen": len(segments),
        "panjang_kml_km": round(total_m / 1000, 3),
        "bounding_box": {
            "min_lat": min(all_lats), "max_lat": max(all_lats),
            "min_lng": min(all_lngs), "max_lng": max(all_lngs),
        },
        "titik_awal": {"lat": start[1], "lng": start[0]},
        "titik_akhir": {"lat": end[1], "lng": end[0]},
    }


# --- Akses SQL baca-saja lintas SEMUA tabel (permintaan user 27 Jul 2026,
# menggantikan batasan lama "tidak ada SQL bebas dari model" -- lihat
# docs/ARCHITECTURE.md kalau butuh riwayat keputusan sebelumnya). Dua lapis
# pertahanan, BUKAN cuma satu:
#   1. Validasi teks (_validasi_sql_readonly): tolak lebih dari satu
#      statement, tolak apa pun yang bukan diawali SELECT/WITH, tolak kata
#      kunci tulis/DDL eksplisit.
#   2. BACKSTOP SESUNGGUHNYA -- "SET TRANSACTION READ ONLY" di level
#      PostgreSQL sebelum query dijalankan: menolak SEMUA statement tulis di
#      dalam transaksi itu APA PUN bentuknya, termasuk trik yang lolos dari
#      pass (1) spt CTE data-modifying ("WITH x AS (DELETE FROM t RETURNING
#      *) SELECT * FROM x" -- valid dimulai dgn WITH, tanpa kata kunci
#      terlarang di awal karena DELETE ada di tengah tapi TETAP tertangkap
#      regex _SQL_KEYWORD_TERLARANG; walau begitu READ ONLY transaction
#      adalah jaring pengaman yang independen dari kelengkapan regex).
_SQL_PRATINJAU = 40          # baris yg dikirim ke model; hasil lengkap disimpan sbg dataset
_SQL_TIMEOUT_MS = 25000
_SQL_KEYWORD_TERLARANG = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|COPY|CALL|VACUUM|REINDEX|MERGE|EXECUTE)\b",
    re.IGNORECASE,
)


def _validasi_sql_readonly(sql: str) -> Optional[str]:
    s = (sql or "").strip()
    if not s:
        return "Query kosong."
    inti = s[:-1].strip() if s.endswith(";") else s
    if ";" in inti:
        return "Hanya satu statement SQL per panggilan (tidak boleh ada titik koma di tengah)."
    if not re.match(r"(?is)^\s*(SELECT|WITH)\b", inti):
        return "Hanya SELECT (atau WITH ... SELECT) yang diizinkan."
    if _SQL_KEYWORD_TERLARANG.search(inti):
        return "Kata kunci yang tidak diizinkan terdeteksi (hanya query baca yang boleh)."
    return None


def _tool_daftar_tabel_database(tabel=None, kelompok_layer=None) -> dict:
    with db_cursor() as cur:
        if kelompok_layer:
            cur.execute(
                "SELECT m.kabupaten, m.layer, m.feature_count, "
                "  (SELECT array_agg(k) FROM jsonb_object_keys((SELECT x.attrs FROM map_layers x "
                "   WHERE x.provinsi = m.provinsi AND x.kabupaten = m.kabupaten AND x.layer = m.layer LIMIT 1)) k) AS contoh_attrs "
                "FROM map_layer_meta m WHERE m.provinsi = %s ORDER BY m.kabupaten, m.layer LIMIT 80",
                (kelompok_layer,),
            )
            rows = cur.fetchall()
            if not rows:
                return {"error": f"Kelompok layer '{kelompok_layer}' tidak ada (lihat daftar_tabel_database tanpa argumen)"}
            return {"kelompok_layer": kelompok_layer, "layer": [jsonable_encoder(dict(r)) for r in rows],
                    "cara_query": "SELECT attrs->>'<kunci>', geom FROM map_layers WHERE provinsi=%s AND layer=... (kabupaten='' utk kelompok nasional)"}
        if tabel:
            cur.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
                (tabel,),
            )
            kolom = cur.fetchall()
            if not kolom:
                return {"error": f"Tabel '{tabel}' tidak ditemukan (cek ejaan lewat daftar_tabel_database tanpa argumen)"}
            return {"tabel": tabel, "kolom": [{"nama": c["column_name"], "tipe": c["data_type"]} for c in kolom]}
        from app import DATA_TABLES  # lazy: hindari circular import (label bahasa Indonesia menu "Data")
        cur.execute(
            "SELECT t.table_name, COALESCE(s.n_live_tup, 0) AS perkiraan_baris "
            "FROM information_schema.tables t LEFT JOIN pg_stat_user_tables s "
            "  ON s.relname = t.table_name AND s.schemaname = 'public' "
            "WHERE t.table_schema='public' AND t.table_type='BASE TABLE' "
            "  AND t.table_name NOT IN ('users', 'psc119_layanan', 'chat_log') ORDER BY t.table_name"
        )
        tabel_list = [{"nama": r["table_name"], "label": DATA_TABLES.get(r["table_name"], ""),
                       "perkiraan_baris": r["perkiraan_baris"]} for r in cur.fetchall()]
        cur.execute(
            "SELECT provinsi AS kelompok, count(*) AS jumlah_layer, sum(feature_count) AS jumlah_fitur, "
            "  (array_agg(DISTINCT layer))[1:6] AS contoh_layer "
            "FROM map_layer_meta GROUP BY provinsi ORDER BY provinsi"
        )
        kelompok = [jsonable_encoder(dict(r)) for r in cur.fetchall()]
        return {"tabel": tabel_list, "kelompok_layer_peta": kelompok,
                "catatan": "Kelompok bernama provinsi = layer RBI per kabupaten; lainnya kelompok tematik nasional. "
                           "Detail layer & kunci attrs: daftar_tabel_database(kelompok_layer=...)."}


_SQL_TABEL_TERLARANG = re.compile(r"\b(users|psc119_layanan|chat_log)\b", re.IGNORECASE)


def _tool_jalankan_query_sql(sql=None, judul=None, actions=None) -> dict:
    error = _validasi_sql_readonly(sql or "")
    if error:
        return {"error": error}
    if _SQL_TABEL_TERLARANG.search(sql):
        return {"error": "Tabel akun pengguna, log chat, dan data pribadi layanan PSC119 tidak boleh diakses lewat chat."}
    if _tanpa_penilaian() and _TABEL_PENILAIAN.search(sql):
        return {"error": "Akun umum tidak memiliki akses ke hasil penilaian IJD (tabel penilaian_bappenas_ai)."}
    inti = sql.strip().rstrip(";")
    try:
        with db_cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute(f"SET LOCAL statement_timeout = {_SQL_TIMEOUT_MS}")
            cur.execute(inti)
            if cur.description is None:
                return {"error": "Query tidak mengembalikan baris (bukan SELECT?)"}
            columns = [d.name for d in cur.description]
            rows = cur.fetchmany(chat_dataset.MAKS_BARIS + 1)
    except Exception as e:
        return {"error": f"Query gagal: {e}"}
    terpotong = len(rows) > chat_dataset.MAKS_BARIS
    rows = [[r[c] for c in columns] for r in rows[: chat_dataset.MAKS_BARIS]]
    judul = (judul or "").strip() or "Hasil query"
    ds_id = chat_dataset.simpan(columns, rows, judul=judul, sql=inti, pengguna=_PENGGUNA.get(), terpotong=terpotong)
    geo = chat_dataset.deteksi_geometri({"columns": columns, "rows": jsonable_encoder(rows[:20])})
    if actions is not None:
        actions.append({"nama": "dataset_tersedia", "argumen": {
            "dataset_id": ds_id, "judul": judul, "jumlah_baris": len(rows), "kolom": columns, "sql": inti}})
    pratinjau = []
    for r in rows[:_SQL_PRATINJAU]:
        baris = {}
        for c, v in zip(columns, r):
            if isinstance(v, str) and len(v) > 300:
                v = v[:300] + "…(dipotong)"
            baris[c] = v
        pratinjau.append(jsonable_encoder(baris))
    return {
        "dataset_id": ds_id,
        "judul": judul,
        "columns": columns,
        "jumlah_baris": len(rows),
        "terpotong_di_20000": terpotong,
        # Terbukti di staging 28 Sep 2026: tanpa ini model menyimpulkan "jarak maks 103 km" dari
        # 40 baris pratinjau, padahal maks seluruh data 360 km.
        "statistik_seluruh_baris": _statistik_kolom(columns, rows),
        "catatan_pratinjau": (f"pratinjau_baris hanya {len(pratinjau)} baris PERTAMA dari {len(rows)}. Untuk "
                              "ringkasan (min/maks/rata-rata/jumlah/terbesar) WAJIB pakai statistik_seluruh_baris "
                              "atau query agregat/ORDER BY, bukan pratinjau." if len(rows) > len(pratinjau) else None),
        "pratinjau_baris": pratinjau,
        "berlokasi": bool(geo["kolom_geometri"] or geo["kolom_lat"]),
        **({"petunjuk": "0 baris. Kemungkinan filter terlalu ketat/penulisan beda: pakai ILIKE '%...%' dan cek "
                        "nilai yg ada via SELECT DISTINCT <kolom> ... sebelum menyimpulkan data tidak ada."}
           if not rows else {}),
    }


def _statistik_kolom(columns, rows) -> dict:
    """min/maks/rata-rata/jumlah kolom angka (+ baris min & maks) dan jumlah nilai unik kolom teks,
    dihitung dari SELURUH baris dataset."""
    out = {}
    for i, c in enumerate(columns):
        vals = [r[i] for r in rows if r[i] is not None]
        angka = []
        for v in vals:
            if isinstance(v, bool):
                continue
            try:
                angka.append(float(v)) if isinstance(v, (int, float)) or type(v).__name__ == "Decimal" else None
            except (TypeError, ValueError):
                pass
        if angka and len(angka) >= len(vals) * 0.8:
            j_min = min(range(len(rows)), key=lambda k: float(rows[k][i]) if isinstance(rows[k][i], (int, float)) or type(rows[k][i]).__name__ == "Decimal" else float("inf"))
            j_max = max(range(len(rows)), key=lambda k: float(rows[k][i]) if isinstance(rows[k][i], (int, float)) or type(rows[k][i]).__name__ == "Decimal" else float("-inf"))
            label = next((columns[t] for t in range(len(columns)) if isinstance(rows[0][t], str)), None) if rows else None
            out[c] = {"min": min(angka), "maks": max(angka), "rata_rata": round(sum(angka) / len(angka), 4),
                      "jumlah": round(sum(angka), 4), "terisi": len(angka)}
            if label:
                out[c]["baris_min"] = rows[j_min][columns.index(label)]
                out[c]["baris_maks"] = rows[j_max][columns.index(label)]
        elif vals and all(isinstance(v, str) for v in vals[:50]) and not any(v.lstrip().startswith("{") for v in vals[:5]):
            out[c] = {"nilai_unik": len(set(vals)), "terisi": len(vals)}
    return jsonable_encoder(out)


def _dataset_atau_error(dataset_id):
    ds = chat_dataset.muat(dataset_id or "")
    if not ds:
        return None, {"error": f"dataset_id '{dataset_id}' tidak ditemukan -- jalankan jalankan_query_sql dulu"}
    return ds, None


def _tool_tampilkan_tabel(dataset_id=None, judul=None, actions=None) -> dict:
    ds, err = _dataset_atau_error(dataset_id)
    if err:
        return err
    geo = chat_dataset.deteksi_geometri(ds)
    actions.append({"nama": "tampilkan_tabel", "argumen": {
        "dataset_id": ds["id"], "judul": judul or ds["judul"], "jumlah_baris": len(ds["rows"]),
        "berlokasi": bool(geo["kolom_geometri"] or geo["kolom_lat"])}})
    return {"status": "tabel ditampilkan di chat dengan tombol unduh", **chat_dataset.ringkas(ds)}


def _tool_buat_grafik(dataset_id=None, jenis="bar", kolom_label=None, kolom_nilai=None, judul=None,
                      urutan="asli", maks_kategori=None, actions=None) -> dict:
    ds, err = _dataset_atau_error(dataset_id)
    if err:
        return err
    kolom_nilai = [kolom_nilai] if isinstance(kolom_nilai, str) else list(kolom_nilai or [])
    hilang = [k for k in [kolom_label, *kolom_nilai] if k not in ds["columns"]]
    if hilang or not kolom_nilai:
        return {"error": f"Kolom tidak ada di dataset: {hilang or 'kolom_nilai kosong'}. Kolom tersedia: {ds['columns']}"}
    idx = [ds["columns"].index(k) for k in kolom_nilai]
    for i, k in zip(idx, kolom_nilai):
        if not any(isinstance(r[i], (int, float)) for r in ds["rows"][:50]):
            return {"error": f"Kolom '{k}' bukan angka -- cast di SQL (mis. ::numeric) atau pilih kolom lain"}
    actions.append({"nama": "buat_grafik", "argumen": {
        "dataset_id": ds["id"], "jenis": jenis if jenis in ("bar", "line", "pie", "scatter") else "bar",
        "kolom_label": kolom_label, "kolom_nilai": kolom_nilai, "judul": judul or ds["judul"],
        "urutan": urutan if urutan in ("desc", "asc") else "asli",
        "maks_kategori": max(1, min(int(maks_kategori), 500)) if maks_kategori else None}})
    n = min(len(ds["rows"]), int(maks_kategori)) if maks_kategori else len(ds["rows"])
    return {"status": "grafik ditampilkan di chat", "jumlah_titik": n}


def _tool_tampilkan_di_peta(dataset_id=None, judul=None, kolom_geometri=None, kolom_lat=None, kolom_lon=None,
                            kolom_label=None, kolom_warna=None, actions=None) -> dict:
    ds, err = _dataset_atau_error(dataset_id)
    if err:
        return err
    # model kadang mengisi ekspresi SQL (mis. "ST_SetSRID(...)") alih-alih nama kolom -> abaikan
    kolom_geometri, kolom_lat, kolom_lon = (k if k in ds["columns"] else None for k in (kolom_geometri, kolom_lat, kolom_lon))
    fc = chat_dataset.ke_geojson(ds, kolom_geometri, kolom_lat, kolom_lon)
    if not fc["features"]:
        return {"error": ("Dataset ini tidak punya kolom lokasi. LANGKAH BERIKUTNYA: jalankan ulang jalankan_query_sql "
                          "dengan menambahkan kolom lat & lon (atau ST_AsGeoJSON(geom) AS geojson), lalu panggil "
                          "tampilkan_di_peta LAGI dgn dataset_id yang baru. Kolom sekarang: " + ", ".join(ds["columns"]))}
    for k in (kolom_label, kolom_warna):
        if k and k not in ds["columns"]:
            return {"error": f"Kolom '{k}' tidak ada. Kolom tersedia: {ds['columns']}"}
    actions.append({"nama": "tampilkan_di_peta", "argumen": {
        "dataset_id": ds["id"], "judul": judul or ds["judul"], "kolom_geometri": fc["kolom_geometri"],
        "kolom_lat": fc["kolom_lat"], "kolom_lon": fc["kolom_lon"], "kolom_label": kolom_label,
        "kolom_warna": kolom_warna, "jumlah_fitur": len(fc["features"])}})
    return {"status": "ditampilkan di peta", "jumlah_fitur": len(fc["features"])}


def _tool_buat_laporan(judul=None, isi_markdown=None, dataset_ids=None, actions=None) -> dict:
    ids = [dataset_ids] if isinstance(dataset_ids, str) else list(dataset_ids or [])
    try:
        hasil = chat_dataset.buat_laporan_docx(judul or "Laporan Analisis", isi_markdown or "", ids, _PENGGUNA.get())
    except Exception as e:
        return {"error": f"Gagal menyusun laporan: {e}"}
    actions.append({"nama": "unduh_laporan", "argumen": {**hasil, "judul": judul}})
    return {"status": "laporan Word siap diunduh dari chat", **hasil}


def _kunci_nama(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _tool_analisis_kabupaten(nama=None, provinsi=None, actions=None) -> dict:
    """Profil + overlay awal satu kab/kota. Semua angka dari tabel/fungsi yang sudah
    tervalidasi di aplikasi (kemantapan_ijd_2026, _program_indikator_jalan,
    usulan_inpres, NPR benchmark, cer_awp1_koridor, map_layers); model hanya
    menarasikan. Bagian penilaian (NPR, CER) disembunyikan utk akun umum."""
    import app  # lazy: hindari circular import
    from wilayah_cocok import PencocokKabupaten  # scripts/ sudah di sys.path oleh app.py

    if not nama:
        return {"error": "nama kabupaten/kota diperlukan"}
    catatan = []
    with db_cursor() as cur:
        cur.execute("SELECT DISTINCT kode_provinsi, provinsi, kode_kabupaten, kabupaten_kota FROM penduduk_kecamatan")
        master = cur.fetchall()
        m = PencocokKabupaten(master).cari(provinsi, nama)
        if not m:
            kandidat = [r["kabupaten_kota"] for r in master if _kunci_nama(nama).replace("kabupaten", "").replace("kota", "")
                        in _kunci_nama(r["kabupaten_kota"])][:8]
            return {"error": f"Kab/kota '{nama}' tidak ditemukan atau ambigu.", "kandidat": kandidat}
        kode_kab, kode_prov = int(m["kode_kabupaten"]), int(m["kode_provinsi"])
        jenis = "Kota" if kode_kab % 100 >= 71 else "Kabupaten"
        nama_kab = re.sub(r"^(KABUPATEN|KOTA)\s+", "", str(m["kabupaten_kota"]).strip(), flags=re.I).title()
        label = f"{jenis} {nama_kab}"
        nama_prov = str(m["provinsi"]).strip()
        tanpa_jenis = not re.search(r"(?i)\b(kab\.?|kabupaten|kota)\b", str(nama))
        kembar_kota = any(int(r["kode_kabupaten"]) % 100 >= 71 and int(r["kode_kabupaten"]) != kode_kab
                          and _kunci_nama(re.sub(r"(?i)^(kota|kabupaten)\s+", "", r["kabupaten_kota"])) == _kunci_nama(nama_kab)
                          for r in master)
        if tanpa_jenis and jenis == "Kabupaten" and kembar_kota:
            catatan.append(f"'{nama}' dibaca sbg {label}; ada juga Kota {nama_kab} -- sebut 'Kota {nama_kab}' bila itu yang dimaksud.")

        # Profil wilayah
        cur.execute("SELECT count(*) AS kec, SUM(jumlah_penduduk) AS pend FROM penduduk_kecamatan WHERE kode_kabupaten=%s", (kode_kab,))
        p = cur.fetchone()
        cur.execute("""SELECT SUM(ST_Area(geom::geography)) / 1e6 AS luas,
                              ST_XMin(ST_Extent(geom)) x1, ST_YMin(ST_Extent(geom)) y1, ST_XMax(ST_Extent(geom)) x2, ST_YMax(ST_Extent(geom)) y2
                       FROM map_layers WHERE provinsi='BATAS KABUPATEN' AND attrs->>'KODE_KABUPATEN' = %s""", (str(kode_kab),))
        g = cur.fetchone()
        ind = app._program_indikator_jalan(cur)
        ij, nas = ind["kab"].get(kode_kab, {}), ind["nasional"]
        jaringan = {k: ij.get(k) for k in ("panjang_jalan_km", "kemantapan_pct", "kepadatan_jalan", "kerapatan_jalan")}
        for k in ("kemantapan_pct", "kepadatan_jalan", "kerapatan_jalan"):
            jaringan[f"indeks_{k}"] = round(ij[k] / nas[k], 2) if ij.get(k) is not None and nas.get(k) else None
        jaringan["nasional"] = nas
        jaringan["sumber"] = "jalan daerah kab/kota, data kemantapan IJD 2026; indeks = nilai ÷ nasional"

        # Usulan IJD 2026
        cur.execute("""SELECT count(*) n, count(*) FILTER (WHERE seleksi_sistem='LULUS') lulus,
                              round(SUM(panjang_penanganan_pemda)::numeric, 1) km, SUM(alokasi_usulan_pemda) rp
                       FROM usulan_inpres WHERE kode_kabupaten=%s""", (kode_kab,))
        u = cur.fetchone()
        cur.execute("SELECT jenis_penanganan j, count(*) n FROM usulan_inpres WHERE kode_kabupaten=%s GROUP BY 1 ORDER BY 2 DESC", (kode_kab,))
        usulan = {"jumlah": u["n"], "lulus_seleksi_sistem": u["lulus"], "panjang_penanganan_km": float(u["km"] or 0),
                  "alokasi_usulan_pemda_rp": int(u["rp"] or 0), "per_jenis": {r["j"]: r["n"] for r in cur.fetchall()}}
        if u["n"] and not _tanpa_penilaian():
            cur.execute("SELECT * FROM usulan_inpres WHERE kode_kabupaten=%s LIMIT 1", (kode_kab,))
            bm = app._npr_benchmark_kabupaten(cur.fetchone(), None)
            usulan["npr_weighted_average_kabupaten"] = bm["npr_wa"]
            usulan["npr_rata_rata"] = bm["npr_rata_rata"]

        # Konektivitas spasial: simpul & koridor di dalam poligon kab/kota
        cur.execute("""WITH k AS (SELECT ST_Union(geom) g FROM map_layers WHERE provinsi='BATAS KABUPATEN' AND attrs->>'KODE_KABUPATEN'=%s)
                       SELECT m.provinsi, m.layer, count(*) n FROM map_layers m, k
                       WHERE ((m.provinsi='BANDARA' AND m.layer='Bandara') OR (m.provinsi='PELABUHAN' AND m.layer='Pelabuhan Nasional')
                              OR m.layer='PETA KORIDOR' OR (m.provinsi='JALAN NASIONAL' AND m.layer='Jalan Nasional')
                              OR (m.provinsi='JALAN TOL' AND m.layer LIKE 'Rencana Umum%%'))
                         AND m.geom && k.g AND ST_Intersects(m.geom, k.g)
                       GROUP BY 1, 2""", (str(kode_kab),))
        sp = {f"{r['provinsi']} / {r['layer']}": r["n"] for r in cur.fetchall()}
        konektivitas = {"bandara": sp.get("BANDARA / Bandara", 0), "pelabuhan_nasional": sp.get("PELABUHAN / Pelabuhan Nasional", 0),
                        "ruas_jalan_nasional": sp.get("JALAN NASIONAL / Jalan Nasional", 0),
                        "ruas_tol_rencana_umum": sp.get("JALAN TOL / Rencana Umum Jalan Tol (JBH 2023)", 0),
                        "ruas_peta_koridor": sum(v for k, v in sp.items() if k.endswith("/ PETA KORIDOR")),
                        "metode": "fitur yang beririsan dgn poligon batas kab/kota"}

        # Riwayat Program IJD & CER AWP-1
        cur.execute("SELECT count(*) n, round(SUM(alokasi_rp)/1e9, 1) m, round(SUM(panjang_jalan_km)::numeric, 1) km FROM program_ijd_riwayat WHERE kode_kabupaten=%s", (kode_kab,))
        pr = cur.fetchone()
        program = {"kegiatan_2023_2026": pr["n"], "alokasi_rp_miliar": float(pr["m"] or 0), "panjang_jalan_km": float(pr["km"] or 0)}
        cer = None
        if not _tanpa_penilaian():
            cur.execute("SELECT to_regclass('public.cer_awp1_koridor') t")
            if cur.fetchone()["t"]:
                cur.execute("""SELECT no_koridor, nama_koridor, round(cer_score::numeric, 2) cer, peringkat_cer,
                                      round(tot_score::numeric, 3) tot FROM cer_awp1_koridor
                               WHERE kode_kabupaten=%s ORDER BY cer_score DESC LIMIT 5""", (kode_kab,))
                top = [dict(r) for r in cur.fetchall()]
                cur.execute("SELECT count(*) n FROM cer_awp1_koridor WHERE kode_kabupaten=%s", (kode_kab,))
                cer = {"jumlah_koridor": cur.fetchone()["n"], "teratas_menurut_cer": top,
                       "catatan": "model eksperimental AWP-1, CER = manfaat ÷ biaya relatif; terpisah dari skor IJD"}

        # Overlay awal: nama layer persis dari map_layer_meta (tidak ditebak model)
        lapis = []
        cur.execute("""SELECT provinsi, kabupaten, layer FROM map_layer_meta
                       WHERE provinsi='BATAS KECAMATAN' AND lower(kabupaten)=lower(%s) AND lower(layer)=lower(%s)""", (nama_prov, label))
        lapis += cur.fetchall()
        cur.execute("""SELECT provinsi, kabupaten, layer FROM map_layer_meta
                       WHERE lower(provinsi)=lower(%s) AND lower(kabupaten)=lower(%s)
                         AND (layer ~* '^jalan' OR layer = 'PETA KORIDOR') ORDER BY layer = 'PETA KORIDOR', layer LIMIT 3""",
                    (nama_prov, label))
        lapis += cur.fetchall()
        cur.execute("SELECT 1 FROM map_layer_meta WHERE provinsi='JALAN NASIONAL' AND kabupaten='' AND layer='Jalan Nasional'")
        if cur.fetchone():
            lapis.append({"provinsi": "JALAN NASIONAL", "kabupaten": nama_prov.title().replace("Dki", "DKI").replace("Di ", "DI "),
                          "layer": "Jalan Nasional"})
    if not any(l["provinsi"] == "BATAS KECAMATAN" for l in lapis):
        catatan.append("Layer batas kecamatan utk wilayah ini tidak ditemukan.")
    if actions is not None:
        for l in lapis:
            actions.append({"nama": "tampilkan_layer_peta_overlay",
                            "argumen": {"provinsi": l["provinsi"], "kabupaten": l["kabupaten"], "layer": l["layer"]}})
        if usulan["jumlah"]:
            actions.append({"nama": "tampilkan_usulan_kabupaten", "argumen": {"kode_kabupaten": kode_kab, "kabupaten_kota": m["kabupaten_kota"]}})
        if g and g["x1"] is not None:
            actions.append({"nama": "zoom_ke_bbox", "argumen": {"barat": g["x1"], "selatan": g["y1"], "timur": g["x2"], "utara": g["y2"]}})
    hasil = {
        "wilayah": {"nama": label, "provinsi": nama_prov, "kode_kabupaten": kode_kab, "kode_provinsi": kode_prov,
                    "jumlah_kecamatan": p["kec"], "penduduk": int(p["pend"] or 0),
                    "luas_km2": round(float(g["luas"]), 1) if g and g["luas"] else None},
        "jaringan_jalan": jaringan, "usulan_ijd_2026": usulan, "konektivitas": konektivitas,
        "riwayat_program_ijd": program, "overlay_dinyalakan": [f"{l['provinsi']} / {l['kabupaten']} / {l['layer']}" for l in lapis],
        "catatan": catatan,
    }
    if cer is not None:
        hasil["cer_awp1"] = cer
    return hasil


CHAT_TOOLS += [{
    "type": "function",
    "function": {
        "name": "baca_catatan_pengetahuan",
        "description": (
            "Membaca satu CATATAN SUMBER DATA (tabel/kolom/layer yang benar utk satu topik, sudah diverifikasi). "
            "Daftar nama catatan ada di system prompt. Panggil bila pertanyaan menyangkut topik yang catatannya "
            "belum disisipkan, SEBELUM menyusun query."
        ),
        "parameters": {
            "type": "object",
            "properties": {"nama": {"type": "string", "description": "Nama catatan dlm kurung siku, mis. 'pelabuhan'"}},
            "required": ["nama"],
        },
    },
}]


CHAT_TOOL_DISPATCH = {
    "cari_usulan_inpres": _tool_cari_usulan_inpres,
    "detail_usulan_inpres": _tool_detail_usulan_inpres,
    "analisa_geometri_kml_usulan": _tool_analisa_geometri_kml_usulan,
    "daftar_tabel_database": _tool_daftar_tabel_database,
    "jalankan_query_sql": _tool_jalankan_query_sql,
    "hitung_skor_ijd_usulan": _tool_hitung_skor_ijd_usulan,
    "daftar_layer_peta_overlay": _tool_daftar_layer_peta_overlay,
    "analisa_spasial_usulan": _tool_analisa_spasial_usulan,
    "tampilkan_layer_batas_administratif_usulan": _tool_tampilkan_layer_batas_administratif_usulan,
    "tampilkan_tabel": _tool_tampilkan_tabel,
    "buat_grafik": _tool_buat_grafik,
    "tampilkan_di_peta": _tool_tampilkan_di_peta,
    "buat_laporan": _tool_buat_laporan,
    "analisis_kabupaten": _tool_analisis_kabupaten,
    "baca_catatan_pengetahuan": _tool_baca_catatan_pengetahuan,
    # "tampilkan_usulan_di_peta" SENGAJA tidak didaftarkan di sini -- ada di
    # CLIENT_ACTION_TOOLS, diteruskan ke frontend lewat _run_tool_call, bukan
    # dieksekusi di server.
}


def _chat_system_text(context: Optional[dict], has_search: bool = False, dengan_catatan: bool = True) -> str:
    system_text = CHAT_SYSTEM_PROMPT + (CHAT_SEARCH_AVAILABLE_NOTE if has_search else CHAT_SEARCH_UNAVAILABLE_NOTE)
    if _tanpa_penilaian():
        system_text += ("\n\nPENGGUNA INI AKUN UMUM (Sikon): jangan menghitung, menyebut, atau menebak skor/"
                        "penilaian/peringkat IJD (skor teknokratis A-E, NPR, prioritas nasional, penilaian "
                        "Bappenas). Data usulan dan data sektor lain tetap boleh dijawab.")
    if dengan_catatan:
        system_text += _CATATAN.get()
    if context:
        system_text += "\n\n" + _teks_konteks(context)
    return system_text


def _teks_konteks(context: dict) -> str:
    return "Konteks aplikasi saat ini (JSON):\n" + json.dumps(context, ensure_ascii=False)


def _run_tool_call(name: str, args: dict, actions: list) -> dict:
    """actions: akumulator per-request (dibuat baru di tiap _call_* provider,
    BUKAN global module-level -- FastAPI bisa melayani beberapa /api/chat
    bersamaan, global mutable di sini akan tercampur antar request). Tool
    CLIENT_ACTION_TOOLS dicatat ke sini dan dibalas dgn status sukses palsu
    supaya model tetap lanjut menyusun kalimat penutup wajar (bukan menunggu
    hasil eksekusi UI yang memang tidak/belum terjadi saat ini)."""
    jejak = _JEJAK.get()
    if jejak is not None:
        jejak["tools"].append(name)
        if name == "jalankan_query_sql" and (args or {}).get("sql"):
            jejak["sql"].append(str(args["sql"]))
    if name in CLIENT_ACTION_TOOLS:
        actions.append({"nama": name, "argumen": args})
        return {"status": "diteruskan_ke_frontend_untuk_dieksekusi"}
    hasil = _jalankan_tool(name, args, actions)
    if jejak is not None and isinstance(hasil, dict):  # utk _periksa_jawaban (Tahap 3)
        n = hasil.get("jumlah_baris", hasil.get("total_ditemukan"))
        # agregat bernilai nol (COUNT/SUM dgn filter salah tulis -> 1 baris berisi 0): perlakukan spt kosong
        prat = hasil.get("pratinjau_baris") or []
        if n == 1 and prat and all((v in (0, None)) for v in prat[0].values() if not isinstance(v, str)) \
                and any(not isinstance(v, str) for v in prat[0].values()):
            n = 0
        jejak["hasil"].append({"tool": name, "n": n, "error": hasil.get("error")})
    if jejak is not None:
        langkah = _langkah_ringkas(name, args, hasil)
        if langkah:
            jejak["langkah"].append(langkah)
    rekam = _HASIL_TOOL.get()
    if rekam is not None:
        rekam.append(json.dumps(jsonable_encoder(hasil), ensure_ascii=False, default=str)[:200000])
    return hasil


def _jalankan_tool(name: str, args: dict, actions: list) -> dict:
    fn = CHAT_TOOL_DISPATCH.get(name)
    if fn is None:
        return {"error": "fungsi tidak dikenal"}
    if name in _TOOLS_PENILAIAN and _tanpa_penilaian():
        return {"error": "Akun umum tidak memiliki akses ke skor/penilaian IJD. Sampaikan ke pengguna bahwa "
                         "informasi ini hanya tersedia di SiJalan untuk akun yang berwenang."}
    try:
        if name in _TOOLS_NEED_ACTIONS_PARAM:
            return fn(actions=actions, **args)
        return fn(**args)
    except TypeError as e:  # model mengirim argumen yg tidak dikenal -> balas error, bukan crash seluruh chat
        return {"error": f"Argumen fungsi {name} tidak valid: {e}"}


# Analisis lintas data butuh banyak langkah (katalog -> kolom -> query -> tabel/grafik/peta/laporan).
_MAKS_PUTARAN_TOOL = 12


def _call_openai_compatible(provider: str, api_url: str, api_key: str, model: str, messages: List, context: Optional[dict]) -> tuple:
    """Chat Completions-compatible provider tanpa pencarian web (Groq, Grok/xAI, DeepSeek).
    Return (teks, actions) -- actions dikumpulkan baru per panggilan (lihat
    _run_tool_call), bukan global module-level."""
    actions: list = []
    chat_messages = [{"role": "system", "content": _chat_system_text(context)}]
    chat_messages += [{"role": m.role, "content": m.text} for m in messages]

    for _ in range(_MAKS_PUTARAN_TOOL):  # batas jumlah putaran pemanggilan fungsi, cegah loop tak berujung
        try:
            resp = requests.post(
                api_url,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                json={"model": model, "messages": chat_messages, "tools": CHAT_TOOLS, "tool_choice": "auto"},
                timeout=120,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            detail = e.response.text if getattr(e, "response", None) is not None else str(e)
            raise RuntimeError(f"{provider}: {detail}")

        data = resp.json()
        _catat_token((data.get("usage") or {}).get("prompt_tokens"), (data.get("usage") or {}).get("completion_tokens"))
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"{provider}: tidak mengembalikan jawaban")
        message = choices[0]["message"]

        tool_calls = message.get("tool_calls")
        if not tool_calls:
            text = message.get("content") or ""
            if not text:
                raise RuntimeError(f"{provider}: jawaban kosong")
            return text, actions

        chat_messages.append(message)
        for tc in tool_calls:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result = _run_tool_call(tc["function"]["name"], args, actions)
            chat_messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(jsonable_encoder(result), ensure_ascii=False),
            })

    raise RuntimeError(f"{provider}: terlalu banyak pemanggilan fungsi")


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
# Format tool Responses API berbeda dari Chat Completions: rata (flat), bukan
# dibungkus {"function": {...}}. web_search_preview adalah tool bawaan OpenAI
# yang berjalan di sisi mereka — tidak perlu didaftarkan di CHAT_TOOL_DISPATCH.
OPENAI_RESPONSES_TOOLS = [{"type": "web_search_preview"}] + [
    {"type": "function", "name": t["function"]["name"], "description": t["function"]["description"], "parameters": t["function"]["parameters"]}
    for t in CHAT_TOOLS
]


def _call_openai_responses(api_key: str, model: str, messages: List, context: Optional[dict]) -> tuple:
    """OpenAI Responses API — satu-satunya provider yang benar-benar mendukung
    pencarian internet (web_search_preview) digabung dengan tool database/KML kita."""
    actions: list = []
    input_items = [{"role": m.role, "content": m.text} for m in messages]

    for _ in range(_MAKS_PUTARAN_TOOL):  # batas jumlah putaran pemanggilan fungsi, cegah loop tak berujung
        try:
            resp = requests.post(
                OPENAI_RESPONSES_URL,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "instructions": _chat_system_text(context, has_search=True),
                    "input": input_items,
                    "tools": OPENAI_RESPONSES_TOOLS,
                },
                timeout=120,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            detail = e.response.text if getattr(e, "response", None) is not None else str(e)
            raise RuntimeError(f"OpenAI: {detail}")

        data = resp.json()
        _catat_token((data.get("usage") or {}).get("input_tokens"), (data.get("usage") or {}).get("output_tokens"))
        output = data.get("output") or []

        function_calls = [item for item in output if item.get("type") == "function_call"]
        if not function_calls:
            text = "".join(
                c.get("text", "")
                for item in output if item.get("type") == "message"
                for c in item.get("content", []) if c.get("type") == "output_text"
            )
            if not text:
                raise RuntimeError("OpenAI: jawaban kosong")
            return text, actions

        # Balas semua output turn ini (termasuk pemanggilan web_search_preview,
        # bila ada) lalu tambahkan function_call_output untuk tiap function_call.
        input_items.extend(output)
        for fc in function_calls:
            try:
                args = json.loads(fc.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result = _run_tool_call(fc["name"], args, actions)
            input_items.append({
                "type": "function_call_output",
                "call_id": fc["call_id"],
                "output": json.dumps(jsonable_encoder(result), ensure_ascii=False),
            })

    raise RuntimeError("OpenAI: terlalu banyak pemanggilan fungsi")


def _openai_tools_to_gemini(tools: list) -> list:
    def upcase_types(schema):
        if not isinstance(schema, dict):
            return schema
        out = {}
        for k, v in schema.items():
            if k == "type" and isinstance(v, str):
                out[k] = v.upper()
            elif k == "properties":
                out[k] = {pk: upcase_types(pv) for pk, pv in v.items()}
            elif k == "items":
                out[k] = upcase_types(v)
            else:
                out[k] = v
        return out

    return [{
        "function_declarations": [
            {"name": t["function"]["name"], "description": t["function"]["description"], "parameters": upcase_types(t["function"]["parameters"])}
            for t in tools
        ],
    }]


GEMINI_CHAT_TOOLS = _openai_tools_to_gemini(CHAT_TOOLS)


def _call_gemini(api_key: str, model: str, messages: List, context: Optional[dict]) -> tuple:
    actions: list = []
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    contents = [{"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.text}]} for m in messages]

    for _ in range(_MAKS_PUTARAN_TOOL):  # batas jumlah putaran pemanggilan fungsi, cegah loop tak berujung
        try:
            resp = requests.post(
                api_url,
                headers={"Content-Type": "application/json", "X-goog-api-key": api_key},
                json={
                    "system_instruction": {"parts": [{"text": _chat_system_text(context)}]},
                    "tools": GEMINI_CHAT_TOOLS,
                    "contents": contents,
                },
                timeout=120,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            detail = e.response.text if getattr(e, "response", None) is not None else str(e)
            raise RuntimeError(f"Gemini: {detail}")

        data = resp.json()
        _catat_token((data.get("usageMetadata") or {}).get("promptTokenCount"),
                     (data.get("usageMetadata") or {}).get("candidatesTokenCount"))
        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError("Gemini: tidak mengembalikan jawaban")
        parts = candidates[0].get("content", {}).get("parts", [])

        function_calls = [p["functionCall"] for p in parts if "functionCall" in p]
        if not function_calls:
            text = "".join(p.get("text", "") for p in parts)
            if not text:
                raise RuntimeError("Gemini: jawaban kosong")
            return text, actions

        # Model bisa memanggil beberapa fungsi sekaligus dalam satu giliran — semua
        # harus dibalas dalam satu content "function", atau giliran berikutnya
        # kembali kosong karena Gemini masih menunggu jawaban yang belum terkirim.
        response_parts = [
            {"functionResponse": {"name": fc["name"], "response": jsonable_encoder(_run_tool_call(fc["name"], fc.get("args") or {}, actions))}}
            for fc in function_calls
        ]
        contents.append({"role": "model", "parts": parts})
        contents.append({"role": "function", "parts": response_parts})

    raise RuntimeError("Gemini: terlalu banyak pemanggilan fungsi")


CLAUDE_TOOLS = [
    {"name": t["function"]["name"], "description": t["function"]["description"], "input_schema": t["function"]["parameters"]}
    for t in CHAT_TOOLS
]
# prompt caching: definisi tool + system prompt statis sama di tiap permintaan -> di-cache
CLAUDE_TOOLS[-1] = {**CLAUDE_TOOLS[-1], "cache_control": {"type": "ephemeral"}}


def _call_claude(api_key: str, model: str, messages: List, context: Optional[dict]) -> tuple:
    actions: list = []
    client = anthropic.Anthropic(api_key=api_key, timeout=300.0)
    claude_messages = [{"role": m.role, "content": m.text} for m in messages]

    for _ in range(_MAKS_PUTARAN_TOOL):  # batas jumlah putaran pemanggilan fungsi, cegah loop tak berujung
        try:
            system_blocks = [{"type": "text", "text": _chat_system_text(None, dengan_catatan=False),
                              "cache_control": {"type": "ephemeral"}}]
            if _CATATAN.get():  # catatan topik berbeda per pertanyaan -> di LUAR blok yg di-cache
                system_blocks.append({"type": "text", "text": _CATATAN.get().strip()})
            if context:  # konteks rute berubah-ubah -> di LUAR blok yg di-cache
                system_blocks.append({"type": "text", "text": _teks_konteks(context)})
            response = client.messages.create(
                model=model,
                max_tokens=16000,
                system=system_blocks,
                tools=CLAUDE_TOOLS,
                messages=claude_messages,
            )
        except anthropic.APIError as e:
            raise RuntimeError(f"Claude: {e.message}")

        u = response.usage
        _catat_token((u.input_tokens or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0)
                     + (getattr(u, "cache_creation_input_tokens", 0) or 0), u.output_tokens)
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        if not tool_use_blocks:
            text = "".join(b.text for b in response.content if b.type == "text")
            if not text:
                raise RuntimeError("Claude: jawaban kosong")
            return text, actions

        claude_messages.append({"role": "assistant", "content": response.content})
        tool_results = [
            {
                "type": "tool_result",
                "tool_use_id": tb.id,
                "content": json.dumps(jsonable_encoder(_run_tool_call(tb.name, tb.input or {}, actions)), ensure_ascii=False),
            }
            for tb in tool_use_blocks
        ]
        claude_messages.append({"role": "user", "content": tool_results})

    raise RuntimeError("Claude: terlalu banyak pemanggilan fungsi")


def _chat_providers() -> list:
    """Provider yang API key-nya diisi di .env, urut prioritas (yang free-tier-nya
    paling longgar duluan) — dicoba satu per satu di _call_chat sampai ada yang
    berhasil, supaya chat tidak macet total hanya karena satu provider kehabisan
    kuota harian. Return [(nama, model, fungsi)]."""
    providers = []
    # Claude duluan: model utama mode analitik (banyak langkah tool + laporan). Kalau gagal
    # (mis. kredit habis / kuota), otomatis lanjut ke provider berikutnya seperti biasa.
    if os.getenv("CLOUDE_API_KEY"):
        providers.append(("Claude", CLAUDE_MODEL, lambda msgs, ctx: _call_claude(os.getenv("CLOUDE_API_KEY"), CLAUDE_MODEL, msgs, ctx)))
    # DeepSeek kedua: model kuat dgn tool calling, cadangan utama bila Claude gagal
    # (mis. kredit habis), sebelum provider yg lebih lemah di alur multi-langkah.
    if os.getenv("DEEPSEEK_API_KEY"):
        providers.append(("DeepSeek", DEEPSEEK_MODEL, lambda msgs, ctx: _call_openai_compatible("DeepSeek", DEEPSEEK_API_URL, os.getenv("DEEPSEEK_API_KEY"), DEEPSEEK_MODEL, msgs, ctx)))
    if os.getenv("GROQ_API_KEY"):
        providers.append(("Groq", GROQ_MODEL, lambda msgs, ctx: _call_openai_compatible("Groq", GROQ_API_URL, os.getenv("GROQ_API_KEY"), GROQ_MODEL, msgs, ctx)))
    if os.getenv("GROK_API_KEY"):
        providers.append(("Grok", GROK_MODEL, lambda msgs, ctx: _call_openai_compatible("Grok", GROK_API_URL, os.getenv("GROK_API_KEY"), GROK_MODEL, msgs, ctx)))
    if os.getenv("OPEN_AI_API_KEY"):
        providers.append(("OpenAI", OPENAI_MODEL, lambda msgs, ctx: _call_openai_responses(os.getenv("OPEN_AI_API_KEY"), OPENAI_MODEL, msgs, ctx)))
    if os.getenv("GEMINI_API_KEY"):
        providers.append(("Gemini", GEMINI_MODEL, lambda msgs, ctx: _call_gemini(os.getenv("GEMINI_API_KEY"), GEMINI_MODEL, msgs, ctx)))
    return providers


# ---------- Tahap 3 kajian agentic workflow: observe -> revise ----------
# Aturan (bukan LLM) yg memeriksa jawaban sebelum dikirim; bila gagal, model
# diberi SATU kesempatan revisi dgn instruksi spesifik. Pola diambil dari
# kegagalan nyata di scripts/uji_chat.py (baseline 7 Okt 2026, gpt-4o-mini).
_POLA_KONFIRMASI = re.compile(r"mohon konfirmasi|apakah anda (ingin|mau) saya|silakan konfirmasi|perlu saya (cari|ambil)", re.I)
_POLA_NIHIL = re.compile(r"\btidak ada\b|\btidak ditemukan\b|\bbelum ada data\b|\bnihil\b|"
                         r"(?<![\d.,])0(?:[.,]0+)? ?(%|persen|usulan|baris|data|kegiatan)\b", re.I)
_POLA_PENOLAKAN = re.compile(r"tidak (boleh|diizinkan|diperbolehkan)|tidak dapat (menghapus|mengubah|menampilkan data pribadi)|"
                             r"read.?only|hanya (dapat )?membaca|privasi|kerahasiaan", re.I)
_AKSI_PETA = {"tampilkan_di_peta", "tampilkan_usulan_di_peta", "tampilkan_layer_peta_overlay"}


def _periksa_jawaban(pertanyaan: str, teks: str, actions: list, jejak: dict) -> Optional[str]:
    """None bila jawaban lolos; selain itu instruksi revisi utk model."""
    p = (pertanyaan or "").lower()
    tools = jejak.get("tools") or []
    hasil = jejak.get("hasil") or []
    aksi = {a.get("nama") for a in actions}
    if _POLA_PENOLAKAN.search(teks):
        return None  # penolakan yg disengaja (data pribadi, tulis data) bukan kegagalan
    if not tools and _POLA_KONFIRMASI.search(teks):
        return ("Jangan meminta konfirmasi -- pertanyaannya sudah jelas. Langsung cari datanya: pakai "
                "daftar_tabel_database bila perlu, lalu jalankan_query_sql, dan jawab dari hasilnya.")
    if not tools and _POLA_NIHIL.search(teks):
        return ("Kamu menyimpulkan datanya tidak ada TANPA memeriksa database. Cari dulu: daftar_tabel_database "
                "lalu jalankan_query_sql, baru jawab dari hasilnya.")
    sql_terakhir = next((h for h in reversed(hasil) if h["tool"] == "jalankan_query_sql"), None)
    if sql_terakhir and (sql_terakhir["error"] or not sql_terakhir["n"]) and _POLA_NIHIL.search(teks):
        return ("Query terakhirmu menghasilkan 0 baris atau error, lalu kamu menyimpulkan datanya tidak ada/0. "
                "Itu sering karena nilai filter salah tulis. Periksa nilai sebenarnya dgn SELECT DISTINCT <kolom> "
                "(nilai teks di database umumnya HURUF BESAR, mis. seleksi_sistem = 'LULUS' / 'TIDAK LULUS', "
                "provinsi = 'PAPUA SELATAN'), atau pakai ILIKE, lalu ulangi query dan jawab dari hasilnya.")
    hanya_cari = "cari_usulan_inpres" in tools and "jalankan_query_sql" not in tools
    filter_lanjut = re.search(r"lulus|seleksi|jenis|kondisi|mantap|status|verifikasi|persen|alokasi|panjang", p)
    if hanya_cari and re.search(r"\bberapa\b|\bjumlah\b|\bpersen", p) and (_POLA_NIHIL.search(teks) or filter_lanjut):
        return ("cari_usulan_inpres hanya menampilkan contoh & tidak bisa memfilter status seleksi/kondisi, jadi "
                "tidak boleh dipakai utk menyimpulkan 'tidak ada'. Hitung dgn jalankan_query_sql (COUNT ... FROM "
                "usulan_inpres WHERE ...), lalu jawab angkanya.")
    angka_teks = [x for x in (y.strip(".,") for y in re.findall(r"\d[\d.,]*", teks)) if not re.fullmatch(r"(19|20)\d\d", x)]
    if re.search(r"\bberapa\b|\bjumlah\b|\bpersen", p) and tools and not angka_teks:
        return ("Pertanyaannya meminta angka, tapi teks jawabanmu tidak menyebut angka hasilnya (tabel/kartu saja tidak "
                "cukup). Tulis angka jawabannya secara eksplisit di kalimat pertama.")
    if re.search(r"\bgrafik|\bchart\b|\bdiagram", p) and "buat_grafik" not in aksi:
        return ("Pengguna meminta grafik, tapi buat_grafik belum dipanggil. Pakai dataset_id dari query yang sudah "
                "ada (atau jalankan query dulu), lalu panggil buat_grafik.")
    if re.search(r"\b(di|ke) peta\b|tampilkan .{0,60}peta", p) and not (aksi & _AKSI_PETA):
        return ("Pengguna meminta ditampilkan di peta, tapi belum ada aksi peta. Panggil tampilkan_di_peta "
                "(dataset berkolom koordinat/geometri) atau tool peta yang sesuai.")
    if re.search(r"\blaporan\b|\bword\b|\bdocx\b", p) and "unduh_laporan" not in aksi:
        return "Pengguna meminta laporan Word, tapi buat_laporan belum dipanggil. Susun isinya lalu panggil buat_laporan."
    if "Peringatan sistem" in teks:
        return ("Tabel di jawabanmu tidak cocok dgn data hasil tool. Susun ulang tabel HANYA dari hasil tool/dataset "
                "yang benar-benar didapat; jangan mengarang baris atau nama.")
    return None


def _catatan_dataset(actions: list) -> str:
    ds = [a["argumen"] for a in actions if a.get("nama") == "dataset_tersedia"]
    if not ds:
        return ""
    return "\n\n[Dataset dari jawaban ini: " + "; ".join(
        f"{d['dataset_id']} = \"{d.get('judul', '')}\" ({d.get('jumlah_baris')} baris; kolom: {', '.join(d.get('kolom') or [])})"
        for d in ds) + "]"


_POLA_ALASAN = [
    (re.compile(r"credit balance is too low|used all available credits|insufficient[_ ]balance|"
                r"insufficient_quota|exceeded your current quota|spending limit", re.I), "saldo/kredit habis"),
    (re.compile(r"\b401\b|invalid[_ ]api[_ ]key|incorrect api key|authentication|unauthorized", re.I), "API key tidak valid"),
    (re.compile(r"\b429\b|rate[_ ]limit|too many requests|resource_exhausted", re.I), "batas permintaan (rate limit)"),
    (re.compile(r"timed? ?out|timeout", re.I), "waktu habis (timeout)"),
]


def _ringkas_alasan(e) -> str:
    """Pesan error provider (sering JSON panjang) -> alasan pendek yg bisa
    dibaca pengguna/admin; pesan asli tetap di log server."""
    teks = str(e)
    for pola, label in _POLA_ALASAN:
        if pola.search(teks):
            return label
    return teks[:160]


def _ping_provider(nama: str, model: str):
    """Permintaan sekecil mungkin (tanpa tools/system prompt) utk memeriksa key
    & saldo provider -- jauh lebih murah drpd mengirim ~7.000 token prompt chat."""
    pesan = [{"role": "user", "content": "ping"}]
    if nama == "Claude":
        anthropic.Anthropic(api_key=os.getenv("CLOUDE_API_KEY"), timeout=30.0).messages.create(
            model=model, max_tokens=5, messages=pesan)
        return
    if nama == "Gemini":
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={os.getenv('GEMINI_API_KEY')}",
            json={"contents": [{"parts": [{"text": "ping"}]}], "generationConfig": {"maxOutputTokens": 5}},
            timeout=30)
    else:
        url, key = {
            "DeepSeek": (DEEPSEEK_API_URL, os.getenv("DEEPSEEK_API_KEY")),
            "Groq": (GROQ_API_URL, os.getenv("GROQ_API_KEY")),
            "Grok": (GROK_API_URL, os.getenv("GROK_API_KEY")),
            "OpenAI": ("https://api.openai.com/v1/chat/completions", os.getenv("OPEN_AI_API_KEY")),
        }[nama]
        r = requests.post(url, headers={"Authorization": f"Bearer {key}"},
                          json={"model": model, "messages": pesan, "max_tokens": 5}, timeout=30)
    if not r.ok:
        raise RuntimeError(f"{r.status_code} {r.text[:500]}")


_STATUS_PROVIDER_CACHE = {"waktu": 0.0, "hasil": None}
_STATUS_PROVIDER_TTL_DETIK = 300


def status_provider(paksa: bool = False) -> dict:
    """Status tiap provider yg key-nya diisi, urut sesuai _chat_providers
    (GET /api/chat/status-provider, admin). Di-cache 5 menit per worker supaya
    membuka panel status tidak memanggil 5 API berbayar tiap kali."""
    if (not paksa and _STATUS_PROVIDER_CACHE["hasil"] is not None
            and time.time() - _STATUS_PROVIDER_CACHE["waktu"] < _STATUS_PROVIDER_TTL_DETIK):
        return _STATUS_PROVIDER_CACHE["hasil"]
    hasil = []
    for nama, model, _ in _chat_providers():
        mulai = time.time()
        try:
            _ping_provider(nama, model)
            ok, alasan = True, None
        except Exception as e:
            ok, alasan = False, _ringkas_alasan(e)
            print(f"  [chat] status provider {nama} ({model}) gagal: {str(e)[:300]}")
        hasil.append({"provider": nama, "model": model, "ok": ok, "alasan": alasan,
                      "durasi_detik": round(time.time() - mulai, 1)})
    aktif = next((h["provider"] for h in hasil if h["ok"]), None)
    data = {"providers": hasil, "provider_aktif": aktif,
            "diuji_pada": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _STATUS_PROVIDER_CACHE.update(waktu=time.time(), hasil=data)
    return data


_SEL_ANGKA = re.compile(r"^[\s\d.,%:+\-/()kmhaRp$]*$", re.IGNORECASE)
# Sel angka bersatuan ("Rp 14,65 triliun", "38,1 %", "2.548.784 jiwa") = angka, bukan teks.
_SEL_SATUAN = re.compile(r"\b(rp|triliun|miliar|milyar|juta|ribu|jt|rb|persen|km|m2|km2|km²|ha|ton|jiwa|unit|ruas|"
                         r"usulan|kegiatan|koridor|kecamatan|kab/kota|menit|jam|hari|tahun|kali|orang)\b\.?", re.IGNORECASE)
_SEL_UMUM = {"total", "jumlah", "rata-rata", "rerata", "subtotal", "lainnya", "nasional", "keterangan", "ya", "tidak"}


def _periksa_tabel_karangan(teks: str, actions: list) -> str:
    """Model yang lebih lemah (terbukti: gpt-4o-mini, 28 Sep 2026) bisa mengisi
    tabel markdown dgn data karangan saat query-nya gagal/0 baris ("Pelabuhan 1
    | Lokasi 1 | 1 km"). Sel teks tiap tabel dicocokkan ke hasil tool request
    ini + isi dataset yg dibuat; bila hampir tidak ada yg cocok, jawaban diberi
    peringatan yang terlihat pengguna. Heuristik -- hanya menandai, tidak
    mengubah isi jawaban."""
    sumber = list(_HASIL_TOOL.get() or [])
    for a in actions:
        if a.get("nama") == "dataset_tersedia":
            ds = chat_dataset.muat(a["argumen"].get("dataset_id", ""))
            if ds:
                sumber.append(json.dumps(ds["rows"], ensure_ascii=False, default=str)[:500000])
    # Normalisasi dua sisi: kunci JSON (kepadatan_jalan) vs label tabel buatan model
    # ("Kepadatan jalan"), dan tanda pisah panjang vs "-" -- dulu memicu peringatan palsu.
    def _norm(t):
        return re.sub(r"\s+", " ", t.lower().replace("_", " ").replace("–", "-").replace("—", "-"))

    korpus = _norm(" ".join(sumber))
    curiga = False
    tabel, dalam = [], False
    for baris in teks.split("\n") + [""]:
        b = baris.strip()
        if b.startswith("|") and b.endswith("|"):
            tabel.append(b)
            dalam = True
            continue
        if dalam:
            isi = [r for r in tabel[2:] if not re.match(r"^\|?\s*:?-{2,}", r)]  # buang header & pemisah
            sel = [c.strip().strip("*").strip() for r in isi for c in r.strip("|").split("|")]
            sel = [c for c in sel if len(c) >= 4 and not _SEL_ANGKA.match(c)
                   and not _SEL_ANGKA.match(_SEL_SATUAN.sub(" ", c)) and c.strip().lower() not in _SEL_UMUM]

            def _cocok(c):
                if _norm(c) in korpus:
                    return True
                # label parafrase ("A. Tematik & Data Dukung"): >=2 kata bermakna & SEMUA ada di data.
                # Label 1 kata ("Pelabuhan 1") tetap harus cocok utuh -> tabel karangan tetap tertangkap.
                kata = [w for w in re.findall(r"[a-z]{4,}", _norm(c))]
                return len(kata) >= 2 and all(w in korpus for w in kata)

            if len(isi) >= 2 and len(sel) >= 2:
                cocok = sum(1 for c in sel if _cocok(c))
                if cocok / len(sel) < 0.3:
                    curiga = True
            tabel, dalam = [], False
    if curiga:
        teks += ("\n\n> ⚠️ **Peringatan sistem:** sebagian besar isi tabel di atas **tidak ditemukan** pada data yang "
                 "diambil asisten dari database — kemungkinan tidak akurat. Periksa bagian *Data & query* atau ulangi "
                 "pertanyaan dengan lebih spesifik.")
    return teks


_MD_GAMBAR = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_TAUTAN = re.compile(r"\[([^\]]+)\]\(([^)]*)\)")


def _rapikan_jawaban(teks: str, actions: list) -> str:
    """Gambar markdown & tautan buatan model (mis. "![grafik](url_grafik)") dibuang -- grafik/peta/unduhan
    sudah tampil sbg kartu; tautan yg bukan http(s) atau path /api/... pasti rusak. Kalau model lupa
    memanggil tampilkan_tabel, dataset non-kosong terakhir otomatis diberi kartu tabel (tombol unduh)."""
    teks = _MD_GAMBAR.sub("", teks)
    teks = _MD_TAUTAN.sub(lambda m: m.group(0) if re.match(r"^(https?://|/api/)", m.group(2).strip()) else m.group(1), teks)
    if not any(a.get("nama") == "tampilkan_tabel" for a in actions):
        terakhir = next((a["argumen"] for a in reversed(actions)
                         if a.get("nama") == "dataset_tersedia" and a["argumen"].get("jumlah_baris")), None)
        if terakhir:
            ds = chat_dataset.muat(terakhir["dataset_id"])
            if ds:
                geo = chat_dataset.deteksi_geometri(ds)
                actions.append({"nama": "tampilkan_tabel", "argumen": {
                    "dataset_id": ds["id"], "judul": ds["judul"], "jumlah_baris": len(ds["rows"]),
                    "berlokasi": bool(geo["kolom_geometri"] or geo["kolom_lat"])}})
    return teks


def _call_chat(messages: List, context: Optional[dict], pengguna: Optional[str] = None,
               peran: Optional[str] = None, hanya_provider: Optional[str] = None) -> tuple:
    """Return (teks, actions, meta) -- actions = daftar CLIENT_ACTION_TOOLS yang
    dipanggil model, diteruskan app.py ke frontend utk dieksekusi di UI.

    meta (Tahap 1 kajian agentic workflow, "gateway transparan"): provider &
    model yang menjawab, apakah itu cadangan (provider di depannya gagal) dan
    kenapa, durasi, token, tool & SQL yg dijalankan. Sebelumnya kegagalan
    provider ditelan diam-diam -- 6 Okt 2026 semua jawaban ternyata dari
    gpt-4o-mini krn kredit Claude & Grok habis, dan tidak ada yg tahu."""
    _PENGGUNA.set(pengguna)
    _PERAN.set(peran)
    teks_user = [m.text for m in messages if m.role == "user"]
    _CATATAN.set(_pilih_catatan(teks_user[-1] if teks_user else "", " ".join(teks_user[-3:-1])))
    providers = _chat_providers()
    if hanya_provider:  # paket uji (scripts/uji_chat.py): ukur satu provider, tanpa cadangan
        providers = [p for p in providers if p[0].lower() == hanya_provider.lower()]
        if not providers:
            raise HTTPException(400, f"Provider '{hanya_provider}' tidak aktif (API key kosong?)")
    if not providers:
        raise HTTPException(
            500,
            "Tidak ada API key LLM yang diset di .env (GROQ_API_KEY / GROK_API_KEY / OPEN_AI_API_KEY / CLOUDE_API_KEY / DEEPSEEK_API_KEY / GEMINI_API_KEY)",
        )

    errors = []
    gagal = []
    mulai = time.time()
    # Blok <memori> di riwayat = hasil tool ASLI giliran sebelumnya: ikut jadi sumber
    # _periksa_tabel_karangan supaya angka yg dipakai ulang tidak ditandai karangan.
    memori_lama = [b for m in messages if m.role == "assistant" for b in _POLA_MEMORI.findall(m.text or "")]
    for name, model, call in providers:
        _HASIL_TOOL.set(list(memori_lama))  # direset per provider: hasil tool provider yg gagal tidak ikut dihitung
        jejak = _jejak_baru()
        _JEJAK.set(jejak)
        try:
            teks, actions = call(messages, context)
        except Exception as e:
            errors.append(f"{name}: {e}")
            gagal.append({"provider": name, "model": model, "alasan": _ringkas_alasan(e)})
            print(f"  [chat] provider {name} ({model}) gagal: {str(e)[:300]}")
            continue
        teks = _periksa_tabel_karangan(_rapikan_jawaban(teks, actions), actions)
        # Tahap 3: periksa -> satu kali revisi dgn provider yg SAMA (jejak/token ikut terakumulasi).
        pertanyaan = next((m.text for m in reversed(messages) if m.role == "user"), "")
        instruksi = _periksa_jawaban(pertanyaan, teks, actions, jejak)
        direvisi = None
        if instruksi:
            ulang = list(messages) + [SimpleNamespace(role="assistant", text=teks + _catatan_dataset(actions)),
                                      SimpleNamespace(role="user", text="[Pemeriksaan otomatis aplikasi] " + instruksi)]
            try:
                teks2, actions2 = call(ulang, context)
                actions = actions + [a for a in actions2 if a not in actions]
                teks = _periksa_tabel_karangan(_rapikan_jawaban(teks2, actions), actions)
                direvisi = instruksi
            except Exception as e:  # revisi gagal -> tetap kirim jawaban pertama
                print(f"  [chat] revisi {name} gagal: {str(e)[:200]}")
        meta = {
            "provider": name,
            "model": model,
            "cadangan": bool(gagal),
            "gagal_sebelumnya": gagal,
            "durasi_detik": round(time.time() - mulai, 1),
            "token_masuk": jejak["token_masuk"] or None,
            "token_keluar": jejak["token_keluar"] or None,
            "tools": jejak["tools"],
            "sql": jejak["sql"],
            "direvisi": direvisi,
            # Tahap 4b: bahan scripts/belajar_catatan_chat.py (lewat chat_log)
            "catatan": list(dict.fromkeys(list(_CATATAN_NAMA.get()) + jejak["catatan_dibaca"])),
            "sql_galat": [h["error"] for h in jejak["hasil"]
                          if h["tool"] == "jalankan_query_sql" and h["error"]][:10],
            "memori": _memori_jawaban(jejak),
        }
        teks = _POLA_MEMORI.sub("", teks).strip()  # model meniru blok <memori> dari riwayat
        return teks, actions, meta

    # Pesan ringkas utk pengguna (alasan per provider); pesan asli sudah di log server.
    raise HTTPException(502, "Semua provider LLM gagal — " + " | ".join(f"{g['provider']}: {g['alasan']}" for g in gagal))
