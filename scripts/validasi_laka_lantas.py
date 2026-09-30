"""Validasi data kecelakaan POLDA (anev_laka_lantas_polda) yang dipakai Skor Prioritas
Pendampingan RAK LLAJ (rak_llaj.py). Read-only; pemeriksaan sama dgn sheet "Validasi Data"
di preview/export Prioritas RAK LLAJ.

Usage (venv aktif):
    python scripts/validasi_laka_lantas.py

Laporan saja: exit 0 walau ada temuan PERHATIAN; exit 1 bila ada MASALAH (mis. POLDA di data
yang tidak terpetakan ke provinsi mana pun).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
from app import PROVINSI_POLDA_MAP  # noqa: E402
import rak_llaj  # noqa: E402

temuan = rak_llaj.validasi(PROVINSI_POLDA_MAP)
for t in temuan:
    print(f"[{t['status']:<9}] {t['cek']}")
    if t["detail"] != "-":
        print(f"             {t['detail']}")
sys.exit(1 if any(t["status"] == "MASALAH" for t in temuan) else 0)
