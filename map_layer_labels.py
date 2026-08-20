"""Label Indonesia utk kode layer SHP RBI (Rupa Bumi Indonesia) Maps/ --
dipakai app.py (endpoint /api/maps/*) dan scripts/import_maps_to_postgis.py,
diekstrak jadi modul terpisah supaya keduanya konsisten tanpa duplikasi."""
import re

# Best-effort Indonesian labels for RBI shapefile layer codes, keyed by the
# name with its trailing _AR_25K/_LN_25K/_PT_25K stripped.
MAP_LAYER_LABELS = {
    "BLACKSPOT KECELAKAAN": "Blackspot Kecelakaan (Bina Marga 2020-2024)",
    "PETA KORIDOR": "Peta Koridor",
    "ADMINISTRASIDESA": "Batas Desa",
    "ADMINISTRASI": "Batas Administrasi",
    "AGRIKEBUN": "Kebun",
    "AGRILADANG": "Ladang",
    "AGRISAWAH": "Sawah",
    "AGRITANAMCAMPUR": "Tanaman Campuran",
    "AIRTERJUN": "Air Terjun",
    "BANGUNAN": "Bangunan",
    "CAGARBUDAYA": "Cagar Budaya",
    "DANAU": "Danau",
    "DEPOMINYAK": "Depo Minyak",
    "GENLISTRIK": "Pembangkit Listrik",
    "INDUSTRI": "Kawasan Industri",
    "JALAN": "Jalan",
    "JALUR KERETA API": "Jalur Kereta Api",
    "JALUR KERETA API AKTIF (BTP)": "Jalur Kereta Api Aktif (BTP)",
    "JEMBATAN": "Jembatan",
    "LOKASI RAWAN KECELAKAAN 2026": "Lokasi Rawan Kecelakaan (LRK) 2026",
    "KABELLISTRIK": "Kabel Listrik",
    "KANTOR SAR": "Kantor SAR",
    "KANTORPOS": "Kantor Pos",
    "KESEHATAN": "Fasilitas Kesehatan",
    "KONTUR": "Kontur",
    "MENARATELPON": "Menara Telekomunikasi",
    "NIAGA": "Kawasan Niaga",
    "NONAGRIALANG": "Alang-alang",
    "NONAGRIHUTANKERING": "Hutan Kering",
    "NONAGRISEMAKBELUKAR": "Semak Belukar",
    "PASIR": "Pasir",
    "PEMERINTAHAN": "Kantor Pemerintahan",
    "PEMUKIMAN": "Permukiman",
    "PENDIDIKAN": "Fasilitas Pendidikan",
    "PESISIR": "Pesisir",
    "PELABUHAN PENUMPANG": "Pelabuhan Penumpang",
    "PELABUHAN PENYEBERANGAN OPERASI": "Pelabuhan Penyeberangan Operasi",
    "PELABUHAN TERSUS/TUKS": "Pelabuhan TERSUS/TUKS",
    "PILARBATAS": "Pilar Batas",
    "PIPAMINYAK": "Pipa Minyak",
    "POS SAR": "Pos SAR",
    "PUNGGUNGBUKIT": "Punggung Bukit",
    "SARANAIBADAH": "Sarana Ibadah",
    "SPOTHEIGHT": "Titik Tinggi",
    "STASIUNKA": "Stasiun Kereta Api",
    "SUNGAI": "Sungai",
    "TERMINALBUS": "Terminal Bus",
    "TEROWONG": "Terowongan",
    "TERMINAL TIPE A": "Terminal Penumpang Tipe A",
    "TONGGAKKM": "Tonggak KM",
    "TOPONIMI": "Toponimi (Nama Tempat)",
    "WILAYAH TANGGUNG JAWAB SAR": "Wilayah Tanggung Jawab SAR",
}

_MAP_LAYER_SUFFIX_RE = re.compile(r"_(AR|LN|PT)_\d+K$", re.IGNORECASE)


def map_layer_label(stem: str) -> str:
    code = _MAP_LAYER_SUFFIX_RE.sub("", stem).upper()
    return MAP_LAYER_LABELS.get(code, stem.replace("_", " ").title())
