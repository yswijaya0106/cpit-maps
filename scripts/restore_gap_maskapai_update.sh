#!/usr/bin/env bash
# Restore backups/gap_maskapai_update.dump -- BUKAN dump penuh, cuma
# maskapai_organisasi (full replace) + overlay peta "MASKAPAI" di
# map_layers/map_layer_meta (via 2 tabel sementara gap_map_layers_maskapai/
# gap_map_layer_meta_maskapai, dipindah ke tabel asli lalu di-drop -- pola
# sama dgn restore_gap_docs_new_update.sh, lihat komentar di sana).
#
# Prasyarat: database target SUDAH punya skema map_layers/map_layer_meta/
# maskapai_organisasi (dari deploy sebelumnya atau restore_staging_dump.sh).
#
# Usage:
#   scripts/restore_gap_maskapai_update.sh                                  # dump default di backups/
#   scripts/restore_gap_maskapai_update.sh --yes backups/gap_maskapai_update.dump

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
  DUMP_FILE="$REPO_ROOT/backups/gap_maskapai_update.dump"
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

echo "=== Restore parsial: maskapai_organisasi + overlay MASKAPAI ==="
echo "  Dump   : $DUMP_FILE ($(du -h "$DUMP_FILE" | cut -f1))"
echo "  Target : $PG_USER@$PG_HOST:$PG_PORT/$PG_DB"
echo

if [ "$SKIP_CONFIRM" -ne 1 ]; then
  read -r -p "Lanjutkan? maskapai_organisasi ditimpa penuh, layer peta MASKAPAI ditimpa (provinsi lain TIDAK disentuh). [y/N] " confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Dibatalkan."
    exit 0
  fi
fi

echo "[1/2] pg_restore..."
pg_restore -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" \
  --clean --if-exists --no-owner --no-privileges -v "$DUMP_FILE"

echo
echo "[2/2] Pindahkan overlay MASKAPAI ke map_layers/map_layer_meta, drop tabel sementara..."
psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
DELETE FROM public.map_layers WHERE provinsi = 'MASKAPAI';
DELETE FROM public.map_layer_meta WHERE provinsi = 'MASKAPAI';
INSERT INTO public.map_layers (provinsi, kabupaten, layer, attrs, geom)
  SELECT provinsi, kabupaten, layer, attrs, geom FROM public.gap_map_layers_maskapai;
INSERT INTO public.map_layer_meta (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp, imported_at)
  SELECT provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp, imported_at
  FROM public.gap_map_layer_meta_maskapai;
DROP TABLE public.gap_map_layers_maskapai;
DROP TABLE public.gap_map_layer_meta_maskapai;
COMMIT;
SQL

echo
echo "Verifikasi cepat..."
psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -c "
  SELECT 'maskapai_organisasi' AS tabel, count(*) FROM maskapai_organisasi
  UNION ALL SELECT 'map_layers (MASKAPAI)', count(*) FROM map_layers WHERE provinsi = 'MASKAPAI';
"

echo "Selesai. Restart proses app.py di server ini supaya cache in-process (_map_layer_geojson_cache dkk) tidak menyajikan data lama."
