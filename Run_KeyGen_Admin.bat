@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Muse Studio - Admin License Key Generator

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" Muse_KeyGen_Admin.py
) else (
    python Muse_KeyGen_Admin.py
)
