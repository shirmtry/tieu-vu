@echo off
REM =====================================================================
REM tieu-vu — chay nhanh tren Windows
REM =====================================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [setup] Tao moi truong ao Python...
    py -3.11 -m venv .venv || python -m venv .venv
    if errorlevel 1 goto :error
)

echo [setup] Cai dependencies (bo qua neu da co)...
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt

echo [run] Khoi dong Tieu Vu...
".venv\Scripts\python.exe" main.py --dev
goto :eof

:error
echo [error] Khong the chuan bi moi truong. Kiem tra Python 3.11/3.12.
pause
