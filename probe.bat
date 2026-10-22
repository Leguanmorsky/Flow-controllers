@echo off
rem Lists the connected Bronkhorst instruments.
rem Usage: probe.bat                (auto-detect COM port)
rem        probe.bat COM9           (specific port)
rem        probe.bat --full         (also read extra parameters, report saved in logs\)
rem        probe.bat --sim --full   (simulated instruments)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call "%~dp0setup_env.bat" nopause
".venv\Scripts\python.exe" -m flowapp --probe %*
pause
