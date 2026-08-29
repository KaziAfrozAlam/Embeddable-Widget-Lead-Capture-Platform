# One-command local run on Windows: deps -> migrate -> seed -> API / worker.
# Usage:  .\run.ps1             (server only)
#         .\run.ps1 -Worker     (background-job worker only)
param(
    [switch]$Worker
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    python -m venv .venv
    & ".\.venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt -r requirements-dev.txt
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[run] created .env from .env.example - edit SECRET_KEY!" -ForegroundColor Yellow
}

& ".\.venv\Scripts\python.exe" -m alembic upgrade head

if ($Worker) {
    & ".\.venv\Scripts\python.exe" -m app.services.worker
    exit $LASTEXITCODE
}

& ".\.venv\Scripts\python.exe" -m app.seed | Out-Null
Write-Host "[run] API on http://localhost:8000  (healthz: http://localhost:8000/healthz)" -ForegroundColor Green
Write-Host "[run] customer site on a different origin:" -ForegroundColor Green
Write-Host '      .\.venv\Scripts\python -m http.server 5500 --directory website      ->  http://localhost:5500/customer-site.html'
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port $env:PORT
exit $LASTEXITCODE