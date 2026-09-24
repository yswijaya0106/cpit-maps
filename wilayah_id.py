"""Referensi wilayah berbasis ID (kode BPS) -- provinsi/kabupaten/kecamatan.

Sumber tunggal: tabel penduduk_kecamatan (master BPS nasional, 2025: 38 provinsi,
514 kab/kota, 7.288 kecamatan; kode konsisten -- satu kode, satu nama).

  ref_wilayah                  tabel referensi (grain kecamatan) berisi ketiga ID
  ref_wilayah_kabupaten (view) distinct kabupaten/kota + provinsi
  ref_wilayah_provinsi  (view) distinct provinsi

Fungsi di sini dipakai scripts/build_ref_wilayah.py, scripts/import_usulan_inpres.py
(upsert_xlsx), dan scripts/import_usulan_riwayat.py. Semua fungsi menerima kursor
psycopg (tuple/dict row factory sama-sama aman: hanya execute, tanpa fetch bergantung tipe).
Perilaku skor IJD TIDAK diubah oleh modul ini -- lihat
docs/kajian_validasi_id_wilayah.md untuk rencana peralihan scorer ke kolom kode.
"""

DDL_REF = """
CREATE TABLE IF NOT EXISTS ref_wilayah (
    kode_kecamatan       INTEGER PRIMARY KEY,
    kode_kabupaten       INTEGER  NOT NULL,
    kode_provinsi        SMALLINT NOT NULL,
    nama_provinsi        TEXT,
    nama_kabupaten_kota  TEXT,
    jenis_kabupaten      TEXT CHECK (jenis_kabupaten IN ('KABUPATEN', 'KOTA')),
    nama_kecamatan       TEXT,
    tahun_sumber         SMALLINT,
    sumber               TEXT DEFAULT 'penduduk_kecamatan',
    diperbarui_at        TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ref_wilayah_kab ON ref_wilayah (kode_kabupaten);
CREATE INDEX IF NOT EXISTS idx_ref_wilayah_prov ON ref_wilayah (kode_provinsi);
CREATE OR REPLACE VIEW ref_wilayah_kabupaten AS
    SELECT DISTINCT kode_kabupaten, kode_provinsi, nama_provinsi, nama_kabupaten_kota, jenis_kabupaten
    FROM ref_wilayah;
CREATE OR REPLACE VIEW ref_wilayah_provinsi AS
    SELECT DISTINCT kode_provinsi, nama_provinsi FROM ref_wilayah;
"""

# kode kab/kota BPS: dua digit terakhir 71-79 = KOTA, selain itu KABUPATEN
SQL_ISI_REF = """
TRUNCATE ref_wilayah;
INSERT INTO ref_wilayah (kode_kecamatan, kode_kabupaten, kode_provinsi, nama_provinsi, nama_kabupaten_kota,
                         jenis_kabupaten, nama_kecamatan, tahun_sumber)
SELECT kode_kecamatan, kode_kabupaten, kode_provinsi, provinsi, kabupaten_kota,
       CASE WHEN kode_kabupaten % 100 >= 71 THEN 'KOTA' ELSE 'KABUPATEN' END,
       kecamatan, tahun
FROM penduduk_kecamatan;
"""


def build_ref_wilayah(cur):
    """(Re)bangun ref_wilayah dari penduduk_kecamatan -- idempotent (TRUNCATE + INSERT)."""
    cur.execute(DDL_REF)
    cur.execute(SQL_ISI_REF)
    cur.execute("SELECT COUNT(*) AS n FROM ref_wilayah")
    row = cur.fetchone()
    return row["n"] if isinstance(row, dict) else row[0]


# kunci nama tanpa spasi/tanda baca ("GUNUNG KIDUL" == "GUNUNGKIDUL")
_KEY = "regexp_replace(upper({col}), '[^A-Z]', '', 'g')"


def _k(col):
    return _KEY.format(col=col)


def isi_kode_usulan(cur):
    """usulan_inpres.kode_provinsi/kode_kabupaten dari wilayah_mapping (pasangan nama SITIA
    persis -- jalur yang SAMA dgn yang dipakai scorer IJD lewat kab_by_wilayah, jadi nilainya
    identik dengan kode_kab yang dipakai skor sekarang). Return jumlah baris yang berubah."""
    cur.execute("ALTER TABLE usulan_inpres ADD COLUMN IF NOT EXISTS kode_provinsi SMALLINT")
    cur.execute("ALTER TABLE usulan_inpres ADD COLUMN IF NOT EXISTS kode_kabupaten INTEGER")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_usulan_inpres_kode_kab ON usulan_inpres (kode_kabupaten)")
    cur.execute("""
        UPDATE usulan_inpres u SET kode_provinsi = w.kode_provinsi, kode_kabupaten = w.kode_kabupaten
        FROM wilayah_mapping w
        WHERE w.provinsi_sitia = u.provinsi AND w.kabupaten_kota_sitia = u.kabupaten_kota
          AND (u.kode_kabupaten IS DISTINCT FROM w.kode_kabupaten OR u.kode_provinsi IS DISTINCT FROM w.kode_provinsi)""")
    return cur.rowcount


