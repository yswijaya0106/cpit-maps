"""Isi kolom ID wilayah (kode BPS) di setiap tabel yang menyimpan NAMA provinsi/kabupaten/kecamatan.

Tujuan: semua tabel berwilayah bisa di-join lewat satu kunci seragam -- kode_provinsi (2 digit),
kode_kabupaten (4 digit), kode_kecamatan (7 digit), INTEGER, sesuai ref_wilayah (master BPS dari
penduduk_kecamatan). Dipakai asisten chat (catatan chat_pengetahuan/join_antar_tabel.md) dan
siapa pun yang menulis query lintas tabel.

Aturan:
- Kolom asli dari sumber TIDAK diubah. Kolom kode yang sudah ada tapi formatnya bukan BPS
  (pelabuhan_daerah: baris tingkat provinsi xx00, kab 98xx, kecamatan desimal 'kab.kec') diberi
  kolom pendamping *_bps, sama dgn konvensi bps_data_bandara.kode_kabupaten_bps.
- Kode sumber dipakai bila ADA di ref_wilayah; selain itu dicari dari nama
  (wilayah_cocok.PencocokKabupaten; kecamatan dicocokkan di dalam kab-nya). Papua Barat Daya 98xx
  -> 92xx lewat nama, bukan aritmetika.
- Kolom yang sudah ada sebelum skrip ini (mis. bps_kecamatan_potensi_tematik.kode_kecamatan) hanya
  diisi yang NULL; kolom buatan skrip ini dihitung ulang penuh tiap jalan.
- Ruas LHR yang melintasi >1 kab/kec: kode_kabupaten/kode_kecamatan hanya diisi bila tunggal,
  daftar lengkap di kode_kabupaten_semua / kode_kecamatan_semua (INTEGER[], pakai = ANY(...)).

Idempotent. JALANKAN ULANG setelah mengimpor ulang tabel mana pun di bawah (importer DELETE+INSERT
mengosongkan kolom tambahan ini). Usage (venv aktif):
    python scripts/isi_kode_wilayah.py               # semua tabel
    python scripts/isi_kode_wilayah.py --tabel bandara_kemenhub --laporan sisa.csv
"""
import argparse
import csv
import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from db import db_cursor  # noqa: E402
from wilayah_cocok import PencocokKabupaten, kunci, kunci_provinsi  # noqa: E402

KODE_KAB_BPS = "NULLIF(trim(kode_kab), '')::int"
# pelabuhan_daerah.kode_kecamatan berformat 'kab.kec' (1107.05) -> kab = bagian bulat, kec BPS = kab*1000 + kec*10
PEL_KAB = "floor(kode_kecamatan)::int"
PEL_KEC = "(floor(kode_kecamatan)::int * 1000 + round((kode_kecamatan - floor(kode_kecamatan)) * 100)::int * 10)"

