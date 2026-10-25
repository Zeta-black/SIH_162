@echo off
REM FIRETRACE demo launcher (double-click friendly)
REM   demo.bat            live feed when available, archive when not
REM   demo.bat offline    force the offline archive
cd /d "%~dp0"
where node >nul 2>nul
if errorlevel 1 (
  echo.
  echo   Node.js 18+ was not found on PATH.
  echo   Install it from https://nodejs.org and run this again.
  echo.
  pause
  exit /b 1
)
if /i "%~1"=="offline" (
  node --no-deprecation scripts\demo.mjs --offline
) else (
  node --no-deprecation scripts\demo.mjs
)
if errorlevel 1 pause
