@echo off
setlocal
cd /d "%~dp0.."

echo.
echo ========================================
echo Stats Live Development
echo ========================================
echo.
echo Close the installed Stats app before using live development.
echo This runs the source code directly on http://127.0.0.1:8765

echo.
where py >nul 2>nul
if errorlevel 1 (
    echo Python 3 is required for live development.
    echo Install Python 3, then run this file again.
    pause
    exit /b 1
)

where git >nul 2>nul
if errorlevel 1 (
    echo Git is required for automatic live development syncing.
    echo Install Git, then run this file again.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating the local development environment...
    py -3 -m venv .venv
    if errorlevel 1 goto :failed
)

echo Checking Python dependencies...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :failed

echo.
echo Live development is starting.
echo Keep this window open while testing Stats.
echo Changes pushed to live-dev are pulled automatically about every 10 seconds.
echo Python, templates, CSS, and JavaScript reload automatically on disk changes.
echo.
".venv\Scripts\python.exe" windows\dev_server.py
exit /b %errorlevel%

:failed
echo.
echo Live development setup failed. Read the error above.
pause
exit /b 1
