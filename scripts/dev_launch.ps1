param()

$ErrorActionPreference = "Stop"
Write-Host "Starting Stormhelm UI. The UI will launch the core if needed."
python -m stormhelm.entrypoints.ui
