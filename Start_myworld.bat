@echo off
setlocal
cd /d "%~dp0"
if exist "runtime\pythonw.exe" (
    start "" "%~dp0runtime\pythonw.exe" "%~dp0launcher.py" %*
    exit /b 0
)
if exist ".venv\Scripts\python.exe" goto deps
py -3.12 -V >nul 2>&1
if not errorlevel 1 (
    py -3.12 -m venv .venv
    goto deps
)
python -V >nul 2>&1
if not errorlevel 1 (
    python -m venv .venv
    goto deps
)
echo Install Python 3.12 64-bit from python.org, or use the portable package.
pause
exit /b 1
:deps
if not exist ".venv\Scripts\python.exe" goto failed
".venv\Scripts\python.exe" -c "import PySide6,pymupdf" >nul 2>&1
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" launcher.py %*
if errorlevel 1 goto failed
exit /b 0
:failed
echo Launch failed. Copy the error shown above for troubleshooting.
pause
exit /b 1
