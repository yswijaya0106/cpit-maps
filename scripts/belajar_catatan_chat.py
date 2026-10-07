# -*- coding: utf-8 -*-
"""Loop belajar catatan chat_pengetahuan/ -- Tahap 4b kajian agentic workflow.

Pola dari "Architecting an Agentic Workflow" (talks.isfa.dev/2026-agentic-workflow):
agen menulis kembali apa yang dipelajarinya ke catatan Markdown (memori yang
bertambah), tetapi catatan baru berstatus usulan dan baru berlaku setelah
direview manusia. Di sini:

1. KUMPULKAN kasus gagal:
   - chat_log (belum dipelajari): dinilai 👎 pengguna, direvisi otomatis
     (Tahap 3), query SQL error, atau semua provider gagal;
   - laporan paket uji (scripts/uji_chat.py, file .json) yg butirnya GAGAL.
2. AGEN (DeepSeek, DEEPSEEK_API_KEY di .env) membaca kasus + semua catatan
   yg berlaku, MEMERIKSA database lewat tool read-only (daftar_tabel_database,
   jalankan_query_sql), lalu mengusulkan catatan baru / perbaikan catatan lama
   lewat tool usulkan_catatan. Setiap fakta wajib punya bukti SQL.
3. VERIFIKASI: setiap bukti SQL dijalankan ulang oleh skrip ini (bukan oleh
   model). Hasilnya ditulis ke file .bukti.md di samping draf.
4. Draf ditulis ke chat_pengetahuan/_usulan/<tgl>-<nama>.md (status: usulan) --
   TIDAK dibaca chat (_muat_pengetahuan hanya membaca tingkat atas folder).
   Setelah dicek: `--terima <draf>` memindahkannya jadi catatan aktif (chat
   memuat ulang otomatis, tanpa restart), lalu jalankan uji_chat.py.

Kasus chat_log yg sudah diolah ditandai dipelajari_pada (kecuali --kering).
Biaya: satu run = satu sesi agen (beberapa-belasan panggilan DeepSeek).

Usage (venv aktif, PG_* & DEEPSEEK_API_KEY di .env):
    python scripts/belajar_catatan_chat.py --kering                 # lihat kasus saja, tanpa LLM
    python scripts/belajar_catatan_chat.py --hari 14
    python scripts/belajar_catatan_chat.py --uji docs/uji_chat/20261007_1530_openai.json
    python scripts/belajar_catatan_chat.py --terima chat_pengetahuan/_usulan/20261008-pelabuhan.md
"""
import argparse
import io
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
import requests  # noqa: E402
from fastapi.encoders import jsonable_encoder  # noqa: E402

import chat_providers as cp  # noqa: E402
from db import db_cursor  # noqa: E402

DIR_CATATAN = ROOT / "chat_pengetahuan"
DIR_USULAN = DIR_CATATAN / "_usulan"
MAKS_PUTARAN = 30
MAKS_BARIS_SQL = 30
_NAMA_VALID = re.compile(r"^[a-z0-9_]{3,40}$")

SISTEM = """Kamu kurator pengetahuan untuk asisten chat aplikasi SiJalan (data jalan, transportasi, wilayah Indonesia, PostgreSQL/PostGIS).
Asisten chat itu dibantu CATATAN SUMBER DATA: file Markdown pendek per topik yang menyebut tabel/kolom/layer yang BENAR dan jebakan datanya, disisipkan ke prompt bila kata kuncinya muncul di pertanyaan.

Tugasmu: dari KASUS GAGAL di bawah, cari penyebab yang bisa dicegah oleh catatan (tabel salah, kolom salah tebak, nilai filter salah tulis, kata kunci catatan tidak cocok dgn cara pengguna bertanya, jebakan data), lalu usulkan catatan baru atau perbaikan catatan lama.

Aturan:
- PERIKSA dulu ke database (daftar_tabel_database, jalankan_query_sql). Jangan menulis nama tabel/kolom/nilai yang belum kamu lihat sendiri hasilnya.
- Setiap usulan wajib menyertakan bukti_sql: 1-4 query SELECT pendek yang membuktikan fakta di catatan (mis. SELECT DISTINCT kolom ..., atau contoh baris). Skrip akan menjalankannya ulang.
- Catatan ringkas (maks ~120 kata), poin-poin, hanya fakta yang membantu menyusun query yang benar. Jangan menulis jawaban pertanyaan tertentu atau angka yang cepat basi.
- Memperbaiki catatan lama: pakai nama yang sama dan tulis ISI LENGKAP penggantinya (bukan hanya tambahan). Kata kunci juga lengkap.
- kata_kunci: kata/frasa yang benar-benar dipakai pengguna, huruf kecil; akhiran * = awalan kata.
- Kasus yang penyebabnya bukan data/catatan (mis. provider error, model malas, pertanyaan di luar data) cukup dilewati.
- Bila tidak ada yang layak diusulkan, katakan saja. Akhiri dgn ringkasan singkat apa yang kamu usulkan dan kenapa."""

