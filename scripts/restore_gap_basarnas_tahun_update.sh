#!/usr/bin/env bash
# Restore backups/gap_basarnas_tahun_update.dump -- refresh PENUH tabel
# basarnas_analisis_kantor (skema berubah: kolom tahun_data baru + PK
# id BIGSERIAL menggantikan "no", lihat schema_basarnas_analisis_kantor.sql
# dan build_basarnas_analisis_kantor.py -- 132 -> 367 baris, 1 baris
# gabungan + 5 baris per tahun 2021-2025 per Kantor SAR). Tabel ini
# sepenuhnya dimiliki script itu (tidak ada tabel map_layers yang perlu
# di-merge di sini, beda dari restore_gap_*_update.sh lain) -- jadi cukup
# pg_restore --clean --if-exists langsung, tanpa langkah tabel sementara.
#
# Usage:
#   scripts/restore_gap_basarnas_tahun_update.sh                                  # dump default di backups/
#   scripts/restore_gap_basarnas_tahun_update.sh --yes backups/gap_basarnas_tahun_update.dump

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
  DUMP_FILE="$REPO_ROOT/backups/gap_basarnas_tahun_update.dump"
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

echo "=== Restore penuh: basarnas_analisis_kantor (skema baru + filter tahun) ==="
echo "  Dump   : $DUMP_FILE ($(du -h "$DUMP_FILE" | cut -f1))"
echo "  Target : $PG_USER@$PG_HOST:$PG_PORT/$PG_DB"
echo

if [ "$SKIP_CONFIRM" -ne 1 ]; then
  read -r -p "Lanjutkan? basarnas_analisis_kantor ditimpa penuh (tabel lain TIDAK disentuh). [y/N] " confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Dibatalkan."
    exit 0
  fi
fi

echo "[1/1] pg_restore..."
pg_restore -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" \
  --clean --if-exists --no-owner --no-privileges -v "$DUMP_FILE"

echo
echo "Verifikasi cepat..."
psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -c "
  SELECT tahun_data, count(*) FROM basarnas_analisis_kantor GROUP BY 1 ORDER BY 1 NULLS FIRST;
"

echo "Selesai. Restart proses app.py di server ini supaya cache in-process tidak menyajikan data lama."
