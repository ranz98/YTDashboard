@echo off
setlocal
title Stage 2 - Edit

rem ---------------------------------------------------------------------------
rem STAGE 2 of 2: edit every downloaded video that has not been edited yet.
rem
rem Looks through output\videos for raw downloads, and for each one that has no
rem finished render (or whose render is older than its source):
rem   detect the caption box -> OCR it -> rewrite caption and title with
rem   DeepSeek -> redraw the caption -> grade the picture -> copy the finished
rem   video into the shared output\videos\toupload folder.
rem
rem Anything already finished is skipped without touching ffmpeg, so running
rem this twice costs almost nothing. If nothing is fresh it just says so.
rem
rem Usage:  2-EDIT.bat                - one video, vivid grade (the default)
rem         2-EDIT.bat cinematic      - a different grade
rem         2-EDIT.bat vivid 3        - the next three
rem         2-EDIT.bat vivid 0        - every fresh video
rem ---------------------------------------------------------------------------

set "BATCH_DIR=%~dp0"
if "%BATCH_DIR:~-1%"=="\" set "BATCH_DIR=%BATCH_DIR:~0,-1%"
for %%I in ("%BATCH_DIR%\..") do set "BASE=%%~fI"
cd /d "%BASE%"

if not defined FILTER set "FILTER=vivid"
if not "%~1"=="" set "FILTER=%~1"

rem One video per run by default, so a double-click is a short, predictable
rem job rather than an open-ended batch. Pass 0 to edit everything fresh.
if not defined LIMIT set "LIMIT=1"
if not "%~2"=="" set "LIMIT=%~2"
set "LIMITARG=--limit %LIMIT%"

echo(
echo   ===============================================================
echo    STAGE 2 of 2 - EDIT
echo   ===============================================================
echo    Grade   : %FILTER%
echo    Videos  : %LIMIT%   (0 = every fresh one)
echo    Output  : output\videos\toupload\
echo   ===============================================================

python "%BASE%\scripts\dashboard_report.py" start --stage edit

python "%BASE%\scripts\edit_pending.py" --filter %FILTER% %LIMITARG%
if errorlevel 1 goto :failed

echo(
python "%BASE%\scripts\dashboard_report.py" finish --stage edit --exit-code 0
exit /b 0

:failed
echo(
echo   One or more videos failed to edit.
echo   Look at frame-detected.jpg in that video's folder to see what was
echo   detected. You can supply the box yourself:
echo       python scripts\cover_caption.py --rewrite --box x,y,w,h "<folder>"
echo(
python "%BASE%\scripts\dashboard_report.py" finish --stage edit --exit-code 1 --message "One or more videos failed to edit - check frame-detected.jpg"
exit /b 1