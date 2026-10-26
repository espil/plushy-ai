@echo off
REM Plushy AI - 3D asset prefetch (GPU PC, Windows).
REM Downloads the SF3D weights, the DINOv2 image tokenizer and rembg's
REM u2net model into the plushy-hf volume, WITH progress visible, and
REM verifies each cache is complete. Run this once before the first
REM self-test / building batch; afterwards conversions run offline.
REM Needs HF_TOKEN set on this PC (the SF3D model is gated; access is
REM granted once on its Hugging Face page, same account as the token).
title Plushy AI 3D Prefetch
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
    echo   NOTE: HF_TOKEN is not set on this PC. The SF3D download needs it.
    echo   Set HF_TOKEN in PowerShell first, then run this file again.
    echo.
    pause
    exit /b 1
)

echo Downloading and verifying all 3D assets...
docker run --rm -e HF_TOKEN -v "%CD%:/app" -v plushy-hf:/root/.cache/huggingface plushy-ai python tools/prefetch_3d.py
echo.
echo Exit code: %ERRORLEVEL%  (0 = PREFETCH PASS)
pause
