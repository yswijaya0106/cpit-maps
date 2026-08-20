-- Survei mandiri kapasitas layanan PSC 119 (Public Safety Center --
-- layanan gawat darurat kesehatan) per kab/kota, 2025-2026
-- (docs/New/8. KESELAMATAN/Data layanan PSC 119 2025 survey.xlsx).
--
-- **REDAKSI PRIVASI WAJIB**: sumber mentahnya memuat data pribadi
-- (nama penanggung jawab, nomor WhatsApp pribadi penanggung jawab &
-- tim teknis) -- kolom-kolom itu SENGAJA TIDAK ADA di skema ini sama
-- sekali (bukan cuma di-null-kan di importer, tapi memang tidak
-- dideklarasikan sebagai kolom), lihat scripts/import_psc119_layanan.py.
-- Yang disimpan cuma data institusi (nama PSC, lokasi, nomor lokal/
-- email RESMI kantor) dan data substantif survei (kapasitas, jumlah
-- kasus per kategori, waktu respon, kendala, kebutuhan anggaran).
--
-- Data ini SELF-REPORTED (survei mandiri via Google Form, bukan data
-- resmi terverifikasi) -- tampilkan dengan disclaimer itu di UI mana
-- pun dipakai. Non-spasial (tanpa koordinat). TIDAK terkait
-- usulan_inpres/IJD. Lihat docs/kajian_data_baru_docs_new.md §9.4.

CREATE TABLE IF NOT EXISTS psc119_layanan (
  id                              BIGSERIAL PRIMARY KEY,
  waktu_submit                    TIMESTAMP,
  nama_psc                        TEXT,
  provinsi                        TEXT,
  kabupaten_kota                  TEXT,
  lokasi_psc                      TEXT,
  nomor_lokal_psc                 TEXT,   -- nomor kantor/ekstensi, BUKAN kontak pribadi
  email_resmi_psc                 TEXT,   -- email resmi institusi, BUKAN email pribadi
  status_operasional_2026         TEXT,
  status_psc                      TEXT,   -- UPT | UPTD
  jumlah_operator_call_center     INTEGER,
  jumlah_personel_lapangan        INTEGER,
  jumlah_ambulans_aktif           INTEGER,
  kesediaan_gps_tracking          TEXT,
  sudah_siap_psc                  TEXT,
  integrasi_rumah_sakit           TEXT,
  kasus_ibu_ditangani             INTEGER,
  rujukan_ibu_hamil_risti         INTEGER,
  kematian_ibu_dalam_perjalanan   INTEGER,
  kasus_bayi_ditangani            INTEGER,
  rujukan_nicu_picu               INTEGER,
  kematian_bayi_dalam_perjalanan  INTEGER,
  kasus_anak_ditangani            INTEGER,
  kematian_anak_pra_rs            INTEGER,
  kasus_kecelakaan_ditangani      INTEGER,
  kasus_luka_berat                INTEGER,
  kasus_luka_ringan               INTEGER,
  meninggal_kecelakaan_perjalanan INTEGER,
  kasus_jantung_ditangani         INTEGER,
  meninggal_jantung_perjalanan    INTEGER,
  kasus_stroke_ditangani          INTEGER,
  meninggal_stroke_perjalanan     INTEGER,
  rata_rata_waktu_respon          TEXT,
  kendala_tantangan               TEXT,
  estimasi_anggaran_pertahun      BIGINT,
  imported_at                     TIMESTAMPTZ NOT NULL DEFAULT now()
);
