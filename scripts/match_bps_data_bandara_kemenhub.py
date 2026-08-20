# -*- coding: utf-8 -*-
"""Name-match bps_data_bandara (251 bandara, xlsx BPS) ke bandara_kemenhub
(596 bandara, live scrape hubud.kemenhub.go.id) -- isi kolom
bandara_kemenhub_id + match_skor di bps_data_bandara. BUKAN penggabungan/
penimpaan data, murni referensi silang (lihat komentar di
scripts/schema_bps_data_bandara.sql untuk alasan kedua tabel tetap
terpisah). TIDAK terkait usulan_inpres/IJD.

Strategi: cocokkan dalam kabupaten yang sama dulu (normalisasi "KABUPATEN
X"/"KOTA X" -> "X"), fallback ke provinsi yang sama kalau kabupaten tak
ketemu persis -- lalu pilih skor kemiripan nama tertinggi (difflib
SequenceMatcher) di antara kandidat. Skor < MIN_SKOR tidak disimpan
(bandara_kemenhub_id tetap NULL, dianggap tak ketemu drpd match salah).

Idempotent: UPDATE ulang tiap run (overwrite match sebelumnya).

Usage (venv aktif):
    python scripts/match_bps_data_bandara_kemenhub.py
"""
import io
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from db import db_cursor as pg_cursor  # noqa: E402

MIN_SKOR_KABUPATEN = 0.55   # kandidat dari kabupaten yg sama -- prior kuat, ambang longgar
MIN_SKOR_PROVINSI = 0.80    # fallback provinsi (kabupaten tak ketemu sama sekali) -- prior lemah,
                            # perlu kemiripan nama jauh lebih tinggi supaya tak salah pasang
                            # bandara lain di provinsi yg sama (kejadian nyata: "Kuala Batu"
                            # di Aceh Barat Daya -- yg memang absen dari bandara_kemenhub --
                            # sempat kepasang ke "Alas Lauser" di Aceh Tenggara skor 0.57)
_PREFIX_RE = re.compile(r"^(KABUPATEN|KOTA)\s+", re.IGNORECASE)


def _norm_kab(v):
    if not v:
        return ""
    v = _PREFIX_RE.sub("", v.strip()).upper()
    return re.sub(r"[^A-Z0-9]+", " ", v).strip()


def _norm_nama(v):
    if not v:
        return ""
    return re.sub(r"[^A-Z0-9 ]", "", v.upper()).strip()


def _skor(a, b):
    return SequenceMatcher(None, _norm_nama(a), _norm_nama(b)).ratio()


def main():
    with pg_cursor() as cur:
        cur.execute("SELECT no, nama_bandara, provinsi, kabupaten FROM bps_data_bandara")
        bps_rows = cur.fetchall()
        cur.execute("SELECT bandara_id, nama_bandara, provinsi, kabupaten FROM bandara_kemenhub")
        kh_rows = cur.fetchall()

    by_kab, by_prov = {}, {}
    for r in kh_rows:
        by_kab.setdefault(_norm_kab(r["kabupaten"]), []).append(r)
        by_prov.setdefault((r["provinsi"] or "").strip().upper(), []).append(r)

    matched = tidak_ketemu = rendah = 0
    with pg_cursor() as cur:
        for row in bps_rows:
            kab_key = _norm_kab(row["kabupaten"])
            kandidat = by_kab.get(kab_key)
            ambang = MIN_SKOR_KABUPATEN
            if not kandidat:
                kandidat = by_prov.get((row["provinsi"] or "").strip().upper(), [])
                ambang = MIN_SKOR_PROVINSI
            if not kandidat:
                tidak_ketemu += 1
                continue
            terbaik = max(kandidat, key=lambda k: _skor(row["nama_bandara"], k["nama_bandara"]))
            skor = _skor(row["nama_bandara"], terbaik["nama_bandara"])
            if skor < ambang:
                rendah += 1
                print(f"  skor rendah ({skor:.2f}): '{row['nama_bandara']}' ({row['kabupaten']}) "
                      f"vs kandidat terbaik '{terbaik['nama_bandara']}' -- dilewati")
                cur.execute(
                    "UPDATE bps_data_bandara SET bandara_kemenhub_id = NULL, match_skor = NULL WHERE no = %s",
                    (row["no"],),
                )
                continue
            cur.execute(
                "UPDATE bps_data_bandara SET bandara_kemenhub_id = %s, match_skor = %s WHERE no = %s",
                (terbaik["bandara_id"], round(skor, 3), row["no"]),
            )
            matched += 1

    print(f"\nSelesai: {matched} matched, {rendah} skor rendah (dilewati), {tidak_ketemu} tanpa kandidat sama sekali.")
    print(f"Total bps_data_bandara: {len(bps_rows)}")


if __name__ == "__main__":
    main()
