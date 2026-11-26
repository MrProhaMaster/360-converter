param([string]$Python = 'python', [string]$OutputDirectory = 'dist')
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Windows build must run on Windows.' }
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    & $Python -m PyInstaller --noconfirm --clean --windowed --onedir --name Pano360 --distpath $OutputDirectory --collect-submodules PIL --copy-metadata Pillow --copy-metadata numpy launch.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
    $BundleDirectory = Join-Path $OutputDirectory 'Pano360'
    & $Python scripts/bundle_ffmpeg.py $BundleDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Bundling FFmpeg failed; do not distribute this incomplete build.' }
    Copy-Item README.md (Join-Path $BundleDirectory 'README.md')
    Copy-Item THIRD_PARTY.md (Join-Path $BundleDirectory 'THIRD_PARTY.md')
    Copy-Item -Recurse presets (Join-Path $BundleDirectory 'presets') -Force
    Copy-Item -Recurse docs (Join-Path $BundleDirectory 'docs') -Force
    Copy-Item requirements-dev.lock.txt (Join-Path $BundleDirectory 'requirements-dev.lock.txt')
    $PythonLicense = & $Python -c "import sys,pathlib; print(pathlib.Path(sys.base_prefix) / 'LICENSE.txt')"
    if (Test-Path -LiteralPath $PythonLicense) { Copy-Item -LiteralPath $PythonLicense -Destination (Join-Path $BundleDirectory 'PYTHON-LICENSE.txt') }
    & $Python scripts/check_windows_bundle.py $BundleDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Portable export verification failed; do not distribute this build.' }
    Write-Output "Built $BundleDirectory\Pano360.exe with bundled FFmpeg; offline export verified."
} finally { Pop-Location }
