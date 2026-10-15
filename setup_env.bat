@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -3.11 -m venv .venv 2>nul || python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
    echo Could not create .venv - install Python 3.11 from python.org first.
    pause
    exit /b 1
)

rem remove the wrong "propar" package if it ever got installed
".venv\Scripts\python.exe" -m pip uninstall -y propar >nul 2>&1
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt

echo.
echo Done. Start the app with run.bat
pause
