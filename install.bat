@echo off
setlocal
cd /d "%~dp0"
echo === Tieu Vu One-Click Installer ===

set "PY=python"
py -3.11 --version >nul 2>nul && set "PY=py -3.11"
%PY% --version 2>nul | findstr /R "3.1[1234]" >nul || (
    echo [ERROR] Python 3.11+ required
    timeout /t 5 /nobreak >nul & exit /b 1
)

if not exist .venv %PY% -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet || (echo [ERROR] pip requirements & timeout /t 5 /nobreak >nul & exit /b 1)
pip install -r requirements-dev.txt --quiet || (echo [ERROR] pip requirements-dev & timeout /t 5 /nobreak >nul & exit /b 1)

if not exist "models\vosk-model-vn-0.4" (
    echo [Downloading Vosk VN model 78MB...]
    powershell -NoProfile -Command "Invoke-WebRequest 'https://alphacephei.com/vosk/models/vosk-model-vn-0.4.zip' -OutFile 'models\vosk.zip'"
    powershell -NoProfile -Command "Expand-Archive -Path 'models\vosk.zip' -DestinationPath 'models' -Force"
    del models\vosk.zip
)

powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_startup_windows.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_auto_dev_windows.ps1
if errorlevel 1 echo [WARN] Auto-dev task not registered (needs Administrator).

if /i "%~1"=="--calibrate" (
    echo [Calibrating gaze...]
    python main.py --calibrate
) else (
    echo [SKIP] Gaze calibration - run: python main.py --calibrate
)

echo.
echo === INSTALL COMPLETE ===
echo Reboot to activate auto-start.
