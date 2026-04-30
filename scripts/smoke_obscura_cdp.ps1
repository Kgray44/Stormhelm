param(
    [string]$Url = "",
    [string]$Config = "",
    [string]$Output = "",
    [switch]$RequireCompatible
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$srcPath = Join-Path $RepoRoot "src"
$existingPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
if ([string]::IsNullOrWhiteSpace($existingPythonPath)) {
    $env:PYTHONPATH = $srcPath
} else {
    $env:PYTHONPATH = "$srcPath;$existingPythonPath"
}

Write-Host "Stormhelm Obscura CDP smoke probe"
Write-Host "CDP mode is optional and disabled by default. Configure web_retrieval.obscura.cdp.* before expecting ready compatibility."
Write-Host "The probe binds only to localhost and cleans up the Obscura process it starts."

$argsList = @("-m", "stormhelm.core.web_retrieval.obscura_cdp_probe")
if (-not [string]::IsNullOrWhiteSpace($Config)) {
    $argsList += @("--config", $Config)
}
if (-not [string]::IsNullOrWhiteSpace($Url)) {
    $argsList += @("--url", $Url)
}
if (-not [string]::IsNullOrWhiteSpace($Output)) {
    $argsList += @("--output", $Output)
}
if ($RequireCompatible) {
    $argsList += "--require-compatible"
}

python @argsList
