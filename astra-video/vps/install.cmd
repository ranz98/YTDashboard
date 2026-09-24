@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0find-python.ps1"
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements.txt
if errorlevel 1 goto failed
where ffmpeg >nul 2>&1
if errorlevel 1 goto ffmpeg
where ffprobe >nul 2>&1
if errorlevel 1 goto ffmpeg
.venv\Scripts\python.exe setup.py
if errorlevel 1 goto failed
.venv\Scripts\python.exe doctor.py
if errorlevel 1 goto failed
echo Open Chrome extensions, enable Developer mode, and load this folder's extension subfolder.
echo Follow WINDOWS-SETUP.md for pairing and first run.
pause
exit /b 0
:ffmpeg
echo Install FFmpeg, add its bin folder to PATH, then reopen this installer.
pause
exit /b 1
:failed
echo Setup failed. Check the error above, fix it, and run install.cmd again.
pause
exit /b 1
