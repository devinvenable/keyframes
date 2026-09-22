[CmdletBinding()]
param([switch]$SkipDeps, [switch]$Clean)
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $root 'venv\Scripts\python.exe'
$dist = Join-Path $root 'dist'
$package = Join-Path $dist 'ShowSync'
$zip = Join-Path $dist 'ShowSync_Windows.zip'

# PowerShell 5 does not turn native-process failures into terminating errors.
function Invoke-Python {
    & $python @args
    if ($LASTEXITCODE -ne 0) { throw "Python failed ($LASTEXITCODE): $args" }
}

Push-Location $root
try {
    if (-not (Test-Path $python)) {
        py -3.11 -m venv venv
        if ($LASTEXITCODE -ne 0) { throw 'Install native 64-bit Windows Python 3.11+.' }
    }
    Invoke-Python -c 'import sys, struct; assert sys.platform == ''win32'' and sys.version_info >= (3, 11) and struct.calcsize(''P'') == 8, ''Native Windows x64 Python 3.11+ required'''
    if (-not $SkipDeps) {
        Invoke-Python -m pip install -r requirements.txt 'PyInstaller>=6.11,<7'
        Invoke-Python -m pip install -r windows/requirements-verify.txt
    }
    if ($Clean) {
        foreach ($path in @('build', 'dist')) {
            if (Test-Path $path) { Remove-Item -Recurse -Force $path }
        }
    }
    # Do not leave a stale successful zip if any stage below fails.
    if (Test-Path $zip) { Remove-Item $zip }
    $icons = Join-Path $root 'showsync\icons'
    Invoke-Python -m PyInstaller --noconfirm --clean --onedir --console --name ShowSync --specpath build --collect-all av --collect-all sounddevice --collect-all soundfile --collect-all rtmidi --hidden-import mido.backends.rtmidi --add-data "${icons}:showsync/icons" --icon (Join-Path $icons 'showsync.ico') main.py
    if (-not (Test-Path (Join-Path $package 'ShowSync.exe'))) { throw 'Missing ShowSync.exe' }
    Copy-Item windows/README.txt (Join-Path $package 'README.txt')
    $licenses = New-Item -ItemType Directory -Force (Join-Path $package 'licenses')
    Copy-Item windows/licenses (Join-Path $licenses 'Qt') -Recurse
    foreach ($metadata in Get-ChildItem (Join-Path $root 'venv\Lib\site-packages') -Directory -Filter '*.dist-info') {
        $source = Join-Path $metadata.FullName 'licenses'
        if (Test-Path $source) {
            Copy-Item $source (Join-Path $licenses $metadata.Name) -Recurse
        }
    }
    $demo = New-Item -ItemType Directory -Force (Join-Path $package 'demo')
    Invoke-Python -c 'from demo.make_demo import main; from pathlib import Path; main(Path(''dist/ShowSync/demo''))'
    Copy-Item tests/fixtures/demo_ramp_reference.yaml (Join-Path $demo 'setlist.yaml')
    Copy-Item demo/click-test.yaml $demo
    # Exercise the FFmpeg decoder too, beyond the libsndfile WAV demo.
    Copy-Item tests/fixtures/tone.m4a (Join-Path $demo 'codec-test.m4a')
    Invoke-Python -m pip freeze | Set-Content -Encoding UTF8 (Join-Path $package 'build-requirements.txt')
    git rev-parse HEAD | Set-Content -Encoding ASCII (Join-Path $package 'build-commit.txt')
    # Zip first, then test an extracted copy outside the checkout. Nothing is
    # delivered unless the GUI, devices and captured playback checks all pass.
    Compress-Archive -Path $package -DestinationPath $zip -Force
    try {
        Invoke-Python scripts/verify_windows.py $zip (Join-Path $dist 'windows-verification')
    } catch {
        Remove-Item $zip
        throw
    }
    Write-Host "Verified release: $zip"
} finally { Pop-Location }
