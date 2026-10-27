@echo off
chcp 65001 >nul
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\CampusClaw.ps1" -Action Stop %*
set "CAMPUSCLAW_EXIT=%ERRORLEVEL%"
if not "%CAMPUSCLAW_NO_PAUSE%"=="1" pause
exit /b %CAMPUSCLAW_EXIT%
