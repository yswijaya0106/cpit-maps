"""Pencocok nama kabupaten/kota dari file sumber (teks bebas) ke master BPS
(penduduk_kecamatan) -- dipakai bersama import_bappenas_lokus_a.py dan
import_kawasan_tematik.py.

Menggantikan indeks lama {(provinsi, nama tanpa awalan): baris} yang punya dua
cacat (laporan penguji 28 Sep 2026, "nama kabupaten tidak terbaca di beberapa
lokasi prioritas", contoh Fakfak):

1. Beda spasi/tanda hubung dianggap nama lain: sumber "FAK FAK" tidak pernah
   cocok dgn master "FAKFAK" -> 15 kecamatan lokus PKPN 3T Fakfak hilang
   (kolom PKPN kosong di Lokasi Prioritas). Kini kunci = huruf+angka saja.
2. Kab & Kota bernama sama saling menimpa di dict (master tidak menyimpan
   awalan; "Kab. Blitar" dan "Kota Blitar" dua-duanya "BLITAR") -> yang
   tersimpan terakhir (Kota) menang: lokus KDMP Kab. Blitar/Kediri/Mojokerto/
   Magelang tercatat ke kode KOTA-nya. Kini jenis dibedakan (kode BPS 2 digit
   terakhir >= 71 = Kota); nama tanpa awalan = Kabupaten bila keduanya ada.

Tambahan: koreksi salah ketik yg NYATA ada di sumber (ALIAS_NAMA -- tambah
entri hanya setelah dicek thd master), alias singkatan provinsi, dan
fallback cari nama se-nasional (hanya bila hasilnya tunggal) utk provinsi
yang salah/kedaluwarsa di sumber (mis. kolom provinsi "JAYAPURA", atau
kabupaten Papua Barat Daya yang masih ditulis "Papua Barat").
"""
import re

# kunci sumber (salah ketik/nama lama) -> kunci master; kunci = huruf+angka saja, huruf besar
ALIAS_NAMA = {
    "GUNGMAS": "GUNUNGMAS",
    "OGAHILIR": "OGANILIR",
    "OGAHKOMERINGILIR": "OGANKOMERINGILIR",
    "OGAHKOMERINGULU": "OGANKOMERINGULU",
    "OGAHKOMERINGULUTIMUR": "OGANKOMERINGULUTIMUR",
    "TULUNGANGUNG": "TULUNGAGUNG",
    "TELUKWODAMA": "TELUKWONDAMA",
    "KUTAIKERTANEGARA": "KUTAIKARTANEGARA",
    "MAHAKAMHUKU": "MAHAKAMULU",
    "TOBASAMOSIR": "TOBA",
    "PARIGIMOUNTOUNG": "PARIGIMOUTONG",
    "PALI": "PENUKALABABLEMATANGILIR",
    "PANGKAJENEKEPULAUAN": "PANGKAJENEDANKEPULAUAN",
    "KEPSIAUTAGULANDANGBIARO": "KEPULAUANSIAUTAGULANDANGBIARO",
    "SIAUTAGULANDANGBIARO": "KEPULAUANSIAUTAGULANDANGBIARO",
    # BIG gdb "Administrasi Kepulauan Seribu", SIGAP/BPS "Adm. Kep. Seribu"
    "ADMINISTRASIKEPULAUANSERIBU": "KEPULAUANSERIBU",
    "ADMKEPSERIBU": "KEPULAUANSERIBU",
    "PADANGSIDEMPUAN": "PADANGSIDIMPUAN",
}

ALIAS_PROVINSI = {
    "NTT": "NUSATENGGARATIMUR",
    "NTB": "NUSATENGGARABARAT",
    "DIY": "DIYOGYAKARTA",
    "YOGYAKARTA": "DIYOGYAKARTA",
    "DAERAHISTIMEWAYOGYAKARTA": "DIYOGYAKARTA",
    "JAKARTA": "DKIJAKARTA",
    "DAERAHKHUSUSIBUKOTAJAKARTA": "DKIJAKARTA",
    "BANGKABELITUNG": "KEPULAUANBANGKABELITUNG",
    "BABEL": "KEPULAUANBANGKABELITUNG",
    "KEPRI": "KEPULAUANRIAU",
    "SUMUT": "SUMATERAUTARA",
    "SUMBAR": "SUMATERABARAT",
    "SUMSEL": "SUMATERASELATAN",
}

