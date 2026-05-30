[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$OutputDir = "dist",

    [Parameter(Mandatory = $false)]
    [string]$ReleaseDir = "Releases",

    [Parameter(Mandatory = $false)]
    [string]$Channel = "stable",

    [Parameter(Mandatory = $false)]
    [string]$PackVersion = "",

    [Parameter(Mandatory = $false)]
    [int]$KeepFullVersions = 6,

    [switch]$SkipClean,
    [switch]$SkipSync,
    [switch]$SkipVelopack,
    [switch]$SkipRenameSetup
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Assert-CommandAvailable {
    param(
        [string]$Name,
        [string]$InstallHint
    )

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        throw ("Missing command: {0}. {1}" -f $Name, $InstallHint)
    }
}

function Assert-UvPythonVersion {
    param([string]$MinimumVersion)

    $versionOutput = & uv run python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
    if ($LASTEXITCODE -ne 0) {
        throw ("Failed to resolve uv Python version with exit code {0}" -f $LASTEXITCODE)
    }

    $versionText = [string]$versionOutput
    $currentVersion = [version]$versionText.Trim()
    $requiredVersion = [version]$MinimumVersion
    if ($currentVersion -lt $requiredVersion) {
        throw ("Python {0}+ is required, uv is using {1}." -f $MinimumVersion, $currentVersion)
    }
}

function Resolve-RepoRoot {
    $scriptRoot = $PSScriptRoot
    if ([string]::IsNullOrWhiteSpace($scriptRoot)) {
        $scriptRoot = Split-Path -Parent $PSCommandPath
    }
    return (Resolve-Path (Join-Path $scriptRoot "..")).Path
}

function Get-PackVersion {
    param(
        [string]$RepoRoot,
        [string]$ProvidedVersion
    )

    if (-not [string]::IsNullOrWhiteSpace($ProvidedVersion)) {
        return $ProvidedVersion.Trim()
    }

    $versionFile = Join-Path $RepoRoot "software\app\version.py"
    $versionContent = Get-Content -LiteralPath $versionFile -Raw
    $match = [regex]::Match($versionContent, '__VERSION__\s*=\s*"([^"]+)"')
    if (-not $match.Success) {
        throw ("Failed to resolve version from: {0}" -f $versionFile)
    }
    return $match.Groups[1].Value.Trim()
}

function Get-NuitkaDistDirectory {
    param([string]$BuildRoot)

    $candidates = @(Get-ChildItem -Path $BuildRoot -Directory -Filter "*.dist" -ErrorAction SilentlyContinue)
    if ($candidates.Count -eq 0) {
        throw ("Nuitka output directory not found under: {0}" -f $BuildRoot)
    }
    if ($candidates.Count -gt 1) {
        throw ("Multiple Nuitka output directories found under: {0}" -f $BuildRoot)
    }
    return $candidates[0].FullName
}

