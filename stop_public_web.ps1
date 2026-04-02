$ErrorActionPreference = "SilentlyContinue"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$serverPidFile = Join-Path $root "public_server.pid"
$tunnelPidFile = Join-Path $root "public_tunnel.pid"

foreach ($pidFile in @($tunnelPidFile, $serverPidFile)) {
    if (-not (Test-Path $pidFile)) {
        continue
    }

    try {
        $pidValue = Get-Content -Raw $pidFile
        if ($pidValue) {
            Stop-Process -Id ([int]$pidValue) -Force
        }
    } catch {
    }

    Remove-Item $pidFile -Force
}

Write-Host "Public web app processes stopped."
