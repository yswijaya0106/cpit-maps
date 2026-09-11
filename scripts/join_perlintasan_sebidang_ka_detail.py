# -*- coding: utf-8 -*-
"""Gabungkan atribut detail teknis/ekonomi dari tabel penanganan_ss_ka_tahap
(sumber: xlsx "[rencum asli] PENANGANAN SS KA PERTAHAP.xlsx", 136 baris,
non-spasial) ke titik overlay peta "PERLINTASAN SEBIDANG KA"
(map_layers, sumber: shapefile "Railway Crossing per Tahap", 136 titik) --
supaya popup identify di peta menampilkan nama_ruas/nomor_ruas/biaya/EIRR/
BCR/NPV/rangking, bukan cuma Name+Tahap mentah dari shp.

TIDAK ADA KEY GABUNG YANG BERSIH antar 2 sumber ini (notasi_jpl di xlsx
kadang cuma angka polos "32" sedangkan Name di shp "JPL 32"; kadang xlsx
sama sekali tidak punya notasi_jpl "-" dan cuma punya nama_ruas). Jumlah
baris per Tahap identik persis (I=39, II=42, III=55) di kedua sumber, jadi
dipakai pencocokan best-effort: similarity string (difflib) antara Name shp
vs notasi_jpl ATAU nama_ruas xlsx, di-assign greedy (pasangan similarity
tertinggi duluan) per grup Tahap supaya tidak ada baris terpakai dobel.
Diverifikasi manual (2026-09-11): rata-rata similarity 94.7%, minimum yang
diperiksa manual tetap valid KECUALI 1 kasus genuinely ambigu -- shapefile
punya 2 titik dengan Name IDENTIK "Bts. Prov Aceh - Simpang Pangkalan Susu
II" (duplikat di sumber shp sendiri) sedangkan xlsx punya baris "...Susu I"
dan "...Susu II" terpisah; tidak ada cara membedakan dari nama saja, jadi
2 baris itu ditandai attrs["_pencocokan_ambigu"]=true.

Semua baris hasil match ditandai attrs["_sumber_detail"]="penanganan_ss_ka_tahap
(pencocokan nama, best-effort)" supaya transparan bahwa ini bukan join by-id
yang eksak.

Idempotent: UPDATE attrs (merge) per id map_layers yang match, aman dijalankan ulang.

Usage (venv aktif):
    python scripts/join_perlintasan_sebidang_ka_detail.py
"""
import re
import sys
import difflib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from psycopg.types.json import Json

from db import db_cursor as pg_cursor  # noqa: E402

PROVINSI = "PERLINTASAN SEBIDANG KA"
DETAIL_COLS = [
    "nama_ruas", "nomor_ruas", "indikasi_panjang_penanganan_m", "lokasi_jpl",
    "indikasi_kebutuhan_frontage", "prakiraan_biaya_konstruksi",
    "kebutuhan_lahan_m2", "prakiraan_biaya_lahan", "ketersediaan_desain",
    "nilai", "total_nilai", "rangking", "eirr", "bcr", "npv",
]
SUMBER_LABEL = "penanganan_ss_ka_tahap (pencocokan nama, best-effort)"
# Nama Name shp yang diketahui muncul >1x identik di sumber shp -- dua
# titik itu tidak bisa dibedakan dari nama saja (lihat docstring).
KNOWN_DUPLICATE_NAMES = {"Bts. Prov Aceh - Simpang Pangkalan Susu II"}


def norm(s):
    if not s:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", s.strip().lower()).strip()


def _to_jsonable(v):
    # Decimal dari psycopg tidak bisa langsung di-serialize psycopg.types.json.Json
    # via json standar -- ubah ke float/int dulu.
    try:
        from decimal import Decimal
        if isinstance(v, Decimal):
            return float(v)
    except ImportError:
        pass
    return v


def main():
    with pg_cursor() as cur:
        cur.execute(
            "SELECT id, attrs->>'Name' AS name, attrs->>'Tahap' AS tahap "
            "FROM map_layers WHERE provinsi=%s", (PROVINSI,),
        )
        shp_rows = cur.fetchall()
        cur.execute(f"SELECT id, tahap, notasi_jpl, {', '.join(DETAIL_COLS)} FROM penanganan_ss_ka_tahap")
        xlsx_rows = cur.fetchall()

    n_matched = n_ambigu = 0
    for tahap in ["I", "II", "III"]:
        shp_g = [r for r in shp_rows if r["tahap"] == tahap]
        xlsx_g = [r for r in xlsx_rows if r["tahap"] == tahap]
        pairs = []
        for s in shp_g:
            sn = norm(s["name"])
            for x in xlsx_g:
                sim = max(
                    difflib.SequenceMatcher(None, sn, norm(x["notasi_jpl"])).ratio(),
                    difflib.SequenceMatcher(None, sn, norm(x["nama_ruas"])).ratio(),
                )
                pairs.append((sim, s, x))
        pairs.sort(key=lambda t: -t[0])
        used_s, used_x = set(), set()
        for sim, s, x in pairs:
            if s["id"] in used_s or x["id"] in used_x:
                continue
            used_s.add(s["id"])
            used_x.add(x["id"])
            attrs_update = {c: _to_jsonable(x[c]) for c in DETAIL_COLS}
            attrs_update["_sumber_detail"] = SUMBER_LABEL
            if s["name"] in KNOWN_DUPLICATE_NAMES:
                attrs_update["_pencocokan_ambigu"] = True
                n_ambigu += 1
            with pg_cursor() as cur:
                cur.execute(
                    "UPDATE map_layers SET attrs = attrs || %s::jsonb WHERE id=%s",
                    (Json(attrs_update), s["id"]),
                )
            n_matched += 1

    print(f"Selesai: {n_matched}/{len(shp_rows)} titik di-update dengan detail "
          f"({n_ambigu} ditandai ambigu).")


if __name__ == "__main__":
    main()
