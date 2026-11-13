# Runs the model server in the foreground and restarts it if it exits.
# Listens on localhost only; containers reach it through host.docker.internal.

$root    = Split-Path -Parent $PSScriptRoot
$exe     = Join-Path $root 'bin\llama\llama-server.exe'
$model   = Join-Path $root 'models\gemma-4-12B-it-heretic-Q4_K_M.gguf'
$keyFile = Join-Path $root 'monitoring\secrets\llama_api_key'
$logDir  = Join-Path $root 'logs'

if (-not (Test-Path $keyFile)) {
    Write-Error "API key file missing. Run scripts\gen-env.ps1 first."
    exit 1
}
New-Item -ItemType Directory -Force $logDir | Out-Null

# Keep the last 5 logs.
Get-ChildItem $logDir -Filter 'llama-server-*.log' | Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 5 | Remove-Item -Force -ErrorAction SilentlyContinue

while ($true) {
    $log = Join-Path $logDir ("llama-server-{0}.log" -f (Get-Date -Format yyyyMMdd-HHmmss))
    & $exe `
        -m $model -a ultron `
        -ngl all -c 16384 -np 1 --load-mode none `
        -fa on -ctk q8_0 -ctv q8_0 `
        --cache-reuse 256 -cram 2048 `
        --reasoning off `
        --host 127.0.0.1 --port 8080 `
        --api-key-file $keyFile `
        --metrics --no-webui `
        --log-file $log
    Start-Sleep -Seconds 5
}
