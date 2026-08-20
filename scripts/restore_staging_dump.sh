#!/usr/bin/env bash
# Restore dump pg_dump custom-format (-Fc) hasil scripts/ (lihat backups/README.md)
# ke database PostgreSQL/PostGIS staging. Baca kredensial PG_* dari .env di root
# repo (format sama dgn yang dipakai db.py/app.py) -- override lewat env var kalau
# staging pakai .env yang beda lokasinya.
#
# Usage (dari root repo, venv tidak perlu aktif -- ini bash, bukan Python):
#   scripts/restore_staging_dump.sh                              # dump terbaru di backups/
#   scripts/restore_staging_dump.sh backups/route_gis_20260820.dump
#   scripts/restore_staging_dump.sh --yes backups/route_gis_20260820.dump   # skip konfirmasi
#   PG_HOST=staging.example.com PG_USER=app scripts/restore_staging_dump.sh dump.dump
#
# --clean --if-exists dipakai supaya aman dijalankan berulang (drop objek yang
# ada sebelum recreate) -- tidak perlu drop database manual dulu tiap refresh
# staging dari dump baru. -j 4 restore paralel (map_layers ~1.5GB, tabel
# terbesar, jauh lebih cepat paralel drpd satu thread).

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
  DUMP_FILE=$(ls -t "$REPO_ROOT"/backups/*.dump 2>/dev/null | head -1 || true)
  if [ -z "$DUMP_FILE" ]; then
    echo "GAGAL: tidak ada file .dump di $REPO_ROOT/backups/ dan tidak ada argumen path yang diberikan." >&2
    exit 1
  fi
  echo "Tidak ada argumen -- pakai dump terbaru: $DUMP_FILE"
fi

if [ ! -f "$DUMP_FILE" ]; then
  echo "GAGAL: file dump tidak ditemukan: $DUMP_FILE" >&2
  exit 1
fi

# Kredensial: env var yang sudah di-set (mis. dari shell staging) menang atas
# .env, sama semangatnya dengan db.py yang baca os.environ.
if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$REPO_ROOT/.env"
  set +a
fi

PG_HOST="${PG_HOST:-127.0.0.1}"
PG_PORT="${PG_PORT:-5432}"
PG_USER="${PG_USER:-postgres}"
PG_DB="${PG_DB:-route_gis}"

if ! command -v pg_restore >/dev/null 2>&1; then
  echo "GAGAL: pg_restore tidak ada di PATH. Di Windows biasanya ada di" >&2
  echo '  "C:\Program Files\PostgreSQL\<versi>\bin\pg_restore.exe" -- tambahkan ke PATH atau panggil langsung.' >&2
  exit 1
fi

echo "=== Restore staging: route_gis ==="
echo "  Dump   : $DUMP_FILE ($(du -h "$DUMP_FILE" | cut -f1))"
echo "  Target : $PG_USER@$PG_HOST:$PG_PORT/$PG_DB"
echo "  Mode   : --clean --if-exists (objek existing di-drop dulu sebelum di-restore ulang)"
echo

if [ "$SKIP_CONFIRM" -ne 1 ]; then
  read -r -p "Lanjutkan restore ke database di atas? Ini akan MENIMPA data yang ada. [y/N] " confirm
  if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Dibatalkan."
    exit 0
  fi
fi

export PGPASSWORD="${PG_PASS:-}"

# Database target harus sudah ada (pg_restore -Fc tidak bisa CREATE DATABASE);
# buat kalau belum ada, aman dipanggil berulang.
if ! psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -lqt | cut -d'|' -f1 | grep -qw "$PG_DB"; then
  echo "Database '$PG_DB' belum ada -- membuat..."
  createdb -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" "$PG_DB"
fi

echo "Menjalankan pg_restore (paralel 4 job)..."
pg_restore -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" \
  --clean --if-exists --no-owner --no-privileges -j 4 -v "$DUMP_FILE"

echo
echo "Verifikasi cepat..."
psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -c "
  SELECT 'usulan_inpres' AS tabel, count(*) FROM usulan_inpres
  UNION ALL SELECT 'map_layers', count(*) FROM map_layers
  UNION ALL SELECT 'pelabuhan_daerah', count(*) FROM pelabuhan_daerah
  UNION ALL SELECT 'basarnas_puslat_fasilitas', count(*) FROM basarnas_puslat_fasilitas;
"

echo "Selesai. Pastikan .env staging (PG_HOST/PORT/USER/PASS/DB=$PG_DB) menunjuk ke database ini,"
echo "lalu restart app.py supaya cache in-process (_ijd_bulk_cache dkk) tidak menyajikan data lama."