ALAT = [
    next(t for t in cp.CHAT_TOOLS if t["function"]["name"] == "daftar_tabel_database"),
    {"type": "function", "function": {
        "name": "jalankan_query_sql",
        "description": f"Jalankan satu SELECT read-only (maks {MAKS_BARIS_SQL} baris kembali).",
        "parameters": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}}},
    {"type": "function", "function": {
        "name": "usulkan_catatan",
        "description": "Usulkan satu catatan baru atau pengganti catatan lama (nama sama = menggantikan).",
        "parameters": {"type": "object", "required": ["nama", "judul", "kata_kunci", "isi", "alasan", "bukti_sql"],
                       "properties": {
                           "nama": {"type": "string", "description": "nama file tanpa .md, huruf kecil/angka/_"},
                           "judul": {"type": "string"},
                           "kata_kunci": {"type": "array", "items": {"type": "string"}},
                           "isi": {"type": "string", "description": "isi catatan Markdown (poin-poin)"},
                           "alasan": {"type": "string", "description": "kasus mana yg dicegah & bagaimana"},
                           "kasus": {"type": "array", "items": {"type": "string"}, "description": "id kasus, mis. log:12, uji:q03"},
                           "bukti_sql": {"type": "array", "items": {"type": "string"}}}}}},
]


# ---------- 1. kasus ----------

def kasus_chat_log(hari: int) -> list:
    with db_cursor() as cur:
        cur.execute("SELECT to_regclass('public.chat_log') t")
        if not cur.fetchone()["t"]:
            return []
        cur.execute((ROOT / "scripts" / "schema_chat_log.sql").read_text(encoding="utf-8"))  # kolom Tahap 4b
        cur.execute(
            """SELECT id, pertanyaan, provider, tools, sql_dijalankan, sql_galat, direvisi, catatan, nilai,
                      komentar, jawaban_dinilai, galat
               FROM chat_log
               WHERE dipelajari_pada IS NULL AND waktu > now() - make_interval(days => %s)
                 AND pengguna IS DISTINCT FROM 'uji_chat'
                 AND (nilai = -1 OR direvisi IS NOT NULL OR cardinality(sql_galat) > 0
                      OR (galat IS NOT NULL AND provider IS NULL))
               ORDER BY id""", (hari,))
        rows = cur.fetchall()
    out = []
    for r in rows:
        if r["galat"] and r["nilai"] != -1 and not r["sql_galat"]:
            continue  # semua provider gagal (saldo/jaringan) -- bukan urusan catatan
        alasan = []
        if r["nilai"] == -1:
            alasan.append("dinilai 👎 pengguna" + (f": {r['komentar']}" if r["komentar"] else ""))
        if r["direvisi"]:
            alasan.append(f"direvisi otomatis: {r['direvisi'][:200]}")
        if r["sql_galat"]:
            alasan.append("query error: " + " | ".join(e[:200] for e in r["sql_galat"][:3]))
        out.append({"id": f"log:{r['id']}", "pertanyaan": r["pertanyaan"], "alasan": alasan,
                    "tools": r["tools"], "sql": [s[:600] for s in (r["sql_dijalankan"] or [])][:6],
                    "catatan_dipakai": r["catatan"], "jawaban": (r["jawaban_dinilai"] or "")[:1500] or None,
                    "_log_id": r["id"]})
    return out


def kasus_uji(paths: list) -> list:
    out = []
    for p in paths:
        for r in json.loads(Path(p).read_text(encoding="utf-8")):
            if r.get("lulus"):
                continue
            out.append({"id": f"uji:{r['id']}", "pertanyaan": r["pertanyaan"], "alasan": r.get("gagal", []),
                        "tools": r.get("tools"), "sql": [s[:600] for s in r.get("sql", [])][:6],
                        "catatan_dipakai": r.get("catatan"), "jawaban": (r.get("jawaban") or "")[:1500]})
    return out


# ---------- 2. agen ----------

