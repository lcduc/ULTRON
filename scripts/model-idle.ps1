# Swaps the model server back to the chat model (`ultron`) once the agent model has been idle.
#
# Only one model fits in VRAM. After agent work, the next chat or voice message would otherwise
# wait ~26 s while `ultron` loads back. This loop checks every $PollSeconds: if `ultron-agent` is
# loaded and has done no work for $IdleMinutes, it sends `ultron` a 1-token request, which makes
# the router swap. It never touches the GPU while a ComfyUI job is running or queued, and does
# nothing when no model is loaded (the GPU broker released it, or the model server is off).
param(
    [int]$IdleMinutes = 5,
    [int]$PollSeconds = 20,
    [string]$LlamaUrl = 'http://127.0.0.1:8080',
    [string]$ComfyUrl = 'http://127.0.0.1:8188'
)

$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
$log = Join-Path $root 'logs\model-idle.log'
$key = [IO.File]::ReadAllText((Join-Path $root 'monitoring\secrets\llama_api_key')).Trim()
$auth = @{ Authorization = "Bearer $key" }

function Write-Log($msg) { Add-Content -Path $log -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg" }

function Get-ModelStatus {
    $s = @{}
    try { (Invoke-RestMethod "$LlamaUrl/v1/models" -Headers $auth -TimeoutSec 5).data | ForEach-Object { $s[$_.id] = $_.status.value } } catch {}
    $s
}

# Work counter of a loaded model: changes whenever it processes or generates any token.
function Get-Activity($model) {
    try {
        $m = Invoke-RestMethod "$LlamaUrl/metrics?model=$model" -Headers $auth -TimeoutSec 5
        $sum = 0.0
        foreach ($line in ($m -split "`n")) {
            if ($line -match '^llamacpp:(prompt_tokens_total|prompt_tokens_cached_total|tokens_predicted_total) ([0-9.e+]+)') { $sum += [double]$Matches[2] }
        }
        $busy = @(Invoke-RestMethod "$LlamaUrl/slots?model=$model" -Headers $auth -TimeoutSec 5) | Where-Object { $_.is_processing }
        if ($busy) { return "busy-$(Get-Date -Format o)" }
        return "$sum"
    } catch { return $null }
}

function Test-ComfyBusy {
    try {
        $q = Invoke-RestMethod "$ComfyUrl/queue" -TimeoutSec 3
        return (@($q.queue_running).Count + @($q.queue_pending).Count) -gt 0
    } catch { return $false }   # ComfyUI not running
}

$lastActivity = $null
$lastActive = Get-Date
while ($true) {
    Start-Sleep -Seconds $PollSeconds
    $status = Get-ModelStatus
    if ($status['ultron-agent'] -ne 'loaded') { $lastActivity = $null; continue }

    $activity = Get-Activity 'ultron-agent'
    if ($null -eq $lastActivity -or $activity -ne $lastActivity) {
        $lastActivity = $activity
        $lastActive = Get-Date
        continue
    }
    if (((Get-Date) - $lastActive).TotalMinutes -lt $IdleMinutes) { continue }
    if (Test-ComfyBusy) { continue }

    $sw = [Diagnostics.Stopwatch]::StartNew()
    try {
        $body = @{ model = 'ultron'; max_tokens = 1; messages = @(@{ role = 'user'; content = 'hi' }) } | ConvertTo-Json -Depth 4
        Invoke-RestMethod "$LlamaUrl/v1/chat/completions" -Method Post -Headers $auth -ContentType 'application/json' -Body $body -TimeoutSec 180 | Out-Null
        Write-Log "ultron-agent idle $IdleMinutes min: swapped back to ultron in $([math]::Round($sw.Elapsed.TotalSeconds)) s"
    } catch {
        Write-Log "swap back to ultron failed: $($_.Exception.Message)"
    }
    $lastActivity = $null
}