# prov/kab/kec: kolom NAMA; kab_hint/kec_hint: ekspresi kode sumber (dipakai bila valid di ref);
# out: kolom tujuan per level; pisah: pemisah multi-nilai; ada: kolom tujuan yg sudah ada sebelumnya (isi NULL saja)
TABEL = [
    dict(tabel="angkutan_perintis", prov="provinsi", kab="wilayah"),
    dict(tabel="bandara_kemenhub", prov="provinsi", kab="kabupaten", kec="kecamatan"),
    dict(tabel="bappenas_koridor", prov="provinsi", kab="kabupaten_kota", kab_hint=[KODE_KAB_BPS]),
    dict(tabel="basarnas_analisis_kantor", prov="provinsi"),
    dict(tabel="bps_kabupaten_indeks_penanaman", kab="nama_kab", kab_hint=[KODE_KAB_BPS]),
    dict(tabel="bps_kabupaten_indeks_penanaman_raster", kab_hint=[KODE_KAB_BPS]),
    dict(tabel="bps_kabupaten_jalan", kab="nama_kab", kab_hint=[KODE_KAB_BPS]),
    dict(tabel="bps_kabupaten_kendaraan", kab="nama_kab", kab_hint=[KODE_KAB_BPS]),
    dict(tabel="bps_kabupaten_padi", kab="nama_kab", kab_hint=[KODE_KAB_BPS]),
    dict(tabel="bps_kecamatan_demografi", kab="nama_kab", kab_hint=[KODE_KAB_BPS], kec="kecamatan"),
    dict(tabel="bps_kecamatan_potensi_tematik", kab="nama_kab", kab_hint=[KODE_KAB_BPS], kec="kecamatan",
         kec_hint=["kode_kecamatan"], ada={"kode_kecamatan"}),
    dict(tabel="bps_kecamatan_produksi_komoditas", kab="nama_kab", kab_hint=[KODE_KAB_BPS], kec="kecamatan",
         kec_hint=["kode_kecamatan"], ada={"kode_kecamatan"}),
    dict(tabel="bps_kinerja_pelabuhan", prov="provinsi"),
    dict(tabel="bps_lhr_ruas_nasional", prov="provinsi", kab="kabupaten", kec="kecamatan", pisah=";"),
    dict(tabel="dpp_ijd_2025", prov="provinsi"),
    dict(tabel="iri_ruas_nasional", prov="provinsi"),
    dict(tabel="jpl_prioritas_djka", prov="provinsi", kab="kota_kab"),
    # kode_provinsi sumber kedua tabel ini sudah BPS -> hanya tambah kode_kabupaten
    dict(tabel="kemantapan_ijd_2026", prov="provinsi", kab="kabupaten_kota", kab_hint=["kode_wilayah"], tanpa=["prov"]),
    dict(tabel="koridor_simpul_terdekat", prov="provinsi", kab="kabupaten_kota", kab_hint=["kode_kab"], tanpa=["prov"]),
    dict(tabel="list_lokpri_kawasan", kab="kabupaten_lengkap"),
    dict(tabel="maskapai_organisasi", prov="geo_provinsi", kab="geo_kabupaten", kec="geo_kecamatan"),
    dict(tabel="pelabuhan_daerah", prov="provinsi", kab="kabupaten_kota", kec="kecamatan",
         kab_hint=["kode_kabupaten", PEL_KAB], kec_hint=[PEL_KEC],
         out={"prov": "kode_provinsi_bps", "kab": "kode_kabupaten_bps", "kec": "kode_kecamatan_bps"}),
    dict(tabel="psc119_layanan", prov="provinsi", kab="kabupaten_kota"),
    # kode kab sudah benar, provinsi tinggal diturunkan
    dict(tabel="konektivitas_jaringan_jalan", kab_hint=["kode_kabupaten"], out={"prov": "kode_provinsi"},
         ada={"kode_kabupaten"}),
]
OUT_DEFAULT = {"prov": "kode_provinsi", "kab": "kode_kabupaten", "kec": "kode_kecamatan"}
TIPE = {"prov": "SMALLINT", "kab": "INTEGER", "kec": "INTEGER"}
_AWALAN_KEC = re.compile(r"^\s*(KECAMATAN|KEC\.?|DISTRIK)\s+", re.I)
_NOMOR_DEPAN = re.compile(r"^\s*[\[(]?\d+[\])]?[.,\s]+")


