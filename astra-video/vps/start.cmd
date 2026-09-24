@echo off
cd /d "%~dp0"
if exist STOP del STOP
if not exist .venv\Scripts\python.exe (
  echo Run install.cmd first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe doctor.py
if errorlevel 1 (
  pause
  exit /b 1
)
.venv\Scripts\python.exe runner.py
pause
