"""Import SHP Infrastruktur 2026 (Drive Konektivitas "9. DATA LAINNYA/SHP Infrastruktur 2026")
-> overlay peta nasional, hanya TEMA YANG BELUM ADA di aplikasi.

Sumber: docs/10102026/SHP Infrastruktur-20260927T095723Z-1-001.zip, diekstrak ke
Maps/_sumber_infrastruktur_2026/ (Maps/ gitignored, seperti sumber SHP lain).

Bucket flat (kabupaten = ''), dipecah per provinsi oleh build_map_layer_wilayah.py:
  LOGISTIK & EKONOMI          pasar, pelabuhan perikanan, terminal BBM/LPG, kilang, alur pelayaran laut
  SUMBER DAYA AIR             bendungan (eksisting/rencana), daerah irigasi rawa & tambak, sabo DAM,
                              pengaman pantai
  ENERGI & KELISTRIKAN        gardu induk, jaringan transmisi, pembangkit (ESDM), pembangkit off-grid APBN
  PERMUKIMAN & LAYANAN DASAR  SPAM, rusunawa, TPA, IPLT
  JALAN NASIONAL              + layer "Rencana Umum Jalan Nasional Non-Tol (SK 367/2023)"
SENGAJA TIDAK diimpor (sudah ada / lebih lama dari data aplikasi): Bandar Udara, Pelabuhan
Umum & Terminal Khusus (= daftar RIPN, import_pelabuhan_ripn.py), Pelabuhan Penyeberangan,
Stasiun & Rel KA, Jalan Nasional Tol/Non-Tol (data 2015; IRI 2026/LHR 2024 lebih baru),
SK 1688 status jalan 2022 (= layer Jalan Nasional, 3.305/3.306 LINKID sama), rencana tol
JBHRENCUM 27-12-2022 (versi 28-02-2023 sudah ada), RENCUM SK 430 (digantikan SK 367),
Pembangkit Listrik.shp (0 fitur), Kawasan Permukiman (1 poligon tanpa atribut).

Atribut: singkatan KUGI yang artinya jelas diberi label Indonesia (LABEL); kolom teknis
(objectid, fcode, srs_id, metadata, koordinat ulang) dibuang; sisanya apa adanya. Satuan
TIDAK ditambahkan bila sumber tidak menyebutnya. Geometri tidak valid diperbaiki
(make_valid), bukan dibuang; jumlah fitur per layer harus sama dgn sumber (impor ditolak bila
tidak). Poligon daerah irigasi (DIR/DIT) disederhanakan saat impor (SIMPLIFY_DERAJAT ~30 m,
preserve topology): resolusi penuhnya ~30 MB gzip per layer nasional di zoom dekat.

DELETE + INSERT per layer, aman di-rerun; lalu jalankan build_map_layer_wilayah.py.

Usage (venv aktif):
    python scripts/import_infrastruktur_2026.py --cek
    python scripts/import_infrastruktur_2026.py
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import geopandas as gpd  # noqa: E402
import shapely  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from psycopg.types.json import Json  # noqa: E402

load_dotenv(REPO_ROOT / ".env")
from db import db_cursor  # noqa: E402
from import_maps_to_postgis import _clean_value  # noqa: E402

SUMBER = REPO_ROOT / "Maps" / "_sumber_infrastruktur_2026" / "SHP Infrastruktur"
B_LOG, B_AIR, B_LISTRIK, B_PERMUKIMAN = ("LOGISTIK & EKONOMI", "SUMBER DAYA AIR", "ENERGI & KELISTRIKAN",
                                         "PERMUKIMAN & LAYANAN DASAR")
# (file sumber relatif SUMBER, bucket, nama layer)
LAYERS = [
    ("Pasar/Pasar.shp", B_LOG, "Pasar"),
    ("Pelabuhan Perikanan/Pelabuhan Perikanan.shp", B_LOG, "Pelabuhan Perikanan"),
    ("Terminal Khusus/Terminal BBM.shp", B_LOG, "Terminal BBM"),
    ("Terminal Khusus/Terminal LPG.shp", B_LOG, "Terminal LPG"),
    ("Lokasi Kilang Minyak/Lokasi Kilang Minyak.shp", B_LOG, "Kilang Minyak"),
    ("Peta Alur Pelayaran Laut/Peta Alur Pelayaran Laut.shp", B_LOG, "Alur Pelayaran Laut"),
    ("Bendungan Eksisting/Bendungan Eksisting.shp", B_AIR, "Bendungan Eksisting"),
    ("Bendungan Rencana/Bendungan Rencana.shp", B_AIR, "Bendungan Rencana"),
    ("Daerah Irigasi Rawa/DIR - Fungsional.shp", B_AIR, "Daerah Irigasi Rawa - Fungsional"),
    ("Daerah Irigasi Rawa/DIR - Potensial.shp", B_AIR, "Daerah Irigasi Rawa - Potensial"),
    ("Daerah Irigasi Rawa/DIR - Baku.shp", B_AIR, "Daerah Irigasi Rawa - Baku"),
    ("Daerah Irigasi Tambak/DIT - Fungsional.shp", B_AIR, "Daerah Irigasi Tambak - Fungsional"),
    ("Daerah Irigasi Tambak/DIT - Potensial.shp", B_AIR, "Daerah Irigasi Tambak - Potensial"),
    ("Sabo DAM/Sabo DAM.shp", B_AIR, "Sabo DAM"),
    ("Pengaman Pantai/Pengaman Pantai.shp", B_AIR, "Pengaman Pantai"),
    ("Gardu Induk/Gardu Induk.shp", B_LISTRIK, "Gardu Induk"),
    ("Jaringan Listrik/Jaringan Listrik.shp", B_LISTRIK, "Jaringan Transmisi Listrik"),
    ("Sebaran Pembangkit Listrik (ESDM)/Sebaran Pembangkit Listrik.shp", B_LISTRIK, "Pembangkit Listrik (ESDM)"),
    ("Pembangkit Offgrid APBN/Pembangkit Offgrid APBN.shp", B_LISTRIK, "Pembangkit Off-grid APBN"),
    ("SPAM/SPAM.shp", B_PERMUKIMAN, "SPAM (Air Minum)"),
    ("Rusunawa/Rusunawa.shp", B_PERMUKIMAN, "Rusunawa"),
    ("TPA/TPA.shp", B_PERMUKIMAN, "TPA (Sampah)"),
    ("IPLT/IPLT.shp", B_PERMUKIMAN, "IPLT (Lumpur Tinja)"),
    ("Jalan (Rencana Umum)/NON TOL/RENCUM_SK367_29122023.shp", "JALAN NASIONAL",
     "Rencana Umum Jalan Nasional Non-Tol (SK 367/2023)"),
]
SIMPLIFY_DERAJAT = 0.0003  # ~33 m; hanya layer poligon daerah irigasi
SIMPLIFY_LAYER = {l for _, _, l in LAYERS if l.startswith("Daerah Irigasi")}
RENCUM = "Rencana Umum Jalan Nasional Non-Tol (SK 367/2023)"
# warna per jenis penanganan rencana umum; HARUS sama dgn LEGENDA_PER_LAYER (maps-overlay.js)
WARNA_RENCUM = {"PEMBANGUNAN": "#7C3AED", "PENINGKATAN": "#DB2777", "JEMBATAN": "#0891B2"}

BUANG = {"objectid", "objectid_1", "objectid_2", "OBJECTID", "OBJECTID_1", "fcode", "srs_id", "srsid", "lcode",
         "metadata", "koord_x", "koord_y", "koord_x_aw", "koord_y_aw", "koord_x_ak", "koord_y_ak", "koord_y__1",
         "longitude", "latitude", "lat_start", "lon_start", "lat_end", "lon_end", "Shape_Leng", "Shape_Area",
         "Lintas", "kode", "kd_prov"}
LABEL = {
    "namobj": "Nama", "nm_inf": "Nama", "namaobj": "Nama", "nm_ruas": "Nama ruas",
    "alamat": "Alamat", "alamatbu": "Alamat", "almt_rusun": "Alamat",
    "propinsi": "Provinsi (sumber)", "provinsi": "Provinsi (sumber)", "prov": "Provinsi (sumber)",
    "kab_kota": "Kab/Kota (sumber)", "kab": "Kab/Kota (sumber)", "kabupaten": "Kab/Kota (sumber)",
    "kab_kot": "Kab/Kota (sumber)", "wadmkk": "Kab/Kota (sumber)", "wadmpr": "Provinsi (sumber)",
    "kecamatan": "Kecamatan", "desa": "Desa", "kel_desa": "Kelurahan/Desa",
    "tippsr": "Tipe pasar", "harops": "Hari operasi", "kpmlkn": "Kepemilikan", "luaslh": "Luas lahan",
    "luasbg": "Luas bangunan", "notelp": "Telepon", "kelas": "Kelas", "pengelola": "Pengelola",
    "status": "Status", "kap": "Kapasitas", "effdat": "Izin mulai", "expdat": "Izin berakhir",
    "bdnush": "Badan usaha", "nmoprt": "Operator", "skema": "Skema",
    "nama_upt": "UPT", "thn_alur": "Tahun penetapan alur", "lbr_alur": "Lebar alur", "pjg_alur": "Panjang alur",
    "sk_tap_alu": "SK penetapan alur", "izin_png": "Izin pengelolaan", "pm_tap_alu": "Penetapan alur",
    "vol_bdgan": "Volume bendungan", "nama_ws": "Wilayah sungai", "nama_das": "DAS", "plta": "PLTA",
    "tipe_bdgan": "Tipe bendungan", "tipe_pelim": "Tipe pelimpah", "irigrasi": "Layanan irigasi",
    "irigasi": "Layanan irigasi", "dmi": "Air baku (DMI)", "thn_mulai": "Tahun mulai", "thn_seles": "Tahun selesai",
    "tahun_dat": "Tahun data", "thn_dat": "Tahun data", "thn_data": "Tahun data", "remark": "Keterangan",
    "remarks": "Keterangan", "jenis": "Jenis", "jenis_di": "Jenis DI", "kewenangan": "Kewenangan",
    "kwenangan": "Kewenangan", "luas_fung": "Luas fungsional", "luas_pot": "Luas potensial",
    "luas_baku": "Luas baku", "nm_sungai": "Sungai", "jml_sabo": "Jumlah sabo", "nm_balai": "Balai",
    "jns_bg": "Jenis bangunan", "kep_pantai": "Kewenangan pantai", "panjang_m": "Panjang (m)",
    "material": "Material", "thn_bgn": "Tahun bangun", "teggi": "Tegangan", "thnopr": "Tahun operasi",
    "kapgi": "Kapasitas GI", "statmlk": "Status milik", "statopr": "Status operasi", "regpln": "Regional PLN",
    "pjgjar": "Panjang jaringan", "daya": "Daya", "enrgprmr": "Energi primer", "jenis_pemb": "Jenis pembangkit",
    "kap___kw_": "Kapasitas per unit (kW)", "total__kw_": "Total kapasitas (kW)", "jumlah": "Jumlah unit",
    "tahun": "Tahun", "thnpbn": "Tahun pembangunan", "kaprod": "Kapasitas produksi", "sts_pngn": "Status pengembangan",
    "stspng": "Status pengembangan", "ckplyn": "Cakupan layanan", "kaptpa": "Kapasitas TPA", "artpa": "Area TPA",
    "jnssmp": "Jenis sistem", "jnsspl": "Jenis sistem", "thnmop": "Tahun mulai operasi",
    "tgt_hunian": "Target hunian", "sumb_dana": "Sumber dana", "biaya": "Biaya", "jml_unit": "Jumlah unit",
    "tipe_unit": "Tipe unit", "thn_bang": "Tahun bangun", "kd_ruas": "Kode ruas", "panjang": "Panjang (km)",
    "ket": "Jenis penanganan", "disclaimer": "Catatan sumber", "data_ver": "Versi data",
}


def baca(path):
    g = gpd.read_file(path, engine="pyogrio", on_invalid="ignore")
    if g.crs is None or g.crs.to_epsg() != 4326:
        g = g.set_crs(4326) if g.crs is None else g.to_crs(4326)
    return g


def baris_layer(g, layer):
    rows, diperbaiki, buang = [], 0, 0
    kolom = [c for c in g.columns if c != "geometry" and c not in BUANG]
    for _, r in g.iterrows():
        geom = r.geometry
        if geom is None or geom.is_empty:
            buang += 1
            continue
        if geom.has_z:
            geom = shapely.force_2d(geom)
        if not geom.is_valid:
            geom = shapely.make_valid(geom)
            diperbaiki += 1
        if layer in SIMPLIFY_LAYER:
            sederhana = geom.simplify(SIMPLIFY_DERAJAT, preserve_topology=True)
            geom = sederhana if not sederhana.is_empty else geom
        attrs = {}
        for c in kolom:
            v = _clean_value(r[c])
            if v in (None, "", "-"):
                continue
            label = LABEL.get(c, c)
            attrs.setdefault(label, v)
        if layer == RENCUM:
            attrs["_warna"] = WARNA_RENCUM.get(str(r.get("ket") or "").upper(), "#7C3AED")
            attrs["_lebar"] = 3
        attrs["Sumber"] = "SHP Infrastruktur 2026 (Drive Konektivitas, 27-09-2026)"
        rows.append((Json(attrs), geom.wkb_hex))
    return rows, diperbaiki, buang


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cek", action="store_true")
    a = ap.parse_args()
    if not SUMBER.exists():
        sys.exit(f"Folder sumber {SUMBER} tidak ada -- ekstrak dulu zip di docs/10102026/ ke Maps/_sumber_infrastruktur_2026/")
    siap = []
    for rel, bucket, layer in LAYERS:
        g = baca(SUMBER / rel)
        rows, perbaiki, buang = baris_layer(g, layer)
        if len(rows) + buang != len(g) or buang:
            sys.exit(f"DITOLAK {layer}: sumber {len(g)} fitur, siap {len(rows)}, kosong {buang}")
        print(f"OK {bucket} / {layer}: {len(rows)} fitur ({g.geom_type.iloc[0]}), geometri diperbaiki {perbaiki}")
        siap.append((rel, bucket, layer, rows))
    if a.cek:
        print("Mode --cek: tidak menulis ke database.")
        return
    with db_cursor() as cur:
        for rel, bucket, layer, rows in siap:
            cur.execute("DELETE FROM map_layers WHERE provinsi=%s AND kabupaten='' AND layer=%s", (bucket, layer))
            cur.executemany(
                "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
                "VALUES (%s, '', %s, %s, ST_GeomFromWKB(decode(%s, 'hex'), 4326))",
                [(bucket, layer, attrs, wkb) for attrs, wkb in rows])
            cur.execute("""
                INSERT INTO map_layer_meta (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp)
                SELECT %s, '', %s, %s, COUNT(*),
                       ROUND((SUM(pg_column_size(geom) + pg_column_size(attrs)) / 1048576.0)::numeric, 2), %s
                FROM map_layers WHERE provinsi = %s AND kabupaten = '' AND layer = %s
                ON CONFLICT (provinsi, kabupaten, layer) DO UPDATE SET label = EXCLUDED.label,
                    feature_count = EXCLUDED.feature_count, size_mb = EXCLUDED.size_mb,
                    source_shp = EXCLUDED.source_shp, imported_at = now()""",
                (bucket, layer, layer, "_sumber_infrastruktur_2026/SHP Infrastruktur/" + rel, bucket, layer))
            cur.execute("SELECT feature_count, size_mb FROM map_layer_meta WHERE provinsi=%s AND kabupaten='' AND layer=%s",
                        (bucket, layer))
            r = cur.fetchone()
            print(f"DB {bucket} / {layer}: {r['feature_count']} fitur, {r['size_mb']} MB")
    print("Selanjutnya: python scripts/build_map_layer_wilayah.py (isi wilayah_provinsi utk pecahan per provinsi)")


if __name__ == "__main__":
    main()
