param(
    [switch]$CheckOnly,
    [switch]$InstallPlaywrightPackage,
    [switch]$InstallPlaywrightChromium,
    [switch]$InstallObscura,
    [switch]$DownloadLatestObscuraRelease,
    [string]$ObscuraZipPath = "",
    [string]$ObscuraReleaseUrl = "",
    [string]$ObscuraAssetName = "",
    [string]$ObscuraReleaseTag = "",
    [string]$ObscuraInstallDir = "",
    [switch]$SetStormhelmObscuraBinary,
    [switch]$AddObscuraToUserPath,
    [switch]$Force,
    [string]$ObscuraBinaryPath = "",
    [string]$ReportPath = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not $ReportPath) {
    $ReportPath = Join-Path $RepoRoot "reports\live_browser_integration\addition-2.6-checkonly-dependencies.json"
}

function Resolve-CommandOrPath {
    param([string]$Value)
    if (-not $Value) {
        return ""
    }
    if ($Value.Contains("\") -or $Value.Contains("/") -or ($Value.Length -gt 1 -and $Value.Substring(1, 1) -eq ":")) {
        if (Test-Path -LiteralPath $Value) {
            return (Resolve-Path -LiteralPath $Value).Path
        }
        return ""
    }
    $Command = Get-Command $Value -ErrorAction SilentlyContinue
    if ($Command) {
        return $Command.Source
    }
    return ""
}

function Invoke-PythonJson {
    param(
        [string]$Python,
        [string]$Code
    )
    try {
        $Output = & $Python -c $Code 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $Output) {
            return @{}
        }
        return ($Output | Select-Object -First 1 | ConvertFrom-Json)
    }
    catch {
        return @{}
    }
}

function Get-DefaultObscuraInstallDir {
    if ($env:LOCALAPPDATA) {
        return (Join-Path $env:LOCALAPPDATA "Stormhelm\tools\obscura")
    }
    return (Join-Path $RepoRoot ".local\tools\obscura")
}

function Get-ObscuraBinaryCandidates {
    param([string]$Directory)
    if (-not $Directory -or -not (Test-Path -LiteralPath $Directory)) {
        return @()
    }
    $Names = @("obscura.exe", "obscura.cmd", "obscura.bat", "obscura")
    $Candidates = @()
    foreach ($Name in $Names) {
        $Candidates += @(Get-ChildItem -LiteralPath $Directory -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -ieq $Name })
    }
    return @($Candidates | Sort-Object FullName -Unique)
}

