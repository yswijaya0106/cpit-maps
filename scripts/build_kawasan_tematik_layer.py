# -*- coding: utf-8 -*-
"""Petakan kawasan tematik Bappenas (tabel `kawasan_tematik`, tidak punya geometri)
ke poligon wilayah -> bucket overlay "KAWASAN TEMATIK BAPPENAS" di map_layers.

Latar (4 Okt 2026, permintaan pengguna): data kawasan sudah ada di database tapi
dalam bentuk tabel (nama kab/kota + daftar kecamatan), bukan KML/poligon, jadi
tidak bisa tampil di peta/legenda. Skrip ini meminjam poligon BATAS KECAMATAN /
BATAS KABUPATEN yang sudah ada di map_layers:

- baris dgn kode_kecamatan        -> poligon kecamatan itu (dasar "kode sumber")
- baris dgn teks daftar kecamatan -> dipecah (koma/titik koma/"dan"), dicocokkan
  ke nama kecamatan resmi (ref_wilayah) DI KAB/KOTA YANG SAMA: persis, lalu
  awalan/penggalan, lalu kemiripan >= 0,85 (dasar "nama"); nama yg tak cocok
  dicatat di atribut "Nama sumber tak cocok"
- baris tanpa kecamatan ("-"/kosong, mis. seluruh TRANSMIGRASI) -> poligon
  kab/kota, atribut Cakupan = "Kab/kota (sumber tidak merinci kecamatan)"

Satu fitur per (kategori, wilayah) -- baris sumber yg menunjuk wilayah sama
digabung (sheet & nama sumber dijadikan daftar). Layer = satu per kategori.
Geometri DISALIN dari poligon batas (INSERT ... SELECT geom), jadi ikut versi
BATAS_ADMINISTRASI yang sedang terimpor; jalankan ulang setelah
import_kawasan_tematik.py atau impor ulang batas wilayah.

wilayah_provinsi diisi langsung dari atribut PROVINSI poligon sumbernya (nama
provinsinya identik dgn BATAS PROVINSI), jadi pemecahan per provinsi di tree
Overlay Peta langsung aktif tanpa build_map_layer_wilayah.py.

DELETE + INSERT seluruh bucket, aman diulang.

Usage (venv aktif, .env berisi PG_*):
    python scripts/build_kawasan_tematik_layer.py
"""
import difflib
import io
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
from psycopg.types.json import Json  # noqa: E402

from db import db_cursor  # noqa: E402

BUCKET = "KAWASAN TEMATIK BAPPENAS"
LAYER = {  # kategori kawasan_tematik -> nama layer
    "PERKEBUNAN": "Kawasan Perkebunan",
    "PERIKANAN": "Kawasan Kelautan & Perikanan",
    "TRANSMIGRASI": "Kawasan Transmigrasi",
    "KI_PRIORITAS": "Kawasan Industri Prioritas",
    "PKPN": "Lokus PKPN 3T",
}
AMBANG_MIRIP = 0.85
AMBANG_MIRIP_POLIGON = 0.8  # nama BPS vs nama di gdb batas (Keramat/Keuramat, Ulu/Hulu)
_AWALAN_KEC = re.compile(r"^(KECAMATAN|KEC\.?|DISTRIK)\s+", re.I)
_SELURUH = re.compile(r"^(SELURU?H|SEMUA)\b", re.I)
# singkatan umum di sumber -> kata lengkap (dicek sbg kata utuh)
_SINGKATAN = [
    (r"\bGn\.?(?=\s|$)", "Gunung"), (r"\bTj\.?(?=\s|$)", "Tanjung"), (r"\bKp\.?(?=\s|$)", "Kampung"),
    (r"\bSei\.?(?=\s|$)", "Sungai"), (r"\bSTM\b", "Sinembah Tanjung Muda"), (r"\bKep\.?(?=\s|$)", "Kepulauan"),
    (r"\bP\.(?=\s)", "Pulau"),
]


def norm(s) -> str:
    s = str(s or "")
    for pola, ganti in _SINGKATAN:
        s = re.sub(pola, ganti, s, flags=re.I)
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def pecah_kecamatan(teks):
    """'Long Ikis, Kuaro dan Batu Sopang' -> ['Long Ikis', 'Kuaro', 'Batu Sopang'].
    'Seluruh Kecamatan' / 'Semua kecamatan' / '-' -> [] (= seluruh kab/kota)."""
    teks = str(teks or "").strip()
    if not teks or teks in {"-", "--", "–"} or _SELURUH.match(teks):
        return []
    bagian = re.split(r"[,;/\n]|\s+dan\s+|\s*&\s*", teks, flags=re.I)
    out = []
    for b in bagian:
        b = _AWALAN_KEC.sub("", b.strip(" .-"))
        if _SELURUH.match(b):
            return []  # salah satu butir "Seluruh Kecamatan" -> seluruh kab/kota
        if b and b not in {"-", "--"}:
            out.append(b)
    return out