_AWALAN_KOTA = re.compile(r"^\s*KOTA(\s+ADM(INISTRASI)?\.?)?\s+", re.I)
_AWALAN_KAB = re.compile(r"^\s*(KABUPATEN|KAB\.?)(\s+ADM(INISTRASI)?\.?)?\s+", re.I)
_AWALAN_PROV = re.compile(r"^\s*(PROVINSI|PROV\.?)\s+", re.I)


def kunci(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def pecah_jenis(nama):
    """-> (jenis 'KOTA'|'KABUPATEN'|None, kunci nama tanpa awalan)."""
    s = str(nama or "").replace("\xa0", " ").strip()
    if _AWALAN_KOTA.match(s):
        return "KOTA", kunci(_AWALAN_KOTA.sub("", s))
    if _AWALAN_KAB.match(s):
        return "KABUPATEN", kunci(_AWALAN_KAB.sub("", s))
    return None, kunci(s)


def kunci_provinsi(s) -> str:
    k = kunci(_AWALAN_PROV.sub("", str(s or "")))
    return ALIAS_PROVINSI.get(k, k)


class PencocokKabupaten:
    """master_rows: dict dgn kode_provinsi, provinsi, kode_kabupaten, kabupaten_kota."""

    def __init__(self, master_rows):
        self.per_prov = {}   # (kunci_prov, kunci_nama) -> [baris]
        self.nasional = {}   # kunci_nama -> [baris]
        for m in master_rows:
            m = dict(m)
            m["jenis"] = "KOTA" if int(m["kode_kabupaten"]) % 100 >= 71 else "KABUPATEN"
            kn = kunci(m["kabupaten_kota"])
            self.per_prov.setdefault((kunci_provinsi(m["provinsi"]), kn), []).append(m)
            self.nasional.setdefault(kn, []).append(m)

    @staticmethod
    def _pilih(kandidat, jenis):
        if not kandidat:
            return None
        if jenis:
            sama = [m for m in kandidat if m["jenis"] == jenis]
            return sama[0] if len(sama) == 1 else None
        if len(kandidat) == 1:
            return kandidat[0]
        # nama tanpa awalan & ada Kab + Kota bernama sama -> Kabupaten (konvensi sumber)
        kab = [m for m in kandidat if m["jenis"] == "KABUPATEN"]
        return kab[0] if len(kab) == 1 else None

    def cari(self, provinsi, kabupaten):
        """Baris master atau None. provinsi boleh None/salah -> fallback se-nasional bila tunggal."""
        if not kabupaten:
            return None
        jenis, kn = pecah_jenis(kabupaten)
        hasil = self._cari(provinsi, jenis, kn)
        if hasil is None and jenis == "KOTA":
            # "Kota Waringin Barat" = Kab. KOTAWARINGIN BARAT: "Kota" bagian dari nama, bukan awalan
            hasil = self._cari(provinsi, None, kunci(kabupaten))
        return hasil

    def kandidat(self, provinsi, kabupaten):
        """Semua baris master yg mungkin dimaksud (utk disaring pemanggil, mis. dgn nama kecamatan)."""
        jenis, kn = pecah_jenis(kabupaten)
        kn = ALIAS_NAMA.get(kn, kn)
        daftar = self.per_prov.get((kunci_provinsi(provinsi), kn)) if provinsi else None
        daftar = daftar or self.nasional.get(kn) or []
        return [m for m in daftar if not jenis or m["jenis"] == jenis]

    def _cari(self, provinsi, jenis, kn):
        hasil = self._cari_kunci(provinsi, jenis, kn)
        # singkatan "Kep. X" -> master "KEPULAUAN X" (mis. "Kep. Talaud"), hanya bila belum ketemu
        if hasil is None and kn.startswith("KEP") and not kn.startswith("KEPULAUAN"):
            hasil = self._cari_kunci(provinsi, jenis, "KEPULAUAN" + kn[3:])
        return hasil

    def _cari_kunci(self, provinsi, jenis, kn):
        kn = ALIAS_NAMA.get(kn, kn)
        if not kn:
            return None
        if provinsi:
            hasil = self._pilih(self.per_prov.get((kunci_provinsi(provinsi), kn)), jenis)
            if hasil:
                return hasil
        kandidat = self.nasional.get(kn) or []
        # fallback nasional hanya bila tidak ambigu: saring jenis dulu (awalan "Kab."/"Kota"
        # membedakan mis. Kab. Banjar/Kalsel vs Kota Banjar/Jabar), lalu harus tunggal
        if jenis:
            kandidat = [m for m in kandidat if m["jenis"] == jenis]
            return kandidat[0] if len(kandidat) == 1 else None
        if len({m["kode_provinsi"] for m in kandidat}) == 1:
            return self._pilih(kandidat, None)
        return None