def sql_readonly(sql: str, maks: int = MAKS_BARIS_SQL) -> dict:
    galat = cp._validasi_sql_readonly(sql or "")
    if galat:
        return {"error": galat}
    if cp._SQL_TABEL_TERLARANG.search(sql):
        return {"error": "tabel terlarang"}
    try:
        with db_cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SET LOCAL statement_timeout = 20000")
            cur.execute(sql.strip().rstrip(";"))
            kolom = [d.name for d in cur.description or []]
            baris = cur.fetchmany(maks)
    except Exception as e:  # noqa: BLE001 -- error dikembalikan ke model
        return {"error": str(e)[:500]}
    return {"kolom": kolom, "jumlah_baris_ditampilkan": len(baris), "baris": jsonable_encoder([dict(b) for b in baris])}


def jalankan_agen(kasus: list, catatan: list, model: str) -> list:
    kunci = os.getenv("DEEPSEEK_API_KEY")
    if not kunci:
        raise SystemExit("DEEPSEEK_API_KEY kosong di .env")
    teks_catatan = "\n\n".join(f"### [{c['nama']}] {c['judul']}\nkata_kunci: {c['kata_kunci']}\n{c['isi']}" for c in catatan)
    teks_kasus = json.dumps([{k: v for k, v in x.items() if not k.startswith("_")} for x in kasus],
                            ensure_ascii=False, indent=1)
    pesan = [{"role": "system", "content": SISTEM},
             {"role": "user", "content": f"CATATAN YANG BERLAKU:\n\n{teks_catatan}\n\nKASUS GAGAL:\n{teks_kasus}"}]
    usulan = []
    for putaran in range(MAKS_PUTARAN):
        r = requests.post(cp.DEEPSEEK_API_URL, timeout=300,
                          headers={"Authorization": f"Bearer {kunci}", "Content-Type": "application/json"},
                          json={"model": model, "messages": pesan, "tools": ALAT, "tool_choice": "auto"})
        if r.status_code != 200:
            raise SystemExit(f"DeepSeek HTTP {r.status_code}: {r.text[:500]}")
        msg = r.json()["choices"][0]["message"]
        pesan.append(msg)  # utuh, termasuk reasoning_content (thinking mode)
        if not msg.get("tool_calls"):
            print("\nRingkasan agen:\n" + (msg.get("content") or "").strip())
            return usulan
        for tc in msg["tool_calls"]:
            nama = tc["function"]["name"]
            try:
                arg = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                arg = {}
            if nama == "daftar_tabel_database":
                hasil = cp._tool_daftar_tabel_database(**{k: v for k, v in arg.items() if k in ("tabel", "kelompok_layer")})
            elif nama == "jalankan_query_sql":
                hasil = sql_readonly(arg.get("sql"))
                print(f"  [sql] {str(arg.get('sql'))[:140]} -> {hasil.get('error') or str(hasil['jumlah_baris_ditampilkan']) + ' baris'}")
            elif nama == "usulkan_catatan":
                if not _NAMA_VALID.match(str(arg.get("nama", ""))):
                    hasil = {"error": "nama harus huruf kecil/angka/_ (3-40 karakter)"}
                elif not arg.get("bukti_sql"):
                    hasil = {"error": "bukti_sql wajib"}
                else:
                    usulan.append(arg)
                    hasil = {"status": "dicatat", "nama": arg["nama"]}
                    print(f"  [usulan] {arg['nama']}: {arg.get('alasan', '')[:160]}")
            else:
                hasil = {"error": "tool tidak dikenal"}
            pesan.append({"role": "tool", "tool_call_id": tc["id"],
                          "content": json.dumps(jsonable_encoder(hasil), ensure_ascii=False, default=str)[:30000]})
    print(f"(berhenti setelah {MAKS_PUTARAN} putaran)")
    return usulan


# ---------- 3-4. verifikasi & tulis draf ----------

