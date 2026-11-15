# GPU broker: lets the agent sandbox hand the GPU between the chat model and
# another GPU app (ComfyUI). Listens on 127.0.0.1 only and exposes three actions:
#   GET  /status   VRAM and which models are loaded
#   POST /release  unload the chat/agent model so another app can use the GPU
#   POST /reclaim  ask ComfyUI to free its models and wait for VRAM to clear
# The chat model reloads by itself on the next chat request (router autoload).
# No secrets are exposed: the broker holds the model-server key, callers do not.
param(
    [int]$Port = 8090,
    [string]$ComfyUrl = 'http://127.0.0.1:8188',
    [string]$LlamaUrl = 'http://127.0.0.1:8080'
)

$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
$key = [IO.File]::ReadAllText((Join-Path $root 'monitoring\secrets\llama_api_key')).Trim()
$auth = @{ Authorization = "Bearer $key" }

function Get-VramMiB { [int]((nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) -join '') }
function Get-Models {
    try { (Invoke-RestMethod "$LlamaUrl/v1/models" -Headers $auth -TimeoutSec 5).data | ForEach-Object { @{ id = $_.id; status = $_.status.value } } }
    catch { @() }
}
function Invoke-Release {
    $unloaded = @()
    foreach ($m in @(Get-Models)) {
        if ($m.status -ne 'unloaded') {
            try {
                Invoke-RestMethod "$LlamaUrl/models/unload" -Method Post -Headers $auth -ContentType 'application/json' `
                    -Body (@{ model = $m.id } | ConvertTo-Json) -TimeoutSec 30 | Out-Null
                $unloaded += $m.id
            } catch {}
        }
    }
    for ($i = 0; $i -lt 30; $i++) {
        if (-not (@(Get-Models) | Where-Object { $_.status -ne 'unloaded' })) { break }
        Start-Sleep -Seconds 1
    }
    Start-Sleep -Seconds 1
    @{ ok = $true; unloaded = $unloaded; vram_used_mib = (Get-VramMiB) }
}
function Invoke-Reclaim {
    $freed = $false
    try {
        Invoke-RestMethod "$ComfyUrl/free" -Method Post -ContentType 'application/json' `
            -Body '{"unload_models":true,"free_memory":true}' -TimeoutSec 10 | Out-Null
        $freed = $true
    } catch {}
    $v = Get-VramMiB
    for ($i = 0; $i -lt 45 -and $v -gt 3000; $i++) { Start-Sleep -Seconds 1; $v = Get-VramMiB }
    @{ ok = ($v -le 3000); comfy_free_called = $freed; vram_used_mib = $v }
}

$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://127.0.0.1:$Port/")
$listener.Start()
Write-Output "GPU broker listening on 127.0.0.1:$Port"

while ($listener.IsListening) {
    $ctx = $listener.GetContext()
    $route = "$($ctx.Request.HttpMethod) $($ctx.Request.Url.AbsolutePath)"
    $status = 200
    try {
        $result = switch ($route) {
            'GET /status'   { @{ ok = $true; vram_used_mib = (Get-VramMiB); models = @(Get-Models) } }
            'POST /release' { Invoke-Release }
            'POST /reclaim' { Invoke-Reclaim }
            default         { $status = 404; @{ ok = $false; error = 'unknown route' } }
        }
    } catch {
        $status = 500
        $result = @{ ok = $false; error = "$($_.Exception.Message)" }
    }
    $bytes = [Text.Encoding]::UTF8.GetBytes(($result | ConvertTo-Json -Depth 5 -Compress))
    $ctx.Response.StatusCode = $status
    $ctx.Response.ContentType = 'application/json'
    $ctx.Response.OutputStream.Write($bytes, 0, $bytes.Length)
    $ctx.Response.Close()
}
