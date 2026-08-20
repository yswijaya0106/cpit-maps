# -*- coding: utf-8 -*-
"""Impor titik bandara (dari tabel bandara_kemenhub, hasil
scrape_bandara_kemenhub.py) ke map_layers sebagai overlay peta baru
(provinsi="BANDARA KEMENHUB") -- pola sama persis dgn
import_maskapai_organisasi_to_postgis.py: sumbernya tabel database
sendiri (sudah punya lat/lon dari link "Buka di Google Maps" pada
halaman detail), bukan file .shp/xlsx. TIDAK terkait usulan_inpres/IJD.

BEDA dari layer "Bandara" (SHP RBI lama, provinsi="BANDARA") -- itu
tetap ada, tidak ditimpa; ini layer overlay TERPISAH, live & lebih
lengkap (596 vs cuma titik+nama SHP). attrs cuma ringkasan Data Umum +
"Bandara ID" (kunci exact match ke GET /api/bandara-kemenhub/{id}) --
rute/fasilitas/terdekat/galeri TIDAK dimasukkan ke attrs (identify popup
Google Maps Data cuma render properti flat key:value, bukan nested
array/object) -- ditampilkan lewat join di popup identify
(attachBandaraKemenhubJoin, static/js/map-tools.js), sama spt Maskapai/
Kantor SAR.

Idempotent: DELETE + reinsert penuh (596 baris, tidak ada alasan utk
upsert per-baris).

Usage (venv aktif):
    python scripts/import_bandara_kemenhub_to_postgis.py
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
LAYER = "Bandara Kemenhub"


def main():
    with pg_cursor() as cur:
        cur.execute(
            "SELECT bandara_id, icao, iata, nama_bandara, provinsi, kabupaten, kecamatan, "
            "penggunaan, kelas, pengelola, tkbn, status_operasi, hierarki, pkp_pk, klasifikasi, "
            "critical_aircraft, pesawat_beroperasi, lalu_lintas_tahun, lalu_lintas_pesawat, "
            "lalu_lintas_penumpang, lalu_lintas_kargo_kg, detail_url, lat, lon "
            "FROM bandara_kemenhub WHERE lat IS NOT NULL AND lon IS NOT NULL"
        )
        rows = cur.fetchall()
    print(f"{len(rows)} bandara punya koordinat.")

    records = []
    for r in rows:
        attrs = {
            "Name": r["nama_bandara"],
            "Bandara ID": r["bandara_id"],
            "ICAO": r["icao"],
            "IATA": r["iata"],
            "Provinsi": r["provinsi"],
            "Kabupaten": r["kabupaten"],
            "Kecamatan": r["kecamatan"],
            "Penggunaan": r["penggunaan"],
            "Kelas": r["kelas"],
            "Pengelola": r["pengelola"],
            "TKBN": r["tkbn"],
            "Status Operasi": r["status_operasi"],
            "Hierarki": r["hierarki"],
            "PKP-PK": r["pkp_pk"],
            "Klasifikasi": r["klasifikasi"],
            "Critical Aircraft": r["critical_aircraft"],
            "Pesawat Beroperasi": r["pesawat_beroperasi"],
            f"Lalu Lintas {r['lalu_lintas_tahun']} - Pesawat": r["lalu_lintas_pesawat"] if r["lalu_lintas_tahun"] else None,
            f"Lalu Lintas {r['lalu_lintas_tahun']} - Penumpang": r["lalu_lintas_penumpang"] if r["lalu_lintas_tahun"] else None,
            "Detail URL": r["detail_url"],
        }
        attrs = {k: v for k, v in attrs.items() if v is not None}
        records.append((PROVINSI, KABUPATEN, LAYER, Json(attrs), float(r["lon"]), float(r["lat"])))

    with pg_cursor() as cur:
        cur.execute("DELETE FROM map_layers WHERE provinsi=%s AND kabupaten=%s AND layer=%s", (PROVINSI, KABUPATEN, LAYER))
        cur.executemany(
            "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom) "
            "VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))",
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
            (PROVINSI, KABUPATEN, LAYER, LAYER, len(records), 0, "tabel bandara_kemenhub (bukan file)"),
        )

    print(f"Selesai: {len(records)} titik bandara diimpor ke map_layers (provinsi='{PROVINSI}').")


if __name__ == "__main__":
    main()
