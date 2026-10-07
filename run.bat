@echo off
rem SoundCloud Downloader - start from source.
rem First run: creates a private Python environment (.venv) and installs what the app needs.
rem After that: refreshes those components once a day (yt-dlp changes often) and starts the app.
setlocal
cd /d "%~dp0"

set "VENV=.venv"
set "STAMP=%VENV%\.components-updated"
rem READY is written only when setup fully finished; without it, .venv is a leftover of a
rem cancelled or failed setup and is rebuilt. (Setups from older versions only wrote STAMP.)
set "READY=%VENV%\.setup-complete"

if exist "%READY%" goto :refresh
if exist "%STAMP%" (type nul > "%READY%" & goto :refresh)
if exist "%VENV%" call :remove_unfinished || goto :in_use

echo Setting up SoundCloud Downloader for the first time.
echo This downloads about 150 MB and takes a few minutes - please leave this window open.
echo.
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto :no_python
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" || goto :old_python
echo [1/3] Creating a private Python environment...
%PY% -m venv "%VENV%" || goto :failed
echo [2/3] Updating pip...
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade pip || goto :failed
echo [3/3] Installing the app's components: PySide6, scdl, yt-dlp, mutagen...
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt || goto :failed
type nul > "%STAMP%"
type nul > "%READY%"
echo Done - starting the app.
goto :start

:remove_unfinished
echo An earlier setup didn't finish - starting it again...
rmdir /s /q "%VENV%" 2>nul
if exist "%VENV%" exit /b 1
exit /b 0

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
echo   - download the ready-made app (no Python needed): https://github.com/kaidenk24/SCDL-GUI-AIO/releases
echo   - or install Python 3.10+ from https://www.python.org/downloads/ (tick "Add python.exe to PATH")
echo     and run this file again.
echo.
pause
exit /b 1

:old_python
echo.
echo Python 3.10 or newer is needed. Get it from https://www.python.org/downloads/
echo or download the ready-made app: https://github.com/kaidenk24/SCDL-GUI-AIO/releases
echo.
pause
exit /b 1

:failed
echo.
echo Setting up failed - check your internet connection and run this file again.
echo (It starts over automatically.)
echo.
pause
exit /b 1

:in_use
echo.
echo The .venv folder from an unfinished setup couldn't be removed - is the app still open?
echo Close it and run this file again.
echo.
pause
exit /b 1
