# Memory test: tells the assistant 5 facts in one conversation, asks about each in a fresh
# conversation, then tests one correction and one "forget that".
# Needs ULTRON_API_KEY (Settings -> Account -> API Keys), as an environment variable or a line in
# compose\.env. Without it the script says so and exits.
#
# It runs in your account, so it cleans up after itself, touching only what it made:
#   - memories: only ones that did not exist before the run AND mention one of the invented
#     test words below (anything else new is listed and left alone);
#   - chats: the requests carry no chat id, so no chat should be saved; any chat that appears
#     during the run and contains this run's tag is deleted.
param(
    [string]$BaseUrl = 'http://localhost:3000',
    [string]$Model = 'ultron',
    [switch]$KeepData   # leave test memories in place (for looking at them)
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = Split-Path -Parent $PSScriptRoot

$key = $env:ULTRON_API_KEY
if (-not $key) {
    $line = [IO.File]::ReadAllLines((Join-Path $root 'compose\.env')) | Where-Object { $_ -match '^\s*ULTRON_API_KEY=\S' } | Select-Object -First 1
    if ($line) { $key = ($line -split '=', 2)[1].Trim() }
}
if (-not $key) { Write-Output 'ULTRON_API_KEY missing - skipped (create one in Settings -> Account -> API Keys).'; exit 0 }
$h = @{ Authorization = "Bearer $key" }
$tag = 'memtest-' + [guid]::NewGuid().ToString('N').Substring(0, 6)

function Api($method, $path, $body = $null) {
    $p = @{ Uri = "$BaseUrl$path"; Method = $method; Headers = $h; UseBasicParsing = $true; TimeoutSec = 300 }
    if ($null -ne $body) {
        $p.Body = [Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json -Depth 10)); $p.ContentType = 'application/json; charset=utf-8'
    }
    $r = Invoke-WebRequest @p
    if ($r.Content) { [Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray()) | ConvertFrom-Json } else { $null }
}

# One turn: sends the conversation so far, returns the assistant's visible text.
function Ask($messages) {
    $body = @{ model = $Model; stream = $true; session_id = $tag; features = @{ memory = $true; web_search = $false }
        messages = @($messages) }
    $bytes = [Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json -Depth 10))
    $r = Invoke-WebRequest "$BaseUrl/api/chat/completions" -Method Post -Headers $h -Body $bytes `
        -ContentType 'application/json; charset=utf-8' -UseBasicParsing -TimeoutSec 600
    $text = New-Object Text.StringBuilder
    foreach ($l in ([Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray()) -split "`n")) {
        if ($l.StartsWith('data:') -and $l -notmatch '\[DONE\]') {
            try { $o = ($l.Substring(5).Trim() | ConvertFrom-Json); foreach ($c in $o.choices) { if ($c.delta.content) { [void]$text.Append($c.delta.content) } } } catch { }
        }
    }
    ([regex]::Replace($text.ToString(), '(?s)<details.*?</details>', '')).Trim()
}
function Memories { @(Api GET '/api/v1/memories/') }

# Invented facts, so nothing real in the account can answer them by accident.
$facts = @(
    @{ say = 'My dog is called Quillfeather.';                 ask = 'What is my dog called?';              expect = 'Quillfeather';  word = 'Quillfeather' },
    @{ say = 'I work as a lighthouse keeper.';                 ask = 'What is my job?';                     expect = 'lighthouse';    word = 'lighthouse' },
    @{ say = 'My sister is called Marguerite.';                ask = 'What is my sister called?';           expect = 'Marguerite';    word = 'Marguerite' },
    @{ say = 'I am allergic to pistachios.';                   ask = 'What am I allergic to?';              expect = 'pistachio';     word = 'pistachio' },
    @{ say = 'My favourite tea is genmaicha.';                 ask = 'What is my favourite tea?';           expect = 'genmaicha';     word = 'genmaicha' }
)
$words = @($facts | ForEach-Object { $_.word }) + @('Rosalind')

