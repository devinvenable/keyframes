[CmdletBinding()]
param(
    [switch]$SkipDeps,
    [switch]$Clean
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$specPath = Join-Path $repoRoot 'keyframes.spec'
$buildDir = Join-Path $repoRoot 'build'
$distDir = Join-Path $repoRoot 'dist'
$packageDir = Join-Path $distDir 'Keyframes_Windows'
$zipPath = Join-Path $distDir 'Keyframes_Windows.zip'

function Remove-PathIfPresent {
    param([string]$Path)
    if (Test-Path $Path) {
        Remove-Item -Recurse -Force $Path
    }
}

Push-Location $repoRoot
try {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw "Python is not on PATH. Install Python 3.11+ and retry."
    }

    if (-not $SkipDeps) {
        python -m pip install --upgrade pip
        python -m pip install -r requirements-win.txt
    }

    if ($Clean) {
        Remove-PathIfPresent $buildDir
        Remove-PathIfPresent $distDir
    }

    python -m PyInstaller --noconfirm --clean $specPath

    $exePath = Join-Path $packageDir 'Keyframes.exe'
    if (-not (Test-Path $exePath)) {
        throw "PyInstaller completed without producing $exePath"
    }

    # Media and mapping remain deliberately outside the executable so users can
    # replace them without rebuilding.  mapping.json is optional until the Media
    # Manager feature creates it.
    Copy-Item (Join-Path $repoRoot 'images') (Join-Path $packageDir 'images') -Recurse -Force
    $mappingPath = Join-Path $repoRoot 'mapping.json'
    if (Test-Path $mappingPath) {
        Copy-Item $mappingPath (Join-Path $packageDir 'mapping.json') -Force
    }
    Copy-Item (Join-Path $repoRoot 'windows\README.txt') (Join-Path $packageDir 'README.txt') -Force

    Remove-PathIfPresent $zipPath
    Compress-Archive -Path $packageDir -DestinationPath $zipPath -Force
    Write-Host "Build complete: $zipPath" -ForegroundColor Green
}
finally {
    Pop-Location
}
