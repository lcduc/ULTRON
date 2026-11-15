# Starts the model server again and waits until it answers. The server loads the
# chat model at startup and swaps to the agent model on demand (scripts\models.ini).

if (Get-Process llama-server -ErrorAction SilentlyContinue) {
    Write-Output "Model server is already running."
    exit 0
}

Start-Process powershell -WindowStyle Hidden -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden',
    '-File', (Join-Path $PSScriptRoot 'start-llama.ps1'))

$ProgressPreference = 'SilentlyContinue'
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 3
    try {
        if ((Invoke-RestMethod 'http://127.0.0.1:8080/health' -TimeoutSec 3).status -eq 'ok') {
            $vram = (nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) -join ''
            Write-Output "Model loaded and ready. GPU memory in use now: $vram MiB."
            exit 0
        }
    } catch {}
}
Write-Output "Model did not become ready within 2 minutes. Close GPU-heavy apps and try again; see the newest file in logs\."
exit 1
