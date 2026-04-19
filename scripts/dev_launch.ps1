param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Missing virtual environment Python at $Python. Create .venv first."
}

$env:PYTHONPATH = Join-Path $ProjectRoot "src"
Write-Host "Starting Stormhelm UI with the workspace virtual environment. The UI will launch the core if needed."
& $Python -m stormhelm.entrypoints.ui
