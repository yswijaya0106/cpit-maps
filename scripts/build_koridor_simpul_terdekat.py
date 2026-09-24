# -*- coding: utf-8 -*-
"""Hitung jarak terdekat tiap koridor PETA KORIDOR ke bandara & pelabuhan.

Satu baris per (NO_KORIDOR, kabupaten) di layer 'PETA KORIDOR' (map_layers);
geometri koridor = gabungan semua ruasnya (disederhanakan ~50 m supaya cepat;
galat jarak << 1 km). Simpul: layer BANDARA/Bandara dan
PELABUHAN/Pelabuhan Nasional dan PELABUHAN PENYEBERANGAN/PP (titik, di map_layers). Kandidat terdekat dicari
dengan KNN (<->) atas CTE titik (256 bandara/359 pelabuhan, tanpa indeks), lalu jaraknya dihitung geodesik
(::geography). Hasil -> koridor_simpul_terdekat, ditampilkan di menu "Data".
kode_kab diambil dari bappenas_koridor (via no_koridor); pulau dari
wilayah_pulau.py berdasarkan kode provinsi (nama provinsi -> penduduk_kecamatan).
Idempotent (DELETE + reinsert) -- jalankan ulang setelah PETA KORIDOR/simpul
diimpor ulang.

Usage (venv aktif):
    python scripts/build_koridor_simpul_terdekat.py
"""
import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from db import db_cursor  # noqa: E402
from wilayah_pulau import PULAU_BY_KODE_PROVINSI  # noqa: E402

SQL = """
WITH kor AS MATERIALIZED (
  SELECT attrs->>'NO_KORIDOR' AS no_koridor,
         MAX(attrs->>'NAMA_KORID') AS nama_koridor,
         provinsi, kabupaten,
         COUNT(*) AS jumlah_ruas,
         SUM(NULLIF(attrs->>'PANJANG_KM', '')::numeric) AS panjang_km,
         ST_Collect(ST_Simplify(geom, 0.0005)) AS g
  FROM map_layers
  WHERE layer = 'PETA KORIDOR' AND attrs->>'NO_KORIDOR' IS NOT NULL
  GROUP BY 1, provinsi, kabupaten
),
band AS MATERIALIZED (
  SELECT attrs->>'Name' AS nama, attrs->>'Kelas' AS kelas, geom, geom::geography AS geog
  FROM map_layers WHERE provinsi = 'BANDARA' AND layer = 'Bandara'
),
pen AS MATERIALIZED (
  SELECT COALESCE(attrs->>'NAMOBJ', attrs->>'LINTAS') AS nama, attrs->>'LINTAS' AS lintas, geom, geom::geography AS geog
  FROM map_layers WHERE provinsi = 'PELABUHAN PENYEBRANGAN' AND layer = 'PP'
),
pel AS MATERIALIZED (
  SELECT attrs->>'Name' AS nama, attrs->>'hierarki' AS hierarki, geom, geom::geography AS geog
  FROM map_layers WHERE provinsi = 'PELABUHAN' AND layer = 'Pelabuhan Nasional'
)
SELECT k.no_koridor, k.nama_koridor, k.provinsi, k.kabupaten, k.jumlah_ruas, k.panjang_km,
       b.nama AS bandara, b.kelas AS kelas_bandara,
       ROUND((ST_Distance(k.g::geography, b.geog) / 1000)::numeric, 2) AS jarak_bandara_km,
       n.nama AS penyeberangan, n.lintas AS lintas_penyeberangan,
       ROUND((ST_Distance(k.g::geography, n.geog) / 1000)::numeric, 2) AS jarak_penyeberangan_km,
       p.nama AS pelabuhan, p.hierarki AS hierarki_pelabuhan,
       ROUND((ST_Distance(k.g::geography, p.geog) / 1000)::numeric, 2) AS jarak_pelabuhan_km
FROM kor k
LEFT JOIN LATERAL (
  SELECT * FROM band ORDER BY band.geom <-> k.g LIMIT 1
) b ON TRUE
LEFT JOIN LATERAL (
  SELECT * FROM pen ORDER BY pen.geom <-> k.g LIMIT 1
) n ON TRUE
LEFT JOIN LATERAL (
  SELECT * FROM pel ORDER BY pel.geom <-> k.g LIMIT 1
) p ON TRUE
"""


def main():
    t0 = time.time()
    with db_cursor() as cur:
        with open(Path(__file__).with_name("schema_koridor_simpul_terdekat.sql"), encoding="utf-8") as f:
            cur.execute(f.read())
        cur.execute("SELECT DISTINCT provinsi, kode_provinsi FROM penduduk_kecamatan")
        kode_prov = {r["provinsi"].upper(): r["kode_provinsi"] for r in cur.fetchall()}
        cur.execute("SELECT no_koridor, MIN(kode_kab) AS kode_kab FROM bappenas_koridor "
                    "WHERE kode_kab IS NOT NULL GROUP BY no_koridor")
        kab_by_kor = {r["no_koridor"]: int(r["kode_kab"]) for r in cur.fetchall()}
        cur.execute(SQL)
        rows = cur.fetchall()
        out = []
        for r in rows:
            kp = kode_prov.get((r["provinsi"] or "").upper())
            out.append((
                r["no_koridor"], r["nama_koridor"], PULAU_BY_KODE_PROVINSI.get(kp), r["provinsi"], kp,
                r["kabupaten"], kab_by_kor.get(r["no_koridor"]), r["jumlah_ruas"], r["panjang_km"],
                r["bandara"], r["kelas_bandara"], r["jarak_bandara_km"],
                r["pelabuhan"], r["hierarki_pelabuhan"], r["jarak_pelabuhan_km"],
                r["penyeberangan"], r["lintas_penyeberangan"], r["jarak_penyeberangan_km"],
            ))
        cur.execute("DELETE FROM koridor_simpul_terdekat")
        cur.executemany(
            "INSERT INTO koridor_simpul_terdekat (no_koridor, nama_koridor, pulau, provinsi, kode_provinsi, kabupaten_kota, kode_kab, "
            "jumlah_ruas, panjang_km, bandara_terdekat, kelas_bandara, jarak_bandara_km, pelabuhan_terdekat, "
            "hierarki_pelabuhan, jarak_pelabuhan_km, penyeberangan_terdekat, lintas_penyeberangan, "
            "jarak_penyeberangan_km) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            out,
        )
    tanpa_pulau = sum(1 for o in out if o[2] is None)
    print(f"Selesai {time.time() - t0:.1f}s: {len(out)} baris; tanpa pulau/kode provinsi: {tanpa_pulau}")


if __name__ == "__main__":
    main()
