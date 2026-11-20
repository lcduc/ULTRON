# Measures the assistant and appends one JSON line to logs\bench-assistant.jsonl.
#   scripts\bench-assistant.ps1 -Label baseline
# Needs the stack running. Chat-level tests need ULTRON_API_KEY (Settings -> Account -> API Keys),
# set as an environment variable or as a line in compose\.env; without it they are skipped.
# The heavy lifting is in bench-assistant.py (host) and two small scripts run inside the
# open-webui container (bench-assistant-container.py, bench-voice-container.py).
param(
    [string]$Label = '',
    [int]$Runs = 10,
    [switch]$SkipToolTest
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force $logDir | Out-Null

# ULTRON_API_KEY: environment first, then compose\.env.
$haveKey = [bool]$env:ULTRON_API_KEY
if (-not $haveKey) {
    $line = [IO.File]::ReadAllLines((Join-Path $root 'compose\.env')) | Where-Object { $_ -match '^\s*ULTRON_API_KEY=\S' } | Select-Object -First 1
    $haveKey = [bool]$line
}
if (-not $haveKey) { Write-Output 'ULTRON_API_KEY missing - chat-level tests will be skipped.' }

$tmp = Join-Path ([IO.Path]::GetTempPath()) ("bench-assistant-{0}.json" -f ([guid]::NewGuid().ToString('N').Substring(0, 8)))
Write-Output "Running benchmark ($Runs runs per median; takes several minutes)..."
& python (Join-Path $PSScriptRoot 'bench-assistant.py') --out $tmp --runs $Runs
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $tmp)) { throw 'bench-assistant.py failed' }
$r = [IO.File]::ReadAllText($tmp, [Text.Encoding]::UTF8) | ConvertFrom-Json
Remove-Item $tmp -Force

# Tool choice: the existing test set, straight against the model server.
$tool = $null
if (-not $SkipToolTest) {
    Write-Output 'Running test-tools.ps1...'
    $out = & (Join-Path $PSScriptRoot 'test-tools.ps1') -Model ultron -KeyFile (Join-Path $root 'monitoring\secrets\llama_api_key') 2>&1 | Out-String
    $m = [regex]::Match($out, 'RESULT: (\d+) of (\d+) passed')
    $tool = if ($m.Success) { @{ pass = [int]$m.Groups[1].Value; total = [int]$m.Groups[2].Value } } else { @{ pass = $null; total = $null } }
}

# Free memory.
$os = Get-CimInstance Win32_OperatingSystem
$ramFreeGb = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
$gpu = (& nvidia-smi --query-gpu=memory.used,memory.free,memory.total --format=csv,noheader,nounits) -split ',\s*'
$vram = @{ used_mib = [int]$gpu[0]; free_mib = [int]$gpu[1]; total_mib = [int]$gpu[2] }

# Table.
$rows = New-Object System.Collections.ArrayList
function Add-Row($area, $metric, $value, $target = '') { [void]$rows.Add([pscustomobject]@{ Area = $area; Metric = $metric; Value = "$value"; Target = $target }) }
$mdl = $r.model
Add-Row 'model' 'prompt tokens, one-line chat' $mdl.prompt_tokens 'under 4000'
Add-Row 'model' '  of which system prompt + question' $mdl.prompt_tokens_no_tools
Add-Row 'model' "  tools attached ($($mdl.tools))" "$($mdl.tool_schema_chars) chars"
Add-Row 'model' 'TTFT, prefix cached (median s)' $mdl.ttft_warm_prefix_s 'under 1.5'
Add-Row 'model' 'TTFT, nothing cached (median s)' $mdl.ttft_cold_s
Add-Row 'tasks' 'follow-ups, GPU s per reply' $r.tasks.follow_up.gpu_s
Add-Row 'tasks' 'follow-ups on ultron-think, GPU s per reply' $r.tasks.follow_up_think.gpu_s
Add-Row 'tasks' 'tags, GPU s (first reply only)' $r.tasks.tags.gpu_s
Add-Row 'tasks' 'title, GPU s (first message only)' $r.tasks.title.gpu_s
$ts = $r.task_settings
Add-Row 'tasks' 'settings now: follow-ups / tags / title' ("{0} / {1} / {2}" -f $(if ($ts.follow_ups) { 'on' } else { 'off' }), $(if ($ts.tags) { 'on' } else { 'off' }), $(if ($ts.title) { 'on' } else { 'off' }))
Add-Row 'tasks' 'background GPU s in a 3-turn chat, ultron' $ts.gpu_s_per_3_turn_chat_ultron
Add-Row 'tasks' 'background GPU s in a 3-turn chat, ultron-think' $ts.gpu_s_per_3_turn_chat_ultron_think
Add-Row 'tasks' 'next-message TTFT, no task before (s)' $r.cache_effect.follow_up.ttft_next_message_direct_s
Add-Row 'tasks' 'next-message TTFT after a follow-up task (s)' $r.cache_effect.follow_up.ttft_next_message_after_task_s
Add-Row 'tasks' 'next-message TTFT after a tags task (s)' $r.cache_effect.tags.ttft_next_message_after_task_s
if ($r.chat.skipped) { Add-Row 'chat' 'Open WebUI chat tests' "skipped: $($r.chat.skipped)" }
elseif ($r.chat.error) { Add-Row 'chat' 'Open WebUI chat tests' "error: $($r.chat.error)" }
else {
    Add-Row 'chat' 'TTFT via Open WebUI (median s)' $r.chat.ttft_s
    Add-Row 'chat' 'model-server requests per turn' $r.chat.llama_requests_per_turn 'answer + at most 1'
    Add-Row 'chat' 'GPU s per turn' $r.chat.gpu_s_per_turn
    Add-Row 'chat' 'prompt tokens via Open WebUI' $r.chat.prompt_tokens
}
if ($r.voice.error) { Add-Row 'voice' 'voice test' "error: $($r.voice.error)" }
else {
    Add-Row 'voice' "STT cold, $($r.voice.clip_seconds) s clip (s)" $r.voice.stt.cold_total_s
    Add-Row 'voice' 'STT warm (median s)' $r.voice.stt.warm_median_s
    Add-Row 'voice' 'TTS, one sentence (median s)' $r.voice.tts_sentence_s.total_median
}
if ($tool) { Add-Row 'tools' 'test-tools.ps1 passed' "$($tool.pass) of $($tool.total)" 'all' }
Add-Row 'system' 'free RAM (GB)' $ramFreeGb 'above 4'
Add-Row 'system' 'VRAM used / free (MiB)' "$($vram.used_mib) / $($vram.free_mib)"
Add-Row 'system' 'memory tool attached' $r.memory_tool_present
$rows | Format-Table -AutoSize | Out-String -Width 200 | Write-Output
if ($r.context_notes) { Write-Output ("Notes: " + ($r.context_notes -join '; ')) }

# JSON line.
$entry = [ordered]@{
    time = (Get-Date).ToString('s'); label = $Label; runs = $Runs; have_api_key = $haveKey
    model = $r.model; tasks = $r.tasks; task_settings = $r.task_settings; cache_effect = $r.cache_effect; chat = $r.chat; voice = $r.voice
    tool_test = $tool; ram_free_gb = $ramFreeGb; vram = $vram; memory_tool_present = $r.memory_tool_present
}
$json = $entry | ConvertTo-Json -Depth 20 -Compress
[IO.File]::AppendAllText((Join-Path $logDir 'bench-assistant.jsonl'), $json + "`n", (New-Object Text.UTF8Encoding $false))
Write-Output "Appended to logs\bench-assistant.jsonl"
