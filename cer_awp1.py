"""Analisis Skoring Jalan AWP-1 -- Cost Effectiveness Ratio (CER) per koridor.

Model EKSPERIMENTAL, terpisah dari skor IJD A-E dan NPR. Rumus disalin dari
deck "20261007 PENAMBAHAN PENYEMPURNAAN SIJALAN" slide 10-20 (contekan rumus:
slide 20) dan diverifikasi angka per angka terhadap file sumbernya
`docs/07102026/VfM-koridor-kirim bappenas.xlsx` sheet All (lihat
scripts/import_cer_awp1.py, yang mencetak laporan kecocokan).

Alur (slide 10): kondisi jalan eksisting -> skenario sesudah penanganan ->
indikator eksisting vs sesudah -> manfaat (delta) -> skor 0-10 (dibagi nilai
MAX seluruh koridor) -> TOT SCORE, C SCORE, CER = TOT / C.

Catatan metodologi yang SENGAJA dipertahankan apa adanya dari file sumber
(lihat juga slide 19-22): normalisasi memakai MAX (bukan persentil), MAX
dihitung dari semua koridor termasuk yang Ditolak, dan biaya memakai Biaya
Standar (bukan biaya usulan Pemda).
"""
from typing import Dict, List, Optional

BIAYA_SATUAN_M_PER_KM = {"B": 0.06, "S": 0.2, "RR": 4.0, "RB": 8.0}   # slide 11
DEGRADASI = 0.0139                                                     # slide 13
KECEPATAN_KMJ = {"B": 43.4, "S": 35.7, "RR": 25.5, "RB": 15.3}        # slide 14
BBM_KOEF = (0.0023, -0.3139, 17.499)                                   # BBM = a v^2 + b v + c
FAKTOR_GRK = 2597.86                                                   # GRK = f * BBM / 100
BOK_RP_PER_KM = {"B": 3749, "S": 5075, "RR": 7015, "RB": 9152}        # slide 15
BOBOT_KELAS_JALAN = {"JN": 0.42, "JP": 0.35, "JK": 0.23}              # slide 16
EFEK_KECELAKAAN = 0.30
BOBOT_MANFAAT = {"hpp": 0.50, "bok": 0.15, "pfa": 0.15, "wt": 0.10, "acc": 0.05, "grk": 0.05}  # slide 18


def _kondisi_sesudah(b, s, rr, rb):
    """Slide 13: RR & RB pulih jadi Baik, lalu jalan menurun 1,39%."""
    return {
        "B": (1 - DEGRADASI) * b + rr + rb,
        "S": (1 - DEGRADASI) * s + DEGRADASI * b,
        "RR": DEGRADASI * s,
        "RB": 0.0,
    }


def _rerata(k: Dict[str, float], tabel: Dict[str, float], total: float) -> Optional[float]:
    if not total:
        return None
    return sum(k[x] * tabel[x] for x in ("B", "S", "RR", "RB")) / total


def _bbm(speed):
    a, b, c = BBM_KOEF
    return a * speed ** 2 + b * speed + c