# nama SITIA lama -> nama kabupaten sekarang (kunci tanpa spasi, format JENIS+NAMA seperti di ref_wilayah).
# Hanya kasus yang terbukti ada di riwayat 2023-2024; tambah baris di sini bila validator menemukan sisa baru.
ALIAS_KAB_RIWAYAT = {
    "KABUPATENTOBASAMOSIR": "KABUPATENTOBA",
    "KABUPATENDAYAI": "KABUPATENDEIYAI",
    "KABUPATENMAHAKAMHULU": "KABUPATENMAHAKAMULU",
    "KABUPATENSIAUTAGULANDANGBIARO": "KABUPATENKEPULAUANSIAUTAGULANDANGBIARO",
}

# kunci JENIS+NAMA di ref_wilayah, mis. "KOTAPALEMBANG" / "KABUPATENSORONG"
_REF_KEY = "regexp_replace(upper(jenis_kabupaten || nama_kabupaten_kota), '[^A-Z]', '', 'g')"


def isi_kode_riwayat(cur):
    """usulan_inpres_riwayat.kode_provinsi/kode_kabupaten. Nama SITIA 2023-2024 tidak persis sama
    dgn 2026 (spasi, provinsi lama sebelum pemekaran, nama kabupaten berubah, kota yang tidak
    ada usulannya di 2026 sehingga tak masuk wilayah_mapping), jadi bertahap:
      1. pasangan (provinsi, kabupaten) persis -- wilayah_mapping
      2. pasangan tanpa spasi/tanda baca
      3. kabupaten saja (tanpa spasi) bila NAMA ITU UNIK di wilayah_mapping (mengatasi provinsi lama)
      4. JENIS+NAMA terhadap ref_wilayah (butuh build_ref_wilayah dulu) -- termasuk kab/kota di luar mapping
      5. alias nama lama -> ref_wilayah
    Baris yang sudah terisi tidak ditimpa; kode provinsi selalu kode provinsi SEKARANG (pasca
    pemekaran), bukan nama provinsi di file lama. Return dict jumlah terisi per tahap."""
    cur.execute("ALTER TABLE usulan_inpres_riwayat ADD COLUMN IF NOT EXISTS kode_provinsi SMALLINT")
    cur.execute("ALTER TABLE usulan_inpres_riwayat ADD COLUMN IF NOT EXISTS kode_kabupaten INTEGER")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_usulan_riwayat_kode_kab ON usulan_inpres_riwayat (kode_kabupaten)")
    hasil = {}
    cur.execute("""
        UPDATE usulan_inpres_riwayat r SET kode_provinsi = w.kode_provinsi, kode_kabupaten = w.kode_kabupaten
        FROM wilayah_mapping w
        WHERE r.kode_kabupaten IS NULL AND upper(w.provinsi_sitia) = upper(r.provinsi)
          AND upper(w.kabupaten_kota_sitia) = upper(r.kabupaten_kota)""")
    hasil["persis"] = cur.rowcount
    cur.execute(f"""
        UPDATE usulan_inpres_riwayat r SET kode_provinsi = w.kode_provinsi, kode_kabupaten = w.kode_kabupaten
        FROM wilayah_mapping w
        WHERE r.kode_kabupaten IS NULL AND {_k('w.provinsi_sitia')} = {_k('r.provinsi')}
          AND {_k('w.kabupaten_kota_sitia')} = {_k('r.kabupaten_kota')}""")
    hasil["tanpa_spasi"] = cur.rowcount
    cur.execute(f"""
        WITH unik AS (
            SELECT {_k('kabupaten_kota_sitia')} AS kunci, MIN(kode_provinsi) AS kode_provinsi,
                   MIN(kode_kabupaten) AS kode_kabupaten
            FROM wilayah_mapping GROUP BY 1 HAVING COUNT(*) = 1)
        UPDATE usulan_inpres_riwayat r SET kode_provinsi = u.kode_provinsi, kode_kabupaten = u.kode_kabupaten
        FROM unik u WHERE r.kode_kabupaten IS NULL AND u.kunci = {_k('r.kabupaten_kota')}""")
    hasil["nama_unik"] = cur.rowcount
    cur.execute(f"""
        WITH ref AS (
            SELECT {_REF_KEY} AS kunci, MIN(kode_provinsi) AS kode_provinsi, MIN(kode_kabupaten) AS kode_kabupaten
            FROM ref_wilayah_kabupaten GROUP BY 1 HAVING COUNT(*) = 1)
        UPDATE usulan_inpres_riwayat r SET kode_provinsi = ref.kode_provinsi, kode_kabupaten = ref.kode_kabupaten
        FROM ref WHERE r.kode_kabupaten IS NULL AND ref.kunci = {_k('r.kabupaten_kota')}""")
    hasil["ref_jenis_nama"] = cur.rowcount
    n_alias = 0
    for lama, baru in ALIAS_KAB_RIWAYAT.items():
        cur.execute(f"""
            WITH ref AS (
                SELECT MIN(kode_provinsi) AS kode_provinsi, MIN(kode_kabupaten) AS kode_kabupaten
                FROM ref_wilayah_kabupaten WHERE {_REF_KEY} = %s HAVING COUNT(*) = 1)
            UPDATE usulan_inpres_riwayat r SET kode_provinsi = ref.kode_provinsi, kode_kabupaten = ref.kode_kabupaten
            FROM ref WHERE r.kode_kabupaten IS NULL AND {_k('r.kabupaten_kota')} = %s""", (baru, lama))
        n_alias += cur.rowcount
    hasil["alias"] = n_alias
    return hasil
