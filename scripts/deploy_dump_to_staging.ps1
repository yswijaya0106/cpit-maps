# Transfer dump route_gis (backups\*.dump) ke server staging GCP via scp,
# lalu restore otomatis lewat ssh (menjalankan scripts/restore_staging_dump.sh
# yang sudah ada di checkout repo staging).
#
# Dijalankan dari Windows (PowerShell), sesuai alur scp yang sudah dipakai
# sebelumnya:
#   scp -i C:\Users\wilda\.ssh\gcp_id_rsa "<file>" baramij@34.128.69.157:~/
#
# Usage:
#   .\scripts\deploy_dump_to_staging.ps1                                   # dump terbaru di backups\
#   .\scripts\deploy_dump_to_staging.ps1 -DumpPath backups\route_gis_20260820.dump
#   .\scripts\deploy_dump_to_staging.ps1 -RemoteRepoDir /opt/analytic-maps   # default, confirmed 20 Aug 2026
#
# Prasyarat di server staging: repo sudah di-clone/di-pull (punya
# scripts/restore_staging_dump.sh dan .env dgn PG_* terisi), PostgreSQL
# client (pg_restore/psql/createdb) terpasang, dan .env staging SUDAH
# menunjuk ke database route_gis yang mau di-restore (script restore
# membaca kredensial dari .env repo staging, bukan dari sini).

param(
    [string]$DumpPath = "",
    [string]$SshKey = "C:\Users\wilda\.ssh\gcp_id_rsa",
    [string]$RemoteHost = "baramij@34.128.69.157",
    [string]$RemoteRepoDir = "/opt/analytic-maps",
    # restore_staging_dump.sh (default) utk dump PENUH (route_gis_*.dump) --
    # database target harus kosong/belum ada skema. Pakai
    # restore_gap_docs_new_update.sh utk dump gap-only (gap_docs_new_update.dump)
    # -- database target HARUS SUDAH punya skema map_layers/map_layer_meta dkk.
    [string]$RestoreScript = "restore_staging_dump.sh",
    [switch]$SkipConfirm
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

if (-not $DumpPath) {
    $latest = Get-ChildItem -Path (Join-Path $RepoRoot "backups") -Filter "*.dump" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) {
        Write-Error "Tidak ada file .dump di backups\ dan -DumpPath tidak diberikan."
        exit 1
    }
    $DumpPath = $latest.FullName
    Write-Host "Tidak ada -DumpPath -- pakai dump terbaru: $DumpPath"
} elseif (-not (Test-Path $DumpPath)) {
    Write-Error "File dump tidak ditemukan: $DumpPath"
    exit 1
}

$DumpFile = Get-Item $DumpPath
$RemoteDumpName = $DumpFile.Name
$SizeMB = [math]::Round($DumpFile.Length / 1MB, 1)

Write-Host "=== Deploy dump ke staging ==="
Write-Host "  Dump   : $($DumpFile.FullName) ($SizeMB MB)"
Write-Host "  Target : $RemoteHost (key: $SshKey)"
Write-Host "  Repo   : $RemoteRepoDir"
Write-Host ""

if (-not $SkipConfirm) {
    $confirm = Read-Host "Lanjutkan transfer + restore ke staging? Ini akan MENIMPA data di database staging. [y/N]"
    if ($confirm -notmatch '^[Yy]$') {
        Write-Host "Dibatalkan."
        exit 0
    }
}

Write-Host "`n[1/2] Transfer dump via scp..."
& scp -i $SshKey $DumpFile.FullName "${RemoteHost}:~/$RemoteDumpName"
if ($LASTEXITCODE -ne 0) {
    Write-Error "scp gagal (exit $LASTEXITCODE)."
    exit $LASTEXITCODE
}

Write-Host "`n[2/2] Restore via ssh (menjalankan scripts/$RestoreScript di repo staging)..."
$remoteCmd = "cd $RemoteRepoDir && git pull && bash scripts/$RestoreScript --yes ~/$RemoteDumpName && rm -f ~/$RemoteDumpName"
& ssh -i $SshKey $RemoteHost $remoteCmd
if ($LASTEXITCODE -ne 0) {
    Write-Error "Restore di staging gagal (exit $LASTEXITCODE). File dump masih ada di ~/$RemoteDumpName di server utk investigasi manual."
    exit $LASTEXITCODE
}

Write-Host "`nSelesai. Restart proses app.py di staging (mis. systemctl restart / supervisor) supaya cache in-process (_ijd_bulk_cache dkk) tidak menyajikan data lama."
