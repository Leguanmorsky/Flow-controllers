@echo off
rem Usage: run.bat            (auto-detect COM port)
rem        run.bat COM5       (force a specific COM port)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call setup_env.bat
if not "%~1"=="" set FLOW_COM_PORT=%~1
cd laboratory_gas_control
"..\.venv\Scripts\python.exe" final_controller.py
if errorlevel 1 pause
