param(
    [switch]$Enable,
    [switch]$Obscura,
    [switch]$ObscuraCdp,
    [switch]$Playwright,
    [switch]$AllowPlaywrightBrowserLaunch,
    [switch]$Strict,
    [string]$Url = "",
    [string]$ObscuraBinary = "",
    [string]$Config = "",
    [string]$Output = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not $Output) {
    $Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $Output = Join-Path $RepoRoot "reports\live_browser_integration\live-browser-$Stamp.json"
}

if ($Enable) {
    $env:STORMHELM_LIVE_BROWSER_TESTS = "true"
}
if ($Obscura) {
    $env:STORMHELM_ENABLE_LIVE_OBSCURA = "true"
}
if ($ObscuraCdp) {
    $env:STORMHELM_ENABLE_LIVE_OBSCURA_CDP = "true"
}
if ($Playwright) {
    $env:STORMHELM_ENABLE_LIVE_PLAYWRIGHT = "true"
}
if ($AllowPlaywrightBrowserLaunch) {
    $env:STORMHELM_PLAYWRIGHT_ALLOW_BROWSER_LAUNCH = "true"
}
if ($Url) {
    $env:STORMHELM_LIVE_BROWSER_TEST_URL = $Url
}
if ($ObscuraBinary) {
    $env:STORMHELM_OBSCURA_BINARY = $ObscuraBinary
}
elseif (-not $env:STORMHELM_OBSCURA_BINARY) {
    $UserObscuraBinary = [Environment]::GetEnvironmentVariable("STORMHELM_OBSCURA_BINARY", "User")
    if ($UserObscuraBinary) {
        $env:STORMHELM_OBSCURA_BINARY = $UserObscuraBinary
    }
}

$env:PYTHONPATH = Join-Path $RepoRoot "src"

Write-Host "Stormhelm live browser checks are opt-in."
Write-Host "Master gate STORMHELM_LIVE_BROWSER_TESTS=$($env:STORMHELM_LIVE_BROWSER_TESTS)"
Write-Host "Obscura CLI gate STORMHELM_ENABLE_LIVE_OBSCURA=$($env:STORMHELM_ENABLE_LIVE_OBSCURA)"
Write-Host "Obscura CDP gate STORMHELM_ENABLE_LIVE_OBSCURA_CDP=$($env:STORMHELM_ENABLE_LIVE_OBSCURA_CDP)"
Write-Host "Playwright gate STORMHELM_ENABLE_LIVE_PLAYWRIGHT=$($env:STORMHELM_ENABLE_LIVE_PLAYWRIGHT)"
Write-Host "Playwright launch gate STORMHELM_PLAYWRIGHT_ALLOW_BROWSER_LAUNCH=$($env:STORMHELM_PLAYWRIGHT_ALLOW_BROWSER_LAUNCH)"
Write-Host "Actions, cookies, login context, and visible-screen verification remain disabled."

$ArgsList = @("-m", "stormhelm.core.live_browser_integration", "--output", $Output)
if ($Config) {
    $ArgsList += @("--config", $Config)
}
if ($Url) {
    $ArgsList += @("--url", $Url)
}
if ($Strict) {
    $ArgsList += "--strict"
}

python @ArgsList
$ExitCode = $LASTEXITCODE
Write-Host "Live browser integration report: $Output"
exit $ExitCode
