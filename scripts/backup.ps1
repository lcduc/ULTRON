# Nightly backup: chat data volume, monitoring volumes, Postgres dump, and secrets.
# Keeps the newest 14 backups. Copy the backups folder off this PC now and then.

$root   = Split-Path -Parent $PSScriptRoot
$stamp  = Get-Date -Format yyyyMMdd-HHmmss
$dest   = Join-Path $root "backups\$stamp"
New-Item -ItemType Directory -Force $dest | Out-Null

$failed = $false

foreach ($vol in 'ultron_open-webui-data', 'ultron_grafana-data', 'ultron_uptime-kuma-data') {
    docker volume inspect $vol 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { continue }
    docker run --rm -v "${vol}:/data:ro" -v "${dest}:/backup" alpine:3.22 `
        tar czf "/backup/$vol.tar.gz" --exclude=./cache -C /data .
    if ($LASTEXITCODE -ne 0) { $failed = $true; Write-Output "FAILED: $vol" }
}

# Postgres (LiteLLM keys and token logs)
docker exec ultron-postgres-1 sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > /tmp/litellm.sql.gz'
if ($LASTEXITCODE -eq 0) {
    docker cp ultron-postgres-1:/tmp/litellm.sql.gz (Join-Path $dest 'litellm.sql.gz')
} else {
    $failed = $true; Write-Output "FAILED: postgres dump"
}

# Config and secrets needed to restore
Copy-Item (Join-Path $root 'compose\.env') (Join-Path $dest 'compose.env')
Copy-Item (Join-Path $root 'monitoring\secrets') (Join-Path $dest 'secrets') -Recurse

Get-ChildItem (Join-Path $root 'backups') -Directory | Sort-Object Name -Descending |
    Select-Object -Skip 14 | Remove-Item -Recurse -Force

if ($failed) { Write-Output "Backup finished WITH ERRORS: $dest"; exit 1 }
Write-Output "Backup complete: $dest"
