param(
    [switch]$SkipDependencyInstall,
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Missing virtual environment Python at $Python. Create .venv first."
}

$RunId = Get-Date -Format "yyyyMMddHHmmssffff"

$Version = (& $Python -c "import sys; from pathlib import Path; sys.path.insert(0, str(Path(r'$ProjectRoot') / 'src')); import stormhelm; print(stormhelm.__version__)" | Select-Object -Last 1).Trim()
if (-not $Version) {
    throw "Could not determine Stormhelm version."
}

$BuildRoot = Join-Path $ProjectRoot "build\pyinstaller"
$RunRoot = Join-Path $BuildRoot "run-$RunId"
$DistRoot = Join-Path $RunRoot "dist"
$WorkRoot = Join-Path $RunRoot "work"
$TempRoot = Join-Path $RunRoot "temp"
$PyInstallerConfig = Join-Path $RunRoot "config"
$ReleaseRoot = Join-Path $ProjectRoot "release\portable"
$PortableName = "Stormhelm-$Version-windows-x64"
$PortableDir = Join-Path $ReleaseRoot $PortableName
$CoreSpec = Join-Path $ProjectRoot "installer\pyinstaller\stormhelm-core.spec"
$UiSpec = Join-Path $ProjectRoot "installer\pyinstaller\stormhelm-ui.spec"

if (-not $SkipDependencyInstall) {
    Write-Host "Ensuring PyInstaller packaging dependencies are installed..."
    Push-Location $ProjectRoot
    try {
        & $Python -m pip install -e ".[packaging]"
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to install Stormhelm packaging dependencies."
        }
    }
    finally {
        Pop-Location
    }
}

Write-Host "Cleaning previous build outputs..."
if (Test-Path -LiteralPath $PortableDir) {
    try {
        Remove-Item -LiteralPath $PortableDir -Recurse -Force -ErrorAction Stop
    }
    catch {
        throw "Failed to remove previous portable release folder at $PortableDir. Close any processes using files in that folder and try again."
    }
}
New-Item -ItemType Directory -Force -Path $DistRoot, $WorkRoot, $TempRoot, $PyInstallerConfig, $PortableDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $PortableDir "config") | Out-Null

$env:TMP = $TempRoot
$env:TEMP = $TempRoot
$env:TMPDIR = $TempRoot
$env:PYINSTALLER_CONFIG_DIR = $PyInstallerConfig
$env:PIP_BUILD_TRACKER = Join-Path $TempRoot "pip-build-tracker"
New-Item -ItemType Directory -Force -Path $env:PIP_BUILD_TRACKER | Out-Null

Write-Host "Building stormhelm-core.exe..."
Push-Location $ProjectRoot
try {
    & $Python -m PyInstaller --noconfirm --clean --distpath $DistRoot --workpath $WorkRoot $CoreSpec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed while building stormhelm-core.exe."
    }
    Write-Host "Building stormhelm-ui.exe..."
    & $Python -m PyInstaller --noconfirm --clean --distpath $DistRoot --workpath $WorkRoot $UiSpec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed while building stormhelm-ui.exe."
    }
}
finally {
    Pop-Location
}

$CoreExe = Join-Path $DistRoot "stormhelm-core.exe"
$UiExe = Join-Path $DistRoot "stormhelm-ui.exe"
if (-not (Test-Path $CoreExe)) {
    throw "Expected packaged core executable at $CoreExe."
}
if (-not (Test-Path $UiExe)) {
    throw "Expected packaged UI executable at $UiExe."
}

Write-Host "Assembling portable release at $PortableDir..."
Copy-Item -LiteralPath $CoreExe -Destination (Join-Path $PortableDir "stormhelm-core.exe")
Copy-Item -LiteralPath $UiExe -Destination (Join-Path $PortableDir "stormhelm-ui.exe")
Copy-Item -LiteralPath (Join-Path $ProjectRoot "README.md") -Destination (Join-Path $PortableDir "README.md")
Copy-Item -LiteralPath (Join-Path $ProjectRoot "LICENSE") -Destination (Join-Path $PortableDir "LICENSE")
Copy-Item -LiteralPath (Join-Path $ProjectRoot "config\default.toml") -Destination (Join-Path $PortableDir "config\default.toml")
Copy-Item -LiteralPath (Join-Path $ProjectRoot "config\development.toml.example") -Destination (Join-Path $PortableDir "config\portable.toml.example")

$BuildInfo = @{
    app_name = "Stormhelm"
    version = $Version
    built_at = (Get-Date).ToString("s")
    portable_root = $PortableDir
    binaries = @("stormhelm-ui.exe", "stormhelm-core.exe")
} | ConvertTo-Json -Depth 4
$BuildInfo | Set-Content -Path (Join-Path $PortableDir "BUILD-INFO.json") -Encoding UTF8

$Launcher = @"
@echo off
start "" "%~dp0stormhelm-ui.exe"
"@
$Launcher | Set-Content -Path (Join-Path $PortableDir "Launch Stormhelm.bat") -Encoding ASCII

if (-not $SkipZip) {
    $ZipPath = Join-Path $ReleaseRoot "$PortableName.zip"
    if (Test-Path -LiteralPath $ZipPath) {
        try {
            Remove-Item -LiteralPath $ZipPath -Force -ErrorAction Stop
        }
        catch {
            throw "Failed to remove previous portable archive at $ZipPath. Close any processes using that file and try again."
        }
    }
    Compress-Archive -Path (Join-Path $PortableDir "*") -DestinationPath $ZipPath
    Write-Host "Created portable zip: $ZipPath"
}

Write-Host ""
Write-Host "Portable build ready:"
Write-Host "  $PortableDir"
