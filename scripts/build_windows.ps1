param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Windows build must run on Windows.' }
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    & $Python -m PyInstaller --noconfirm --clean --windowed --onedir --name Pano360 --collect-submodules PIL launch.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
    Copy-Item README.md dist\Pano360\README.md
    Copy-Item THIRD_PARTY.md dist\Pano360\THIRD_PARTY.md
    Copy-Item -Recurse presets dist\Pano360\presets -Force
    Write-Output 'Built dist\Pano360\Pano360.exe. Supply a separate trusted ffmpeg.exe via the app settings.'
} finally { Pop-Location }
