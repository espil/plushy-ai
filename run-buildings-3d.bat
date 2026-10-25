@echo off
REM Plushy AI - Waitemata building 3D batch (GPU PC, Windows).
REM Converts the 18 isometric building images in inputs\buildings_iso\
REM to spec GLBs (low-poly + textures + gltfpack) in outputs\models3d\.
REM Resumable: finished buildings are skipped on re-run. Extra args are
REM passed through, e.g.  run-buildings-3d.bat --only wm_b04_family_house
REM First run downloads the SF3D model (~3GB) into the plushy-hf volume;
REM that needs HF_TOKEN set on this PC and access granted once on the
REM SF3D model page (same Hugging Face account as the token).
title Plushy AI Building 3D Batch
cd /d "%~dp0"

docker --version >nul 2>&1
if errorlevel 1 (
    echo   Docker not found. Start Docker Desktop first, then run this again.
    pause
    exit /b 1
)

docker image inspect plushy-ai >nul 2>&1
if errorlevel 1 (
    echo   The plushy-ai image is not built yet. Build it first:
    echo     docker build -t plushy-ai .
    pause
    exit /b 1
)

if not defined HF_TOKEN (
    echo   NOTE: HF_TOKEN is not set on this PC. The first run needs it to
    echo   download the SF3D model. If every building fails with a 401 /
    echo   gated error, stop this window, set HF_TOKEN in PowerShell,
    echo   and run this file again - finished buildings are skipped.
    echo.
)

if not exist "outputs" mkdir outputs
echo Producing building GLBs into outputs\models3d\ ...
docker run --rm --gpus all -e HF_TOKEN -e PLUSHY_OUTPUT_DIR=/app/outputs -v "%CD%:/app" -v "%CD%\outputs:/app/outputs" -v plushy-hf:/root/.cache/huggingface plushy-ai python run_buildings_3d.py %*
echo.
echo Exit code: %ERRORLEVEL%  (0 = all buildings done)
pause
