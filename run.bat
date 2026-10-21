@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set NO_PROXY=127.0.0.1,localhost
set no_proxy=127.0.0.1,localhost
cd /d "%~dp0"
title Muse Studio - AI Media & Video (Desktop App)

echo ========================================================
echo   MUSE STUDIO - AI MEDIA ^& VIDEO DESKTOP APPLICATION
echo   Che do: Cua so Desktop doc lap (1440x900)
echo ========================================================

REM 1. Kiem tra Python (Tu dong cai dat ngam qua winget neu may khach chua co Python)
if not exist ".venv\Scripts\python.exe" (
    python --version >nul 2>&1
    if errorlevel 1 (
        echo [Auto-Setup] May tinh chua co Python. Dang tu dong cai dat Python 3.12...
        winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
        set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
    )
    echo [0/3] Dang khoi tao moi truong ao .venv...
    python -m venv .venv
)

set "PY_CMD=.venv\Scripts\python.exe"

REM 2. Kiem tra FFmpeg (Tu dong cai dat ngam neu may khach chua co FFmpeg de ghep Video dai)
where ffmpeg >nul 2>&1
if errorlevel 1 (
    if not exist "C:\ffmpeg\bin\ffmpeg.exe" (
        echo [1/3] Dang tu dong cai dat FFmpeg ho tro ghep Chuoi Video Dai...
        winget install -e --id Gyan.FFmpeg --silent --accept-package-agreements --accept-source-agreements >nul 2>&1
    )
)

echo [2/3] Dang kiem tra thu vien Desktop (pywebview / FastAPI / Playwright)...
"%PY_CMD%" -m pip install -r requirements.txt --quiet --no-warn-script-location
if not errorlevel 1 (
    echo ready > ".venv\.muse_deps_ready"
)

echo [3/3] Dang mo cua so ung dung Desktop Muse Studio (1440x900)...
"%PY_CMD%" app.py
