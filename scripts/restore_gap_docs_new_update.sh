#!/usr/bin/env bash
# Restore backups/gap_docs_new_update.dump -- BUKAN dump penuh database, cuma
# tabel-tabel yang diimpor dari gap docs/New/ sesi ini: pelabuhan_daerah,
# basarnas_puslat_fasilitas (tabel baru, di-restore langsung dgn nama aslinya),
# dan overlay peta "ANGKUTAN PERINTIS" (map_layers/map_layer_meta) yang
# di-restore ke 2 tabel sementara (gap_map_layers_angkutan_perintis/
# gap_map_layer_meta_angkutan_perintis, krn pg_dump tidak bisa filter baris
# saat --table=map_layers -- lihat komentar di scripts/import_angkutan_perintis_geometri.py),
# lalu dipindahkan ke map_layers/map_layer_meta yang sebenarnya (scoped
# DELETE+INSERT, TIDAK menyentuh baris provinsi lain) dan tabel sementaranya
# di-drop.
#
# Prasyarat: database target SUDAH punya seluruh skema aplikasi (map_layers/
# map_layer_meta dkk) -- script ini menambah data, bukan setup awal database
# kosong (pakai scripts/restore_staging_dump.sh + dump penuh utk itu).
#
# Usage (dari root repo):
#   scripts/restore_gap_docs_new_update.sh                                      # dump default di backups/
#   scripts/restore_gap_docs_new_update.sh backups/gap_docs_new_update.dump
#   scripts/restore_gap_docs_new_update.sh --yes backups/gap_docs_new_update.dump

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
  DUMP_FILE="$REPO_ROOT/backups/gap_docs_new_update.dump"
fi
if [ ! -f "$DUMP_FILE" ]; then
  echo "GAGAL: file dump tidak ditemukan: $DUMP_FILE" >&2
  exit 1
fi

# Env var yang SUDAH di-set oleh caller (shell staging, atau override manual)
# harus menang atas .env -- simpan dulu sebelum di-source, krn source .env
# TIMPA TANPA SYARAT variabel shell yang ada (bukan cuma isi yang kosong).
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
export PGPASSWORD="${PG_PASS:-}"

echo "=== Restore parsial (gap docs/New/): pelabuhan_daerah, basarnas_puslat_fasilitas, overlay ANGKUTAN PERINTIS ==="
echo "  Dump   : $DUMP_FILE ($(du -h "$DUMP_FILE" | cut -f1))"
echo "  Target : $PG_USER@$PG_HOST:$PG_PORT/$PG_DB"
echo

if [ "$SKIP_CONFIRM" -ne 1 ]; then
  read -r -p "Lanjutkan? pelabuhan_daerah/basarnas_puslat_fasilitas ditimpa penuh, layer peta ANGKUTAN PERINTIS ditimpa (baris provinsi lain TIDAK disentuh). [y/N] " confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Dibatalkan."
    exit 0
  fi
fi

echo "[1/2] pg_restore (pelabuhan_daerah, basarnas_puslat_fasilitas, 2 tabel sementara gap_*)..."
pg_restore -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" \
  --clean --if-exists --no-owner --no-privileges -v "$DUMP_FILE"

echo
echo "[2/2] Pindahkan overlay ANGKUTAN PERINTIS ke map_layers/map_layer_meta, drop tabel sementara..."
psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
DELETE FROM public.map_layers WHERE provinsi = 'ANGKUTAN PERINTIS';
DELETE FROM public.map_layer_meta WHERE provinsi = 'ANGKUTAN PERINTIS';
INSERT INTO public.map_layers (provinsi, kabupaten, layer, attrs, geom)
  SELECT provinsi, kabupaten, layer, attrs, geom FROM public.gap_map_layers_angkutan_perintis;
INSERT INTO public.map_layer_meta (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp, imported_at)
  SELECT provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp, imported_at
  FROM public.gap_map_layer_meta_angkutan_perintis;
DROP TABLE public.gap_map_layers_angkutan_perintis;
DROP TABLE public.gap_map_layer_meta_angkutan_perintis;
COMMIT;
SQL

echo
echo "Verifikasi cepat..."
psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -c "
  SELECT 'pelabuhan_daerah' AS tabel, count(*) FROM pelabuhan_daerah
  UNION ALL SELECT 'basarnas_puslat_fasilitas', count(*) FROM basarnas_puslat_fasilitas
  UNION ALL SELECT 'map_layers (ANGKUTAN PERINTIS)', count(*) FROM map_layers WHERE provinsi = 'ANGKUTAN PERINTIS'
  UNION ALL SELECT 'map_layer_meta (ANGKUTAN PERINTIS)', count(*) FROM map_layer_meta WHERE provinsi = 'ANGKUTAN PERINTIS';
"

echo "Selesai. Restart proses app.py di server ini supaya cache in-process (_map_layer_geojson_cache dkk) tidak menyajikan data lama."
