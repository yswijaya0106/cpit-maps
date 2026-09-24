# -*- coding: utf-8 -*-
"""Pengelompokan provinsi (kode BPS 2 digit) ke gugus pulau -- dipakai filter
"Pulau" di viewer Data (app.py) dan scripts/build_koridor_simpul_terdekat.py.
Kelompok mengikuti pembagian umum wilayah pulau di statistik nasional."""

PULAU_KODE_PROVINSI = {
    "Sumatera": [11, 12, 13, 14, 15, 16, 17, 18, 19, 21],
    "Jawa": [31, 32, 33, 34, 35, 36],
    "Bali & Nusa Tenggara": [51, 52, 53],
    "Kalimantan": [61, 62, 63, 64, 65],
    "Sulawesi": [71, 72, 73, 74, 75, 76],
    "Maluku": [81, 82],
    "Papua": [91, 92, 94, 95, 96, 97],
}

PULAU_BY_KODE_PROVINSI = {k: p for p, ks in PULAU_KODE_PROVINSI.items() for k in ks}
