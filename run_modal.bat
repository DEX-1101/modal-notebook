@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
title Modal Notebook

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install Python 3.10+ from python.org
    echo and tick "Add python.exe to PATH" during install.
    pause
    exit /b 1
)

:menu
cls
echo ==========================================
echo    Modal Notebook
echo ==========================================
echo.
echo   1. First-time setup (install Modal, log in, save HF token)
echo   2. Start JupyterLab on Modal
echo   3. Start JupyterLab and RESET notebook to local file
echo   4. Download all my notebooks from Modal
echo   5. Download a folder from Modal
echo   6. STOP the running session (stops billing)
echo   7. Exit
echo.
set "choice="
set /p choice=Choose 1-7: 
if "%choice%"=="1" goto setup
if "%choice%"=="2" goto run
if "%choice%"=="3" goto runreset
if "%choice%"=="4" goto getnb
if "%choice%"=="5" goto getout
if "%choice%"=="6" goto stop
if "%choice%"=="7" exit /b 0
goto menu

:setup
echo.
echo [1/3] Installing Modal...
python -m pip install --upgrade modal
if errorlevel 1 goto fail
echo.
echo [2/3] Logging in to Modal (a browser window will open)...
python -m modal setup
if errorlevel 1 goto fail
echo.
echo [3/3] Save an API token as a Modal secret (optional).
echo Example: secret name = huggingface, variable name = HF_TOKEN.
echo Leave the secret name empty to skip. The token is visible while you type.
set "SNAME="
set /p SNAME=Secret name: 
if "%SNAME%"=="" goto setupdone
set "SVAR="
set /p SVAR=Variable name: 
set "SVAL="
set /p SVAL=Token: 
python -m modal secret create %SNAME% %SVAR%=%SVAL% --force
if errorlevel 1 goto fail
set "SVAL="
echo Saved. Add "%SNAME%" to the SECRETS list in modal_jupyter.py to give it to your notebooks.
:setupdone
echo.
echo Setup finished.
pause
goto menu

:run
set "MINS="
set /p MINS=Stop after how many idle minutes? (Enter = default, 0 = never): 
echo.
echo Keep this window open. Open the ">>> Open JupyterLab" link when it appears.
echo Press Ctrl+C to stop. You are billed while it runs, until it stops itself when idle.
echo.
if "%MINS%"=="" (
    python -m modal run modal_jupyter.py
) else (
    python -m modal run modal_jupyter.py --idle-minutes %MINS%
)
pause
goto menu

:runreset
set "MINS="
set /p MINS=Stop after how many idle minutes? (Enter = default, 0 = never): 
echo.
echo Keep this window open. Open the ">>> Open JupyterLab" link when it appears.
echo Press Ctrl+C to stop. You are billed while it runs, until it stops itself when idle.
echo.
if "%MINS%"=="" (
    python -m modal run modal_jupyter.py --reset
) else (
    python -m modal run modal_jupyter.py --idle-minutes %MINS% --reset
)
pause
goto menu

:getnb
echo.
python -m modal volume get modal-root /notebooks _notebook\from_modal --force
if errorlevel 1 goto fail
echo Done. Notebooks are in the _notebook\from_modal folder.
pause
goto menu

:getout
echo.
set "FOLDER="
set /p FOLDER=Folder inside your drive to download (for example outputs): 
if "%FOLDER%"=="" goto menu
python -m modal volume get modal-root /%FOLDER% modal_downloads\%FOLDER% --force
if errorlevel 1 goto fail
echo Done. Files are in the modal_downloads\%FOLDER% folder.
pause
goto menu

:stop
echo.
python -m modal app list
echo.
set "APPID="
set /p APPID=Paste the App ID (ap-...) of the running app to stop, or press Enter to cancel: 
if "%APPID%"=="" goto menu
python -m modal app stop %APPID%
pause
goto menu

:fail
echo.
echo Something went wrong. Read the message above, then try again.
pause
goto menu
