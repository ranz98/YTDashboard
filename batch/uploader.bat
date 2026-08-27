@echo off
setlocal
title Stage 3 - Upload

rem ---------------------------------------------------------------------------
rem STAGE 3 of 3: upload the next finished video to YouTube.
rem
rem Videos already recorded in output\uploaded.json are never picked again, so
rem a scheduled run that finds nothing new stops instead of re-uploading the
rem last video.
rem
rem Runs unattended under Task Scheduler: set NOPAUSE=1 (or run it from
rem RUNPIPELINE.bat, which sets it) and no prompt is ever shown.
rem
rem Usage:  uploader.bat                       - next pending video
rem         uploader.bat "path\to\video.mp4"   - that file, ignoring the record
rem ---------------------------------------------------------------------------

set "BATCH_DIR=%~dp0"
if "%BATCH_DIR:~-1%"=="\" set "BATCH_DIR=%BATCH_DIR:~0,-1%"
for %%I in ("%BATCH_DIR%\..") do set "BASE=%%~fI"

rem Ask the uploader itself what it would pick, BEFORE opening Chrome. Same
rem code path and same state file as the real run, so the answer cannot drift.
rem Exit 2 means every video is already recorded in output\uploaded.json.
python -u "%BASE%\scripts\trainer.py" --check-only %*
if errorlevel 2 goto :nothing_pending

python "%BASE%\scripts\dashboard_report.py" start --stage upload

echo Opening YouTube Studio upload page...

start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" ^
    --profile-directory="Default" ^
    "https://studio.youtube.com/channel/UC4laQaWkDDNJt8x_2O935Ng/content?d=ud"

echo.
echo Waiting 10 seconds for YouTube Studio to start loading...
timeout /t 10 /nobreak >nul

echo.
echo Running Python script to choose a video and click Publish...

python -u "%BASE%\scripts\trainer.py" %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" goto :failed

python "%BASE%\scripts\dashboard_report.py" finish --stage upload --exit-code 0
echo.
echo Done.
if not defined NOPAUSE pause
exit /b 0

:failed
python "%BASE%\scripts\dashboard_report.py" finish --stage upload --exit-code %RC% --message "trainer.py exited with code %RC%"
echo.
echo   UPLOAD FAILED - trainer.py exited with code %RC%
echo   Check the newest log in output\logs\ for the stage that failed.
echo.
if not defined NOPAUSE pause
exit /b %RC%

:nothing_pending
rem Reported as a skipped run, not a failure: nothing was wrong, there was
rem simply nothing new to upload.
python "%BASE%\scripts\dashboard_report.py" finish --stage upload --exit-code 0 --skipped --message "Nothing pending - every finished video is already uploaded"
echo.
echo   ===============================================================
echo    NOTHING TO UPLOAD
echo   ===============================================================
echo.
echo   Every finished video is already recorded as uploaded.
echo   Run batch\RUNPIPELINE.bat to produce a new one.
echo.
echo   To force a re-upload, either remove that video's entry from
echo   output\uploaded.json, or pass the file directly:
echo       batch\uploader.bat "path\to\video.mp4"
echo.
if not defined NOPAUSE pause
exit /b 0
