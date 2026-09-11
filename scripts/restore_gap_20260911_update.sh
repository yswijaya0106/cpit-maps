#!/usr/bin/env bash
# Restore backups/gap_20260911_update.dump -- 3 tabel baru sepenuhnya
# (basarnas_analisis_kantor, jpl_prioritas_djka, penanganan_ss_ka_tahap,
# lihat docs/kajian_data_baru_11092026.md §3 + skema baru "Analisis
# Basarnas per Kantor/Pos SAR") plus overlay peta baru di map_layers/
# map_layer_meta (lewat 2 tabel sementara gap_map_layers_20260911/
# gap_map_layer_meta_20260911, dipindah ke tabel asli lalu di-drop -- pola
# sama dgn restore_gap_20260821_update.sh, lihat komentar di sana):
#   - JALAN DARURAT (bucket baru, 42 fitur)
#   - PERLINTASAN SEBIDANG KA (bucket baru, 136 fitur)
#   - RTRW (bucket baru, kabupaten="Kalimantan Barat", 2 layer/640 fitur)
#   - BANDARA KEMENHUB / layer "Rute Penerbangan (Kemenhub)" -- provinsi
#     bucket INI SENDIRI SUDAH ADA di staging (layer titik "Bandara
#     Kemenhub" dari gap_20260821_full.dump), makanya DELETE di bawah
#     discope per (provinsi, layer), BUKAN blanket "DELETE ... WHERE
#     provinsi = 'BANDARA KEMENHUB'" spt pola provinsi-tunggal di script
#     restore_gap_* sebelumnya -- itu akan ikut menghapus layer titik lama.
#
# Prasyarat: database target SUDAH punya skema map_layers/map_layer_meta
# (dari deploy sebelumnya atau restore_staging_dump.sh).
#
# Usage:
#   scripts/restore_gap_20260911_update.sh                                  # dump default di backups/
#   scripts/restore_gap_20260911_update.sh --yes backups/gap_20260911_update.dump

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKIP_CONFIRM=0
DUMP_FILE=""

for arg in "$@"; do
  case "$arg" in
    --yes|-y) SKIP_CONFIRM=1 ;;
    *) DUMP_FILE="$arg" ;;
  esac
done

if [ -z "$DUMP_FILE" ]; then
  DUMP_FILE="$REPO_ROOT/backups/gap_20260911_update.dump"
fi
if [ ! -f "$DUMP_FILE" ]; then
  echo "GAGAL: file dump tidak ditemukan: $DUMP_FILE" >&2
  exit 1
fi

_PRESET_PG_HOST="${PG_HOST-}"
_PRESET_PG_PORT="${PG_PORT-}"
_PRESET_PG_USER="${PG_USER-}"
_PRESET_PG_DB="${PG_DB-}"
_PRESET_PG_PASS="${PG_PASS-}"

if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$REPO_ROOT/.env"
  set +a
fi

PG_HOST="${_PRESET_PG_HOST:-${PG_HOST:-127.0.0.1}}"
PG_PORT="${_PRESET_PG_PORT:-${PG_PORT:-5432}}"
PG_USER="${_PRESET_PG_USER:-${PG_USER:-postgres}}"
PG_DB="${_PRESET_PG_DB:-${PG_DB:-route_gis}}"
PG_PASS="${_PRESET_PG_PASS:-${PG_PASS:-}}"
export PGPASSWORD="$PG_PASS"

echo "=== Restore parsial (11 Sep 2026): basarnas_analisis_kantor, jpl_prioritas_djka, ==="
echo "    penanganan_ss_ka_tahap, overlay JALAN DARURAT + PERLINTASAN SEBIDANG KA + RTRW"
echo "    + layer 'Rute Penerbangan (Kemenhub)' (tambahan di provinsi BANDARA KEMENHUB)"
echo "  Dump   : $DUMP_FILE ($(du -h "$DUMP_FILE" | cut -f1))"
echo "  Target : $PG_USER@$PG_HOST:$PG_PORT/$PG_DB"
echo

if [ "$SKIP_CONFIRM" -ne 1 ]; then
  read -r -p "Lanjutkan? 3 tabel di atas ditimpa penuh, layer JALAN DARURAT/PERLINTASAN SEBIDANG KA/RTRW/'Rute Penerbangan (Kemenhub)' ditimpa (layer BANDARA KEMENHUB lain & provinsi lain TIDAK disentuh). [y/N] " confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Dibatalkan."
    exit 0
  fi
fi

echo "[1/2] pg_restore..."
pg_restore -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" \
  --clean --if-exists --no-owner --no-privileges -v "$DUMP_FILE"

echo
echo "[2/2] Pindahkan overlay baru ke map_layers/map_layer_meta, drop tabel sementara..."
psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
DELETE FROM public.map_layers
  WHERE provinsi IN ('JALAN DARURAT', 'PERLINTASAN SEBIDANG KA', 'RTRW')
     OR (provinsi = 'BANDARA KEMENHUB' AND layer = 'Rute Penerbangan (Kemenhub)');
DELETE FROM public.map_layer_meta
  WHERE provinsi IN ('JALAN DARURAT', 'PERLINTASAN SEBIDANG KA', 'RTRW')
     OR (provinsi = 'BANDARA KEMENHUB' AND layer = 'Rute Penerbangan (Kemenhub)');
INSERT INTO public.map_layers (provinsi, kabupaten, layer, attrs, geom)
  SELECT provinsi, kabupaten, layer, attrs, geom FROM public.gap_map_layers_20260911;
INSERT INTO public.map_layer_meta (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp, imported_at)
  SELECT provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp, imported_at
  FROM public.gap_map_layer_meta_20260911;
DROP TABLE public.gap_map_layers_20260911;
DROP TABLE public.gap_map_layer_meta_20260911;
COMMIT;
SQL

echo
echo "Verifikasi cepat..."
psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -c "
  SELECT 'basarnas_analisis_kantor' AS tabel, count(*) FROM basarnas_analisis_kantor
  UNION ALL SELECT 'jpl_prioritas_djka', count(*) FROM jpl_prioritas_djka
  UNION ALL SELECT 'penanganan_ss_ka_tahap', count(*) FROM penanganan_ss_ka_tahap
  UNION ALL SELECT 'map_layers (JALAN DARURAT)', count(*) FROM map_layers WHERE provinsi = 'JALAN DARURAT'
  UNION ALL SELECT 'map_layers (PERLINTASAN SEBIDANG KA)', count(*) FROM map_layers WHERE provinsi = 'PERLINTASAN SEBIDANG KA'
  UNION ALL SELECT 'map_layers (RTRW)', count(*) FROM map_layers WHERE provinsi = 'RTRW'
  UNION ALL SELECT 'map_layers (BANDARA KEMENHUB, Rute Penerbangan)', count(*) FROM map_layers WHERE provinsi = 'BANDARA KEMENHUB' AND layer = 'Rute Penerbangan (Kemenhub)';
"

echo "Selesai. Restart proses app.py di server ini supaya cache in-process (_map_layer_geojson_cache dkk) tidak menyajikan data lama."
