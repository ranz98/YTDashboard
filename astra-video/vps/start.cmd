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
:run
if exist STOP exit /b 0
"%ASTRA_RUNTIME%" runner.py
if exist STOP exit /b 0
echo Runner exited. Restarting in 15 seconds. Close this window to stop.
timeout /t 15 /nobreak >nul
goto run
