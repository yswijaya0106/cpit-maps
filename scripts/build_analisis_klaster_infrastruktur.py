# -*- coding: utf-8 -*-
"""Infrastruktur logistik & pendukung TERDEKAT per Klaster/Subklaster Merauke (layer "SUBKLASTER",
32 poligon) -- pelengkap build_analisis_klaster_subklaster.py (bandara/pelabuhan RBI/koridor/jalan +
rute OSRM), yang TIDAK diubah atau dijalankan ulang oleh skrip ini (11 Okt 2026, permintaan user).

Sasaran (semua jarak GARIS LURUS geodesik dari tepi poligon subklaster, bukan jarak tempuh):
  - Pelabuhan umum RIPN (hierarki PU/PP/PR/PL)          bucket PELABUHAN RIPN (import_pelabuhan_ripn.py)
  - Pelabuhan & terminal khusus RTRW Papua Selatan       RTRW / Papua Selatan, Jenis Pelabuhan*/Terminal Khusus
  - Pelabuhan perikanan, pasar, terminal BBM             LOGISTIK & EKONOMI (import_infrastruktur_2026.py)
  - Pusat permukiman (PKN/PKSN/PKW/PKL), pembangkit/gardu, telekomunikasi, jaringan irigasi
                                                         RTRW / Papua Selatan (import_rtrw_papua_selatan_struktur_ruang.py)
Jalankan SETELAH ketiga importer itu.

Hasil:
  1. Tabel `subklaster_infrastruktur_terdekat` (satu baris per subklaster x jenis), menu "Data".
  2. attrs layer "SUBKLASTER" (32): teks "Terdekat - <jenis>" + array tersembunyi `_infra_terdekat`
     (titik utk digambar saat poligon diklik, attachSubklasterAnalisis di map-tools.js).
     Layer "SUBKLASTER DETAIL - *" (10.328 poligon) HANYA menerima teks ringkas, TANPA array:
     array yang disalin ke poligon detail pernah membuat PostgreSQL staging OOM (lihat
     KUNCI_BERAT_DETAIL di build_analisis_klaster_subklaster.py). Frontend mengambil array dari induk.

Pengaman: setiap subklaster harus mendapat hasil utk setiap jenis yang punya fitur; jarak SQL
dicek ulang independen (shapely, proyeksi UTM 54S) utk 3 subklaster -- beda > 2% ditolak.
Idempotent (DELETE + reinsert tabel; merge attrs menimpa kunci yang sama, kunci lama dihapus dulu).

Usage (venv aktif):
    python scripts/build_analisis_klaster_infrastruktur.py --cek
    python scripts/build_analisis_klaster_infrastruktur.py
"""
import argparse
import io
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
import geopandas as gpd  # noqa: E402
import shapely  # noqa: E402
from psycopg.types.json import Json  # noqa: E402

from db import db_cursor  # noqa: E402

BUCKET = "KLASTER SUBKLASTER"
RTRW = ("RTRW", "Papua Selatan")
L_SIMPUL = "Simpul Transportasi & Logistik (RTRW Papua Selatan)"
# (jenis, bucket, kabupaten, layer, filter SQL tambahan, ekspresi nama, ekspresi keterangan, warna, glyph)
SASARAN = [
    ("Pelabuhan umum (RIPN)", "PELABUHAN RIPN", "", "Pelabuhan Umum (RIPN)", "",
     "attrs->>'Nama Pelabuhan'", "attrs->>'Hierarki'", "#0d9488", "jangkar"),
    ("Pelabuhan (RTRW Papua Selatan)", *RTRW, L_SIMPUL, "AND attrs->>'Jenis' ILIKE 'Pelabuhan%%'",
     "attrs->>'Nama'", "attrs->>'Jenis' || ' (' || COALESCE(attrs->>'Status', '-') || ')'", "#0f766e", "jangkar"),
    ("Terminal khusus (RTRW Papua Selatan)", *RTRW, L_SIMPUL, "AND attrs->>'Jenis' = 'Terminal Khusus'",
     "attrs->>'Nama'", "attrs->>'Status'", "#a16207", "jangkar"),
    ("Pelabuhan perikanan", "LOGISTIK & EKONOMI", "", "Pelabuhan Perikanan", "",
     "attrs->>'Nama'", "attrs->>'Kelas'", "#0369a1", "kapal"),
    ("Pasar", "LOGISTIK & EKONOMI", "", "Pasar", "", "attrs->>'Nama'", "attrs->>'Hari operasi'", "#be185d", "gudang"),
    ("Terminal BBM", "LOGISTIK & EKONOMI", "", "Terminal BBM", "", "attrs->>'Nama'", "attrs->>'Status'", "#7c2d12", "gudang"),
    ("Pusat permukiman (RTRW)", *RTRW, "Sistem Pusat Permukiman (RTRW Papua Selatan)", "",
     "attrs->>'Nama'", "attrs->>'Jenis'", "#7c3aed", "bintang"),
    ("Pembangkit/gardu listrik (RTRW)", *RTRW, "Infrastruktur Energi (RTRW Papua Selatan)", "",
     "attrs->>'Nama'", "attrs->>'Jenis' || ' (' || COALESCE(attrs->>'Status', '-') || ')'", "#ca8a04", "titik"),
    ("Telekomunikasi (RTRW)", *RTRW, "Jaringan Telekomunikasi (RTRW Papua Selatan)", "",
     "attrs->>'Nama'", "attrs->>'Status'", "#475569", "titik"),
    ("Jaringan irigasi (RTRW)", *RTRW, "Jaringan Irigasi (RTRW Papua Selatan)", "",
     "attrs->>'Nama'", "attrs->>'Status'", "#2563eb", "titik"),
]
KUNCI_PREFIX = "Terdekat - "
# Jenis yg TIDAK punya fitur dalam MAKS_KM dari subklaster mana pun dilewati (bukan ditampilkan dgn
# jarak ribuan km): Terminal BBM -- sumber nasional tanpa satu pun titik di Papua (terdekat ~1.650 km).
MAKS_KM = 500
# Celah cakupan sumber yg harus ikut tampil supaya "terdekat" tidak dibaca sbg "tidak ada pasar di Merauke"
CATATAN_CAKUPAN = {
    "Pasar": "data titik pasar (SHP Infrastruktur 2026) hanya 2 di Papua Selatan (Agats, Kepi); pasar di "
             "Kab. Merauke tidak tercatat di sumber",
}
UTM54S = 32754

