param(
    [string]$InnoCompilerPath = "",
    [switch]$SkipPortableBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Missing virtual environment Python at $Python. Create .venv first."
}

$Version = (& $Python -c "import sys; from pathlib import Path; sys.path.insert(0, str(Path(r'$ProjectRoot') / 'src')); import stormhelm; print(stormhelm.__version__)" | Select-Object -Last 1).Trim()
if (-not $Version) {
    throw "Could not determine Stormhelm version."
}

$PortableDir = Join-Path $ProjectRoot "release\portable\Stormhelm-$Version-windows-x64"
$PortableScript = Join-Path $ProjectRoot "scripts\package_portable.ps1"
$IssPath = Join-Path $ProjectRoot "installer\inno\Stormhelm.iss"

if (-not $SkipPortableBuild) {
    & powershell -ExecutionPolicy Bypass -File $PortableScript
    if ($LASTEXITCODE -ne 0) {
        throw "Portable build step failed."
    }
}

if (-not (Test-Path $PortableDir)) {
    throw "Portable release folder not found at $PortableDir."
}

if (-not $InnoCompilerPath) {
    $CandidatePaths = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
    )
    foreach ($Candidate in $CandidatePaths) {
        if ($Candidate -and (Test-Path $Candidate)) {
            $InnoCompilerPath = $Candidate
            break
        }
    }
}

if (-not $InnoCompilerPath) {
    Write-Host "Portable build is ready at: $PortableDir"
    Write-Host "Inno Setup was not found automatically."
    Write-Host "Later installer step:"
    Write-Host "  ISCC.exe /DMyAppVersion=$Version /DSourceDir=""$PortableDir"" ""$IssPath"""
    return
}

Write-Host "Compiling Inno Setup installer..."
& $InnoCompilerPath "/DMyAppVersion=$Version" "/DSourceDir=$PortableDir" $IssPath
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compilation failed."
}