class Master:
    def __init__(self, cur):
        cur.execute("""SELECT DISTINCT kode_provinsi, provinsi, kode_kabupaten, kabupaten_kota FROM penduduk_kecamatan""")
        rows = [dict(r) for r in cur.fetchall()]
        self.kab = PencocokKabupaten(rows)
        self.kab_valid = {int(r["kode_kabupaten"]) for r in rows}
        self.prov = {kunci_provinsi(r["provinsi"]): int(r["kode_provinsi"]) for r in rows}
        self.nama_kab = {int(r["kode_kabupaten"]): kunci(r["kabupaten_kota"]) for r in rows}
        cur.execute("SELECT kode_kecamatan, kode_kabupaten, kecamatan FROM penduduk_kecamatan")
        self.kec = {}
        self.kec_per_kab = {}
        self.kec_valid = {}
        for r in cur.fetchall():
            kab, kk = int(r["kode_kabupaten"]), self.kunci_kec(r["kecamatan"])
            self.kec.setdefault((kab, kk), []).append(int(r["kode_kecamatan"]))
            self.kec_per_kab.setdefault(kab, []).append(kk)
            self.kec_valid[int(r["kode_kecamatan"])] = kab

    @staticmethod
    def kunci_kec(s):
        # BPS Dalam Angka menulis nomor urut di depan nama: "030 Aek Kuo", "[060] Abung Timur", "3  Jatilawang"
        s = _NOMOR_DEPAN.sub("", str(s or ""))
        return kunci(_AWALAN_KEC.sub("", s))

    def baris_total_kab(self, kab, nama):
        """Baris rekap kab ("Kabupaten Magetan", "Dairi") di tabel per kecamatan -- bukan kecamatan."""
        k = kunci(re.sub(r"^\s*(KABUPATEN|KAB\.?|KOTA)\s+", "", str(nama or ""), flags=re.I))
        return kab is not None and k == self.nama_kab.get(kab)

    def cari_prov(self, nama):
        if not nama:
            return None
        # "PAPUA\nB. BIAK" (angkutan_perintis): baris pertama = provinsi; "NTB - NTT" sengaja tidak cocok
        return self.prov.get(kunci_provinsi(str(nama).split("\n")[0]))

    # Nama dulu, kode sumber sbg cadangan: kode sumber bisa lolos validasi tapi salah arti (urutan
    # Kemendagri Papua Tengah/Pegunungan), sedangkan pencocok nama mengembalikan None bila ambigu.
    def cari_kab(self, prov, nama, hints):
        if nama and kunci(nama) not in ("KABUPATEN", "KOTA"):
            m = self.kab.cari(prov, nama)
            if m:
                return int(m["kode_kabupaten"])
        for h in hints:
            if h is not None and int(h) in self.kab_valid:
                return int(h)
        return None

    def cari_kec(self, kab, nama, hints):
        if kab is not None and nama:
            kk = self.kunci_kec(nama)
            calon = [kk]
            if kk.startswith("KOTA"):  # "Kota Ternate Utara" -> TERNATE UTARA
                calon.append(kk[4:])
            for c in calon:
                k = self.kec.get((kab, c))
                if k and len(k) == 1:
                    return k[0]
            # ejaan beda sedikit (Elikobal/Elikobel), HANYA di dalam kab yg sama & kandidat tunggal yg jelas
            mirip = difflib.get_close_matches(kk, self.kec_per_kab.get(kab, []), n=2, cutoff=0.88)
            if len(mirip) == 1 or (len(mirip) == 2 and difflib.SequenceMatcher(None, kk, mirip[0]).ratio()
                                    - difflib.SequenceMatcher(None, kk, mirip[1]).ratio() >= 0.05):
                k = self.kec.get((kab, mirip[0]))
                if k and len(k) == 1:
                    return k[0]
        for h in hints:
            if h is not None and int(h) in self.kec_valid and (kab is None or self.kec_valid[int(h)] == kab):
                return int(h)
        return None


def kolom_output(cfg):
    """{level: kolom tujuan}. Level terendah di tabel menentukan: kec -> prov+kab+kec, kab -> prov+kab.
    Dipakai juga scripts/validasi_id_wilayah.py."""
    levels = {"prov"} if cfg.get("prov") else set()
    if cfg.get("kab") or cfg.get("kab_hint"):
        levels |= {"prov", "kab"}
    if cfg.get("kec") or cfg.get("kec_hint"):
        levels |= {"prov", "kab", "kec"}
    out = {lv: OUT_DEFAULT[lv] for lv in ("prov", "kab", "kec") if lv in levels}
    out.update(cfg.get("out", {}))
    for lv in cfg.get("tanpa", []):
        out.pop(lv, None)
    return out


