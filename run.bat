@echo off
rem Flow controllers - the one launcher (the desktop shortcut starts this file too).
rem   run.bat             start screen: connect to the instruments or test mode
rem   run.bat --sim       straight into test mode (simulated instruments, no gas)
rem   run.bat COM9        connect to the instruments on COM9 straight away
rem   run.bat --console   keep this window open and show the log here (troubleshooting)
rem   run.bat --probe     list the connected instruments in this window (add --full for more)
rem   run.bat --card-probe 192.168.1.10   read the vacuum control card once (read-only)
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"

rem Install or update the packages on the first start and whenever requirements.txt changed.
if not exist "%PY%" goto setup
fc /b requirements.txt ".venv\requirements.installed" >nul 2>&1 || goto setup
goto start

:setup
echo Preparing Flow controllers (first start or after an update), this can take a few minutes...
rem The packages exist ready-made only for 64-bit Python 3.11-3.15; rebuild a .venv made from another Python.
if exist "%PY%" call :python_ok "%PY%" || (
    echo The existing .venv uses an unsupported Python - building it again.
    rmdir /s /q .venv
)
for %%V in (3.13 3.12 3.11 3.14 3.15) do if not exist "%PY%" py -%%V -m venv .venv >nul 2>&1
if not exist "%PY%" python -m venv .venv
if not exist "%PY%" (
    echo Could not create .venv - install Python 3.13 ^(64-bit^) from python.org first.
    pause
    exit /b 1
)
call :python_ok "%PY%" || (
    echo.
    "%PY%" -c "import sys, struct; print('This computer has Python', sys.version.split()[0], struct.calcsize('P') * 8, 'bit')"
    echo The app needs 64-bit Python 3.11 to 3.15. Install Python 3.13 ^(64-bit^) from python.org,
    echo delete the .venv folder next to run.bat and start run.bat again.
    pause
    exit /b 1
)
rem the PyPI package called just "propar" is unrelated and breaks "import propar"
"%PY%" -m pip uninstall -y propar >nul 2>&1
"%PY%" -m pip install --upgrade pip
rem ready-made packages only: never try to compile anything (that needs a C compiler)
"%PY%" -m pip install --only-binary=:all: -r requirements.txt
if errorlevel 1 (
    echo.
    "%PY%" -c "import sys, struct; print('Python', sys.version.split()[0], struct.calcsize('P') * 8, 'bit')"
    echo Installing the packages failed - check the internet connection and start run.bat again.
    echo If it fails again, send the text in this window.
    pause
    exit /b 1
)
copy /y requirements.txt ".venv\requirements.installed" >nul

:start
echo %* | findstr /i /c:"--console" /c:"--probe" /c:"--card-probe" /c:"--monitor" >nul && goto console
rem Normal start: the app runs without a console window (its log is in the app and in logs\).
start "" ".venv\Scripts\pythonw.exe" -m flowapp %*
exit /b 0

:console
"%PY%" -m flowapp %*
pause
exit /b

rem Exit code 0 when %1 is a 64-bit, non-free-threaded Python 3.11-3.15 (the versions with ready-made packages).
:python_ok
%1 -c "import sys, struct, sysconfig; ok = (3, 11) <= sys.version_info[:2] <= (3, 15) and struct.calcsize('P') == 8 and not sysconfig.get_config_var('Py_GIL_DISABLED'); sys.exit(0 if ok else 1)" >nul 2>&1
exit /b