DDL = """
CREATE TABLE IF NOT EXISTS subklaster_infrastruktur_terdekat (
    id SERIAL PRIMARY KEY,
    klaster TEXT, subklaster TEXT,
    jenis TEXT,                -- jenis sasaran (lihat SASARAN di skrip)
    nama TEXT, keterangan TEXT,
    jarak_km NUMERIC(10, 2),   -- garis lurus geodesik dari tepi poligon subklaster (0 = di dalam/menyentuh)
    lat DOUBLE PRECISION, lon DOUBLE PRECISION,   -- titik terdekat pada fitur sasaran
    sumber_layer TEXT,
    dihitung_at TIMESTAMPTZ DEFAULT now()
);
"""


def hitung(cur):
    cur.execute("""
        SELECT attrs->>'Klaster' AS klaster, attrs->>'Subklaster' AS subklaster,
               ST_CollectionExtract(ST_MakeValid(geom), 3) AS g
        FROM map_layers WHERE provinsi = %s AND layer = 'SUBKLASTER' ORDER BY 1, 2""", (BUCKET,))
    subk = cur.fetchall()
    hasil, kosong = [], []
    for jenis, bucket, kab, layer, filt, e_nama, e_ket, warna, glyph in SASARAN:
        cur.execute(f"SELECT COUNT(*) n FROM map_layers WHERE provinsi=%s AND kabupaten=%s AND layer=%s {filt}",
                    (bucket, kab, layer))
        if cur.fetchone()["n"] == 0:
            kosong.append(jenis)
            continue
        for s in subk:
            # KNN planar 5 kandidat (pakai indeks) -> jarak geodesik terkecil
            cur.execute(f"""
                SELECT nama, ket, jarak_m, ST_Y(p) AS lat, ST_X(p) AS lon, ST_Y(r) AS ref_lat, ST_X(r) AS ref_lon
                FROM (SELECT {e_nama} AS nama, {e_ket} AS ket,
                             ST_Distance(geom::geography, %(g)s::geometry::geography) AS jarak_m,
                             ST_ClosestPoint(geom, %(g)s::geometry) AS p,
                             ST_ClosestPoint(%(g)s::geometry, geom) AS r
                      FROM map_layers
                      WHERE provinsi = %(b)s AND kabupaten = %(k)s AND layer = %(l)s {filt}
                      ORDER BY geom <-> %(g)s::geometry LIMIT 5) c
                ORDER BY jarak_m LIMIT 1""", {"g": s["g"], "b": bucket, "k": kab, "l": layer})
            r = cur.fetchone()
            hasil.append(dict(klaster=s["klaster"], subklaster=s["subklaster"], jenis=jenis, nama=r["nama"],
                              keterangan=r["ket"], jarak_km=round(r["jarak_m"] / 1000, 2), lat=r["lat"], lon=r["lon"],
                              ref_lat=r["ref_lat"], ref_lon=r["ref_lon"], warna=warna, glyph=glyph,
                              sumber_layer=f"{bucket}/{kab + '/' if kab else ''}{layer}", _g=s["g"]))
    for jenis in {h["jenis"] for h in hasil}:
        if min(float(h["jarak_km"]) for h in hasil if h["jenis"] == jenis) > MAKS_KM:
            kosong.append(f"{jenis} (terdekat > {MAKS_KM} km)")
            hasil = [h for h in hasil if h["jenis"] != jenis]
    for h in hasil:
        if h["jenis"] in CATATAN_CAKUPAN:
            h["keterangan"] = "; ".join(filter(None, [h["keterangan"], CATATAN_CAKUPAN[h["jenis"]]]))
    return subk, hasil, kosong


