@echo off
rem TEST MODE: the app with simulated instruments only. The real flow controllers are not opened,
rem so no gas can flow. The simulated gases are set in config\simulator.json.
"%~dp0run.bat" --sim
