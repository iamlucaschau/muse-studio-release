@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Muse Studio - Admin OTA Update Publisher & Customer Packager

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" Publish_Update_Admin.py
) else (
    python Publish_Update_Admin.py
)
