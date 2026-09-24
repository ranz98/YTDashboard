@echo off
cd /d "%~dp0"
type nul > STOP
echo Stop requested. Wait for the runner to finish stopping the current stage.
