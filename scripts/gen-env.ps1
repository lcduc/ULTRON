# Creates compose\.env from compose\.env.example with random secrets, and writes
# monitoring\secrets\* for Prometheus bearer auth. Never prints secret values.
$ErrorActionPreference = 'Stop'
$root       = Split-Path -Parent $PSScriptRoot
$example    = Join-Path $root 'compose\.env.example'
$envFile    = Join-Path $root 'compose\.env'
$secretsDir = Join-Path $root 'monitoring\secrets'
$utf8       = New-Object System.Text.UTF8Encoding($false)

function New-HexSecret([int]$bytes) {
    $buf = New-Object byte[] $bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buf) } finally { $rng.Dispose() }
    return (($buf | ForEach-Object { $_.ToString('x2') }) -join '')
}

function Get-EnvValue([string[]]$lines, [string]$name) {
    foreach ($l in $lines) {
        if ($l -match ('^' + [regex]::Escape($name) + '=(.*)$')) { return $Matches[1].Trim() }
    }
    return $null
}

$written = @()

if (-not (Test-Path -LiteralPath $envFile)) {
    if (-not (Test-Path -LiteralPath $example)) { throw "Missing $example" }
    $llama = New-HexSecret 32
    $values = @{
        'OPENAI_API_KEY'         = $llama
        'LLAMA_API_KEY'          = $llama
        'WEBUI_SECRET_KEY'       = New-HexSecret 32
        'POSTGRES_PASSWORD'      = New-HexSecret 24
        'LITELLM_MASTER_KEY'     = 'sk-' + (New-HexSecret 24)
        'LITELLM_SALT_KEY'       = New-HexSecret 32
        'GRAFANA_ADMIN_PASSWORD' = New-HexSecret 16
    }
    $out = @()
    foreach ($line in [System.IO.File]::ReadAllLines($example)) {
        $replaced = $false
        foreach ($k in $values.Keys) {
            if ($line -match ('^' + [regex]::Escape($k) + '=')) {
                $out += ($k + '=' + $values[$k])
                $replaced = $true
                break
            }
        }
        if (-not $replaced) { $out += $line }
    }
    [System.IO.File]::WriteAllText($envFile, (($out -join "`n") + "`n"), $utf8)
    $written += $envFile
}

# (Re)generate missing secret files from .env
$lines = [System.IO.File]::ReadAllLines($envFile)
if (-not (Test-Path -LiteralPath $secretsDir)) { New-Item -ItemType Directory -Path $secretsDir | Out-Null }
$map = @{
    'llama_api_key'      = 'LLAMA_API_KEY'
    'litellm_master_key' = 'LITELLM_MASTER_KEY'
}
foreach ($f in $map.Keys) {
    $path = Join-Path $secretsDir $f
    if (-not (Test-Path -LiteralPath $path)) {
        $v = Get-EnvValue $lines $map[$f]
        if ([string]::IsNullOrEmpty($v)) { throw ("Variable " + $map[$f] + " is empty in .env") }
        [System.IO.File]::WriteAllText($path, $v, $utf8)
        $written += $path
    }
}

if ($written.Count -eq 0) { Write-Host 'Nothing to do: .env and secret files already exist.' }
else { foreach ($w in $written) { Write-Host ('Wrote ' + $w) } }
