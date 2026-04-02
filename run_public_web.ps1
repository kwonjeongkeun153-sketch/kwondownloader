$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $root ".venv_web\Scripts\python.exe"
$cloudflared = Join-Path $root "cloudflared.exe"
$serverPidFile = Join-Path $root "public_server.pid"
$tunnelPidFile = Join-Path $root "public_tunnel.pid"
$serverLog = Join-Path $root "public_server.log"
$serverErrLog = Join-Path $root "public_server.err.log"
$tunnelLog = Join-Path $root "public_tunnel.log"
$tunnelErrLog = Join-Path $root "public_tunnel.err.log"
$publicUrlFile = Join-Path $root "public_url.txt"

if (-not (Test-Path $venvPython)) {
    Write-Host "Create venv first:" -ForegroundColor Yellow
    Write-Host "  py -3.12 -m venv .venv_web"
    Write-Host "  .\.venv_web\Scripts\python -m pip install -r web_requirements.txt"
    exit 1
}

if (-not (Test-Path $cloudflared)) {
    Write-Host "cloudflared.exe not found in project root." -ForegroundColor Yellow
    Write-Host "Download it first or ask me to set it up again." -ForegroundColor Yellow
    exit 1
}

foreach ($path in @($serverLog, $serverErrLog, $tunnelLog, $tunnelErrLog, $publicUrlFile)) {
    if (Test-Path $path) {
        Remove-Item $path -Force
    }
}

foreach ($pair in @(
    @{ File = $serverPidFile; Name = "server" },
    @{ File = $tunnelPidFile; Name = "tunnel" }
)) {
    if (Test-Path $pair.File) {
        try {
            $pidValue = Get-Content -Raw $pair.File
            if ($pidValue) {
                Stop-Process -Id ([int]$pidValue) -Force -ErrorAction SilentlyContinue
            }
        } catch {
        }
        Remove-Item $pair.File -Force -ErrorAction SilentlyContinue
    }
}

$server = Start-Process -FilePath $venvPython `
    -ArgumentList "-m", "waitress", "--listen=127.0.0.1:8000", "web_app:app" `
    -WorkingDirectory $root `
    -RedirectStandardOutput $serverLog `
    -RedirectStandardError $serverErrLog `
    -WindowStyle Hidden `
    -PassThru

$server.Id | Set-Content -Path $serverPidFile -NoNewline

$healthy = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $response = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8000/api/health"
        if ($response.StatusCode -eq 200) {
            $healthy = $true
            break
        }
    } catch {
    }
}

if (-not $healthy) {
    Write-Host "Local server did not become healthy." -ForegroundColor Red
    if (Test-Path $serverErrLog) {
        Get-Content -Raw $serverErrLog
    }
    exit 1
}

$tunnel = Start-Process -FilePath $cloudflared `
    -ArgumentList "tunnel", "--url", "http://127.0.0.1:8000", "--no-autoupdate" `
    -WorkingDirectory $root `
    -RedirectStandardOutput $tunnelLog `
    -RedirectStandardError $tunnelErrLog `
    -WindowStyle Hidden `
    -PassThru

$tunnel.Id | Set-Content -Path $tunnelPidFile -NoNewline

$publicUrl = $null
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 2

    foreach ($logPath in @($tunnelLog, $tunnelErrLog)) {
        if (-not (Test-Path $logPath)) {
            continue
        }

        $content = Get-Content -Raw $logPath
        if (-not $content) {
            continue
        }

        $match = [regex]::Match($content, 'https://[-a-z0-9]+\.trycloudflare\.com')
        if ($match.Success) {
            $publicUrl = $match.Value
            break
        }
    }

    if ($publicUrl) {
        break
    }
}

if (-not $publicUrl) {
    Write-Host "Tunnel URL was not created." -ForegroundColor Red
    if (Test-Path $tunnelErrLog) {
        Get-Content -Raw $tunnelErrLog
    }
    exit 1
}

$publicUrl | Set-Content -Path $publicUrlFile -NoNewline

Write-Host ""
Write-Host "Public URL:" -ForegroundColor Cyan
Write-Host "  $publicUrl" -ForegroundColor Green
Write-Host ""
Write-Host "Anyone with this link can use the downloader while this PC stays on and these processes keep running." -ForegroundColor Yellow
Write-Host "To stop it later, run: .\stop_public_web.ps1" -ForegroundColor Yellow