def hitung_komponen(r: dict, harga: Dict[str, float]) -> dict:
    """Komponen mentah satu koridor (sebelum normalisasi). r = input dari sheet All.
    harga = {nama komoditas: Rp/kg} dari sheet price."""
    b, s, rr, rb = (float(r.get(k) or 0) for k in ("b_km", "s_km", "rr_km", "rb_km"))
    total = b + s + rr + rb
    eks = {"B": b, "S": s, "RR": rr, "RB": rb}
    aft = _kondisi_sesudah(b, s, rr, rb)
    biaya_std = sum(eks[k] * BIAYA_SATUAN_M_PER_KM[k] for k in eks)

    pf = []
    for i in (1, 2, 3):
        kom = r.get(f"komoditas_{i}")
        prod = float(r.get(f"produksi_{i}_ton") or 0)
        pf.append(harga.get(kom, 0.0) * prod * 1000 if kom else 0.0)
    hpp = sum(pf)

    out = {"total_km": total, "biaya_std_m": biaya_std, "pf1": pf[0], "pf2": pf[1], "pf3": pf[2], "hpp": hpp,
           "pfa": sum(float(r.get(k) or 0) for k in ("fas_pendidikan", "fas_kesehatan", "fas_pemerintahan", "fas_sppg"))}
    sp_e, sp_a = _rerata(eks, KECEPATAN_KMJ, total), _rerata(aft, KECEPATAN_KMJ, total)
    if sp_e is None:  # koridor tanpa panjang: semua manfaat kondisi = 0
        out.update(speed_eks=None, speed_aft=None, bbm_eks=None, bbm_aft=None, grk_eks=None, grk_aft=None,
                   bok_eks=None, bok_aft=None, wt_eks=None, wt_aft=None, d_grk=0.0, d_bok=0.0, d_wt=0.0)
    else:
        bbm_e, bbm_a = _bbm(sp_e), _bbm(sp_a)
        grk_e, grk_a = FAKTOR_GRK * bbm_e / 100, FAKTOR_GRK * bbm_a / 100
        bok_e, bok_a = _rerata(eks, BOK_RP_PER_KM, total), _rerata(aft, BOK_RP_PER_KM, total)
        wt_e, wt_a = total / sp_e, total / sp_a
        out.update(speed_eks=sp_e, speed_aft=sp_a, bbm_eks=bbm_e, bbm_aft=bbm_a, grk_eks=grk_e, grk_aft=grk_a,
                   bok_eks=bok_e, bok_aft=bok_a, wt_eks=wt_e, wt_aft=wt_a,
                   d_grk=grk_e - grk_a, d_bok=max(bok_e - bok_a, 0.0), d_wt=max(wt_e - wt_a, 0.0))

    jn, jp, jk = (float(r.get(k) or 0) for k in ("jn_km", "jp_km", "jk_km"))
    acc_prov = float(r.get("acc_provinsi") or 0)
    pembagi = BOBOT_KELAS_JALAN["JN"] * jn + BOBOT_KELAS_JALAN["JP"] * jp + BOBOT_KELAS_JALAN["JK"] * jk
    acc_kab = (jk * BOBOT_KELAS_JALAN["JK"]) / pembagi * acc_prov if pembagi else 0.0
    acc_kor = total / jk * acc_kab if jk else 0.0
    out.update(acc_kab=acc_kab, acc_koridor=acc_kor, d_acc=EFEK_KECELAKAAN * acc_kor)
    return out


def hitung_skor(daftar: List[dict]) -> dict:
    """Normalisasi 0-10 (dibagi MAX seluruh koridor) + TOT/C/CER. Mengubah
    `daftar` di tempat (menambah skor_*), mengembalikan nilai MAX yang dipakai."""
    maks = {
        "hpp": max((d["hpp"] for d in daftar), default=0),
        "bok": max((d["d_bok"] for d in daftar), default=0),
        "pfa": max((d["pfa"] for d in daftar), default=0),
        "wt": max((d["d_wt"] for d in daftar), default=0),
        "acc": max((d["d_acc"] for d in daftar), default=0),
        "grk": max((d["d_grk"] for d in daftar), default=0),
        "biaya_std": max((d["biaya_std_m"] for d in daftar), default=0),
    }

    def sk(v, m, guard=False):
        if not m or (guard and not v > 0):
            return 0.0
        return v / m * 10

    for d in daftar:
        d["skor_hpp"] = sk(d["hpp"], maks["hpp"])
        d["skor_bok"] = sk(d["d_bok"], maks["bok"])
        d["skor_pfa"] = sk(d["pfa"], maks["pfa"], guard=True)
        d["skor_wt"] = sk(d["d_wt"], maks["wt"])
        d["skor_acc"] = sk(d["d_acc"], maks["acc"])
        d["skor_grk"] = sk(d["d_grk"], maks["grk"], guard=True)
        d["tot_score"] = sum(BOBOT_MANFAAT[k] * d[f"skor_{k}"] for k in BOBOT_MANFAAT)
        d["c_score"] = d["biaya_std_m"] / maks["biaya_std"] * 10 if maks["biaya_std"] else 0.0
        d["cer_score"] = d["tot_score"] / d["c_score"] if d["c_score"] > 0 else 0.0
    return maks