function Resolve-ObscuraBinaryInDir {
    param([string]$Directory)
    $Candidates = @(Get-ObscuraBinaryCandidates $Directory)
    if ($Candidates.Count -eq 0) {
        return @{ path = ""; count = 0; ambiguous = $false }
    }
    $Ranked = @(
        $Candidates | ForEach-Object {
            $ExtensionWeight = if ($_.Extension -ieq ".exe") { 0 } elseif ($_.Extension -ieq ".cmd") { 10 } elseif ($_.Extension -ieq ".bat") { 20 } else { 30 }
            $Relative = $_.FullName.Substring((Resolve-Path -LiteralPath $Directory).Path.Length).TrimStart("\", "/")
            [pscustomobject]@{
                FullName = $_.FullName
                Score = (($Relative -split "[\\/]").Count * 100) + $ExtensionWeight
            }
        } | Sort-Object Score, FullName
    )
    $Best = $Ranked | Select-Object -First 1
    $Ties = @($Ranked | Where-Object { $_.Score -eq $Best.Score })
    if ($Ties.Count -gt 1) {
        return @{ path = ""; count = $Candidates.Count; ambiguous = $true }
    }
    return @{ path = $Best.FullName; count = $Candidates.Count; ambiguous = $false }
}

function Get-BoundedText {
    param(
        [object]$Value,
        [int]$Limit = 500
    )
    $Text = [string]($Value -join "`n")
    $Text = $Text -replace "(?i)(password|token|api[_-]?key)=([^&\s]+)", '$1=[redacted]'
    if ($Text.Length -le $Limit) {
        return $Text
    }
    return $Text.Substring(0, [Math]::Max(0, $Limit - 3)) + "..."
}

function Test-ObscuraVersion {
    param([string]$BinaryPath)
    if (-not $BinaryPath -or -not (Test-Path -LiteralPath $BinaryPath)) {
        return @{
            status = "binary_missing"
            output = ""
            executable = $false
        }
    }
    try {
        $PreviousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $Output = & $BinaryPath --version 2>&1
        $ExitCode = $LASTEXITCODE
        $ErrorActionPreference = $PreviousErrorActionPreference
        $Bounded = Get-BoundedText $Output
        if ($ExitCode -eq 0 -and $Bounded) {
            return @{
                status = "supported"
                output = $Bounded
                executable = $true
            }
        }
        return @{
            status = "version_unknown"
            output = $Bounded
            executable = $true
        }
    }
    catch {
        if ($PreviousErrorActionPreference) {
            $ErrorActionPreference = $PreviousErrorActionPreference
        }
        return @{
            status = "binary_not_executable"
            output = Get-BoundedText $_.Exception.Message
            executable = $false
        }
    }
}

function Add-DirectoryToUserPath {
    param([string]$Directory)
    if (-not $Directory) {
        return $false
    }
    $Current = [Environment]::GetEnvironmentVariable("Path", "User")
    $Parts = @()
    if ($Current) {
        $Parts = $Current.Split(";") | Where-Object { $_ }
    }
    if ($Parts | Where-Object { $_ -ieq $Directory }) {
        return $false
    }
    $Next = (@($Parts) + $Directory) -join ";"
    [Environment]::SetEnvironmentVariable("Path", $Next, "User")
    return $true
}

function Invoke-ObscuraReleaseSelection {
    param(
        [string]$ReleaseUrl = "",
        [string]$ReleaseTag = "",
        [string]$AssetName = ""
    )
    if (-not $PythonAvailable) {
        return @{
            status = "failed"
            error_code = "python_missing"
            bounded_error_message = "Python is required for official Obscura release discovery in this helper."
            obscura_release_repo = "h4ckf0r0day/obscura"
            checksum_status = "unavailable"
        }
    }
    $env:PYTHONPATH = Join-Path $RepoRoot "src"
    $Args = @("-m", "stormhelm.core.live_browser_dependencies")
    if ($ReleaseUrl) {
        $Args += @("--release-url", $ReleaseUrl)
    }
    if ($ReleaseTag) {
        $Args += @("--release-tag", $ReleaseTag)
    }
    if ($AssetName) {
        $Args += @("--asset-name", $AssetName)
    }
    try {
        $Output = & $PythonPath @Args 2>&1
        if ($LASTEXITCODE -ne 0 -or -not $Output) {
            return @{
                status = "failed"
                error_code = "release_discovery_failed"
                bounded_error_message = Get-BoundedText $Output
                obscura_release_repo = "h4ckf0r0day/obscura"
                checksum_status = "unavailable"
            }
        }
        return ($Output | Select-Object -First 1 | ConvertFrom-Json)
    }
    catch {
        return @{
            status = "failed"
            error_code = "release_discovery_failed"
            bounded_error_message = Get-BoundedText $_.Exception.Message
            obscura_release_repo = "h4ckf0r0day/obscura"
            checksum_status = "unavailable"
        }
    }
}

function Invoke-ObscuraSetup {
    $InstallDir = if ($ObscuraInstallDir) { $ObscuraInstallDir } else { Get-DefaultObscuraInstallDir }
    $UserObscuraBinary = [Environment]::GetEnvironmentVariable("STORMHELM_OBSCURA_BINARY", "User")
    $BinaryInput = if ($ObscuraBinaryPath) { $ObscuraBinaryPath } elseif ($env:STORMHELM_OBSCURA_BINARY) { $env:STORMHELM_OBSCURA_BINARY } elseif ($UserObscuraBinary) { $UserObscuraBinary } else { "obscura" }
    $Resolved = Resolve-CommandOrPath $BinaryInput
    $InstallMode = if ($Resolved) { "existing_path" } else { "skipped" }
    $InstallStatus = if ($Resolved) { "present" } else { "not_found" }
    $ErrorCode = if ($Resolved) { "" } else { "binary_missing" }
    $Message = if ($Resolved) { "" } else { "Obscura binary was not found." }
    $ReleaseUrlDisplay = Get-BoundedText $ObscuraReleaseUrl
    $ZipDisplay = Get-BoundedText $ObscuraZipPath
    $ReleaseRepo = "h4ckf0r0day/obscura"
    $ReleaseTag = ""
    $ReleaseName = ""
    $AssetName = ""
    $AssetUrl = ""
    $ChecksumStatus = "unavailable"
    $DownloadAttempted = $false
    $DownloadStatus = "not_requested"
    $DownloadPath = ""
    $ExtractionStatus = "not_requested"
    $BinaryCandidatesFound = 0
    $SetEnvHint = ""

    if ($InstallObscura) {
        $InstallStatus = "failed"
        $Resolved = ""
        $ErrorCode = ""
        $Message = ""
        $ExistingBinary = Resolve-ObscuraBinaryInDir $InstallDir
        if ((Test-Path -LiteralPath $InstallDir) -and -not $Force) {
            if ($ExistingBinary.path) {
                $Resolved = $ExistingBinary.path
                $BinaryCandidatesFound = [int]$ExistingBinary.count
                $InstallMode = "existing_path"
                $InstallStatus = "existing_binary_found"
                $DownloadStatus = "skipped_existing_binary"
                $ExtractionStatus = "skipped_existing_binary"
                $ErrorCode = ""
                $Message = ""
            }
            elseif (@(Get-ChildItem -LiteralPath $InstallDir -Force -ErrorAction SilentlyContinue).Count -gt 0) {
                $InstallMode = "existing_install_dir"
                $ErrorCode = "install_dir_exists_requires_force"
                $Message = "Obscura install directory already exists and is not empty; pass -Force to overwrite."
            }
        }
        if (-not $Resolved -and -not $ErrorCode -and $ExistingBinary.ambiguous) {
            $ErrorCode = "multiple_binaries_matched"
            $Message = "Multiple Obscura binaries matched in the install directory."
            $BinaryCandidatesFound = [int]$ExistingBinary.count
        }
        if (-not $Resolved -and -not $ErrorCode -and $ObscuraZipPath) {
            $InstallMode = "local_zip"
            if (-not (Test-Path -LiteralPath $ObscuraZipPath)) {
                $ErrorCode = "zip_missing"
                $Message = "Obscura zip path does not exist."
            }
            else {
                try {
                    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
                    Expand-Archive -LiteralPath $ObscuraZipPath -DestinationPath $InstallDir -Force
                    $ExtractionStatus = "extracted"
                    $ResolvedInfo = Resolve-ObscuraBinaryInDir $InstallDir
                    $Resolved = $ResolvedInfo.path
                    $BinaryCandidatesFound = [int]$ResolvedInfo.count
                    if ($Resolved) {
                        $InstallStatus = "installed"
                        $ErrorCode = ""
                        $Message = ""
                    }
                    elseif ($ResolvedInfo.ambiguous) {
                        $ErrorCode = "multiple_binaries_matched"
                        $Message = "Multiple Obscura binaries matched after extraction."
                    }
                    else {
                        $ErrorCode = "binary_missing_after_extract"
                        $Message = "No obscura executable was found after extraction."
                    }
                }
                catch {
                    $ErrorCode = "zip_extract_failed"
                    $Message = $_.Exception.Message
                }
            }
        }
        elseif (-not $Resolved -and -not $ErrorCode -and ($ObscuraReleaseUrl -or $DownloadLatestObscuraRelease)) {
            $InstallMode = "release_url"
            $Selection = if ($ObscuraReleaseUrl) {
                Invoke-ObscuraReleaseSelection -ReleaseUrl $ObscuraReleaseUrl
            }
            else {
                $InstallMode = "official_release"
                Invoke-ObscuraReleaseSelection -ReleaseTag $ObscuraReleaseTag -AssetName $ObscuraAssetName
            }
            $ReleaseRepo = [string]($Selection.obscura_release_repo)
            $ReleaseTag = [string]($Selection.obscura_release_tag)
            $ReleaseName = [string]($Selection.obscura_release_name)
            $AssetName = [string]($Selection.obscura_asset_name)
            $AssetUrl = [string]($Selection.obscura_asset_url_redacted_or_bounded)
            $ChecksumStatus = [string]($Selection.checksum_status)
            $ReleaseUrlDisplay = $AssetUrl
            if ($Selection.status -ne "selected") {
                $ErrorCode = [string]($Selection.error_code)
                $Message = [string]($Selection.bounded_error_message)
                $DownloadStatus = "not_attempted"
            }
            else {
                $TempZip = Join-Path ([System.IO.Path]::GetTempPath()) "stormhelm-obscura-$([guid]::NewGuid().ToString('N')).zip"
                try {
                    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
                    $DownloadAttempted = $true
                    $DownloadPath = $TempZip
                    Invoke-WebRequest -Uri $AssetUrl -OutFile $TempZip -UseBasicParsing
                    $DownloadStatus = "downloaded"
                    Expand-Archive -LiteralPath $TempZip -DestinationPath $InstallDir -Force
                    $ExtractionStatus = "extracted"
                    $ResolvedInfo = Resolve-ObscuraBinaryInDir $InstallDir
                    $Resolved = $ResolvedInfo.path
                    $BinaryCandidatesFound = [int]$ResolvedInfo.count
                    if ($Resolved) {
                        $InstallStatus = "installed"
                        $ErrorCode = ""
                        $Message = ""
                    }
                    elseif ($ResolvedInfo.ambiguous) {
                        $ErrorCode = "multiple_binaries_matched"
                        $Message = "Multiple Obscura binaries matched after extraction."
                    }
                    else {
                        $ErrorCode = "binary_missing_after_extract"
                        $Message = "No obscura executable was found after extraction."
                    }
                }
                catch {
                    if ($DownloadStatus -eq "downloaded") {
                        $ErrorCode = "extraction_failed"
                        $ExtractionStatus = "failed"
                    }
                    else {
                        $ErrorCode = "download_failed"
                        $DownloadStatus = "failed"
                    }
                    $Message = $_.Exception.Message
                }
                finally {
                    Remove-Item -LiteralPath $TempZip -Force -ErrorAction SilentlyContinue
                }
            }
        }
        elseif (-not $Resolved -and -not $ErrorCode) {
            $InstallMode = "skipped"
            $ErrorCode = "install_source_missing"
            $Message = "Provide -ObscuraZipPath, -ObscuraReleaseUrl, or -DownloadLatestObscuraRelease with -InstallObscura."
        }
    }

    if (-not $Resolved -and -not $InstallObscura) {
        $Resolved = Resolve-CommandOrPath $BinaryInput
    }
    if ($Resolved -and -not (Test-Path -LiteralPath $Resolved)) {
        $Resolved = ""
    }

    $Version = Test-ObscuraVersion $Resolved
    if ($Resolved -and $Version.status -eq "binary_not_executable") {
        $ErrorCode = "binary_not_executable"
        $Message = $Version.output
    }

    $AddedToPath = $false
    $StormhelmBinarySet = $false
    if ($Resolved) {
        if ($AddObscuraToUserPath) {
            $AddedToPath = Add-DirectoryToUserPath (Split-Path -Parent $Resolved)
        }
        if ($SetStormhelmObscuraBinary) {
            $env:STORMHELM_OBSCURA_BINARY = $Resolved
            [Environment]::SetEnvironmentVariable("STORMHELM_OBSCURA_BINARY", $Resolved, "User")
            $StormhelmBinarySet = $true
            $SetEnvHint = "STORMHELM_OBSCURA_BINARY=$Resolved"
        }
    }

    return @{
        obscura_release_repo = $ReleaseRepo
        obscura_release_tag = $ReleaseTag
        obscura_release_name = $ReleaseName
        obscura_asset_name = $AssetName
        obscura_asset_url_redacted_or_bounded = $AssetUrl
        download_attempted = [bool]$DownloadAttempted
        download_status = $DownloadStatus
        download_path = $DownloadPath
        extraction_status = $ExtractionStatus
        binary_candidates_found = [int]$BinaryCandidatesFound
        checksum_status = $ChecksumStatus
        binary_input = $BinaryInput
        binary_found = [bool]$Resolved
        binary_path = $Resolved
        obscura_binary_path = $Resolved
        install_requested = [bool]$InstallObscura
        install_mode = $InstallMode
        install_dir = $InstallDir
        zip_path = $ZipDisplay
        release_url = $ReleaseUrlDisplay
        added_to_path = [bool]$AddedToPath
        stormhelm_obscura_binary_set = [bool]$StormhelmBinarySet
        set_env_hint = $SetEnvHint
        version_status = $Version.status
        version_output_bounded = $Version.output
        binary_executable = [bool]$Version.executable
        install_status = $InstallStatus
        error_code = $ErrorCode
        bounded_error_message = Get-BoundedText $Message
        install_note = "Install Obscura only with explicit -InstallObscura and a local zip path or release URL. Pass -ObscuraBinary to live checks when avoiding PATH changes."
    }
}

$StartedAt = (Get-Date).ToUniversalTime().ToString("o")
$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
$PythonPath = if ($PythonCommand) { $PythonCommand.Source } else { "" }
$PythonAvailable = [bool]$PythonCommand
$InstallResults = @()

$ObscuraReport = Invoke-ObscuraSetup

if ($PythonAvailable -and $InstallPlaywrightPackage) {
    & $PythonPath -m pip install playwright
    $InstallResults += @{
        name = "playwright_package"
        command = "$PythonPath -m pip install playwright"
        exit_code = $LASTEXITCODE
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Playwright package installation failed with exit code $LASTEXITCODE."
    }
}

if ($PythonAvailable -and $InstallPlaywrightChromium) {
    & $PythonPath -m playwright install chromium
    $InstallResults += @{
        name = "playwright_chromium"
        command = "$PythonPath -m playwright install chromium"
        exit_code = $LASTEXITCODE
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Playwright Chromium installation failed with exit code $LASTEXITCODE."
    }
}

$PlaywrightProbe = @{}
$EngineProbe = @{}
if ($PythonAvailable) {
    $PlaywrightProbe = Invoke-PythonJson $PythonPath "import importlib.util, json; print(json.dumps({'dependency_installed': importlib.util.find_spec('playwright') is not None}))"
    if ($PlaywrightProbe.dependency_installed) {
        $EngineProbe = Invoke-PythonJson $PythonPath "import json; from pathlib import Path; from playwright.sync_api import sync_playwright; p=sync_playwright().start(); exe=p.chromium.executable_path; ok=Path(exe).exists(); p.stop(); print(json.dumps({'chromium_executable_path': str(exe), 'chromium_available': ok}))"
    }
}

$Report = [ordered]@{
    report_id = "live-browser-deps-$([guid]::NewGuid().ToString('N').Substring(0,12))"
    mode = if ($InstallObscura -or $InstallPlaywrightPackage -or $InstallPlaywrightChromium) { "explicit_install" } else { "check_only" }
    started_at = $StartedAt
    completed_at = (Get-Date).ToUniversalTime().ToString("o")
    install_requested = @{
        obscura = [bool]$InstallObscura
        playwright_package = [bool]$InstallPlaywrightPackage
        playwright_chromium = [bool]$InstallPlaywrightChromium
        obscura_auto_install = $false
    }
    install_results = $InstallResults
    python_available = $PythonAvailable
    python_executable = $PythonPath
    obscura = $ObscuraReport
    playwright = @{
        dependency_installed = [bool]$PlaywrightProbe.dependency_installed
        chromium_available = [bool]$EngineProbe.chromium_available
        chromium_executable_path = if ($EngineProbe.chromium_executable_path) { [string]$EngineProbe.chromium_executable_path } else { "" }
        actions_enabled = $false
        uses_user_profile = $false
    }
    safety = @{
        installs_are_explicit_only = $true
        normal_ci_dependency_free = $true
        action_capabilities_disabled = $true
        no_user_browser_profile = $true
        no_obscura_download_without_install_flag = $true
        no_path_mutation_without_explicit_flag = $true
    }
}

$ReportDirectory = Split-Path -Parent $ReportPath
if ($ReportDirectory) {
    New-Item -ItemType Directory -Force -Path $ReportDirectory | Out-Null
}
$Json = $Report | ConvertTo-Json -Depth 10
[System.IO.File]::WriteAllText($ReportPath, $Json, [System.Text.UTF8Encoding]::new($false))
Write-Host $Json
Write-Host "Dependency setup report: $ReportPath"
