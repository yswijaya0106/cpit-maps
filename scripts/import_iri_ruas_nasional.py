# -*- coding: utf-8 -*-
"""Impor rekap kondisi & kemantapan jalan nasional berdasarkan survei IRI
(docs/250820206/Data_rekap_iri_centerline_km_mean_sk_Semua Provinsi_2026_1_05-08-2026.xlsx,
sheet "Detail Data IRI", status Juli 2026) ke tabel `iri_ruas_nasional`, lalu
MENAMBAHKAN atribut ringkasnya ke layer jalan nasional di `map_layers`.

Satu baris per ruas (kunci `Linkid` = LINKID layer jalan nasional; 3.306 ruas,
100% cocok dgn layer "Jalan Nasional" dan 6 layer LN_JALAN_NASIONAL_PULAU_*).
Baris terakhir "TOTAL" dilewati. Kolom sumber: panjang SK, IRI marginal, kondisi
Baik/Sedang/Rusak Ringan/Rusak Berat + Mantap/Tidak Mantap (km dan %) utk jalan
berperkerasan (paved), tak berperkerasan (unpaved) dan total, serta rata-rata IRI.

Atribut yang ditambahkan ke `map_layers.attrs` (provinsi "JALAN NASIONAL", layer
ber-LINKID) memakai nilai TOTAL (paved + unpaved), muncul di popup identify:
"IRI rata-rata", "Kondisi Baik/Sedang/Rusak Ringan/Rusak Berat (km | %)",
"Mantap"/"Tidak mantap", dst. Idempotent (UPSERT tabel; atribut ditimpa kunci
per kunci). Cache layer di server (`_map_layer_geojson_cache`): restart server
setelah menjalankan skrip ini.

Usage (venv aktif):
    python scripts/import_iri_ruas_nasional.py [path.xlsx]
"""
import glob
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import openpyxl  # noqa: E402
from psycopg.types.json import Json  # noqa: E402

from db import db_cursor  # noqa: E402

XLSX_GLOB = str(ROOT / "docs" / "250820206" / "Data_rekap_iri_centerline*Semua Provinsi*.xlsx")
KONDISI = ["baik", "sedang", "rusak_ringan", "rusak_berat", "mantap", "tidak_mantap"]
KONDISI_LABEL = {"baik": "Baik", "sedang": "Sedang", "rusak_ringan": "Rusak ringan", "rusak_berat": "Rusak berat",
                 "mantap": "Mantap", "tidak_mantap": "Tidak mantap"}


def kolom_tabel():
    """(nama_kolom, indeks_sumber) berurutan sesuai layout sheet."""
    cols = [("panjang_sk_km", 5), ("iri_marginal_paved_km", 6), ("iri_marginal_paved_pct", 7)]
    for blok, awal in (("paved", 8), ("unpaved", 22), ("total", 34)):
        if blok == "unpaved":
            cols += [("iri_marginal_unpaved_km", 20), ("iri_marginal_unpaved_pct", 21)]
        for i, k in enumerate(KONDISI):
            cols += [(f"{blok}_{k}_km", awal + 2 * i), (f"{blok}_{k}_pct", awal + 2 * i + 1)]
    cols.append(("rata2_iri", 46))
    return cols


def f(v):
    return float(v) if isinstance(v, (int, float)) else None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else (glob.glob(XLSX_GLOB) or [None])[0]
    if not path:
        sys.exit("xlsx tidak ditemukan")
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    status = ""
    baris = []
    for i, r in enumerate(ws.iter_rows(values_only=True), 1):
        if i == 3 and r[0]:
            status = str(r[0]).replace("STATUS :", "").strip()
        if i < 7 or r[0] in (None, ""):
            continue
        lid = str(r[0]).strip()
        if lid.upper() == "TOTAL":
            continue
        baris.append((lid, r))
    cols = kolom_tabel()
    ddl_cols = ",\n  ".join(f"{n} NUMERIC(14, 4)" for n, _ in cols)
    with db_cursor() as cur:
        cur.execute(f"""
CREATE TABLE IF NOT EXISTS iri_ruas_nasional (
  linkid TEXT PRIMARY KEY,
  provinsi TEXT, link_name TEXT, lintas TEXT, tiga_t TEXT,
  {ddl_cols},
  status_survei TEXT
)""")
        nama = ", ".join(n for n, _ in cols)
        ph = ", ".join(["%s"] * (len(cols) + 6))
        upd = ", ".join(f"{n}=EXCLUDED.{n}" for n in ["provinsi", "link_name", "lintas", "tiga_t", "status_survei"] + [n for n, _ in cols])
        cur.executemany(
            f"INSERT INTO iri_ruas_nasional (linkid, provinsi, link_name, lintas, tiga_t, {nama}, status_survei) "
            f"VALUES ({ph}) ON CONFLICT (linkid) DO UPDATE SET {upd}",
            [(lid, r[1], r[2], r[3], r[4], *[f(r[i]) for _, i in cols], status) for lid, r in baris])
        print(f"tabel iri_ruas_nasional: {len(baris)} ruas (status {status})")

        # tambahkan atribut ke layer jalan nasional (semua layer ber-LINKID di bucket JALAN NASIONAL)
        diperbarui = 0
        for lid, r in baris:
            v = {n: f(r[i]) for n, i in cols}
            at = {"IRI rata-rata": v["rata2_iri"], "Panjang SK survei IRI (km)": v["panjang_sk_km"],
                  "Lintas (survei IRI)": r[3], "Wilayah 3T": r[4],
                  "Survei IRI": status or None}
            for k in KONDISI:
                at[f"Kondisi {KONDISI_LABEL[k]} (km)"] = v[f"total_{k}_km"]
                at[f"Kondisi {KONDISI_LABEL[k]} (%)"] = v[f"total_{k}_pct"]
            unp = sum(v[f"unpaved_{k}_km"] or 0 for k in ("baik", "sedang", "rusak_ringan", "rusak_berat"))
            at["Tak berperkerasan (km)"] = round(unp, 2)
            at = {k: x for k, x in at.items() if x is not None and x != "-"}
            cur.execute(
                "UPDATE map_layers SET attrs = attrs || %s::jsonb "
                "WHERE provinsi='JALAN NASIONAL' AND attrs->>'LINKID' = %s", (Json(at), lid))
            diperbarui += cur.rowcount
        print(f"atribut IRI ditambahkan ke {diperbarui} fitur layer jalan nasional")
        cur.execute("SELECT COUNT(*) n FROM map_layers WHERE provinsi='JALAN NASIONAL' AND attrs->>'LINKID' IS NOT NULL "
                    "AND NOT (attrs ? 'IRI rata-rata')")
        print(f"fitur ber-LINKID TANPA data IRI: {cur.fetchone()['n']}")


if __name__ == "__main__":
    main()
