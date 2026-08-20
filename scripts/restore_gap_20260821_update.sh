#!/usr/bin/env bash
# Restore backups/gap_20260821_full.dump -- dump gabungan sekali-jalan (21
# Aug 2026) utk semua tabel/layer yang masih tertinggal di staging saat itu:
# pelabuhan_daerah, basarnas_puslat_fasilitas, ka_perkotaan_layanan,
# bandara_kemenhub (+_rute/_terdekat/_fasilitas), bps_data_bandara (kolom
# cross-ref bandara_kemenhub_id/match_skor), plus overlay peta ANGKUTAN
# PERINTIS + BANDARA KEMENHUB di map_layers/map_layer_meta (lewat 2 tabel
# sementara gap_map_layers_20260821/gap_map_layer_meta_20260821, dipindah
# ke tabel asli lalu di-drop -- pola sama dgn restore_gap_docs_new_update.sh/
# restore_gap_maskapai_update.sh, lihat komentar di situ).
#
# Prasyarat: database target SUDAH punya skema map_layers/map_layer_meta.
#
# Usage:
#   scripts/restore_gap_20260821_update.sh                                 # dump default di backups/
#   scripts/restore_gap_20260821_update.sh --yes backups/gap_20260821_full.dump

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
  DUMP_FILE="$REPO_ROOT/backups/gap_20260821_full.dump"
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

echo "=== Restore parsial (21 Aug 2026 catch-up): pelabuhan_daerah, basarnas_puslat_fasilitas, ==="
echo "    ka_perkotaan_layanan, bandara_kemenhub(+_rute/_terdekat/_fasilitas), bps_data_bandara,"
echo "    overlay ANGKUTAN PERINTIS + BANDARA KEMENHUB"
echo "  Dump   : $DUMP_FILE ($(du -h "$DUMP_FILE" | cut -f1))"
echo "  Target : $PG_USER@$PG_HOST:$PG_PORT/$PG_DB"
echo

if [ "$SKIP_CONFIRM" -ne 1 ]; then
  read -r -p "Lanjutkan? Tabel di atas ditimpa penuh, layer peta ANGKUTAN PERINTIS/BANDARA KEMENHUB ditimpa (provinsi lain TIDAK disentuh). [y/N] " confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Dibatalkan."
    exit 0
  fi
fi

echo "[1/2] pg_restore..."
pg_restore -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" \
  --clean --if-exists --no-owner --no-privileges -v "$DUMP_FILE"

echo
echo "[2/2] Pindahkan overlay ANGKUTAN PERINTIS + BANDARA KEMENHUB ke map_layers/map_layer_meta, drop tabel sementara..."
psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
DELETE FROM public.map_layers WHERE provinsi IN ('ANGKUTAN PERINTIS', 'BANDARA KEMENHUB');
DELETE FROM public.map_layer_meta WHERE provinsi IN ('ANGKUTAN PERINTIS', 'BANDARA KEMENHUB');
INSERT INTO public.map_layers (provinsi, kabupaten, layer, attrs, geom)
  SELECT provinsi, kabupaten, layer, attrs, geom FROM public.gap_map_layers_20260821;
INSERT INTO public.map_layer_meta (provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp, imported_at)
  SELECT provinsi, kabupaten, layer, label, feature_count, size_mb, source_shp, imported_at
  FROM public.gap_map_layer_meta_20260821;
DROP TABLE public.gap_map_layers_20260821;
DROP TABLE public.gap_map_layer_meta_20260821;
COMMIT;
SQL

echo
echo "Verifikasi cepat..."
psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -c "
  SELECT 'pelabuhan_daerah' AS tabel, count(*) FROM pelabuhan_daerah
  UNION ALL SELECT 'basarnas_puslat_fasilitas', count(*) FROM basarnas_puslat_fasilitas
  UNION ALL SELECT 'ka_perkotaan_layanan', count(*) FROM ka_perkotaan_layanan
  UNION ALL SELECT 'bandara_kemenhub', count(*) FROM bandara_kemenhub
  UNION ALL SELECT 'bandara_kemenhub_rute', count(*) FROM bandara_kemenhub_rute
  UNION ALL SELECT 'bandara_kemenhub_terdekat', count(*) FROM bandara_kemenhub_terdekat
  UNION ALL SELECT 'bandara_kemenhub_fasilitas', count(*) FROM bandara_kemenhub_fasilitas
  UNION ALL SELECT 'bps_data_bandara', count(*) FROM bps_data_bandara
  UNION ALL SELECT 'map_layers (ANGKUTAN PERINTIS)', count(*) FROM map_layers WHERE provinsi = 'ANGKUTAN PERINTIS'
  UNION ALL SELECT 'map_layers (BANDARA KEMENHUB)', count(*) FROM map_layers WHERE provinsi = 'BANDARA KEMENHUB';
"

echo "Selesai. Restart proses app.py di server ini supaya cache in-process (_map_layer_geojson_cache dkk) tidak menyajikan data lama."