function Remove-IfExists {
    param([string]$Path)

    if (Test-Path $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

function Remove-PathsByPattern {
    param(
        [string]$BaseDir,
        [string[]]$Patterns
    )

    foreach ($pattern in $Patterns) {
        Get-ChildItem -Path $BaseDir -Recurse -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like $pattern } |
            ForEach-Object {
                Remove-Item -LiteralPath $_.FullName -Recurse -Force
            }
    }
}

function Remove-ReleaseSetupIfExists {
    param(
        [string]$ReleaseRoot,
        [string[]]$FileNames
    )

    foreach ($fileName in $FileNames) {
        Remove-IfExists -Path (Join-Path $ReleaseRoot $fileName)
    }
}

$repoRoot = Resolve-RepoRoot
$targetRoot = Join-Path $repoRoot $OutputDir
$releaseRoot = Join-Path $repoRoot $ReleaseDir
$buildRoot = Join-Path $repoRoot "build\nuitka"
$nuitkaCacheRoot = Join-Path $repoRoot "build\nuitka-cache"
$nuitkaDistDir = Join-Path $buildRoot "SurveyController.dist"
$packDir = Join-Path $targetRoot "lib"
$mainExe = Join-Path $packDir "SurveyController.exe"
$packVersion = Get-PackVersion -RepoRoot $repoRoot -ProvidedVersion $PackVersion
$setupName = "SurveyController_v$($packVersion)_setup.exe"
$generatedSetupName = "SurveyController-$Channel-Setup.exe"
$expectedSetupName = if ($SkipRenameSetup) { $generatedSetupName } else { $setupName }
$manifestPath = Join-Path $releaseRoot "releases.$Channel.json"

Write-Step "Check environment"
Assert-CommandAvailable -Name "python" -InstallHint "Install Python first and ensure python is available in PATH."
Assert-CommandAvailable -Name "uv" -InstallHint "Install uv first: powershell -ExecutionPolicy ByPass -c ""irm https://astral.sh/uv/install.ps1 | iex"""
Assert-UvPythonVersion -MinimumVersion "3.13.13"

Write-Host ("Repo root: {0}" -f $repoRoot)
Write-Host ("Output dir: {0}" -f $targetRoot)
Write-Host ("Pack dir: {0}" -f $packDir)
Write-Host ("Release dir: {0}" -f $releaseRoot)
Write-Host ("Pack version: {0}" -f $packVersion)
Write-Host ("Nuitka cache dir: {0}" -f $nuitkaCacheRoot)

if (-not $SkipClean) {
    Write-Step "Clean old artifacts"
    foreach ($path in @($buildRoot, $packDir)) {
        if (Test-Path $path) {
            Remove-Item -Recurse -Force $path
        }
    }
}

if (-not $SkipSync) {
    Write-Step "Sync Python dependencies"
    Push-Location $repoRoot
    try {
        uv sync --locked --group build
    }
    finally {
        Pop-Location
    }
}

Write-Step "Build standalone bundle with Nuitka"
New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
New-Item -ItemType Directory -Path $nuitkaCacheRoot -Force | Out-Null
# Pre-create the standalone dist directory before invoking Nuitka to avoid
# Windows short-path lookup failures during early build setup.
New-Item -ItemType Directory -Path $nuitkaDistDir -Force | Out-Null
Push-Location $repoRoot
try {
    $env:NUITKA_CACHE_DIR = $nuitkaCacheRoot
    $env:NUITKA_CACHE_DIR_CLCACHE = Join-Path $nuitkaCacheRoot "clcache"
    $env:NUITKA_CACHE_DIR_DOWNLOADS = Join-Path $nuitkaCacheRoot "downloads"
    $env:NUITKA_CACHE_DIR_BYTECODE = Join-Path $nuitkaCacheRoot "bytecode"
    $env:NUITKA_CACHE_DIR_DLL_DEPENDENCIES = Join-Path $nuitkaCacheRoot "dll-dependencies"

    Write-Host "Nuitka compiler cache: use Nuitka bundled clcache when MSVC is selected" -ForegroundColor DarkGreen

    $nuitkaArgs = @(
        "-m"
        "nuitka"
        "--standalone"
        "--assume-yes-for-downloads"
        "--windows-console-mode=disable"
        "--enable-plugin=pyside6"
        "--enable-plugin=anti-bloat"
        "--python-flag=no_asserts"
        "--python-flag=no_docstrings"
        "--noinclude-pytest-mode=nofollow"
        "--noinclude-setuptools-mode=nofollow"
        "--nofollow-import-to=numpy"
        "--include-qt-plugins=platforms,styles,imageformats,networkinformation,tls"
        "--nofollow-import-to=qfluentwidgets.multimedia"
        "--nofollow-import-to=PySide6.QtMultimedia"
        "--nofollow-import-to=PySide6.QtMultimediaWidgets"
        "--nofollow-import-to=PySide6.QtPdf"
        "--nofollow-import-to=PySide6.QtPdfWidgets"
        "--nofollow-import-to=pytest"
        "--nofollow-import-to=setuptools"
        "--nofollow-import-to=unittest"
        "--include-module=software.ui.shell.main_window"
        "--include-module=wjx.provider.parser"
        "--include-module=wjx.provider.http_runtime"
        "--include-module=tencent.provider.parser"
        "--include-module=tencent.provider.http_runtime"
        "--include-module=tencent.provider.answering_builders"
        "--include-module=tencent.provider.answering_rules"
        "--include-module=credamo.provider.parser"
        "--include-module=credamo.provider.http_runtime"
        "--include-module=win32api"
        "--include-module=win32con"
        "--include-module=win32gui"
        "--include-module=win32print"
        "--include-data-file=assets/icon.png=assets/icon.png"
        "--include-data-file=assets/WeDonate.png=assets/WeDonate.png"
        "--include-data-file=assets/AliDonate.jpg=assets/AliDonate.jpg"
        "--include-data-file=assets/community_qr.png=assets/community_qr.png"
        "--include-data-file=assets/pay_ldxp_favicon.ico=assets/pay_ldxp_favicon.ico"
        "--include-data-file=assets/reverse_fill_example.xlsx=assets/reverse_fill_example.xlsx"
        "--include-data-file=assets/gui.png=assets/gui.png"
        "--include-data-dir=software/assets=software/assets"
        "--include-data-file=software/ui/theme.json=software/ui/theme.json"
        "--include-data-file=icon.ico=icon.ico"
        "--windows-icon-from-ico=icon.ico"
        "--output-dir=$buildRoot"
        "--output-filename=SurveyController.exe"
        "SurveyController.py"
    )
    & uv run python @nuitkaArgs
    if ($LASTEXITCODE -ne 0) {
        throw ("Nuitka build failed with exit code {0}" -f $LASTEXITCODE)
    }
}
finally {
    Pop-Location
}

Write-Step "Move Nuitka bundle into dist/lib"
$compiledDistDir = Get-NuitkaDistDirectory -BuildRoot $buildRoot
if (Test-Path $packDir) {
    Remove-Item -Recurse -Force $packDir
}
New-Item -ItemType Directory -Path $targetRoot -Force | Out-Null
Move-Item -LiteralPath $compiledDistDir -Destination $packDir -Force

Write-Step "Trim packaged bloat"

$blockedQtFiles = @(
    "qt6multimedia.dll",
    "qt6multimediawidgets.dll",
    "qt6pdf.dll",
    "PySide6\QtMultimedia.pyd",
    "PySide6\QtMultimediaWidgets.pyd",
    "PySide6\qt-plugins\platforms\qminimal.dll",
    "PySide6\qt-plugins\platforms\qoffscreen.dll",
    "PySide6\qt-plugins\platforms\qdirect2d.dll"
)
foreach ($relativePath in $blockedQtFiles) {
    Remove-IfExists -Path (Join-Path $packDir $relativePath)
}

$blockedQtPluginPatterns = @(
    "qicns.dll",
    "qpdf.dll",
    "qtga.dll",
    "qwbmp.dll",
    "qtiff.dll",
    "qcertonlybackend.dll",
    "qopensslbackend.dll"
)
Remove-PathsByPattern -BaseDir (Join-Path $packDir "PySide6\qt-plugins") -Patterns $blockedQtPluginPatterns

if (-not $SkipVelopack) {
    Write-Step "Check Velopack environment"
    $env:PATH = "$env:USERPROFILE\.dotnet\tools;$env:PATH"
    Assert-CommandAvailable -Name "dotnet" -InstallHint "Install .NET SDK first."
    Assert-CommandAvailable -Name "vpk" -InstallHint "Install Velopack CLI: dotnet tool install -g vpk"

    Write-Step "Build Velopack release"
    New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
    Remove-ReleaseSetupIfExists -ReleaseRoot $releaseRoot -FileNames @($setupName, $generatedSetupName)

    if (Test-Path $manifestPath) {
        Write-Step "Drop existing same-version assets"
        Push-Location $repoRoot
        try {
            & uv run python CI/release_tools/trim_velopack_feed.py `
                --release-dir $releaseRoot `
                --channel $Channel `
                --keep-full $KeepFullVersions `
                --drop-version $packVersion
            if ($LASTEXITCODE -ne 0) {
                throw ("Velopack feed trim failed with exit code {0}" -f $LASTEXITCODE)
            }
        }
        finally {
            Pop-Location
        }
    }

    Push-Location $repoRoot
    try {
        & vpk pack `
            --packId SurveyController `
            --packTitle "SurveyController" `
            --packVersion $packVersion `
            --packDir $packDir `
            --mainExe "SurveyController.exe" `
            --icon (Join-Path $packDir "icon.ico") `
            --delta "BestSpeed" `
            --channel $Channel `
            --outputDir $releaseRoot
        if ($LASTEXITCODE -ne 0) {
            throw ("Velopack pack failed with exit code {0}" -f $LASTEXITCODE)
        }
    }
    finally {
        Pop-Location
    }

    if (-not $SkipRenameSetup) {
        Write-Step "Rename setup installer"
        $generatedSetupPath = Join-Path $releaseRoot $generatedSetupName
        $setupPath = Join-Path $releaseRoot $setupName
        if (-not (Test-Path $generatedSetupPath)) {
            throw ("Velopack setup executable not found: {0}" -f $generatedSetupPath)
        }
        Move-Item -LiteralPath $generatedSetupPath -Destination $setupPath -Force
    }

    Write-Step "Trim Velopack feed history"
    Push-Location $repoRoot
    try {
        & uv run python CI/release_tools/trim_velopack_feed.py `
            --release-dir $releaseRoot `
            --channel $Channel `
            --keep-full $KeepFullVersions
        if ($LASTEXITCODE -ne 0) {
            throw ("Velopack feed trim failed with exit code {0}" -f $LASTEXITCODE)
        }
    }
    finally {
        Pop-Location
    }
}

Write-Step "Verify bundle"
if (-not (Test-Path $packDir)) {
    throw ("Pack directory not found: {0}" -f $packDir)
}
if (-not (Test-Path $mainExe)) {
    throw ("Main executable not found: {0}" -f $mainExe)
}
foreach ($relativePath in $blockedQtFiles) {
    $candidate = Join-Path $packDir $relativePath
    if (Test-Path $candidate) {
        throw ("Blocked payload still exists: {0}" -f $candidate)
    }
}

if (-not $SkipVelopack) {
    Write-Step "Verify release output"
    $setupPath = Join-Path $releaseRoot $expectedSetupName
    if (-not (Test-Path $releaseRoot)) {
        throw ("Release directory not found: {0}" -f $releaseRoot)
    }
    if (-not (Test-Path $setupPath)) {
        throw ("Setup installer not found: {0}" -f $setupPath)
    }
    if (-not (Test-Path $manifestPath)) {
        throw ("Velopack feed manifest not found: {0}" -f $manifestPath)
    }
    $nupkgs = Get-ChildItem -Path $releaseRoot -Filter "*.nupkg"
    if (-not $nupkgs) {
        throw "No Velopack nupkg packages were produced"
    }
}

Write-Step "Build finished"
Get-ChildItem $packDir | Sort-Object Name | Format-Table Name, Length, LastWriteTime -AutoSize
if (-not $SkipVelopack) {
    Get-ChildItem $releaseRoot | Sort-Object Name | Format-Table Name, Length, LastWriteTime -AutoSize
}

Write-Host ""
Write-Host ("Standalone bundle: {0}" -f $packDir) -ForegroundColor Green
Write-Host ("Main executable: {0}" -f $mainExe) -ForegroundColor Green
if (-not $SkipVelopack) {
    Write-Host ("Release dir: {0}" -f $releaseRoot) -ForegroundColor Green
    Write-Host ("Setup installer: {0}" -f (Join-Path $releaseRoot $expectedSetupName)) -ForegroundColor Green
}
