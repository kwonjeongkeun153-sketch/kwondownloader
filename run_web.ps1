$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $root ".venv_web\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "Create venv first:" -ForegroundColor Yellow
    Write-Host "  py -3.12 -m venv .venv_web"
    Write-Host "  .\.venv_web\Scripts\python -m pip install -r web_requirements.txt"
    exit 1
}

& $venvPython "$root\web_app.py"
