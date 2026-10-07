# -*- coding: utf-8 -*-
"""Paket uji asisten chat -- Tahap 2 docs/kajian_agentic_workflow_fitur_ai.md.

Menjalankan setiap pertanyaan di scripts/uji_chat/pertanyaan.yaml lewat jalur
chat yang SAMA dgn aplikasi (chat_providers._call_chat, tanpa HTTP), memaksa
satu provider (tanpa cadangan) supaya kualitas tiap model terukur terpisah,
lalu memeriksa kriteria tiap butir dari SQL/tool/aksi yang benar-benar
dijalankan (meta) -- bukan sekadar membaca teks jawaban.

Tidak menulis ke chat_log (yang mencatat hanya route /api/chat). Biaya: satu
run = jumlah pertanyaan x provider panggilan LLM berbayar.

Usage (venv aktif, PG_* di .env -> DB yang jawaban kuncinya cocok):
    python scripts/uji_chat.py --provider DeepSeek
    python scripts/uji_chat.py --provider OpenAI --id q01,q03
    python scripts/uji_chat.py --provider DeepSeek --keluaran docs/uji_chat
Exit code 0 bila semua lulus, 1 bila ada yang gagal.
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import yaml  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")
import app  # noqa: E402  (memuat chat_providers + path scripts/)
import chat_providers as cp  # noqa: E402
from db import db_cursor  # noqa: E402

PERTANYAAN = Path(__file__).resolve().parent / "uji_chat" / "pertanyaan.yaml"
POLA_BERHENTI_DINI = re.compile(r"mohon konfirmasi|apakah anda ingin saya|apakah anda mau saya|silakan konfirmasi", re.I)
SATUAN = {"triliun": 1e12, "t": 1e12, "miliar": 1e9, "m": 1e9, "milyar": 1e9, "juta": 1e6, "jt": 1e6, "ribu": 1e3, "rb": 1e3}
POLA_ANGKA = re.compile(r"(?<![\d.,])(\d[\d.,]*)(?:\s*(triliun|miliar|milyar|juta|ribu|jt|rb|t|m)\b)?", re.I)


def _tafsir(token: str):
    """Angka teks -> kandidat nilai. Format Indonesia (1.234,5) maupun Inggris
    (1,234.5) dicoba, krn model tidak konsisten. Mengembalikan set float."""
    t = token.strip(".,")
    out = set()
    for ribuan, desimal in ((".", ","), (",", ".")):
        s = t
        if desimal in s and s.count(desimal) == 1:
            utuh, pecahan = s.split(desimal)
            if ribuan in utuh and not re.fullmatch(r"\d{1,3}(\%s\d{3})+" % ribuan, utuh):
                continue
            s = utuh.replace(ribuan, "") + "." + pecahan
        else:
            if ribuan in s and not re.fullmatch(r"\d{1,3}(\%s\d{3})+" % ribuan, s):
                # "38.1" tanpa koma: bisa desimal gaya Inggris
                if ribuan == "." and s.count(".") == 1:
                    out.add(float(s))
                continue
            s = s.replace(ribuan, "")
        try:
            out.add(float(s))
        except ValueError:
            pass
    return out


def angka_dalam(teks: str):
    hasil = []
    for m in POLA_ANGKA.finditer(teks):
        kali = SATUAN.get((m.group(2) or "").lower(), 1)
        for v in _tafsir(m.group(1)):
            hasil.append(v * kali)
            if kali != 1:
                hasil.append(v)
    return hasil


def cocok_angka(target: dict, nilai_jawaban) -> bool:
    v = float(target["nilai"])
    tol = target.get("abs")
    if tol is None:
        tol = abs(v) * float(target.get("rel", 0)) or 0.5  # bilangan bulat: harus persis
    return any(abs(x - v) <= tol for x in nilai_jawaban)


def nilai_db(sql):
    with db_cursor() as cur:
        cur.execute(sql)
        return list(cur.fetchone().values())[0]


def periksa(butir, teks, actions, meta, db_sebelum):
    gagal = []
    tools = [t.lower() for t in meta.get("tools", [])]
    sqls = " ".join(meta.get("sql", [])).lower()
    nama_aksi = {a.get("nama") for a in actions}
    if butir.get("harus_memakai"):
        if not any(x.lower() in tools or x.lower() in sqls for x in butir["harus_memakai"]):
            gagal.append(f"tidak memakai {' / '.join(butir['harus_memakai'])}")
    for a in butir.get("aksi_wajib", []):
        if a not in nama_aksi:
            gagal.append(f"aksi {a} tidak dipanggil")
    angka = angka_dalam(teks)
    for t in butir.get("angka", []):
        if not cocok_angka(t, angka):
            gagal.append(f"angka {t['nilai']:g} tidak ada di jawaban")
    for t in butir.get("teks_wajib", []):
        alternatif = t if isinstance(t, list) else [t]   # daftar = salah satu cukup
        if not any(x.lower() in teks.lower() for x in alternatif):
            gagal.append(f"teks '{' / '.join(alternatif)}' tidak ada")
    for pola in butir.get("tidak_boleh", []):
        if re.search(pola, teks, re.I):
            gagal.append(f"memuat pola terlarang /{pola}/")
    if butir.get("cek_db") and nilai_db(butir["cek_db"]) != db_sebelum:
        gagal.append("DATA BERUBAH -- guardrail tulis-data jebol")
    if POLA_BERHENTI_DINI.search(teks) and not actions and not tools:
        gagal.append("berhenti dini (minta konfirmasi tanpa mencoba)")
    if "Peringatan sistem" in teks:
        gagal.append("ditandai tabel karangan")
    return gagal


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", required=True, help="nama provider persis spt di _chat_providers (DeepSeek, OpenAI, Claude, ...)")
    ap.add_argument("--id", help="subset id dipisah koma, mis. q01,q03")
    ap.add_argument("--keluaran", type=Path, default=REPO_ROOT / "docs" / "uji_chat")
    args = ap.parse_args()

    butir_semua = yaml.safe_load(PERTANYAAN.read_text(encoding="utf-8"))
    if args.id:
        pilih = {x.strip() for x in args.id.split(",")}
        butir_semua = [b for b in butir_semua if b["id"] in pilih]

    hasil = []
    for b in butir_semua:
        db_sebelum = nilai_db(b["cek_db"]) if b.get("cek_db") else None
        mulai = time.time()
        try:
            teks, actions, meta = cp._call_chat([app.ChatMessage(role="user", text=b["pertanyaan"])], None,
                                                pengguna="uji_chat", peran="admin", hanya_provider=args.provider)
            gagal = periksa(b, teks, actions, meta, db_sebelum)
            galat = None
        except Exception as e:  # provider error = gagal, bukan crash seluruh run
            teks, actions, meta, gagal, galat = "", [], {}, [f"error: {str(e)[:200]}"], str(e)
        r = {"id": b["id"], "kategori": b["kategori"], "pertanyaan": b["pertanyaan"], "lulus": not gagal,
             "gagal": gagal, "durasi_detik": round(time.time() - mulai, 1), "model": meta.get("model"),
             "token_masuk": meta.get("token_masuk"), "token_keluar": meta.get("token_keluar"),
             "tools": meta.get("tools", []), "aksi": [a.get("nama") for a in actions], "jawaban": teks[:3000], "galat": galat,
             "direvisi": meta.get("direvisi"), "catatan": meta.get("catatan", []), "sql": meta.get("sql", []),
             "sql_galat": meta.get("sql_galat", [])}
        hasil.append(r)
        print(f"{'LULUS' if r['lulus'] else 'GAGAL'}  {b['id']} [{b['kategori']}] {r['durasi_detik']}s"
              + (" (direvisi)" if r["direvisi"] else "")
              + ("" if r["lulus"] else "  -> " + "; ".join(gagal)), flush=True)

    n_lulus = sum(r["lulus"] for r in hasil)
    per_kat = {}
    for r in hasil:
        k = per_kat.setdefault(r["kategori"], [0, 0])
        k[0] += r["lulus"]
        k[1] += 1
    tok_in = sum(r["token_masuk"] or 0 for r in hasil)
    tok_out = sum(r["token_keluar"] or 0 for r in hasil)
    model = next((r["model"] for r in hasil if r["model"]), args.provider)

    args.keluaran.mkdir(parents=True, exist_ok=True)
    cap = datetime.now().strftime("%Y%m%d_%H%M")
    dasar = args.keluaran / f"{cap}_{args.provider.lower()}"
    dasar.with_suffix(".json").write_text(json.dumps(hasil, ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# Uji asisten chat: {args.provider} ({model})", "",
          f"{datetime.now():%d %b %Y %H:%M} · {len(hasil)} pertanyaan · **lulus {n_lulus}/{len(hasil)} "
          f"({100 * n_lulus / max(1, len(hasil)):.0f}%)** · token masuk {tok_in:,} / keluar {tok_out:,} · "
          f"rata-rata {sum(r['durasi_detik'] for r in hasil) / max(1, len(hasil)):.1f} dtk/pertanyaan", "",
          "| Kategori | Lulus |", "|---|---|"]
    md += [f"| {k} | {v[0]}/{v[1]} |" for k, v in sorted(per_kat.items())]
    n_revisi = sum(1 for r in hasil if r.get("direvisi"))
    md += ["", f"Direvisi otomatis (Tahap 3): {n_revisi} pertanyaan.", "",
           "| ID | Kategori | Hasil | Revisi | Durasi | Tool dipakai | Alasan gagal |", "|---|---|---|---|---|---|---|"]
    md += [f"| {r['id']} | {r['kategori']} | {'✅' if r['lulus'] else '❌'} | {'ya' if r.get('direvisi') else ''} | {r['durasi_detik']} dtk | "
           f"{', '.join(dict.fromkeys(r['tools'])) or '-'} | {'; '.join(r['gagal']) or ''} |" for r in hasil]
    dasar.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\nLulus {n_lulus}/{len(hasil)}. Laporan: {dasar.with_suffix('.md')}")
    sys.exit(0 if n_lulus == len(hasil) else 1)


if __name__ == "__main__":
    main()
