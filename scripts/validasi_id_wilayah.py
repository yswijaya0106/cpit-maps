"""Validasi penggunaan ID (kode BPS) wilayah di IJD dan data pendukungnya, terhadap ref_wilayah.

Read-only. Memeriksa:
  A. integritas ref_wilayah (satu kode = satu nama, hierarki kode konsisten)
  B. kode di tabel pendukung yang TIDAK ada di ref_wilayah (orphan), per level provinsi/kab/kec
  C. konsistensi hierarki kode di tabel yang punya beberapa level
  D. usulan_inpres: kelengkapan kode_kabupaten dan konflik kode_kecamatan vs kode_kabupaten
  E. tabel yang hanya berisi NAMA wilayah (tanpa kode) dan tipe kolom kode yang tidak seragam

Usage (venv aktif):
    python scripts/validasi_id_wilayah.py

Exit code 1 bila ada temuan "MASALAH" yang belum dikenal (temuan yang sudah diketahui dan
didokumentasikan di docs/kajian_validasi_id_wilayah.md ditandai "DIKETAHUI", tidak menggagalkan).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import db_cursor  # noqa: E402

masalah = 0


def q(sql, args=None):
    with db_cursor() as cur:
        cur.execute(sql, args)
        return [dict(r) for r in cur.fetchall()]


def lapor(ok, teks, diketahui=False):
    global masalah
    tag = "OK       " if ok else ("DIKETAHUI" if diketahui else "MASALAH  ")
    if not ok and not diketahui:
        masalah += 1
    print(f"  [{tag}] {teks}")


# ---------------------------------------------------------------- A
print("A. Integritas ref_wilayah")
if not q("SELECT to_regclass('public.ref_wilayah') AS t")[0]["t"]:
    sys.exit("ref_wilayah belum ada -- jalankan scripts/build_ref_wilayah.py dulu")
n = q("SELECT COUNT(*) n, COUNT(DISTINCT kode_provinsi) p, COUNT(DISTINCT kode_kabupaten) k FROM ref_wilayah")[0]
print(f"  {n['n']} kecamatan, {n['p']} provinsi, {n['k']} kabupaten/kota")
lapor(q("SELECT COUNT(*) n FROM (SELECT kode_provinsi FROM ref_wilayah GROUP BY 1 HAVING COUNT(DISTINCT nama_provinsi) > 1) x")[0]["n"] == 0,
      "satu kode_provinsi = satu nama")
lapor(q("SELECT COUNT(*) n FROM (SELECT kode_kabupaten FROM ref_wilayah GROUP BY 1 HAVING COUNT(DISTINCT nama_kabupaten_kota) > 1) x")[0]["n"] == 0,
      "satu kode_kabupaten = satu nama")
lapor(q("SELECT COUNT(*) n FROM ref_wilayah WHERE kode_kecamatan / 1000 <> kode_kabupaten OR kode_kabupaten / 100 <> kode_provinsi")[0]["n"] == 0,
      "hierarki kode konsisten (kecamatan/1000 = kabupaten, kabupaten/100 = provinsi)")
lapor(q("SELECT COUNT(*) n FROM penduduk_kecamatan p WHERE NOT EXISTS (SELECT 1 FROM ref_wilayah r WHERE r.kode_kecamatan = p.kode_kecamatan)")[0]["n"] == 0,
      "ref_wilayah mencakup seluruh penduduk_kecamatan (jalankan build_ref_wilayah.py bila tidak)")

# ---------------------------------------------------------------- B
print("\nB. Kode di tabel pendukung yang tidak ada di ref_wilayah")
KAB = [  # (tabel, kolom, tipe) -- 'chr' = CHAR/varchar berisi angka
    ("bappenas_lokus_a", "kode_kabupaten", "int"), ("kawasan_tematik", "kode_kabupaten", "int"),
    ("simpul_transportasi", "kode_kabupaten", "int"), ("konektivitas_jaringan_jalan", "kode_kabupaten", "int"),
    ("kecamatan_data_turunan", "kode_kabupaten", "int"), ("usulan_kecamatan_dilalui", "kode_kabupaten", "int"),
    ("simpul_transportasi_kecamatan_radius", "kode_kabupaten", "int"), ("bps_api_kepadatan_kabupaten", "kode_kabupaten", "int"),
    ("pelabuhan_daerah", "kode_kabupaten", "int"), ("bps_data_bandara", "kode_kabupaten", "int"),
    ("usulan_inpres", "kode_kabupaten", "int"), ("usulan_inpres_riwayat", "kode_kabupaten", "int"),
    ("wilayah_mapping", "kode_kabupaten", "int"),
    ("bps_kabupaten_indeks_penanaman", "kode_kab", "chr"), ("bps_kabupaten_indeks_penanaman_raster", "kode_kab", "chr"),
    ("bps_kabupaten_jalan", "kode_kab", "chr"), ("bps_kabupaten_kendaraan", "kode_kab", "chr"),
    ("bps_kabupaten_padi", "kode_kab", "chr"), ("bps_kecamatan_demografi", "kode_kab", "chr"),
    ("bps_kecamatan_potensi_tematik", "kode_kab", "chr"), ("bps_kecamatan_produksi_komoditas", "kode_kab", "chr"),
    ("bappenas_koridor", "kode_kab", "chr"),
]
# orphan yang sudah diketahui: (tabel, kolom) -> alasan
DIKETAHUI = {
    ("bps_kabupaten_indeks_penanaman", "kode_kab"): "Papua Barat Daya memakai 98xx, master 92xx",
    ("bps_kecamatan_demografi", "kode_kab"): "kode 1972 (duplikat Pangkalpinang, master 1971)",
    ("pelabuhan_daerah", "kode_kabupaten"): "191 baris berkode tingkat PROVINSI (xx00, mis. 'Provinsi Sumatera Utara') + 98xx; "
                                            "kab sebenarnya = bagian bulat kode_kecamatan (format 'kab.kec', bukan 7 digit BPS)",
    ("bps_data_bandara", "kode_kabupaten"): "Papua Barat Daya 98xx (master 92xx) dan kode_provinsi non-BPS (97/73/74)",
}
# hierarki yang salah tapi sudah diketahui: (tabel, potongan teks kondisi) -> alasan
DIKETAHUI_C = {
    "bps_data_bandara": "kode_provinsi non-BPS (PBD 97, Sulsel 73, Sulteng 74) -- kode_kabupaten yang dipakai, kecuali PBD 98xx",
    "pelabuhan_daerah": "kode_kecamatan berformat desimal 'kab.kec' (1107.05), BUKAN 7 digit BPS; "
                        "konversi: kab*1000 + kec*10 (745/752 cocok nama)",
}
for t, c, tipe in KAB:
    # kolom HARUS dikualifikasi nama tabel: nama seperti kode_kabupaten juga ada di ref_wilayah,
    # tanpa kualifikasi subquery membandingkan kolom ref dengan dirinya sendiri (selalu cocok).
    # Bandingkan sebagai INTEGER terhadap ref_wilayah_kabupaten (514 baris) -- versi ::text lambat.
    ekspr = f"{t}.{c}" if tipe == "int" else f"NULLIF(trim({t}.{c}), '')::int"
    r = q(f"""SELECT COUNT(*) FILTER (WHERE {t}.{c} IS NOT NULL) berkode,
                     COUNT(*) FILTER (WHERE {t}.{c} IS NOT NULL AND NOT EXISTS
                        (SELECT 1 FROM ref_wilayah_kabupaten w WHERE w.kode_kabupaten = {ekspr})) orphan FROM {t}""")[0]
    contoh = ""
    if r["orphan"]:
        contoh = [x["v"] for x in q(f"""SELECT DISTINCT {ekspr} v FROM {t} WHERE {t}.{c} IS NOT NULL AND NOT EXISTS
                 (SELECT 1 FROM ref_wilayah_kabupaten w WHERE w.kode_kabupaten = {ekspr}) LIMIT 5""")]
    lapor(r["orphan"] == 0, f"{t}.{c}: {r['berkode']} berkode, orphan={r['orphan']} {contoh}",
          diketahui=(t, c) in DIKETAHUI)
    if r["orphan"] and (t, c) in DIKETAHUI:
        print(f"              -> {DIKETAHUI[(t, c)]}")
# kemantapan_ijd_2026: baris tingkat provinsi (xx00) bukan kab; sisanya harus ada di ref
r = q("""SELECT COUNT(*) FILTER (WHERE k.kode_wilayah % 100 <> 0 AND NOT EXISTS
            (SELECT 1 FROM ref_wilayah w WHERE w.kode_kabupaten = k.kode_wilayah)) orphan_kab FROM kemantapan_ijd_2026 k""")[0]
lapor(r["orphan_kab"] == 0, f"kemantapan_ijd_2026.kode_wilayah (baris kab/kota): orphan={r['orphan_kab']}", diketahui=True)
if r["orphan_kab"]:
    print("              -> Papua Barat Daya memakai 98xx (9801-9806), master 92xx")
for t in ["si_kendaraan_provinsi", "si_lahan_sawah_provinsi", "si_padi_jagung_provinsi", "si_panjang_jalan_provinsi",
          "si_perikanan_tangkap_provinsi", "bappenas_lokus_a", "kawasan_tematik", "wilayah_mapping", "usulan_inpres", "usulan_inpres_riwayat"]:
    r = q(f"""SELECT COUNT(*) FILTER (WHERE kode_provinsi IS NOT NULL AND kode_provinsi <> 0 AND NOT EXISTS
              (SELECT 1 FROM ref_wilayah w WHERE w.kode_provinsi = {t}.kode_provinsi)) orphan FROM {t}""")[0]
    lapor(r["orphan"] == 0, f"{t}.kode_provinsi (kode 0 = Indonesia dikecualikan): orphan={r['orphan']}")
for t in ["bappenas_lokus_a", "kawasan_tematik", "kecamatan_data_turunan", "usulan_kecamatan_dilalui",
          "simpul_transportasi_kecamatan_radius", "bps_kecamatan_potensi_tematik", "usulan_konektivitas_jalan", "usulan_inpres"]:
    r = q(f"""SELECT COUNT(*) FILTER (WHERE kode_kecamatan IS NOT NULL AND NOT EXISTS
              (SELECT 1 FROM ref_wilayah w WHERE w.kode_kecamatan = {t}.kode_kecamatan)) orphan FROM {t}""")[0]
    lapor(r["orphan"] == 0, f"{t}.kode_kecamatan: orphan={r['orphan']}")

# ---------------------------------------------------------------- C
print("\nC. Hierarki kode di tabel bertingkat")
for t in ["bappenas_lokus_a", "kawasan_tematik", "kecamatan_data_turunan", "usulan_kecamatan_dilalui",
          "simpul_transportasi_kecamatan_radius", "bps_data_bandara", "pelabuhan_daerah"]:
    cols = {x["column_name"] for x in q("SELECT column_name FROM information_schema.columns WHERE table_name=%s", (t,))}
    cek = []
    if {"kode_kecamatan", "kode_kabupaten"} <= cols:
        cek.append("kode_kecamatan IS NOT NULL AND kode_kabupaten IS NOT NULL AND kode_kecamatan::int / 1000 <> kode_kabupaten")
    if {"kode_kabupaten", "kode_provinsi"} <= cols:
        cek.append("kode_kabupaten IS NOT NULL AND kode_provinsi IS NOT NULL AND kode_kabupaten / 100 <> kode_provinsi")
    for w in cek:
        n = q(f"SELECT COUNT(*) n FROM {t} WHERE {w}")[0]["n"]
        lapor(n == 0, f"{t}: {w.split(' AND ')[-1].split(' <>')[0].strip()} konsisten (baris salah={n})",
              diketahui=t in DIKETAHUI_C)
        if n and t in DIKETAHUI_C:
            print(f"              -> {DIKETAHUI_C[t]}")

# ---------------------------------------------------------------- D
print("\nD. usulan_inpres (tarikan 2026)")
r = q("SELECT COUNT(*) n, COUNT(kode_kabupaten) kab, COUNT(kode_kecamatan) kec FROM usulan_inpres")[0]
lapor(r["kab"] == r["n"], f"kode_kabupaten terisi {r['kab']}/{r['n']} (kode_kecamatan {r['kec']}/{r['n']} -- hasil spatial join, wajar tidak lengkap)")
r = q("""SELECT COUNT(*) n, COUNT(*) FILTER (WHERE kode_kecamatan / 1000 / 100 <> kode_provinsi) lintas_prov
         FROM usulan_inpres WHERE kode_kecamatan IS NOT NULL AND kode_kabupaten IS NOT NULL AND kode_kecamatan / 1000 <> kode_kabupaten""")[0]
lapor(r["n"] == 0, f"kabupaten menurut nama pengusul (kode_kabupaten) BEDA dengan kabupaten menurut geometri (kode_kecamatan/1000): "
                   f"{r['n']} usulan, {r['lintas_prov']} di antaranya lintas provinsi", diketahui=True)
print("              -> scorer memakai kode_kecamatan/1000 bila ada, selain itu nama->kode: sumber kabupaten bisa berbeda antar parameter")

# ---------------------------------------------------------------- E
print("\nE. Tabel yang HANYA memuat nama wilayah (tanpa kode) -- perlu dipetakan lewat ref_wilayah bila dipakai join")
NAMA_SAJA = [("dpp_ijd_2025", "provinsi (+ nama kegiatan), sumber Parameter E"), ("psc119_layanan", "provinsi, kabupaten_kota"),
             ("jpl_prioritas_djka", "provinsi, kota_kab"), ("bps_lhr_ruas_nasional", "provinsi, kabupaten, kecamatan (multi-nilai ';')"),
             ("angkutan_perintis", "provinsi, wilayah"), ("bps_kinerja_pelabuhan", "provinsi"),
             ("basarnas_analisis_kantor", "provinsi"), ("list_lokpri_kawasan", "kabupaten"),
             ("maskapai_organisasi", "geo_provinsi/kabupaten/kecamatan")]
for t, ket in NAMA_SAJA:
    n = q(f"SELECT COUNT(*) n FROM {t}")[0]["n"]
    print(f"  [NAMA SAJA] {t} ({n} baris): {ket}")
n = q("SELECT COUNT(*) n FROM bps_kecamatan_produksi_komoditas WHERE kode_kecamatan IS NULL")[0]["n"]
print(f"  [NAMA SAJA] bps_kecamatan_produksi_komoditas.kode_kecamatan kosong di {n} baris (hanya kode_kab + nama kecamatan)")
tipe = q("""SELECT table_name, data_type FROM information_schema.columns WHERE column_name = 'kode_kab' AND table_schema='public'
            AND data_type NOT IN ('integer','smallint','bigint') ORDER BY 1""")
print(f"  [TIPE] kode_kab bertipe teks/CHAR di {len(tipe)} tabel (bps_*, bappenas_koridor) vs INTEGER di tabel lain -- butuh cast ::text/trim saat join")

print(f"\nRingkasan: {masalah} temuan MASALAH baru" + (" -> exit 1" if masalah else " (semua sesuai/DIKETAHUI)"))
sys.exit(1 if masalah else 0)
