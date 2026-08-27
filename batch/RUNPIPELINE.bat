@echo off
setlocal
title Full pipeline

rem ---------------------------------------------------------------------------
rem Both stages back to back. Each stage also runs on its own:
rem
rem   1-DOWNLOAD.bat   find the newest Short and download it
rem   2-EDIT.bat       edit anything not edited yet, copy it to toupload
rem
rem Usage:  RUNPIPELINE.bat                     - @Clips_Edge, vivid grade
rem         RUNPIPELINE.bat @SomeHandle         - another channel
rem         RUNPIPELINE.bat @SomeHandle cool    - and a different grade
rem         RUNPIPELINE.bat <video-url>         - skip the search
rem ---------------------------------------------------------------------------

set "BATCH_DIR=%~dp0"
if "%BATCH_DIR:~-1%"=="\" set "BATCH_DIR=%BATCH_DIR:~0,-1%"
for %%I in ("%BATCH_DIR%\..") do set "BASE=%%~fI"
cd /d "%BASE%"

set "NOPAUSE=1"
if not defined FILTER set "FILTER=vivid"
if not "%~2"=="" set "FILTER=%~2"

call "%BATCH_DIR%\1-DOWNLOAD.bat" %1
if errorlevel 1 goto :stop

call "%BATCH_DIR%\2-EDIT.bat" %FILTER%
if errorlevel 1 goto :stop

echo(
echo   ===============================================================
echo    PIPELINE COMPLETE
echo   ===============================================================
echo(
echo   Finished videos:  output\videos\toupload\
echo(
set "NOPAUSE="
pause
exit /b 0

:stop
echo(
echo   Pipeline stopped - see the message above.
echo(
set "NOPAUSE="
pause
exit /b 1