def proses(cur, master, cfg, laporan):
    t = cfg["tabel"]
    out = kolom_output(cfg)
    pisah = cfg.get("pisah")
    ada = cfg.get("ada", set())
    for lv, kol in out.items():
        cur.execute(f'ALTER TABLE {t} ADD COLUMN IF NOT EXISTS {kol} {TIPE[lv]}')
    if pisah:
        cur.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS kode_kabupaten_semua INTEGER[]")
        cur.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS kode_kecamatan_semua INTEGER[]")

    sumber = [("prov", cfg.get("prov")), ("kab", cfg.get("kab")), ("kec", cfg.get("kec"))]
    sel = [f'{c}::text AS n_{lv}' if c else f"NULL::text AS n_{lv}" for lv, c in sumber]
    sel += [f"({h})::bigint AS hk{i}" for i, h in enumerate(cfg.get("kab_hint", []))]
    sel += [f"({h})::bigint AS hc{i}" for i, h in enumerate(cfg.get("kec_hint", []))]
    cur.execute(f"SELECT DISTINCT {', '.join(sel)} FROM {t}")
    kombinasi = [dict(r) for r in cur.fetchall()]

    hasil = []
    for r in kombinasi:
        hk = [r[k] for k in sorted(r) if k.startswith("hk")]
        hc = [r[k] for k in sorted(r) if k.startswith("hc")]
        prov = master.cari_prov(r["n_prov"])
        if pisah:
            kabs = [x.strip() for x in (r["n_kab"] or "").split(pisah) if x.strip()]
            kecs = [x.strip() for x in (r["n_kec"] or "").split(pisah) if x.strip()]
            kab_semua = [k for k in (master.cari_kab(r["n_prov"], n, []) for n in kabs) if k]
            kec_semua = []
            for n in kecs:  # kecamatan dicari di semua kab yg dilalui ruas
                c = next((c for c in (master.cari_kec(k, n, []) for k in kab_semua) if c), None)
                if c:
                    kec_semua.append(c)
                else:
                    laporan.append((t, "kecamatan", r["n_prov"], r["n_kab"], n))
            for n, k in zip(kabs, [master.cari_kab(r["n_prov"], n, []) for n in kabs]):
                if not k:
                    laporan.append((t, "kabupaten", r["n_prov"], n, ""))
            kab = kab_semua[0] if len(set(kab_semua)) == 1 and len(kabs) == 1 else None
            kec = kec_semua[0] if len(kec_semua) == 1 and len(kecs) == 1 else None
            hasil.append((r, prov or (kab_semua[0] // 100 if kab_semua else None), kab, kec,
                          sorted(set(kab_semua)) or None, sorted(set(kec_semua)) or None))
            continue
        kab = master.cari_kab(r["n_prov"], r["n_kab"], hk) if "kab" in out else None
        kec = master.cari_kec(kab, r["n_kec"], hc) if "kec" in out else None
        if kec and not kab:
            kab = kec // 1000
        if kab:
            prov = kab // 100  # kode provinsi selalu ikut kab (nama provinsi di sumber bisa pra-pemekaran)
        if "kab" in out and not kab and (r["n_kab"] or any(h is not None for h in hk)) \
                and not str(r["n_kab"] or "").upper().startswith("PROVINSI"):
            laporan.append((t, "kabupaten", r["n_prov"], r["n_kab"], hk))
        if "kec" in out and kab and r["n_kec"] and not kec and not master.baris_total_kab(kab, r["n_kec"]):
            laporan.append((t, "kecamatan", r["n_prov"], r["n_kab"], r["n_kec"]))
        if "prov" in out and not prov and r["n_prov"]:
            laporan.append((t, "provinsi", r["n_prov"], "", ""))
        hasil.append((r, prov, kab, kec, None, None))

    # tulis lewat tabel sementara yg dikunci kombinasi nama+hint (IS NOT DISTINCT FROM: NULL = NULL)
    kunci_kol = [k for k in kombinasi[0]] if kombinasi else []
    cur.execute("DROP TABLE IF EXISTS _kode_tmp")
    cur.execute("CREATE TEMP TABLE _kode_tmp (" + ", ".join(
        f"{k} {'text' if k.startswith('n_') else 'bigint'}" for k in kunci_kol)
        + ", v_prov int, v_kab int, v_kec int, v_kab_semua int[], v_kec_semua int[])")
    if hasil:
        cur.executemany(
            f"INSERT INTO _kode_tmp ({', '.join(kunci_kol)}, v_prov, v_kab, v_kec, v_kab_semua, v_kec_semua) "
            f"VALUES ({', '.join(['%s'] * (len(kunci_kol) + 5))})",
            [tuple(r[k] for k in kunci_kol) + (p, kb, kc, ks, cs) for r, p, kb, kc, ks, cs in hasil])
    # COALESCE(...) = COALESCE(...) (bukan IS NOT DISTINCT FROM) supaya planner bisa hash join
    on = []
    for lv, c in sumber:
        if c:
            on.append(f"COALESCE({t}.{c}::text, '<null>') = COALESCE(x.n_{lv}, '<null>')")
    on += [f"COALESCE(({h})::bigint, -1) = COALESCE(x.hk{i}, -1)" for i, h in enumerate(cfg.get("kab_hint", []))]
    on += [f"COALESCE(({h})::bigint, -1) = COALESCE(x.hc{i}, -1)" for i, h in enumerate(cfg.get("kec_hint", []))]
    # (kolom _kode_tmp bernama n_*/hk*/hc*/v_* -> kolom di ekspresi hint pasti merujuk tabel tujuan)
    sets = []
    for lv, kol in out.items():
        v = f"x.v_{lv}"
        sets.append(f"{kol} = COALESCE({t}.{kol}, {v})" if kol in ada else f"{kol} = {v}")
    if pisah:
        sets += ["kode_kabupaten_semua = x.v_kab_semua", "kode_kecamatan_semua = x.v_kec_semua"]
    cur.execute(f"UPDATE {t} SET {', '.join(sets)} FROM _kode_tmp x WHERE {' AND '.join(on)}")
    for lv, kol in out.items():
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{t}_{kol} ON {t} ({kol})")
    cur.execute(f"SELECT count(*) n, " + ", ".join(f"count({kol}) {kol}" for kol in out.values()) + f" FROM {t}")
    r = cur.fetchone()
    return {"baris": r["n"], **{kol: r[kol] for kol in out.values()}}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tabel", action="append", help="hanya tabel ini (boleh berulang)")
    ap.add_argument("--laporan", help="tulis nama yang tidak cocok ke CSV")
    a = ap.parse_args()
    laporan = []
    with db_cursor() as cur:
        master = Master(cur)
        for cfg in TABEL:
            if a.tabel and cfg["tabel"] not in a.tabel:
                continue
            cur.execute("SELECT to_regclass(%s) AS t", (f"public.{cfg['tabel']}",))
            if not cur.fetchone()["t"]:
                print(f"  {cfg['tabel']:40s} (tabel tidak ada, dilewati)")
                continue
            n0 = len(laporan)
            st = proses(cur, master, cfg, laporan)
            isi = ", ".join(f"{k}={v}/{st['baris']}" for k, v in st.items() if k != "baris")
            print(f"  {cfg['tabel']:40s} {isi}  (tak cocok: {len(laporan) - n0} nama)")
    if laporan:
        print(f"\n{len(laporan)} nama tidak cocok (contoh):")
        for x in laporan[:25]:
            print("   ", x)
        if a.laporan:
            with open(a.laporan, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["tabel", "level", "provinsi", "kabupaten", "kecamatan/hint"])
                w.writerows(laporan)
            print(f"Laporan lengkap: {a.laporan}")


if __name__ == "__main__":
    main()
