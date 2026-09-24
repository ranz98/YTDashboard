@echo off
setlocal
title Stage 1 - Download

rem ---------------------------------------------------------------------------
rem STAGE 1 of 2: find the channel's newest Short and download it.
rem
rem Downloads only. No editing, no DeepSeek, no re-encoding - so it is quick and
rem safe to run whenever, including several times a day. Run 2-EDIT.bat after.
rem
rem Each video lands in its own folder:
rem   output\videos\<date>\<Title> [videoid]\video.mp4   + frame.jpg + title.txt
rem
rem Usage:  1-DOWNLOAD.bat                 - newest Short from @Clips_Edge
rem         1-DOWNLOAD.bat @SomeHandle     - another channel
rem         1-DOWNLOAD.bat <video-url>     - skip the search, fetch this one
rem ---------------------------------------------------------------------------

set "BASE=%~dp0"
if "%BASE:~-1%"=="\" set "BASE=%BASE:~0,-1%"
cd /d "%BASE%"

set "ARG=%~1"
set "URL="
set "HANDLE="
if not defined ARG goto :use_channel
echo %ARG% | findstr /i /c:"http" >nul
if errorlevel 1 (set "HANDLE=%ARG%") else (set "URL=%ARG%")
goto :start

:use_channel
set "HANDLE=@Clips_Edge"

:start
echo(
echo   ===============================================================
echo    STAGE 1 of 2 - DOWNLOAD
echo   ===============================================================

if defined URL goto :download

echo(
echo   [1/2] Finding the newest Short for %HANDLE%
echo   ---------------------------------------------------------------
call "%BASE%\run.bat" %HANDLE%
if errorlevel 1 goto :failed_find
set "LATEST=%BASE%\output\latest-short.txt"
if not exist "%LATEST%" goto :failed_find
set /p URL=<"%LATEST%"

:download
echo(
echo   [2/2] Downloading %URL%
echo         (already-downloaded videos are reused, not re-fetched)
echo   ---------------------------------------------------------------
python "%BASE%\download.py" "%URL%"
if errorlevel 1 goto :failed_download

echo(
echo   ===============================================================
echo    DOWNLOAD DONE
echo   ===============================================================
echo(
echo   Next:  2-EDIT.bat     (edits anything not edited yet)
echo(
exit

:failed_find
echo(
echo   FAILED - could not get a Short URL.
echo   Run setup.bat if the extension is not loaded yet.
echo(
exit

:failed_download
echo(
echo   FAILED - the download did not complete.
echo   If yt-dlp reported a format error, update it:
echo       python -m pip install -U yt-dlp
echo(
exit