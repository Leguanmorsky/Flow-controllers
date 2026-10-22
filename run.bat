@echo off
rem Starts the flow controller app.
rem Usage: run.bat            (port from config, otherwise auto-detect)
rem        run.bat COM5       (specific COM port)
rem        run.bat --sim      (simulated instruments, no hardware needed)
cd /d "%~dp0"

rem (Re)install the packages when .venv is missing or requirements.txt changed since the last install.
if not exist ".venv\Scripts\python.exe" goto setup
fc /b requirements.txt ".venv\requirements.installed" >nul 2>&1 || goto setup
goto run

:setup
call "%~dp0setup_env.bat" nopause

:run
".venv\Scripts\python.exe" -m flowapp %*
if errorlevel 1 pause
