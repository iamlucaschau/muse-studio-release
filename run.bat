@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Muse Studio (AI Media & Video Automation) - http://127.0.0.1:18688

echo ========================================================
echo   MUSE STUDIO - AI MEDIA & VIDEO AUTOMATION ENGINE
echo   URL: http://127.0.0.1:18688
echo ========================================================

if exist ".venv\Scripts\python.exe" (
    set "PY_CMD=.venv\Scripts\python.exe"
) else (
    set "PY_CMD=python"
)

echo [1/2] Dang kiem tra thu vien Python...
%PY_CMD% -m pip install -r requirements.txt --quiet --no-warn-script-location

echo [2/2] Dang khoi chay Muse Studio Server tai http://127.0.0.1:18688 ...
%PY_CMD% app.py

pause
