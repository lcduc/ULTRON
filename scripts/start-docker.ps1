# Starts Docker Desktop after moving aside stale socket folders.
# On this PC, sockets left over from a previous Docker run cannot be removed by
# Docker itself ("The file cannot be accessed by the system"), which crashes it
# at startup. Renaming the parent folder works, so do that before every launch.

$ErrorActionPreference = 'Continue'

$engineUp = $false
$job = Start-Job { docker version --format '{{.Server.Version}}' 2>$null; $LASTEXITCODE }
if (Wait-Job $job -Timeout 8) {
    $out = @(Receive-Job $job)
    if ($out.Count -gt 0 -and $out[-1] -eq 0) { $engineUp = $true }
} else {
    Stop-Job $job
}
Remove-Job $job -Force -ErrorAction SilentlyContinue

if ($engineUp) {
    Write-Output "Docker engine already running."
    exit 0
}

Get-Process | Where-Object { $_.Name -match '^Docker Desktop$|^com\.docker\.' } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

$socketDirs = @(
    (Join-Path $env:LOCALAPPDATA 'Docker\run'),
    (Join-Path $env:LOCALAPPDATA 'docker-secrets-engine')
)
$stamp = Get-Date -Format yyyyMMddHHmmss
foreach ($dir in $socketDirs) {
    if (Test-Path -LiteralPath $dir) {
        $leaf = Split-Path $dir -Leaf
        try {
            Rename-Item -LiteralPath $dir -NewName "$leaf.stale-$stamp" -ErrorAction Stop
            Write-Output "Moved aside: $dir"
        } catch {
            Write-Output "Could not move $dir : $($_.Exception.Message)"
        }
    }
    # Best-effort removal of older stale copies (may fail; they are empty files).
    $parent = Split-Path $dir -Parent
    $leaf = Split-Path $dir -Leaf
    Get-ChildItem -LiteralPath $parent -Directory -Filter "$leaf.stale-*" -ErrorAction SilentlyContinue |
        ForEach-Object { cmd /c rd /s /q "`"$($_.FullName)`"" 2>$null | Out-Null }
}

$exe = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
Start-Process $exe
Write-Output "Docker Desktop launch requested; waiting for engine..."

for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 5
    $job = Start-Job { docker version --format '{{.Server.Version}}' 2>$null; $LASTEXITCODE }
    if (Wait-Job $job -Timeout 8) {
        $out = @(Receive-Job $job)
        Remove-Job $job -Force -ErrorAction SilentlyContinue
        if ($out.Count -gt 1 -and $out[-1] -eq 0) {
            Write-Output "Docker engine up: $($out[0])"
            exit 0
        }
    } else {
        Stop-Job $job
        Remove-Job $job -Force -ErrorAction SilentlyContinue
    }
}
Write-Output "Docker engine did not come up within 5 minutes."
exit 1
