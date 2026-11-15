# Runs the model server (router mode) in the foreground and restarts it if it exits.
# Models and their settings are defined in scripts\models.ini; one is loaded at a time
# and the router swaps them on demand by the "model" name in each request.
# Listens on localhost only; containers reach it through host.docker.internal.

$root    = Split-Path -Parent $PSScriptRoot
$exe     = Join-Path $root 'bin\llama\llama-server.exe'
$presets = Join-Path $PSScriptRoot 'models.ini'
$keyFile = Join-Path $root 'monitoring\secrets\llama_api_key'
$logDir  = Join-Path $root 'logs'

if (-not (Test-Path $keyFile)) {
    Write-Error "API key file missing. Run scripts\gen-env.ps1 first."
    exit 1
}
New-Item -ItemType Directory -Force $logDir | Out-Null
Set-Location $root    # preset model paths are relative to the repository root

# Keep the last 5 logs.
Get-ChildItem $logDir -Filter 'llama-server-*.log' | Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 5 | Remove-Item -Force -ErrorAction SilentlyContinue

while ($true) {
    $log = Join-Path $logDir ("llama-server-{0}.log" -f (Get-Date -Format yyyyMMdd-HHmmss))
    & $exe `
        --models-preset $presets --models-max 1 `
        --host 127.0.0.1 --port 8080 `
        --api-key-file $keyFile `
        --metrics --no-webui `
        --log-file $log
    Start-Sleep -Seconds 5
}
