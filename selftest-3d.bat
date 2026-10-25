@echo off
REM Plushy AI - 3D pipeline self-test (GPU PC, Windows).
REM Runs one real image-to-3D conversion inside the Docker image and
REM verifies the GLB is a real textured mesh (a sphere can never pass).
REM First run downloads the SF3D model (~3GB) into the plushy-hf volume;
REM that needs HF_TOKEN set on this PC and access granted once on the
REM SF3D model page (same Hugging Face account as the token).
title Plushy AI 3D Self-Test
cd /d "%~dp0"

docker --version >nul 2>&1
if errorlevel 1 (
    echo   Docker not found. Start Docker Desktop first, then run this again.
    pause
    exit /b 1
)

docker image inspect plushy-ai >nul 2>&1
if errorlevel 1 (
    echo   The plushy-ai image is not built yet. Run start-gui.bat once
    echo   ^(it builds the image^), close it, then run this again.
    pause
    exit /b 1
)

if not defined HF_TOKEN (
    echo   NOTE: HF_TOKEN is not set on this PC. The first run needs it to
    echo   download the SF3D model. Stop this window, set HF_TOKEN in
    echo   PowerShell, and run this file again if the test fails with a
    echo   401 / gated error below.
    echo.
)

echo Running the 3D self-test inside the container...
docker run --rm --gpus all -e HF_TOKEN -v "%CD%:/app" -v plushy-hf:/root/.cache/huggingface plushy-ai python tools/selftest_3d.py
echo.
echo Exit code: %ERRORLEVEL%  (0 = SELFTEST PASS)
pause
