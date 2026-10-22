@echo off
rem Creates .venv and installs requirements.txt. run.bat calls this automatically when needed.
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
if errorlevel 1 (
    echo.
    echo Installing the packages failed - check the internet connection and run setup_env.bat again.
    pause
    exit /b 1
)
copy /y requirements.txt ".venv\requirements.installed" >nul

echo.
echo Done. Start the app with run.bat
if /i not "%~1"=="nopause" pause
