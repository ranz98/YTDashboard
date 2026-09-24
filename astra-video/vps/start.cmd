@echo off
cd /d "%~dp0"
if exist STOP del STOP
if not exist data\python-path.txt (
  echo Run install.cmd first.
  pause
  exit /b 1
)
set /p "ASTRA_RUNTIME=" < "data\python-path.txt"
"%ASTRA_RUNTIME%" doctor.py
if errorlevel 1 (
  pause
  exit /b 1
)
"%ASTRA_RUNTIME%" runner.py
pause
