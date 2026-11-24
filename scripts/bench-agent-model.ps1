# Benchmarks a large MoE model with part of it on the CPU, sweeping --n-cpu-moe.
# Runs a temporary llama-server on port 8081 (localhost, no key). The normal
# model server must be stopped first (scripts\model-off.ps1).
param(
    [string]$Model = 'Qwen3.6-35B-A3B-UD-Q4_K_M-MTP.gguf',
    [int[]]$CpuMoe = @(40, 32, 28, 24, 20),
    [int]$Context = 32768
)

$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $root 'bin\llama\llama-server.exe'
$modelPath = Join-Path $root "models\$Model"
$log = Join-Path $root 'logs\bench-agent.log'

# ~3000-token prompt to measure prompt processing, as agent work has long prompts.
$filler = (1..260 | ForEach-Object { "Line ${_}: the service on port $((8000 + $_)) reported status ok with latency $(($_ * 7) % 90) ms." }) -join "`n"

function Stop-Bench { Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force; Start-Sleep -Seconds 3 }
function Chat($content, $max) {
    $body = @{ model = 'bench'; max_tokens = $max; chat_template_kwargs = @{ enable_thinking = $false }
        messages = @(@{ role = 'user'; content = $content }) } | ConvertTo-Json -Depth 6
    Invoke-RestMethod 'http://127.0.0.1:8081/v1/chat/completions' -Method Post -ContentType 'application/json' `
        -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 900
}

$rows = foreach ($n in $CpuMoe) {
    Stop-Bench
    $p = Start-Process $exe -WindowStyle Hidden -PassThru -ArgumentList @(
        '-m', "`"$modelPath`"", '-a', 'bench', '-ngl', '99', '--n-cpu-moe', $n, '-c', $Context, '-np', '1',
        '-fa', 'on', '-ctk', 'q8_0', '-ctv', 'q8_0', '--host', '127.0.0.1', '--port', '8081', '--no-webui',
        '--log-file', "`"$log`"")
    $up = $false
    for ($i = 0; $i -lt 100; $i++) {
        Start-Sleep -Seconds 3
        if ($p.HasExited) { break }
        try { if ((Invoke-RestMethod 'http://127.0.0.1:8081/health' -TimeoutSec 3).status -eq 'ok') { $up = $true; break } } catch {}
    }
    if (-not $up) {
        [pscustomobject]@{ CpuMoe = $n; Loaded = $false; VramMiB = $null; RamFreeGB = $null; GenTokS = $null; PromptTokS = $null; ProcRamGB = $null }
        continue
    }
    try {
        Chat 'Say hi.' 8 | Out-Null    # warm-up
        $g = Chat 'Write a 250-word explanation of how DNS resolution works.' 320
        $l = Chat ("Here is a log.`n$filler`nWhich line number has the highest latency? Answer in one sentence.") 60
        $vram = [int]((nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) -join '')
        $os = Get-CimInstance Win32_OperatingSystem
        [pscustomobject]@{
            CpuMoe     = $n
            Loaded     = $true
            VramMiB    = $vram
            RamFreeGB  = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
            GenTokS    = [math]::Round($g.timings.predicted_per_second, 1)
            PromptTokS = [math]::Round($l.timings.prompt_per_second, 0)
            ProcRamGB  = [math]::Round((Get-Process llama-server).WorkingSet64 / 1GB, 1)
        }
    } catch {
        [pscustomobject]@{ CpuMoe = $n; Loaded = "error: $($_.Exception.Message)"; VramMiB = $null; RamFreeGB = $null; GenTokS = $null; PromptTokS = $null; ProcRamGB = $null }
    }
}
Stop-Bench
$rows | Format-Table -AutoSize | Out-String | Write-Output
