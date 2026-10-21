@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Muse Studio - AI Media & Video (Desktop App)

echo ========================================================
echo   MUSE STUDIO - AI MEDIA ^& VIDEO DESKTOP APPLICATION
echo   Che do: Cua so Desktop doc lap (1440x900)
echo ========================================================

if not exist ".venv\Scripts\python.exe" (
    echo [0/2] Dang khoi tao moi truong ao .venv...
    python -m venv .venv
)

set "PY_CMD=.venv\Scripts\python.exe"

echo [1/2] Dang kiem tra thu vien Desktop (pywebview / FastAPI)...
"%PY_CMD%" -m pip install -r requirements.txt --quiet --no-warn-script-location

echo [2/2] Dang mo cua so ung dung Desktop Muse Studio (1440x900)...
"%PY_CMD%" app.py
