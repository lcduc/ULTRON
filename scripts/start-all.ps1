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

# 2b. GPU broker (lets the agent hand the GPU to ComfyUI and back)
$brokerRunning = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.CommandLine -match 'gpu-broker\.ps1' }
if (-not $brokerRunning) {
    Start-Process powershell -WindowStyle Hidden -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden',
        '-File', (Join-Path $PSScriptRoot 'gpu-broker.ps1'))
    Write-Output "gpu broker starting"
}

# 2c. (Retired 2026-11-22) model-idle.ps1 swapped back to the chat model after agent
# work. With one model for every chat name there is nothing to swap; the script is
# kept in case two models come back.
# $idleRunning = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
#     Where-Object { $_.CommandLine -match 'model-idle\.ps1' }
# if (-not $idleRunning) {
#     Start-Process powershell -WindowStyle Hidden -ArgumentList @(
#         '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden',
#         '-File', (Join-Path $PSScriptRoot 'model-idle.ps1'))
#     Write-Output "model idle watcher starting"
# }

# 3. Docker Desktop (clears stale sockets first)
& (Join-Path $PSScriptRoot 'start-docker.ps1')

# 4. Containers
Set-Location (Join-Path $root 'compose')
docker compose --profile gateway --profile monitoring --profile agent up -d

# 5. Publish the chat UI to the tailnet (no-op if Tailscale is not installed or signed in)
$ts = 'C:\Program Files\Tailscale\tailscale.exe'
if (Test-Path $ts) {
    # At sign-in Tailscale is often still starting (state NoState) and serve silently publishes nothing,
    # so wait until it is Running, then apply the rules and check they stuck.
    function Wait-Tailscale($seconds) {
        for ($i = 0; $i -lt $seconds / 5; $i++) {
            try { if ((& $ts status --json | ConvertFrom-Json).BackendState -eq 'Running') { return $true } } catch {}
            Start-Sleep -Seconds 5
        }
        return $false
    }
    $published = $false
    for ($try = 1; $try -le 3 -and -not $published; $try++) {
        if (-not (Wait-Tailscale 180)) { Write-Output "Tailscale not running yet (attempt $try)"; continue }
        # Reset first so a renamed machine or tailnet does not leave the mapping on the old name.
        & $ts serve reset
        & $ts serve --bg 3000
        # ntfy (phone pushes) on a second HTTPS port; the chat UI stays on the root.
        & $ts serve --bg --https=8443 http://127.0.0.1:2586
        # Tonight's spoken briefing (the iPhone Shortcut fetches it); tailnet only, never funnel.
        & $ts serve --bg --https=8445 http://127.0.0.1:2587
        $published = ((& $ts serve status | Out-String) -split "`n" | Where-Object { $_ -match '^https://' }).Count -ge 3
        if (-not $published) { Write-Output "Tailscale serve rules not applied (attempt $try)" }
    }
    if ($published) { Write-Output "Tailscale serve rules published" } else { Write-Output "WARNING: Tailscale serve rules NOT published; run this script again" }
}

# 6. Load the Whisper model in the background, so the first voice message is not the slow one.
Start-Process powershell -WindowStyle Hidden -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden',
    '-File', (Join-Path $PSScriptRoot 'warm-voice.ps1'))

Stop-Transcript | Out-Null
