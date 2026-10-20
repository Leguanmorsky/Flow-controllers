@echo off
rem Lists the connected Bronkhorst instruments.
rem Usage: probe.bat           (auto-detect COM port)
rem        probe.bat COM9      (specific port)
rem        probe.bat --sim     (simulated instruments)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call setup_env.bat
".venv\Scripts\python.exe" -m flowapp --probe %*
pause
