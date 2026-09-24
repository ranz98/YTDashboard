@echo off
setlocal EnableDelayedExpansion
title First Short Grabber

rem ---------------------------------------------------------------------------
rem Opens Chrome directly on the extension's own trigger page:
rem   chrome-extension://<id>/trigger.html?channel=@Handle
rem
rem An extension page always loads, cannot be redirected, and messages the
rem service worker itself. The old approach -- a youtube.com URL carrying a
rem ?ytgrab=1 marker -- depended on a tabs event waking the worker, which is
rem what silently failed.
rem
rem Writes:
rem   output\latest-short.txt   - just the URL, one line
rem   output\shorts-log.txt     - every capture so far, newest first
rem   output\error.txt          - only on failure
rem
rem Usage:  run.bat              - uses @Clips_Edge
rem         run.bat @SomeHandle  - any other channel
rem ---------------------------------------------------------------------------

set "BASE=%~dp0"
if "%BASE:~-1%"=="\" set "BASE=%BASE:~0,-1%"
set "PROFILE=%BASE%\chrome-profile"
set "OUTDIR=%BASE%\output"
set "LATEST=%OUTDIR%\latest-short.txt"
set "ERRFILE=%OUTDIR%\error.txt"
set "NONEW=%OUTDIR%\no-new.txt"
set "IDFILE=%PROFILE%\extension-id.txt"

set "HANDLE=%~1"
if not defined HANDLE set "HANDLE=@Clips_Edge"
if not "%HANDLE:~0,1%"=="@" set "HANDLE=@%HANDLE%"

if not exist "%PROFILE%" goto :no_profile
call :find_chrome
if not defined CHROME goto :no_chrome
if not exist "%OUTDIR%" mkdir "%OUTDIR%"

echo(
echo   ---------------------------------------------------------------
echo    First Short Grabber
echo   ---------------------------------------------------------------
echo    Channel : %HANDLE%
echo    Profile : %PROFILE%
echo    Output  : %OUTDIR%
echo   ---------------------------------------------------------------
echo(

rem --- resolve the extension's ID from the profile -------------------------
echo   [1/4] Looking up the extension ID...
call :find_extension_id
if not defined EXTID goto :no_extid
echo         id = %EXTID%

set "TARGET=chrome-extension://%EXTID%/trigger.html?channel=%HANDLE%"

rem --- clear previous results ----------------------------------------------
echo   [2/4] Clearing old output...
if exist "%LATEST%"  del /q "%LATEST%"
if exist "%ERRFILE%" del /q "%ERRFILE%"
if exist "%NONEW%"   del /q "%NONEW%"

rem --- launch ---------------------------------------------------------------
echo   [3/4] Launching Chrome...
echo         %TARGET%
start "" "%CHROME%" --user-data-dir="%PROFILE%" --no-first-run --no-default-browser-check "%TARGET%"

echo   [4/4] Waiting for the result - up to 150 seconds.
echo         Live progress is shown in the Chrome window that just opened.
echo(

set /a TRIES=0
:wait
if exist "%LATEST%"  goto :found
if exist "%ERRFILE%" goto :failed
set /a TRIES+=1
if %TRIES% GEQ 150 goto :timedout
set /a BEAT=TRIES %% 5
if %BEAT%==0 echo         ...still waiting ^(%TRIES%s^)
rem ping, not timeout: timeout fails when stdin is redirected.
ping -n 2 127.0.0.1 >nul
goto :wait

:found
rem Brief settle so the file is fully flushed before it is read.
ping -n 2 127.0.0.1 >nul
set "URL="
for /f "usebackq delims=" %%L in ("%LATEST%") do if not defined URL set "URL=%%L"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Set-Clipboard -Value (Get-Content -LiteralPath '%LATEST%' -Raw).Trim()"

rem The extension writes no-new.txt before latest-short.txt, so if this run
rem found nothing new the marker is already on disk by now.
if exist "%NONEW%" goto :nothing_new

echo(
echo   ===============================================================
echo    NEW SHORT
echo    %URL%
echo   ===============================================================
echo(
echo   Copied to the clipboard.
echo   Saved to  %LATEST%
echo   Added to  %OUTDIR%\shorts-log.txt
echo(
ping -n 7 127.0.0.1 >nul
powershell -NoProfile -Command "$p='%PROFILE%'; Get-CimInstance Win32_Process -Filter 'Name = ''chrome.exe''' | ? { $_.CommandLine -like ('*--user-data-dir=*' + $p + '*') } | %% { Stop-Process -Id $_.ProcessId -Force }"

exit /b 0

:nothing_new
echo(
echo   ---------------------------------------------------------------
echo    NO NEW SHORTS - newest was already captured
echo    %URL%
echo   ---------------------------------------------------------------
echo(
type "%NONEW%"
echo(
echo   The log was left untouched. URL copied to the clipboard anyway.
echo(
ping -n 7 127.0.0.1 >nul
powershell -NoProfile -Command "$p='%PROFILE%'; Get-CimInstance Win32_Process -Filter 'Name = ''chrome.exe''' | ? { $_.CommandLine -like ('*--user-data-dir=*' + $p + '*') } | %% { Stop-Process -Id $_.ProcessId -Force }"

exit /b 0

:failed
echo(
echo   ===============================================================
echo    The extension reported a failure:
echo   ===============================================================
echo(
type "%ERRFILE%"
echo(
pause
exit /b 1

:timedout
echo(
echo   TIMED OUT - nothing was written after 150 seconds.
echo(
echo   Look at the Chrome window that opened - the trigger page prints
echo   each step. If it is blank, the extension did not load:
echo     - open chrome://extensions in that profile
echo     - check the extension is enabled, then hit its reload arrow
echo(
pause
exit /b 1

rem --- extension ID lookup --------------------------------------------------
rem Unpacked extensions get an ID derived from their folder path, recorded in
rem the profile. Cached after the first lookup.
:find_extension_id
set "EXTID="
if exist "%IDFILE%" set /p EXTID=<"%IDFILE%"
if defined EXTID exit /b 0
powershell -NoProfile -ExecutionPolicy Bypass -File "%BASE%\find-extension-id.ps1" -Base "%BASE%" -ProfileDir "%PROFILE%" > "%TEMP%\fsg-extid.txt" 2>nul
if exist "%TEMP%\fsg-extid.txt" set /p EXTID=<"%TEMP%\fsg-extid.txt"
if exist "%TEMP%\fsg-extid.txt" del /q "%TEMP%\fsg-extid.txt"
if defined EXTID echo %EXTID%>"%IDFILE%"
exit /b 0

:no_extid
echo(
echo   ERROR: Could not find this extension in the Chrome profile.
echo(
echo   That means it is not loaded yet. Run setup.bat and follow the
echo   Load unpacked steps, then try again.
echo(
pause
exit /b 1

:no_profile
echo(
echo   ERROR: No Chrome profile yet. Run setup.bat first.
echo(
pause
exit /b 1

:no_chrome
echo(
echo   ERROR: Could not find chrome.exe.
echo(
pause
exit /b 1

rem Plain IF tests, not a FOR list: %ProgramFiles(x86)% contains a closing
rem paren that would terminate a parenthesized block early.
:find_chrome
set "CHROME="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if defined CHROME exit /b 0
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if defined CHROME exit /b 0
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
exit /b 0
