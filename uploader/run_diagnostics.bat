@echo off
setlocal enabledelayedexpansion

rem ---------------------------------------------------------------------
rem run_diagnostics.bat
rem
rem Runs the diagnostic scripts and writes everything -- stdout, stderr,
rem tracebacks -- to logs\diagnostics_<timestamp>.txt while still showing
rem it on screen.
rem
rem Put this next to trainder.py and run it THE SAME WAY you run the
rem uploader (same elevation, same scheduled task). Running it by hand
rem from an open RDP window will report a healthy session and tell you
rem nothing useful.
rem ---------------------------------------------------------------------

cd /d "%~dp0"

set "LOGDIR=%~dp0logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

rem wmic is gone on Server 2025, so get the timestamp from PowerShell.
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HHmmss"') do set "STAMP=%%I"
set "OUT=%LOGDIR%\diagnostics_%STAMP%.txt"

rem -u  = unbuffered, so nothing is lost if the script crashes mid-run.
rem PYTHONIOENCODING stops UnicodeEncodeError when writing to a file.
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

echo Writing to %OUT%
echo.

rem Header, so a pasted log says how it was launched.
(
  echo ======================================================================
  echo DIAGNOSTIC RUN %DATE% %TIME%
  echo ======================================================================
  echo Launched from: %~f0
  echo Working dir:   %CD%
  echo User:          %USERNAME%
  echo Computer:      %COMPUTERNAME%
  echo.
) > "%OUT%"

rem Tee via PowerShell: shows on screen AND appends to the file.
powershell -NoProfile -Command ^
  "& { python -u '%~dp0diagnose_session.py' 2>&1 | Tee-Object -FilePath '%OUT%' -Append }"

echo.
echo ---------------------------------------------------------------------- >> "%OUT%"
echo.

rem Uncomment to run the click diagnostic in the same file.
rem powershell -NoProfile -Command ^
rem   "& { python -u '%~dp0diagnose_click.py' 2>&1 | Tee-Object -FilePath '%OUT%' -Append }"

rem Grab the most recent uploader log too -- it usually has the real story.
if exist "%LOGDIR%\upload_*.log" (
  echo. >> "%OUT%"
  echo ====================== LATEST UPLOAD LOG ============================ >> "%OUT%"
  for /f "delims=" %%F in ('dir /b /o-d "%LOGDIR%\upload_*.log" 2^>nul') do (
    echo --- %%F --- >> "%OUT%"
    type "%LOGDIR%\%%F" >> "%OUT%"
    goto :done_log
  )
)
:done_log

echo.
echo Saved to: %OUT%
echo.

rem Open it so you can copy the contents straight out.
start "" notepad "%OUT%"

endlocal
pause