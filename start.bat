@echo off
REM Plushy AI - double-click launcher (mock mode, no GPU needed).
REM Sets everything up on first run, then just starts the server.
title Plushy AI
cd /d "%~dp0"

echo [1/4] Checking Python...
set PYCMD=py
py --version >nul 2>&1
if errorlevel 1 (
    python --version >nul 2>&1
    if errorlevel 1 (
        echo.
        echo   Python not found. Install it from https://www.python.org/downloads/
        echo   ^(tick "Add python.exe to PATH" on the first installer screen^)
        echo.
        pause
        exit /b 1
    )
    set PYCMD=python
)

if not exist ".venv" (
    echo [2/4] Creating virtual environment ^(first run only^)...
    %PYCMD% -m venv .venv
    if errorlevel 1 (
        echo   Failed to create virtual environment.
        pause
        exit /b 1
    )
) else (
    echo [2/4] Virtual environment found.
)

call .venv\Scripts\activate.bat

echo [3/4] Installing dependencies ^(first run takes a minute or two^)...
python -m pip install -q --upgrade pip
python -m pip install -q fastapi uvicorn python-multipart httpx pillow numpy
if errorlevel 1 (
    echo.
    echo   Dependency install failed. Run this file again;
    echo   if it persists, send the error above to Roman.
    echo.
    pause
    exit /b 1
)

set PLUSHY_MOCK=1
echo [4/4] Starting Plushy AI...
echo.
echo   Opening http://localhost:8000/studio in your browser.
echo   Press CTRL+C here to stop the server.
echo.
timeout /t 2 >nul
start http://localhost:8000/studio
python -m uvicorn app:app --port 8000
echo.
echo Server stopped.
pause
