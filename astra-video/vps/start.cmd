@echo off
cd /d "%~dp0"
if exist STOP del STOP
py -3 runner.py
pause
