# Tool-calling and thinking checks against any OpenAI-compatible endpoint.
param(
    [string]$Url = 'http://127.0.0.1:8080',
    [string]$Model = 'ultron',
    [string]$KeyFile = ''
)
$ProgressPreference = 'SilentlyContinue'
$h = @{}
if ($KeyFile) { $h.Authorization = 'Bearer ' + [IO.File]::ReadAllText($KeyFile).Trim() }

function Post($obj) {
    $bytes = [Text.Encoding]::UTF8.GetBytes(($obj | ConvertTo-Json -Depth 12))
    $r = Invoke-WebRequest "$Url/v1/chat/completions" -Method Post -Headers $h `
        -ContentType 'application/json; charset=utf-8' -Body $bytes -TimeoutSec 600 -UseBasicParsing
    [Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray()) | ConvertFrom-Json
}
function Fn($name, $desc, $props, $req) {
    @{ type = 'function'; function = @{ name = $name; description = $desc; parameters = @{ type = 'object'; properties = $props; required = $req } } }
}
$tools = @(
    (Fn 'web_search' 'Search the web and return result snippets.' @{ query = @{ type = 'string' } } @('query')),
    (Fn 'get_weather' 'Get current weather for a city.' @{ city = @{ type = 'string' }; unit = @{ type = 'string'; enum = @('c', 'f') } } @('city')),
    (Fn 'run_command' 'Run a shell command in the sandbox and return its output.' @{ command = @{ type = 'string' } } @('command')),
    (Fn 'read_file' 'Read a text file from the workspace.' @{ path = @{ type = 'string' } } @('path'))
)
$off = @{ enable_thinking = $false }
$pass = 0; $total = 0
function Check($name, $ok, $detail) { $script:total++; if ($ok) { $script:pass++ }; "{0}  {1}  {2}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name, $detail }

# 1. right tool, right arguments
$r = Post @{ model = $Model; max_tokens = 300; tools = $tools; chat_template_kwargs = $off
    messages = @(@{ role = 'user'; content = 'What is the weather in Hanoi right now, in celsius?' }) }
$tc = $r.choices[0].message.tool_calls
Check 'single tool call' ($tc -and $tc[0].function.name -eq 'get_weather' -and $tc[0].function.arguments -match 'Hanoi') "$($tc[0].function.name) $($tc[0].function.arguments)"

# 2. no tool when none is needed
$r = Post @{ model = $Model; max_tokens = 80; tools = $tools; chat_template_kwargs = $off
    messages = @(@{ role = 'user'; content = 'What is 17 times 3? Answer with just the number.' }) }
Check 'no tool for simple maths' (-not $r.choices[0].message.tool_calls -and "$($r.choices[0].message.content)" -match '51') "$($r.choices[0].message.content)".Trim()

# 3. simulated 4-step chain: the harness feeds back tool results; the model must keep going and finish
$msgs = New-Object System.Collections.ArrayList
[void]$msgs.Add(@{ role = 'system'; content = 'You are an agent working in a sandbox. Use the tools to complete the task, one step at a time. When the task is done, reply with a short summary and no tool call.' })
[void]$msgs.Add(@{ role = 'user'; content = 'A service runs on http://localhost:8188. Find out which API routes it offers (it serves a route list at /routes), then check its /system_stats route, then tell me how much VRAM is free.' })
$fake = @{
    routes = '["/prompt","/history","/system_stats","/object_info","/free"]'
    stats  = '{"devices":[{"name":"cuda:0","vram_total":12884901888,"vram_free":3221225472}]}'
}
$steps = 0; $sawRoutes = $false; $sawStats = $false; $final = ''
for ($i = 0; $i -lt 6; $i++) {
    $r = Post @{ model = $Model; max_tokens = 400; tools = $tools; chat_template_kwargs = $off; messages = $msgs }
    $m = $r.choices[0].message
    if (-not $m.tool_calls) { $final = "$($m.content)"; break }
    $steps++
    $c = $m.tool_calls[0]
    [void]$msgs.Add(@{ role = 'assistant'; content = ''; tool_calls = @(@{ id = $c.id; type = 'function'; function = @{ name = $c.function.name; arguments = $c.function.arguments } }) })
    $a = $c.function.arguments
    $out = if ($a -match 'system_stats') { $sawStats = $true; $fake.stats } elseif ($a -match '/routes') { $sawRoutes = $true; $fake.routes } else { 'error: 404 not found' }
    [void]$msgs.Add(@{ role = 'tool'; tool_call_id = $c.id; content = $out })
}
Check 'multi-step chain' ($sawRoutes -and $sawStats -and $final -match '3(\.0+)?\s*G|3221225472|3,221') "steps=$steps routes=$sawRoutes stats=$sawStats final=$($final.Substring(0,[Math]::Min(90,$final.Length)).Replace("`n",' '))"

# 4. recovers from a tool error
$r1 = Post @{ model = $Model; max_tokens = 300; tools = $tools; chat_template_kwargs = $off
    messages = @(@{ role = 'user'; content = 'Read the file config.yaml in the workspace and tell me the port it sets.' }) }
$c = $r1.choices[0].message.tool_calls[0]
if ($c) {
    $r2 = Post @{ model = $Model; max_tokens = 300; tools = $tools; chat_template_kwargs = $off; messages = @(
        @{ role = 'user'; content = 'Read the file config.yaml in the workspace and tell me the port it sets.' },
        @{ role = 'assistant'; content = ''; tool_calls = @(@{ id = $c.id; type = 'function'; function = @{ name = $c.function.name; arguments = $c.function.arguments } }) },
        @{ role = 'tool'; tool_call_id = $c.id; content = 'error: config.yaml not found. Files in workspace: config.yml, README.md' }) }
    $c2 = $r2.choices[0].message.tool_calls
    Check 'recovers from tool error' ($c2 -and $c2[0].function.arguments -match 'config\.yml') "$($c2[0].function.name) $($c2[0].function.arguments)"
} else { Check 'recovers from tool error' $false 'no first tool call' }

# 5. thinking toggle
$r = Post @{ model = $Model; max_tokens = 1500; chat_template_kwargs = @{ enable_thinking = $true }
    messages = @(@{ role = 'user'; content = 'If 5 machines make 5 widgets in 5 minutes, how long do 100 machines take to make 100 widgets?' }) }
$m = $r.choices[0].message
Check 'thinking on gives a trace and an answer' ("$($m.reasoning_content)".Length -gt 0 -and "$($m.content)" -match '5') "trace=$("$($m.reasoning_content)".Length) chars, tokens=$($r.usage.completion_tokens)"

"RESULT: $pass of $total passed ($Model)"