$beforeMem = @(Memories | ForEach-Object { $_.id })
$beforeChats = @((Api GET '/api/v1/chats/?page=1') | ForEach-Object { $_.id })
$results = New-Object System.Collections.ArrayList
function Result($name, $ok, $detail) { [void]$results.Add([pscustomobject]@{ Test = $name; Result = $(if ($ok) { 'PASS' } else { 'FAIL' }); Detail = $detail }) }

try {
    # 1. Tell the five facts in one conversation.
    Write-Output "Telling 5 facts in one conversation (run tag $tag)..."
    $conv = New-Object System.Collections.ArrayList
    foreach ($f in $facts) {
        [void]$conv.Add(@{ role = 'user'; content = "($tag) $($f.say)" })
        $reply = Ask $conv
        [void]$conv.Add(@{ role = 'assistant'; content = $reply })
    }
    Start-Sleep -Seconds 2
    $new = @(Memories | Where-Object { $beforeMem -notcontains $_.id })
    Result 'facts saved as memories' ($new.Count -ge 5) "$($new.Count) new memories"

    # 2. Ask about each in a fresh conversation.
    foreach ($f in $facts) {
        $reply = Ask @(@{ role = 'user'; content = "($tag) $($f.ask)" })
        Result "recall: $($f.word)" ($reply -match $f.expect) ($reply.Substring(0, [Math]::Min(80, $reply.Length)).Replace("`n", ' '))
    }

    # 3. Correction.
    $null = Ask @(@{ role = 'user'; content = "($tag) Actually, my sister is called Rosalind, not Marguerite." })
    Start-Sleep -Seconds 2
    $mem = Memories
    $oldLeft = @($mem | Where-Object { $_.content -match 'Marguerite' -and $_.content -notmatch 'Rosalind' })
    $reply = Ask @(@{ role = 'user'; content = "($tag) What is my sister called?" })
    Result 'correction: new name recalled' ($reply -match 'Rosalind') ($reply.Substring(0, [Math]::Min(80, $reply.Length)).Replace("`n", ' '))
    Result 'correction: old fact gone' ($oldLeft.Count -eq 0) "$($oldLeft.Count) memories still say Marguerite alone"

    # 4. Forget.
    $null = Ask @(@{ role = 'user'; content = "($tag) Forget that I am allergic to pistachios." })
    Start-Sleep -Seconds 2
    $left = @(Memories | Where-Object { $_.content -match 'pistachio' })
    Result 'forget: memory removed' ($left.Count -eq 0) "$($left.Count) memories still mention pistachios"
}
finally {
    # Clean up: only memories new since the start that mention a test word; only chats containing the tag.
    $removedMem = 0; $leftover = @()
    foreach ($m in @(Memories | Where-Object { $beforeMem -notcontains $_.id })) {
        $hit = $false; foreach ($w in $words) { if ($m.content -match [regex]::Escape($w)) { $hit = $true } }
        if ($hit -and -not $KeepData) { try { $null = Api DELETE "/api/v1/memories/$($m.id)"; $removedMem++ } catch { $leftover += $m.content } }
        elseif (-not $hit) { $leftover += $m.content }
    }
    $removedChats = 0
    foreach ($c in @((Api GET '/api/v1/chats/?page=1') | Where-Object { $beforeChats -notcontains $_.id })) {
        try {
            $full = Api GET "/api/v1/chats/$($c.id)"
            if (($full | ConvertTo-Json -Depth 20 -Compress) -match [regex]::Escape($tag)) { $null = Api DELETE "/api/v1/chats/$($c.id)"; $removedChats++ }
        } catch { }
    }
    Write-Output "Cleanup: deleted $removedMem test memories and $removedChats test chats."
    if ($leftover.Count) { Write-Output "Left alone ($($leftover.Count) new memories that are not clearly from this test): $($leftover -join ' | ')" }
}

$results | Format-Table -AutoSize | Out-String -Width 200 | Write-Output
$pass = @($results | Where-Object { $_.Result -eq 'PASS' }).Count
Write-Output "RESULT: $pass of $($results.Count) passed"
if ($pass -ne $results.Count) { exit 1 }
