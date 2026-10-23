@echo off
rem Flow controllers - the one launcher (the desktop shortcut starts this file too).
rem   run.bat             start screen: connect to the instruments or test mode
rem   run.bat --sim       straight into test mode (simulated instruments, no gas)
rem   run.bat COM9        connect to the instruments on COM9 straight away
rem   run.bat --console   keep this window open and show the log here (troubleshooting)
rem   run.bat --probe     list the connected instruments in this window (add --full for more)
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"

rem Install or update the packages on the first start and whenever requirements.txt changed.
if not exist "%PY%" goto setup
fc /b requirements.txt ".venv\requirements.installed" >nul 2>&1 || goto setup
goto start

:setup
echo Preparing Flow controllers (first start or after an update), this can take a few minutes...
if not exist "%PY%" py -3.11 -m venv .venv 2>nul
if not exist "%PY%" python -m venv .venv
if not exist "%PY%" (
    echo Could not create .venv - install Python 3.11 from python.org first.
    pause
    exit /b 1
)
rem the PyPI package called just "propar" is unrelated and breaks "import propar"
"%PY%" -m pip uninstall -y propar >nul 2>&1
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Installing the packages failed - check the internet connection and start run.bat again.
    pause
    exit /b 1
)
copy /y requirements.txt ".venv\requirements.installed" >nul

:start
echo %* | findstr /i /c:"--console" /c:"--probe" /c:"--monitor" >nul && goto console
rem Normal start: the app runs without a console window (its log is in the app and in logs\).
start "" ".venv\Scripts\pythonw.exe" -m flowapp %*
exit /b 0

:console
"%PY%" -m flowapp %*
pause
