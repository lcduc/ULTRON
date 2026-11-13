# Starts the whole stack. Safe to run repeatedly; runs at Windows sign-in.

$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force $logDir | Out-Null
Start-Transcript -Path (Join-Path $logDir 'start-all.log') -Force | Out-Null

# 1. Model server (native, GPU)
if (-not (Get-Process llama-server -ErrorAction SilentlyContinue)) {
    Start-Process powershell -WindowStyle Hidden -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden',
        '-File', (Join-Path $PSScriptRoot 'start-llama.ps1'))
    Write-Output "llama-server starting"
} else {
    Write-Output "llama-server already running"
}

# 2. GPU metrics exporter (native)
if (-not (Get-Process nvidia_gpu_exporter -ErrorAction SilentlyContinue)) {
    Start-Process (Join-Path $root 'bin\gpu-exporter\nvidia_gpu_exporter.exe') `
        -ArgumentList '--web.listen-address=127.0.0.1:9835' -WindowStyle Hidden
    Write-Output "gpu exporter starting"
}

# 3. Docker Desktop (clears stale sockets first)
& (Join-Path $PSScriptRoot 'start-docker.ps1')

# 4. Containers
Set-Location (Join-Path $root 'compose')
docker compose --profile gateway --profile monitoring up -d

# 5. Publish the chat UI to the tailnet (no-op if Tailscale is not installed or signed in)
$ts = 'C:\Program Files\Tailscale\tailscale.exe'
if (Test-Path $ts) {
    # Reset first so a renamed machine or tailnet does not leave the mapping on the old name.
    & $ts serve reset
    & $ts serve --bg 3000
}

Stop-Transcript | Out-Null
