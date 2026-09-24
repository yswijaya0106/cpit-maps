"""Export Excel profil Road Safety per kab/kota TANPA data kecelakaan/fatalitas.

Logika ada di road_safety.py (juga dipakai endpoint /api/road-safety/kabupaten/*
di app.py). Kajian: docs/kajian_road_safety_ketersediaan_data.md.

Pakai: python scripts/export_road_safety_kabupaten.py [output.xlsx]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import road_safety

OUT_DEFAULT = "docs/24092026/Profil_Road_Safety_Kab_Kota_tanpa_kecelakaan.xlsx"

out = Path(sys.argv[1] if len(sys.argv) > 1 else OUT_DEFAULT)
out.parent.mkdir(parents=True, exist_ok=True)
sheets = road_safety.get_sheets()
road_safety.write_workbook(sheets, out)
print(f"OK: {out} — {len(sheets['Profil Kab-Kota'])} kab/kota")
