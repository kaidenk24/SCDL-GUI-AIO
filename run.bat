@echo off
rem SoundCloud Downloader - start from source.
rem First run: creates a private Python environment (.venv) and installs what the app needs.
rem After that: refreshes those components once a day (yt-dlp changes often) and starts the app.
setlocal
cd /d "%~dp0"

set "VENV=.venv"
set "STAMP=%VENV%\.components-updated"

if exist "%VENV%\Scripts\pythonw.exe" goto :refresh

echo Setting up SoundCloud Downloader for the first time. This takes a minute or two...
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto :no_python
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" || goto :old_python
%PY% -m venv "%VENV%" || goto :failed
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt || goto :failed
type nul > "%STAMP%"
goto :start

:refresh
powershell -NoProfile -Command "if ((Get-Item '%STAMP%' -ErrorAction SilentlyContinue).LastWriteTime -gt (Get-Date).AddDays(-1)) { exit 1 }"
if errorlevel 1 goto :start
echo Checking for component updates...
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade -r requirements.txt && type nul > "%STAMP%"

:start
rem (SCDL_GUI_SETUP_ONLY=1 prepares everything without opening the app - used for testing.)
if defined SCDL_GUI_SETUP_ONLY exit /b 0
start "" "%VENV%\Scripts\pythonw.exe" "%~dp0scdl-gui.pyw"
exit /b 0

:no_python
echo.
echo Python wasn't found. Either:
echo   - download the ready-made app (no Python needed): https://github.com/kaidenk24/scdl-gui/releases
echo   - or install Python 3.10+ from https://www.python.org/downloads/ (tick "Add python.exe to PATH")
echo     and run this file again.
echo.
pause
exit /b 1

:old_python
echo.
echo Python 3.10 or newer is needed. Get it from https://www.python.org/downloads/
echo or download the ready-made app: https://github.com/kaidenk24/scdl-gui/releases
echo.
pause
exit /b 1

:failed
echo.
echo Setting up failed - check your internet connection and run this file again.
echo If it keeps failing, delete the .venv folder next to this file and try once more.
echo.
pause
exit /b 1
