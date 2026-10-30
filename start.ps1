$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "==> Where2Invest local start" -ForegroundColor Cyan

if (-not (Test-Path "$Root\.venv")) {
  Write-Host "Creating venv..."
  python -m venv .venv
}

& "$Root\.venv\Scripts\python.exe" -m pip install -U pip
& "$Root\.venv\Scripts\pip.exe" install -r "$Root\backend\requirements.txt"

if (-not (Test-Path "$Root\frontend\node_modules")) {
  Push-Location "$Root\frontend"
  npm install
  Pop-Location
}

$env:PYTHONPATH = "$Root\backend"
Write-Host "Starting API on http://127.0.0.1:8000 ..." -ForegroundColor Green
Start-Process -FilePath "$Root\.venv\Scripts\python.exe" -ArgumentList @(
  "-m", "uvicorn", "app.main:app",
  "--app-dir", "$Root\backend",
  "--host", "127.0.0.1",
  "--port", "8000",
  "--reload"
) -WorkingDirectory $Root

Start-Sleep -Seconds 2
Write-Host "Starting UI on http://127.0.0.1:5173 ..." -ForegroundColor Green
Push-Location "$Root\frontend"
npm run dev -- --host 127.0.0.1 --port 5173
Pop-Location
