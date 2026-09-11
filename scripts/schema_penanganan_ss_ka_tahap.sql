-- Rencana penanganan SS (perlintasan Sebidang) KA bertahap
-- (docs/New/11092026/.../[rencum asli] PENANGANAN SS KA PERTAHAP.xlsx),
-- 3 sheet Tahap I/II/III (39+42+55 = 136 lokasi) digabung + kolom tahap.
-- Pelengkap jpl_prioritas_djka (schema_jpl_prioritas_djka.sql) -- yang itu
-- daftar prioritas keselamatan tanpa rencana penanganan, ini rencana
-- penanganan (flyover/underpass/frontage) dengan kelayakan ekonomi
-- (EIRR/BCR/NPV) dan rangking. TIDAK di-join otomatis ke keduanya
-- (notasi JPL antar sumber tidak konsisten formatnya -- kadang "JPL 227",
-- kadang cuma angka mentah "23" -- lihat docs/kajian_data_baru_11092026.md
-- §3, belum diverifikasi cukup presisi utk join otomatis).
--
-- Juga TIDAK di-join ke layer titik map_layers "PERLINTASAN SEBIDANG KA"
-- (scripts/import_railway_crossing_tahap_to_postgis.py) meski jumlah baris
-- per tahap sama persis (39/42/55 vs 39/42/29+26) -- kesamaan jumlah bukan
-- jaminan kecocokan urutan/baris, tetap 2 sumber independen.
--
-- Kolom finansial (Prakiraan Biaya Konstruksi/Lahan) dalam Rupiah, NPV
-- dalam satuan yang sama dgn sumber (kemungkinan juta Rupiah, belum
-- dikonfirmasi -- disimpan apa adanya).
--
-- Diisi scripts/import_penanganan_ss_ka_tahap.py. TIDAK terkait
-- usulan_inpres/IJD.

CREATE TABLE IF NOT EXISTS penanganan_ss_ka_tahap (
  id                              BIGSERIAL PRIMARY KEY,
  tahap                           TEXT NOT NULL,   -- 'I' | 'II' | 'III'
  no                              INTEGER,
  notasi_ss_konsultan             TEXT,
  nomor_notasi                    INTEGER,
  notasi_ss_kepmen367             TEXT,
  notasi_jpl                      TEXT,            -- format tidak konsisten antar tahap, lihat catatan di atas
  nama_ruas                       TEXT,
  nomor_ruas                      TEXT,
  indikasi_panjang_penanganan_m   NUMERIC(10, 2),
  lokasi_jpl                      TEXT,
  indikasi_kebutuhan_frontage     TEXT,
  prakiraan_biaya_konstruksi      NUMERIC(18, 2),
  kebutuhan_lahan_m2              NUMERIC(12, 2),
  prakiraan_biaya_lahan           NUMERIC(18, 2),
  ketersediaan_desain             TEXT,            -- Ya | Tidak | Sebagian
  nilai                           NUMERIC(10, 2),
  total_nilai                     NUMERIC(10, 2),
  rangking                        INTEGER,
  eirr                            NUMERIC(10, 6),
  bcr                             NUMERIC(10, 6),
  npv                             NUMERIC(18, 4),
  imported_at                     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_penanganan_ss_ka_tahap_tahap ON penanganan_ss_ka_tahap (tahap);
CREATE INDEX IF NOT EXISTS idx_penanganan_ss_ka_tahap_rangking ON penanganan_ss_ka_tahap (rangking);
