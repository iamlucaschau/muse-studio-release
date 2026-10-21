@echo off
chcp 65001 >nul
title Muse Studio (AI Media & Video Automation)
cd /d "%~dp0"

echo ============================================================
echo   MUSE STUDIO - AI MEDIA ^& VIDEO AUTOMATION
echo   Dang don cong 18688 va khoi dong Server...
echo ============================================================

powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 18688 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"

python app.py
pause
