@echo off
rem Starts the OLD Tkinter app (fallback until the new app has passed the lab check; removed in Block 3).
rem Usage: run_legacy.bat         (auto-detect COM port)
rem        run_legacy.bat COM5    (specific COM port)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call "%~dp0setup_env.bat" nopause
if not "%~1"=="" set FLOW_COM_PORT=%~1
cd laboratory_gas_control
"..\.venv\Scripts\python.exe" final_controller.py
if errorlevel 1 pause
