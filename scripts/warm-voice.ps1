# Waits for Open WebUI to be healthy, then loads the Whisper speech-to-text model so the
# first real voice message is not the slow one (about 15 s after a restart).
#
# Open WebUI loads Whisper lazily, inside its web server process (app.state.faster_whisper_model),
# on the first call to /api/v1/audio/transcriptions. Only that API call warms the model that
# serves your voice messages, and it needs a login, so this script uses ULTRON_API_KEY
# (Settings -> Account -> API Keys; env var or a line in compose\.env).
# Without the key it only reads the Whisper files into the disk cache (a smaller gain) and says so.
param(
    [string]$BaseUrl = 'http://localhost:3000',
    [int]$WaitSeconds = 300
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot

# 1. Wait until Open WebUI answers.
$deadline = (Get-Date).AddSeconds($WaitSeconds)
$up = $false
while ((Get-Date) -lt $deadline) {
    try {
        $r = Invoke-WebRequest "$BaseUrl/health" -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) { $up = $true; break }
    } catch { }
    Start-Sleep -Seconds 3
}
if (-not $up) { Write-Output "Open WebUI did not become healthy within $WaitSeconds s: voice not warmed."; exit 1 }
Write-Output 'Open WebUI is healthy.'

# 2. The key.
$key = $env:ULTRON_API_KEY
if (-not $key) {
    $line = [IO.File]::ReadAllLines((Join-Path $root 'compose\.env')) | Where-Object { $_ -match '^\s*ULTRON_API_KEY=\S' } | Select-Object -First 1
    if ($line) { $key = ($line -split '=', 2)[1].Trim() }
}

if (-not $key) {
    Write-Output 'ULTRON_API_KEY missing - skipped the real warm-up. The Whisper model inside the web server is NOT loaded;'
    Write-Output 'warming only the disk cache (the first voice message will still load the model, but faster).'
    $py = @'
import os
from faster_whisper import WhisperModel
WhisperModel("small.en", device="cpu", compute_type="int8", download_root=os.environ["WHISPER_MODEL_DIR"], local_files_only=True)
print("disk cache warmed")
'@
    $py | & docker exec -i ultron-open-webui-1 python3 -
    exit 0
}

# 3. A 1-second silent 16 kHz mono WAV, sent like a recorded clip.
$wav = Join-Path ([IO.Path]::GetTempPath()) 'ultron-warm.wav'
$n = 16000 * 2
$ms = New-Object IO.MemoryStream
$w = New-Object IO.BinaryWriter($ms)
$w.Write([Text.Encoding]::ASCII.GetBytes('RIFF')); $w.Write([int](36 + $n)); $w.Write([Text.Encoding]::ASCII.GetBytes('WAVEfmt '))
$w.Write([int]16); $w.Write([int16]1); $w.Write([int16]1); $w.Write([int]16000); $w.Write([int]32000); $w.Write([int16]2); $w.Write([int16]16)
$w.Write([Text.Encoding]::ASCII.GetBytes('data')); $w.Write([int]$n); $w.Write((New-Object byte[] $n))
$w.Flush()
[IO.File]::WriteAllBytes($wav, $ms.ToArray())

# Multipart upload like the browser's microphone upload (HttpClient keeps the key out of any command line).
Add-Type -AssemblyName System.Net.Http
function Send-Clip {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $client = New-Object System.Net.Http.HttpClient
    $client.Timeout = [TimeSpan]::FromSeconds(180)
    $client.DefaultRequestHeaders.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue('Bearer', $key)
    $form = New-Object System.Net.Http.MultipartFormDataContent
    $part = New-Object System.Net.Http.ByteArrayContent(,[IO.File]::ReadAllBytes($wav))
    $part.Headers.ContentType = New-Object System.Net.Http.Headers.MediaTypeHeaderValue('audio/wav')
    $form.Add($part, 'file', 'ultron-warm.wav')
    try { $code = [int]$client.PostAsync("$BaseUrl/api/v1/audio/transcriptions", $form).GetAwaiter().GetResult().StatusCode }
    catch { $code = 0 }
    finally { $client.Dispose() }
    $sw.Stop()
    [pscustomobject]@{ Code = "$code"; Seconds = [math]::Round($sw.Elapsed.TotalSeconds, 1) }
}
try {
    $a = Send-Clip
    if ($a.Code -ne '200') { Write-Output "Warm-up request failed with HTTP $($a.Code) (is the API key valid and enabled?)."; exit 1 }
    $b = Send-Clip
    Write-Output "Whisper is loaded in Open WebUI: first request $($a.Seconds) s, second $($b.Seconds) s."
} finally {
    Remove-Item $wav -Force -ErrorAction SilentlyContinue
}