def cocokkan(nama, kandidat):
    """nama sumber -> (kode_kec, nama_resmi) di kab yg sama, atau None.
    kandidat: list (kode_kec, nama_resmi)."""
    n = norm(nama)
    if not n:
        return None
    by_norm = {norm(k[1]): k for k in kandidat}
    if n in by_norm:
        return by_norm[n]
    awal = [k for k in kandidat if norm(k[1]).startswith(n) or n.startswith(norm(k[1]))]
    if len(awal) == 1:
        return awal[0]
    mirip = difflib.get_close_matches(n, list(by_norm), n=1, cutoff=AMBANG_MIRIP)
    return by_norm[mirip[0]] if mirip else None


def main():
    with db_cursor() as cur:
        cur.execute("SELECT kode_kecamatan, kode_kabupaten, nama_kecamatan, nama_kabupaten_kota, jenis_kabupaten, "
                    "nama_provinsi FROM ref_wilayah")
        ref = cur.fetchall()
        kec_per_kab = defaultdict(list)
        nama_kab = {}
        for r in ref:
            kec_per_kab[r["kode_kabupaten"]].append((r["kode_kecamatan"], r["nama_kecamatan"]))
            nama_kab[r["kode_kabupaten"]] = (f"{'Kota' if r['jenis_kabupaten'] == 'KOTA' else 'Kab.'} "
                                             f"{str(r['nama_kabupaten_kota']).title()}")

        # poligon kab/kota: KODE_KABUPATEN -> id (semua berkode sejak perbaikan 3 Okt 2026)
        cur.execute("SELECT id, attrs FROM map_layers WHERE provinsi='BATAS KABUPATEN'")
        kab_poly, kab_kode_by_nama = {}, {}
        for r in cur.fetchall():
            a = r["attrs"] or {}
            if a.get("KODE_KABUPATEN") is not None:
                k = int(a["KODE_KABUPATEN"])
                kab_poly.setdefault(k, r["id"])
                kab_kode_by_nama[(a.get("PROVINSI"), norm(a.get("KABUPATEN_KOTA")))] = k

        # poligon kecamatan: kode -> id, plus (kode_kab, nama) -> id utk poligon tanpa kode (mis. DKI)
        cur.execute("SELECT id, attrs FROM map_layers WHERE provinsi='BATAS KECAMATAN'")
        kec_poly, kec_poly_nama, kec_poly_per_kab = {}, {}, defaultdict(list)
        for r in cur.fetchall():
            a = r["attrs"] or {}
            kode = a.get("KODE_KECAMATAN")
            if kode is not None:
                kode = int(float(kode))
                kec_poly.setdefault(kode, r["id"])
                kab = kode // 1000
            else:
                kab = kab_kode_by_nama.get((a.get("PROVINSI"), norm(a.get("KABUPATEN_KOTA"))))
            if kab is not None:
                kec_poly_nama.setdefault((kab, norm(a.get("KECAMATAN"))), r["id"])
                kec_poly_per_kab[kab].append((norm(a.get("KECAMATAN")), r["id"]))

        cur.execute("SELECT kategori, provinsi_asli, kabupaten_asli, kecamatan_asli, kode_kabupaten, kode_kecamatan, "
                    "keterangan, sumber_sheet FROM kawasan_tematik ORDER BY kategori, id")
        rows = cur.fetchall()

    fitur = {}  # (kategori, tingkat, kode) -> dict
    statistik = defaultdict(lambda: defaultdict(int))
    tak_cocok_total = []

    def tambah(kat, tingkat, kode, dasar, row, nama_sumber, tak_cocok=()):
        kunci = (kat, tingkat, kode)
        f = fitur.setdefault(kunci, {"dasar": set(), "sheet": set(), "nama": set(), "ket": set(), "tak_cocok": set(),
                                     "kode_kab": row["kode_kabupaten"]})
        f["dasar"].add(dasar)
        if row["sumber_sheet"]:
            f["sheet"].add(row["sumber_sheet"].strip())
        if nama_sumber:
            f["nama"].add(nama_sumber)
        if row["keterangan"]:
            f["ket"].add(row["keterangan"].strip())
        f["tak_cocok"].update(tak_cocok)

    for row in rows:
        kat, kab = row["kategori"], row["kode_kabupaten"]
        if row["kode_kecamatan"]:
            tambah(kat, "kec", int(row["kode_kecamatan"]), "kode sumber", row, row["kecamatan_asli"])
            statistik[kat]["kode sumber"] += 1
            continue
        nama_list = pecah_kecamatan(row["kecamatan_asli"])
        if not kab:
            statistik[kat]["tanpa kode kab/kota (dilewati)"] += 1
            tak_cocok_total.append((kat, row["kabupaten_asli"], row["kecamatan_asli"], "kab/kota tak berkode"))
            continue
        cocok, gagal = [], []
        for nama in nama_list:
            hasil = cocokkan(nama, kec_per_kab.get(kab, []))
            (cocok if hasil else gagal).append((nama, hasil))
        for nama, hasil in cocok:
            tambah(kat, "kec", hasil[0], "nama", row, nama)
        if gagal:
            tak_cocok_total.extend((kat, row["kabupaten_asli"], n, "kecamatan tak cocok") for n, _ in gagal)
        if not cocok:  # tanpa daftar kecamatan, atau tak satu pun cocok -> tingkat kab/kota
            tambah(kat, "kab", kab, "seluruh kab/kota" if not nama_list else "nama kecamatan tak cocok", row,
                   row["kecamatan_asli"], [n for n, _ in gagal])
            statistik[kat]["kab/kota" if not nama_list else "kab/kota (nama kec tak cocok)"] += 1
        else:
            statistik[kat]["nama"] += 1

    nama_kec = {r["kode_kecamatan"]: r["nama_kecamatan"] for r in ref}
    tanpa_poligon = []
    sisip = []
    for (kat, tingkat, kode), f in fitur.items():
        if tingkat == "kec":
            kab = kode // 1000
            pid = kec_poly.get(kode) or kec_poly_nama.get((kab, norm(nama_kec.get(kode))))
            if pid is None:  # ejaan BPS vs gdb beda (Keramat/Keuramat) -> cari yg mirip di kab sama
                calon = dict(kec_poly_per_kab.get(kab, []))
                mirip = difflib.get_close_matches(norm(nama_kec.get(kode)), list(calon), n=1, cutoff=AMBANG_MIRIP_POLIGON)
                pid = calon[mirip[0]] if mirip else None
        else:
            pid = kab_poly.get(kode)
            kab = kode
        if pid is None:
            tanpa_poligon.append((kat, tingkat, kode))
            continue
        attrs = {
            "Kategori": LAYER.get(kat, kat),
            "Kabupaten/Kota": nama_kab.get(kab, str(kab)),
            "Kecamatan": str(nama_kec.get(kode, "")).title() if tingkat == "kec" else "Seluruh kab/kota",
            "Cakupan": "Kecamatan" if tingkat == "kec" else "Kab/kota (sumber tidak merinci kecamatan)",
            "Dasar pencocokan": ", ".join(sorted(f["dasar"])),
            "Nama di sumber": "; ".join(sorted(f["nama"])) or None,
            "Nama sumber tak cocok": "; ".join(sorted(f["tak_cocok"])) or None,
            "Sumber": "Bappenas — " + "; ".join(sorted(f["sheet"])),
            "Keterangan": "; ".join(sorted(f["ket"])) or None,
            "Kode wilayah (BPS)": kode,
        }
        sisip.append((LAYER.get(kat, kat), Json({k: v for k, v in attrs.items() if v is not None}), pid))

    with db_cursor() as cur:
        cur.execute("DELETE FROM map_layers WHERE provinsi=%s", (BUCKET,))
        cur.execute("DELETE FROM map_layer_meta WHERE provinsi=%s", (BUCKET,))
        cur.executemany(
            "INSERT INTO map_layers (provinsi, kabupaten, layer, attrs, geom, wilayah_provinsi) "
            "SELECT %s, '', %s, %s, s.geom, ARRAY[s.attrs->>'PROVINSI'] FROM map_layers s WHERE s.id = %s",
            [(BUCKET, layer, attrs, pid) for layer, attrs, pid in sisip])
        cur.execute("""
            INSERT INTO map_layer_meta (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp)
            SELECT provinsi, kabupaten, layer, layer, COUNT(*),
                   ROUND((SUM(pg_column_size(geom) + pg_column_size(attrs)) / 1048576.0)::numeric, 2),
                   'tabel kawasan_tematik x poligon BATAS KECAMATAN/KABUPATEN (scripts/build_kawasan_tematik_layer.py)'
            FROM map_layers WHERE provinsi = %s GROUP BY provinsi, kabupaten, layer""", (BUCKET,))
        cur.execute("SELECT layer, feature_count, size_mb FROM map_layer_meta WHERE provinsi=%s ORDER BY layer", (BUCKET,))
        hasil = cur.fetchall()

    print(f"Bucket {BUCKET}:")
    for r in hasil:
        print(f"  {r['layer']}: {r['feature_count']} poligon ({r['size_mb']} MB)")
    print("Dasar per kategori (baris sumber):")
    for kat, d in statistik.items():
        print(f"  {kat}: " + ", ".join(f"{k} {v}" for k, v in d.items()))
    if tanpa_poligon:
        print(f"Wilayah tanpa poligon batas ({len(tanpa_poligon)}): {tanpa_poligon[:10]}")
    if tak_cocok_total:
        print(f"Nama tak cocok ({len(tak_cocok_total)}), contoh:")
        for t in tak_cocok_total[:15]:
            print("  ", t)


if __name__ == "__main__":
    main()