def cek_independen(cur, hasil, subk):
    """Jarak ulang dgn shapely di UTM 54S (Merauke) utk 3 subklaster pertama."""
    for s in subk[:3]:
        poly = gpd.GeoSeries([shapely.from_wkb(bytes.fromhex(s["g"]))], crs=4326).to_crs(UTM54S).iloc[0]
        for h in [h for h in hasil if h["subklaster"] == s["subklaster"] and h["klaster"] == s["klaster"]]:
            titik = gpd.GeoSeries([shapely.Point(h["lon"], h["lat"])], crs=4326).to_crs(UTM54S).iloc[0]
            km = poly.distance(titik) / 1000
            if abs(km - float(h["jarak_km"])) > max(0.2, 0.02 * km):
                raise SystemExit(f"DITOLAK: jarak {h['jenis']} utk {s['subklaster']}: SQL {h['jarak_km']} km vs shapely {km:.2f} km")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cek", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    with db_cursor() as cur:
        subk, hasil, kosong = hitung(cur)
        if not subk:
            sys.exit("DITOLAK: layer SUBKLASTER kosong -- jalankan import_subklaster_to_postgis.py dulu")
        n_jenis = len({h["jenis"] for h in hasil})
        if len(hasil) != len(subk) * n_jenis:
            sys.exit(f"DITOLAK: {len(hasil)} hasil, harus {len(subk)} x {n_jenis}")
        cek_independen(cur, hasil, subk)
        print(f"OK {len(subk)} subklaster x {n_jenis} jenis = {len(hasil)} hasil; jarak dicek ulang (shapely UTM 54S)"
              + (f"; jenis tanpa fitur (dilewati): {kosong}" if kosong else ""))
        for jenis in [x[0] for x in SASARAN if any(h["jenis"] == x[0] for h in hasil)]:
            js = sorted(float(h["jarak_km"]) for h in hasil if h["jenis"] == jenis)
            print(f"   {jenis}: jarak min {js[0]:.1f} / median {js[len(js) // 2]:.1f} / maks {js[-1]:.1f} km")
        if a.cek:
            print("Mode --cek: tidak menulis ke database.")
            return

        cur.execute(DDL)
        cur.execute("DELETE FROM subklaster_infrastruktur_terdekat")
        kol = ["klaster", "subklaster", "jenis", "nama", "keterangan", "jarak_km", "lat", "lon", "sumber_layer"]
        cur.executemany(f"INSERT INTO subklaster_infrastruktur_terdekat ({', '.join(kol)}) VALUES "
                        f"({', '.join(['%s'] * len(kol))})", [[h[c] for c in kol] for h in hasil])

        # attrs: hapus kunci lama berawalan "Terdekat - " + _infra_terdekat, lalu merge
        per_subk = {}
        for h in hasil:
            per_subk.setdefault((h["klaster"], h["subklaster"]), []).append(h)
        n_induk = n_detail = 0
        for (klaster, subklaster), hs in per_subk.items():
            teks = {f"{KUNCI_PREFIX}{h['jenis']}": f"{h['nama'] or '?'}"
                    f"{' - ' + h['keterangan'] if h['keterangan'] else ''} ({float(h['jarak_km']):.1f} km garis lurus)"
                    for h in hs}
            arr = [{"jenis": h["jenis"], "nama": h["nama"], "jarak_km": float(h["jarak_km"]), "lat": h["lat"],
                    "lon": h["lon"], "ref_lat": h["ref_lat"], "ref_lon": h["ref_lon"], "warna": h["warna"],
                    "glyph": h["glyph"]} for h in hs]
            hapus = """attrs - '_infra_terdekat' - ARRAY(SELECT k FROM jsonb_object_keys(attrs) k
                                                           WHERE k LIKE 'Terdekat - %%')"""
            cur.execute(f"UPDATE map_layers SET attrs = ({hapus}) || %s::jsonb "
                        "WHERE provinsi=%s AND layer='SUBKLASTER' AND attrs->>'Klaster'=%s AND attrs->>'Subklaster'=%s",
                        (Json({**teks, "_infra_terdekat": arr}), BUCKET, klaster, subklaster))
            n_induk += cur.rowcount
            cur.execute(f"UPDATE map_layers SET attrs = ({hapus}) || %s::jsonb "
                        "WHERE provinsi=%s AND layer LIKE 'SUBKLASTER DETAIL - %%' "
                        "AND attrs->>'Klaster'=%s AND attrs->>'Subklaster'=%s",
                        (Json(teks), BUCKET, klaster, subklaster))
            n_detail += cur.rowcount
        cur.execute("UPDATE map_layer_meta SET imported_at = now() "
                    "WHERE provinsi=%s AND (layer='SUBKLASTER' OR layer LIKE 'SUBKLASTER DETAIL - %%')", (BUCKET,))
        print(f"DB subklaster_infrastruktur_terdekat: {len(hasil)} baris; attrs: {n_induk} poligon SUBKLASTER, "
              f"{n_detail} poligon detail ({time.time() - t0:.1f}s)")


if __name__ == "__main__":
    main()
