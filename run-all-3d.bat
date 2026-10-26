@echo off
REM Plushy AI - 3D pipeline ALL-IN-ONE run (GPU PC, Windows).
REM One double-click: environment check, asset prefetch + verify,
REM self-test, then the full Waitemata building batch. Everything is
REM logged to outputs\run-all-log.txt - send that ONE file back.
REM Needs HF_TOKEN set on this PC (first download only; afterwards
REM everything is cached and runs offline).
title Plushy AI 3D - All In One
cd /d "%~dp0"

docker --version >nul 2>&1
if errorlevel 1 (
    echo   Docker not found. Start Docker Desktop first, then run this again.
    pause
    exit /b 1
)

docker image inspect plushy-ai >nul 2>&1
if errorlevel 1 (
    echo   The plushy-ai image is not built yet. Build it first
    echo   ^(docker build -t plushy-ai .^), then run this again.
    pause
    exit /b 1
)

if not defined HF_TOKEN (
    echo   NOTE: HF_TOKEN is not set on this PC. Set it in PowerShell
    echo   first ^(needed only until the models are cached^).
    pause
    exit /b 1
)

echo Running everything: prefetch, self-test, building batch...
echo Log: outputs\run-all-log.txt
docker run --rm --gpus all -e HF_TOKEN -v "%CD%:/app" -v plushy-hf:/root/.cache/huggingface plushy-ai python tools/run_all_3d.py
echo.
echo Exit code: %ERRORLEVEL%  (0 = ALL PASS - see outputs\run-all-log.txt)
pause
