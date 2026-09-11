# -*- coding: utf-8 -*-
"""Impor rute penerbangan (dari tabel bandara_kemenhub_rute, hasil
scrape_bandara_kemenhub.py) ke map_layers sebagai overlay peta baru --
garis lurus (ST_MakeLine dua titik) dari bandara asal ke koordinat tujuan
(tujuan_lat/tujuan_lon, sudah diisi scraper dari blok Highcharts.mapChart
di halaman detail bandara). Sibling dari import_bandara_kemenhub_to_postgis.py
(titik bandara) -- sama-sama provinsi="BANDARA KEMENHUB", jadi otomatis
muncul sebagai layer TAMBAHAN di kategori tree yang sama (bandara-kemenhub,
static/js/maps-overlay.js), tanpa perlu perubahan kode frontend: tree/klik/
identify popup untuk LineString sudah generik (lihat applyLayerStyle di
maps-overlay.js utk styling garis, onFeatureClick di map-tools.js utk popup
atribut).

Baris yang bandara asal ATAU tujuannya tidak punya koordinat dilewati (tidak
bisa digambar). TIDAK terkait usulan_inpres/IJD.

Idempotent: DELETE + reinsert penuh -- sama pola dgn
import_bandara_kemenhub_to_postgis.py.

Usage (venv aktif):
    python scripts/import_bandara_kemenhub_rute_to_postgis.py
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from psycopg.types.json import Json

from db import db_cursor as pg_cursor  # noqa: E402

PROVINSI = "BANDARA KEMENHUB"
KABUPATEN = ""
LAYER = "Rute Penerbangan (Kemenhub)"


def main():
    with pg_cursor() as cur:
        cur.execute(
            "SELECT r.bandara_id, b.nama_bandara AS asal, b.lat AS asal_lat, b.lon AS asal_lon, "
            "r.tipe, r.tujuan, r.maskapai, r.pesawat, r.frekuensi, r.tujuan_lat, r.tujuan_lon "
            "FROM bandara_kemenhub_rute r "
            "JOIN bandara_kemenhub b ON b.bandara_id = r.bandara_id "
            "WHERE b.lat IS NOT NULL AND b.lon IS NOT NULL "
            "AND r.tujuan_lat IS NOT NULL AND r.tujuan_lon IS NOT NULL"
        )
        rows = cur.fetchall()
    print(f"{len(rows)} rute punya koordinat asal+tujuan lengkap.")

    records = []
    for r in rows:
        attrs = {
            "Name": f"{r['asal']} - {r['tujuan']}",
            "Asal": r["asal"],
            "Tujuan": r["tujuan"],
            "Tipe": r["tipe"],
            "Maskapai": r["maskapai"],
            "Pesawat": r["pesawat"],
            "Frekuensi": r["frekuensi"],
            "Bandara ID": r["bandara_id"],
        }
        attrs = {k: v for k, v in attrs.items() if v is not None}
        records.append((
            PROVINSI, KABUPATEN, LAYER, Json(attrs),
            float(r["asal_lon"]), float(r["asal_lat"]),
            float(r["tujuan_lon"]), float(r["tujuan_lat"]),
        ))

    with pg_cursor() as cur:
        cur.execute("DELETE FROM map_layers WHERE provinsi=%s AND kabupaten=%s AND layer=%s", (PROVINSI, KABUPATEN, LAYER))
        cur.executemany(
            "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
            "VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakeLine(ST_MakePoint(%s, %s), ST_MakePoint(%s, %s)), 4326))",
            records,
        )
        cur.execute(
            """INSERT INTO map_layer_meta
                   (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (provinsi, kabupaten, layer) DO UPDATE SET
                   label=EXCLUDED.label, feature_count=EXCLUDED.feature_count,
                   size_mb=EXCLUDED.size_mb, source_shp=EXCLUDED.source_shp,
                   imported_at=now()""",
            (PROVINSI, KABUPATEN, LAYER, LAYER, len(records), 0, "tabel bandara_kemenhub_rute (bukan file)"),
        )

    print(f"Selesai: {len(records)} garis rute diimpor ke map_layers (provinsi='{PROVINSI}', layer='{LAYER}').")


if __name__ == "__main__":
    main()
