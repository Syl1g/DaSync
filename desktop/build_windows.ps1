# Локальная сборка установщика на Windows:  .\build_windows.ps1 -Version 0.1.0
param([string]$Version = "0.0.0-dev")
$ErrorActionPreference = "Stop"
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\pip install -r requirements.txt pyinstaller
.\.venv\Scripts\pyinstaller dasync.spec --noconfirm
$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) { Write-Host "Поставь Inno Setup 6: https://jrsoftware.org/isdl.php"; exit 1 }
$env:DASYNC_VERSION = $Version
& $iscc installer.iss
Write-Host "Готово: dist\DaSync-Setup.exe"
