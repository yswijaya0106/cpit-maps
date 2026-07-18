"""Smoke-check ringan untuk memverifikasi app.py tidak berubah perilaku --
dipakai sebagai jaring pengaman selama refactor bertahap (pindah fungsi
`_..._` dari app.py ke modul terpisah tanpa mengubah endpoint/logikanya).

Bukan test suite -- cuma membandingkan STRUKTUR respons (keys + tipe) dari
sekumpulan endpoint read-only, sebelum vs sesudah sebuah perubahan. Nilai
(skor, angka, timestamp) sengaja tidak dibandingkan persis karena bisa
berubah wajar antar-run (data DB, cache) tanpa berarti ada regresi.

Cara pakai (venv aktif):
    python scripts/smoke_check.py --save d:\\tmp\\baseline.json
    # ...lakukan perubahan (mis. pindah fungsi ke modul baru)...
    python scripts/smoke_check.py --check d:\\tmp\\baseline.json
"""
import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from fastapi.testclient import TestClient  # noqa: E402
from app import app  # noqa: E402

client = TestClient(app)


def _json_or_none(r):
    try:
        return r.json()
    except ValueError:
        return {"_non_json_content_length": len(r.content)}


def build_calls():
    """Kumpulkan daftar (method, path, params) -- id/kode dinamis diambil
    dari DB lewat endpoint list, supaya script tetap jalan walau data usulan
    tertentu sudah tidak ada."""
    calls = [
        ("GET", "/api/config", {}),
        ("GET", "/api/usulan-inpres/provinsi", {}),
        ("GET", "/api/usulan-inpres", {"limit": 5}),
        ("GET", "/api/prioritas-nasional", {"limit": 5}),
        ("GET", "/api/pagu-provinsi", {}),
        ("GET", "/api/data/tables", {}),
        ("GET", "/api/data/usulan_inpres", {"limit": 5}),
        ("GET", "/api/data/geo/provinces", {}),
        ("GET", "/api/maps/provinces", {}),
        ("GET", "/api/bappenas-lokus-a/kriteria", {}),
    ]

    usulan = client.get("/api/usulan-inpres", params={"limit": 1}).json().get("usulan") or []
    if usulan:
        uid = usulan[0]["id"]
        calls += [
            ("GET", f"/api/usulan-inpres/{uid}", {}),
            ("GET", f"/api/usulan-inpres/{uid}/ijd-score", {}),
            ("GET", f"/api/usulan-inpres/{uid}/skor-prioritas-nasional", {}),
            ("GET", f"/api/usulan-inpres/{uid}/penilaian-bappenas", {}),
        ]

    provinsi_rows = client.get("/api/usulan-inpres/provinsi").json() or []
    if provinsi_rows:
        prov = provinsi_rows[0]["provinsi"]
        calls.append(("GET", "/api/usulan-inpres/ijd-score/preview", {"limit": 5, "provinsi": prov}))

    maps_provinces = client.get("/api/maps/provinces").json() or []
    if maps_provinces:
        map_prov = maps_provinces[0]["provinsi"]
        calls.append(("GET", "/api/maps/kabupaten", {"provinsi": map_prov}))

    return calls


def run(calls):
    results = {}
    for method, path, params in calls:
        r = client.request(method, path, params=params)
        key = f"{method} {path}?{json.dumps(params, sort_keys=True)}"
        results[key] = {"status": r.status_code, "body": _json_or_none(r)}
    return results


def _structure(v):
    """Bentuk (tipe + key), bukan nilai persis."""
    if isinstance(v, dict):
        return {k: _structure(v[k]) for k in sorted(v)}
    if isinstance(v, list):
        return [_structure(v[0])] if v else []
    return type(v).__name__


def diff(baseline: dict, current: dict) -> list:
    problems = []
    for key, b in baseline.items():
        if key not in current:
            problems.append(f"HILANG: {key}")
            continue
        c = current[key]
        if b["status"] != c["status"]:
            problems.append(f"STATUS BEDA [{key}]: {b['status']} -> {c['status']}")
            continue
        bd, cd = _structure(b["body"]), _structure(c["body"])
        if bd != cd:
            problems.append(f"STRUKTUR BEDA [{key}]:\n    baseline={bd}\n    current ={cd}")
    for key in current:
        if key not in baseline:
            problems.append(f"BARU (tidak ada di baseline): {key}")
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--save", metavar="FILE", help="rekam baseline ke FILE")
    ap.add_argument("--check", metavar="FILE", help="bandingkan skr vs baseline di FILE")
    args = ap.parse_args()
    if not args.save and not args.check:
        ap.error("pakai --save FILE atau --check FILE")

    calls = build_calls()
    results = run(calls)

    if args.save:
        Path(args.save).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Baseline disimpan: {args.save} ({len(results)} panggilan)")
        return

    baseline = json.loads(Path(args.check).read_text(encoding="utf-8"))
    problems = diff(baseline, results)
    if problems:
        print(f"GAGAL -- {len(problems)} perbedaan struktural:")
        for p in problems:
            print(" -", p)
        sys.exit(1)
    print(f"OK -- {len(results)} endpoint strukturnya identik dengan baseline.")


if __name__ == "__main__":
    main()
