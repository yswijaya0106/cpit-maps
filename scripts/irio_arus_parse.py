# -*- coding: utf-8 -*-
"""Parser workbook IRIO antar-provinsi (docs/24092026/tabel-inter-regional-...xlsx)
-> arus perdagangan domestik per pasangan provinsi asal->tujuan.

Sheet yang dipakai: 34 sheet "Penjualan <Provinsi>" (asal = provinsi sheet).
Tiap sheet: blok RUPIAH (juta Rp, baris 5-56 = 52 industri, kolom E..AL = 34
provinsi tujuan; kolom C = jenis muatan kontainer/curah/MP, kosong = jasa),
blok TON (baris 61-112, ton = rupiah x faktor ton/rupiah di kolom B), baris
Total (113) dan "Persentase Moda" (116-120: Jalan/Laut/Udara/ASDP/KA per
tujuan, HANYA terisi utk sebagian pasangan). Sheet lain: "Pembelian Aceh"
(sudut pandang tujuan Aceh; dipakai utk uji konsistensi), "IRIO-PDD (52x52)"
(matriks dasar), "Sheet1" & "KOnversi" (HS ekspor-impor luar negeri + konversi
industri<->HS; bukan arus antar-provinsi, tidak dipakai utk garis).
"""
import glob
import re

import openpyxl

XLSX_GLOB = "docs/24092026/tabel-inter-regional-input-output*.xlsx"
MODA_ROWS = {"jalan": 116, "laut": 117, "udara": 118, "asdp": 119, "ka": 120}  # nomor baris 1-based


def _f(v):
    return float(v) if isinstance(v, (int, float)) else 0.0


def parse(path=None):
    path = path or glob.glob(XLSX_GLOB)[0]
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    pairs = {}
    provs = []
    for ws in wb.worksheets:
        if not ws.title.startswith("Penjualan "):
            continue
        rows = list(ws.iter_rows(values_only=True))
        dest = []
        for c in range(4, 4 + 34):
            m = re.match(r"\s*(\d+)\.\s*(.+)", str(rows[3][c] or ""))
            dest.append((int(m.group(1)), m.group(2).strip()))
        prov_asal = ws.title.replace("Penjualan ", "")
        provs.append((ws.title, dest))
        ind = []
        for r in range(4, 56):  # baris 5-56 (index 4..55)
            ind.append((str(rows[r][3] or "").strip(), str(rows[r][2] or "").strip().lower()))
        for j, (kode_t, nama_t) in enumerate(dest):
            c = 4 + j
            rp = [_f(rows[r][c]) for r in range(4, 56)]
            ton = [_f(rows[r][c]) for r in range(60, 112)]  # baris 61-112
            moda = {k: rows[n - 1][c] for k, n in MODA_ROWS.items()}
            moda = {k: float(v) for k, v in moda.items() if isinstance(v, (int, float))}
            pairs[(prov_asal, kode_t)] = {
                "asal_sheet": prov_asal, "kode_tujuan": kode_t, "nama_tujuan": nama_t,
                "rp": rp, "ton": ton, "industri": ind, "moda": moda,
                "total_ton_sheet": _f(rows[112][c]),
            }
    return pairs, provs


if __name__ == "__main__":
    pairs, provs = parse()
    print(len(provs), "sheet penjualan;", len(pairs), "pasangan")
    n_moda = sum(1 for p in pairs.values() if p["moda"])
    print("pasangan dgn persentase moda:", n_moda)
    bad = [(k, sum(v["ton"]), v["total_ton_sheet"]) for k, v in pairs.items()
           if abs(sum(v["ton"]) - v["total_ton_sheet"]) > 1e-6 * max(1, v["total_ton_sheet"])]
    print("selisih total ton vs jumlah baris:", len(bad), bad[:3])
    print("total rp (juta) semua:", sum(sum(v["rp"]) for v in pairs.values()))
    print("total ton semua:", sum(sum(v["ton"]) for v in pairs.values()))
    print("ex moda:", next(p["moda"] for p in pairs.values() if p["moda"]))
