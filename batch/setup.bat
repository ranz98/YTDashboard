@echo off
setlocal
title First Short Grabber - one-time setup

rem ---------------------------------------------------------------------------
rem Run this ONCE. It creates a dedicated Chrome profile beside this script,
rem points that profile's downloads at .\output, and opens chrome://extensions
rem so you can load the extension into it.
rem
rem A dedicated profile is required: Chrome 137+ ignores --load-extension, so
rem the extension has to live in a profile that persists. A separate profile
rem also keeps all of this away from your everyday Chrome.
rem ---------------------------------------------------------------------------

set "BATCH_DIR=%~dp0"
if "%BATCH_DIR:~-1%"=="\" set "BATCH_DIR=%BATCH_DIR:~0,-1%"
for %%I in ("%BATCH_DIR%\..") do set "BASE=%%~fI"
set "PROFILE=%BASE%\chrome-profile"
set "OUTDIR=%BASE%\output"
set "EXTDIR=%BASE%\extension"

call :find_chrome
if not defined CHROME goto :no_chrome

if not exist "%OUTDIR%" mkdir "%OUTDIR%"
if not exist "%PROFILE%\Default" mkdir "%PROFILE%\Default"

rem This sentinel file skips Chrome's first-run wizard.
if not exist "%PROFILE%\First Run" type nul > "%PROFILE%\First Run"

rem Seed the profile so downloads land in .\output with no save dialog.
rem PowerShell writes it so the Windows path is escaped correctly for JSON, and
rem WriteAllText is used rather than Set-Content because Chrome's preference
rem parser rejects the UTF-8 BOM that Set-Content -Encoding utf8 emits.
if exist "%PROFILE%\Default\Preferences" goto :prefs_ready
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = @{ download = @{ default_directory = '%OUTDIR%'; prompt_for_download = $false; directory_upgrade = $true }; profile = @{ exit_type = 'Normal'; exited_cleanly = $true }; browser = @{ has_seen_welcome_page = $true } }; [IO.File]::WriteAllText('%PROFILE%\Default\Preferences', ($p | ConvertTo-Json -Depth 5), (New-Object System.Text.UTF8Encoding $false))"
if errorlevel 1 echo   WARNING: could not seed download preferences - set the download folder manually.
:prefs_ready

cls
echo(
echo   ===============================================================
echo    First Short Grabber - one-time setup
echo   ===============================================================
echo(
echo    Chrome profile : %PROFILE%
echo    Output folder  : %OUTDIR%
echo(
echo   A separate Chrome window is opening on the Extensions page.
echo   In THAT window:
echo(
echo     1. Turn on  "Developer mode"   - toggle, top right
echo     2. Click    "Load unpacked"
echo     3. Choose this folder:
echo(
echo        %EXTDIR%
echo(
echo     4. Close that Chrome window once the extension is listed.
echo(
echo   Then you are done - use run.bat from now on.
echo(
echo   ===============================================================
echo(

start "" "%CHROME%" --user-data-dir="%PROFILE%" --no-first-run --no-default-browser-check "chrome://extensions"

echo   Press any key once you have loaded the extension...
pause >nul
exit /b 0

:no_chrome
echo(
echo   ERROR: Could not find chrome.exe in any of the usual locations.
echo   Install Google Chrome, or edit the find_chrome section of this script.
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