def tulis_draf(u: dict, model: str, berlaku: set) -> Path:
    DIR_USULAN.mkdir(parents=True, exist_ok=True)
    bukti, semua_ok = [], True
    for sql in u["bukti_sql"][:4]:
        h = sql_readonly(sql, maks=10)
        ok = not h.get("error") and h["jumlah_baris_ditampilkan"] > 0
        semua_ok &= ok
        bukti.append((sql, ok, h))
    tgl = date.today().strftime("%Y%m%d")
    draf = DIR_USULAN / f"{tgl}-{u['nama']}.md"
    kunci = ", ".join(k.strip().lower() for k in u["kata_kunci"] if k.strip())
    draf.write_text(
        "---\n"
        f"judul: {u['judul'].strip()}\n"
        f"kata_kunci: [{kunci}]\n"
        "status: usulan\n"
        f"menggantikan: {u['nama'] + '.md' if u['nama'] in berlaku else '-'}\n"
        f"kasus: [{', '.join(u.get('kasus') or [])}]\n"
        f"verifikasi: {'lolos' if semua_ok else 'GAGAL -- periksa .bukti.md'}\n"
        f"dibuat: {datetime.now():%Y-%m-%d %H:%M} oleh {model} (scripts/belajar_catatan_chat.py)\n"
        "---\n" + u["isi"].strip() + "\n", encoding="utf-8", newline="\n")
    baris = [f"# Bukti usulan catatan `{u['nama']}`", "", f"**Alasan agen:** {u.get('alasan', '')}", ""]
    if u["nama"] in berlaku:
        baris += ["**Catatan lama yang digantikan:**", "", "```", (DIR_CATATAN / f"{u['nama']}.md").read_text(encoding="utf-8").strip(), "```", ""]
    for sql, ok, h in bukti:
        baris += [f"## {'✅' if ok else '❌'} bukti", "", "```sql", sql.strip(), "```", "",
                  "```json", json.dumps(h, ensure_ascii=False, indent=1, default=str)[:4000], "```", ""]
    draf.with_suffix(".bukti.md").write_text("\n".join(baris), encoding="utf-8", newline="\n")
    return draf


def terima(path: str):
    draf = Path(path).resolve()
    teks = draf.read_text(encoding="utf-8")
    m = re.match(r"---\s*\n(.*?)\n---\s*\n(.*)", teks, re.S)
    if not m or "status: usulan" not in m.group(1):
        raise SystemExit("Bukan draf usulan (frontmatter status: usulan tidak ada)")
    kepala = dict(re.findall(r"^(\w+):\s*(.+)$", m.group(1), re.M))
    if kepala.get("verifikasi", "").startswith("GAGAL"):
        print("PERINGATAN: verifikasi bukti SQL gagal -- pastikan isinya sudah dibetulkan manual.")
    nama = re.sub(r"^\d{8}-", "", draf.stem)
    tujuan = DIR_CATATAN / f"{nama}.md"
    tujuan.write_text(f"---\njudul: {kepala['judul']}\nkata_kunci: {kepala['kata_kunci']}\n---\n{m.group(2).strip()}\n",
                      encoding="utf-8", newline="\n")
    draf.unlink()
    draf.with_suffix(".bukti.md").unlink(missing_ok=True)
    print(f"Diterima -> {tujuan.relative_to(ROOT)} (chat memuatnya otomatis). "
          "Jalankan scripts/uji_chat.py --provider DeepSeek utk memastikan tidak ada regresi.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hari", type=int, default=30, help="ambil kasus chat_log N hari terakhir")
    ap.add_argument("--uji", nargs="*", default=[], help="laporan .json scripts/uji_chat.py")
    ap.add_argument("--maks-kasus", type=int, default=20)
    ap.add_argument("--model", default=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"))
    ap.add_argument("--kering", action="store_true", help="hanya tampilkan kasus, tanpa LLM & tanpa menandai")
    ap.add_argument("--terima", help="jadikan satu draf _usulan/ catatan aktif")
    args = ap.parse_args()
    if args.terima:
        return terima(args.terima)

    kasus = (kasus_chat_log(args.hari) + kasus_uji(args.uji))[: args.maks_kasus]
    print(f"{len(kasus)} kasus:")
    for k in kasus:
        print(f"  {k['id']:10s} {str(k['pertanyaan'])[:90]!r} -- {'; '.join(k['alasan'])[:150]}")
    if not kasus or args.kering:
        return

    catatan = [{"nama": c["nama"], "judul": c["judul"], "isi": c["isi"],
                "kata_kunci": re.search(r"kata_kunci:\s*(.+)", (DIR_CATATAN / f"{c['nama']}.md").read_text(encoding="utf-8")).group(1)}
               for c in cp._muat_pengetahuan()]
    usulan = jalankan_agen(kasus, catatan, args.model)
    berlaku = {c["nama"] for c in catatan}
    for u in usulan:
        draf = tulis_draf(u, args.model, berlaku)
        print(f"Draf: {draf.relative_to(ROOT)}  (+ .bukti.md)")

    log_ids = [k["_log_id"] for k in kasus if "_log_id" in k]
    if log_ids:
        with db_cursor() as cur:
            cur.execute("UPDATE chat_log SET dipelajari_pada = now() WHERE id = ANY(%s)", (log_ids,))
    if usulan:
        print("\nReview tiap draf + .bukti.md, lalu: python scripts/belajar_catatan_chat.py --terima <draf>")


if __name__ == "__main__":
    main()
