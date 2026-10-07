<#
.SYNOPSIS
    Builds the Windows app (dist\scdl-gui\scdl-gui.exe) and the release zip (dist\scdl-gui-windows-x64.zip).
    Used by the GitHub release workflow; also works locally after: pip install -r requirements-dev.txt
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

python -m PyInstaller packaging/scdl-gui.spec --noconfirm --clean --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$exe = Join-Path $root 'dist\scdl-gui\scdl-gui.exe'
if (-not (Test-Path $exe)) { throw "Build produced no $exe" }

# Smoke test: the packaged worker must import scdl/yt-dlp and answer.
$out = & $exe --worker --describe 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) { throw "Packaged worker failed:`n$out" }

$zip = Join-Path $root 'dist\scdl-gui-windows-x64.zip'
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path (Join-Path $root 'dist\scdl-gui') -DestinationPath $zip -CompressionLevel Optimal
Write-Host ("Built {0} ({1:N0} MB)" -f $zip, ((Get-Item $zip).Length / 1MB))
