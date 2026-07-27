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
import json
import os
import re
from typing import List, Optional

import anthropic
import requests
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from pyproj import Geod

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

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-4-8")

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")

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
jalankan_query_sql (SELECT SQL bebas, hasil dibatasi 200 baris) — panggil daftar_tabel_database dulu kalau \
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
Klasifikasi jalan OSM adalah perkiraan, bukan data resmi PUPR."""

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
                "Melihat skema database: tanpa argumen, mengembalikan daftar SEMUA tabel yang ada. "
                "Dengan argumen 'tabel', mengembalikan daftar kolom (nama + tipe data) tabel itu. "
                "WAJIB dipanggil dulu (kalau belum tahu nama tabel/kolom yang tepat) sebelum "
                "jalankan_query_sql, supaya query yang disusun memakai nama tabel/kolom yang benar-benar ada."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tabel": {"type": "string", "description": "Nama tabel spesifik (opsional) untuk melihat daftar kolomnya"},
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
                "(INSERT/UPDATE/DELETE/DDL akan ditolak sistem); hasil dibatasi 200 baris pertama."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "Satu statement SQL SELECT (boleh diawali WITH)"},
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
]

# Tool yang PANGGILANNYA diteruskan MENTAH ke frontend utk dieksekusi di UI,
# BUKAN dijalankan/di-dispatch di server (lihat _run_tool_call) -- lapisan
# pertama fitur "AI bisa bertindak, bukan cuma menjawab" (27 Jul 2026).
CLIENT_ACTION_TOOLS = {"tampilkan_usulan_di_peta"}

# Tool "hibrida": TETAP di-dispatch normal lewat CHAT_TOOL_DISPATCH (jalan di
# server dulu -- resolve nama layer yang benar dari lokasi usulan), TAPI
# fungsinya juga menerima param `actions` dan menambahkan aksi klien sendiri
# di akhir (lihat _tool_tampilkan_layer_batas_administratif_usulan) --
# ARGUMEN aksi yang dikirim ke frontend jadi SUDAH pasti valid (provinsi/
# kabupaten/layer persis dari map_layer_meta), bukan ditebak model spt kalau
# modelnya sendiri yang disuruh panggil daftar_layer_peta_overlay dulu.
_TOOLS_NEED_ACTIONS_PARAM = {"tampilkan_layer_batas_administratif_usulan"}

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
_SQL_MAX_ROWS = 200
_SQL_TIMEOUT_MS = 8000
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


def _tool_daftar_tabel_database(tabel=None) -> dict:
    with db_cursor() as cur:
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
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name"
        )
        return {"tabel": [r["table_name"] for r in cur.fetchall()]}


def _tool_jalankan_query_sql(sql=None) -> dict:
    error = _validasi_sql_readonly(sql or "")
    if error:
        return {"error": error}
    inti = sql.strip().rstrip(";")
    try:
        with db_cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute(f"SET LOCAL statement_timeout = {_SQL_TIMEOUT_MS}")
            cur.execute(inti)
            if cur.description is None:
                return {"error": "Query tidak mengembalikan baris (bukan SELECT?)"}
            rows = cur.fetchmany(_SQL_MAX_ROWS + 1)
    except Exception as e:
        return {"error": f"Query gagal: {e}"}
    terpotong = len(rows) > _SQL_MAX_ROWS
    rows = rows[:_SQL_MAX_ROWS]
    columns = list(rows[0].keys()) if rows else []
    return {
        "columns": columns,
        "rows": [jsonable_encoder(dict(r)) for r in rows],
        "jumlah_baris": len(rows),
        "dipotong_sampai_200_baris": terpotong,
    }


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
    # "tampilkan_usulan_di_peta" SENGAJA tidak didaftarkan di sini -- ada di
    # CLIENT_ACTION_TOOLS, diteruskan ke frontend lewat _run_tool_call, bukan
    # dieksekusi di server.
}


def _chat_system_text(context: Optional[dict], has_search: bool = False) -> str:
    system_text = CHAT_SYSTEM_PROMPT + (CHAT_SEARCH_AVAILABLE_NOTE if has_search else CHAT_SEARCH_UNAVAILABLE_NOTE)
    if context:
        system_text += "\n\nData rute saat ini (JSON):\n" + json.dumps(context, ensure_ascii=False)
    return system_text


def _run_tool_call(name: str, args: dict, actions: list) -> dict:
    """actions: akumulator per-request (dibuat baru di tiap _call_* provider,
    BUKAN global module-level -- FastAPI bisa melayani beberapa /api/chat
    bersamaan, global mutable di sini akan tercampur antar request). Tool
    CLIENT_ACTION_TOOLS dicatat ke sini dan dibalas dgn status sukses palsu
    supaya model tetap lanjut menyusun kalimat penutup wajar (bukan menunggu
    hasil eksekusi UI yang memang tidak/belum terjadi saat ini)."""
    if name in CLIENT_ACTION_TOOLS:
        actions.append({"nama": name, "argumen": args})
        return {"status": "diteruskan_ke_frontend_untuk_dieksekusi"}
    fn = CHAT_TOOL_DISPATCH.get(name)
    if fn is None:
        return {"error": "fungsi tidak dikenal"}
    if name in _TOOLS_NEED_ACTIONS_PARAM:
        return fn(actions=actions, **args)
    return fn(**args)


def _call_openai_compatible(provider: str, api_url: str, api_key: str, model: str, messages: List, context: Optional[dict]) -> tuple:
    """Chat Completions-compatible provider tanpa pencarian web (Groq, Grok/xAI).
    Return (teks, actions) -- actions dikumpulkan baru per panggilan (lihat
    _run_tool_call), bukan global module-level."""
    actions: list = []
    chat_messages = [{"role": "system", "content": _chat_system_text(context)}]
    chat_messages += [{"role": m.role, "content": m.text} for m in messages]

    for _ in range(4):  # batas jumlah putaran pemanggilan fungsi, cegah loop tak berujung
        try:
            resp = requests.post(
                api_url,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                json={"model": model, "messages": chat_messages, "tools": CHAT_TOOLS, "tool_choice": "auto"},
                timeout=30,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            detail = e.response.text if getattr(e, "response", None) is not None else str(e)
            raise RuntimeError(f"{provider}: {detail}")

        data = resp.json()
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

    for _ in range(4):  # batas jumlah putaran pemanggilan fungsi, cegah loop tak berujung
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
                timeout=30,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            detail = e.response.text if getattr(e, "response", None) is not None else str(e)
            raise RuntimeError(f"OpenAI: {detail}")

        data = resp.json()
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

    for _ in range(4):  # batas jumlah putaran pemanggilan fungsi, cegah loop tak berujung
        try:
            resp = requests.post(
                api_url,
                headers={"Content-Type": "application/json", "X-goog-api-key": api_key},
                json={
                    "system_instruction": {"parts": [{"text": _chat_system_text(context)}]},
                    "tools": GEMINI_CHAT_TOOLS,
                    "contents": contents,
                },
                timeout=30,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            detail = e.response.text if getattr(e, "response", None) is not None else str(e)
            raise RuntimeError(f"Gemini: {detail}")

        data = resp.json()
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


def _call_claude(api_key: str, model: str, messages: List, context: Optional[dict]) -> tuple:
    actions: list = []
    client = anthropic.Anthropic(api_key=api_key)
    claude_messages = [{"role": m.role, "content": m.text} for m in messages]

    for _ in range(4):  # batas jumlah putaran pemanggilan fungsi, cegah loop tak berujung
        try:
            response = client.messages.create(
                model=model,
                max_tokens=4096,
                system=_chat_system_text(context),
                tools=CLAUDE_TOOLS,
                messages=claude_messages,
            )
        except anthropic.APIError as e:
            raise RuntimeError(f"Claude: {e.message}")

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
    kuota harian."""
    providers = []
    if os.getenv("GROQ_API_KEY"):
        providers.append(("Groq", lambda msgs, ctx: _call_openai_compatible("Groq", GROQ_API_URL, os.getenv("GROQ_API_KEY"), GROQ_MODEL, msgs, ctx)))
    if os.getenv("GROK_API_KEY"):
        providers.append(("Grok", lambda msgs, ctx: _call_openai_compatible("Grok", GROK_API_URL, os.getenv("GROK_API_KEY"), GROK_MODEL, msgs, ctx)))
    if os.getenv("OPEN_AI_API_KEY"):
        providers.append(("OpenAI", lambda msgs, ctx: _call_openai_responses(os.getenv("OPEN_AI_API_KEY"), OPENAI_MODEL, msgs, ctx)))
    if os.getenv("CLOUDE_API_KEY"):
        providers.append(("Claude", lambda msgs, ctx: _call_claude(os.getenv("CLOUDE_API_KEY"), CLAUDE_MODEL, msgs, ctx)))
    if os.getenv("GEMINI_API_KEY"):
        providers.append(("Gemini", lambda msgs, ctx: _call_gemini(os.getenv("GEMINI_API_KEY"), GEMINI_MODEL, msgs, ctx)))
    return providers


def _call_chat(messages: List, context: Optional[dict]) -> tuple:
    """Return (teks, actions) -- actions = daftar CLIENT_ACTION_TOOLS yang
    dipanggil model, diteruskan app.py ke frontend utk dieksekusi di UI."""
    providers = _chat_providers()
    if not providers:
        raise HTTPException(
            500,
            "Tidak ada API key LLM yang diset di .env (GROQ_API_KEY / GROK_API_KEY / OPEN_AI_API_KEY / CLOUDE_API_KEY / GEMINI_API_KEY)",
        )

    errors = []
    for name, call in providers:
        try:
            return call(messages, context)
        except Exception as e:
            errors.append(f"{name}: {e}")

    raise HTTPException(502, "Semua provider LLM gagal — " + " | ".join(errors))
