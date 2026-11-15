# Checks that `ultron` answers without thinking and `ultron-think` with thinking,
# alternating requests to catch parameters leaking between the two names.
param([int]$Rounds = 5)

$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot
$envl = [IO.File]::ReadAllLines((Join-Path $root 'compose\.env'))
$vk = (($envl | Where-Object { $_ -match '^OPENAI_API_KEY=' }) -split '=', 2)[1]

function Ask($model) {
    $body = @{ model = $model; max_tokens = 1200
        messages = @(@{ role = 'user'; content = 'A farmer has 17 sheep. All but 9 run away. How many are left? Answer briefly.' }) } |
        ConvertTo-Json -Depth 6
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $r = Invoke-RestMethod 'http://127.0.0.1:4000/v1/chat/completions' -Method Post `
        -Headers @{ Authorization = "Bearer $vk" } -ContentType 'application/json' -Body $body -TimeoutSec 300
    $sw.Stop()
    $msg = $r.choices[0].message
    [pscustomobject]@{
        Model     = $model
        Thought   = ("$($msg.reasoning_content)".Length -gt 0)
        Tokens    = $r.usage.completion_tokens
        TokPerSec = [math]::Round($r.usage.completion_tokens / $sw.Elapsed.TotalSeconds, 1)
        HasAnswer = ("$($msg.content)".Trim().Length -gt 0)
    }
}

$results = for ($i = 0; $i -lt $Rounds; $i++) { Ask 'ultron'; Ask 'ultron-think' }
$results | Format-Table -AutoSize | Out-String | Write-Output

$bad = @($results | Where-Object { ($_.Model -eq 'ultron' -and $_.Thought) -or ($_.Model -eq 'ultron-think' -and -not $_.Thought) -or -not $_.HasAnswer })
if ($bad.Count -eq 0) { Write-Output "PASS: modes stay separate across $($results.Count) requests." }
else { Write-Output "FAIL: $($bad.Count) of $($results.Count) requests had the wrong mode or no answer."; exit 1 }
