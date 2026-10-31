@echo off
setlocal
cd /d "%~dp0"
if exist "runtime\python.exe" (
    "runtime\python.exe" app.py %*
    pause
    exit /b
)
call Start_myworld.bat %*
