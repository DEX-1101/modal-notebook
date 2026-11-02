@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 goto nopython

python -c "import PySide6" >nul 2>nul
if errorlevel 1 (
    echo Installing the interface library PySide6, one moment...
    python -m pip install PySide6
    if errorlevel 1 goto fail
)

where pythonw >nul 2>nul
if errorlevel 1 (
    python modal_gui.py
) else (
    start "" pythonw modal_gui.py
)
exit /b 0

:nopython
echo Python was not found. Install Python 3.10 or newer from python.org
echo and tick "Add python.exe to PATH" during install.
pause
exit /b 1

:fail
echo Could not install PySide6. Check your internet connection and try again.
pause
exit /b 1
