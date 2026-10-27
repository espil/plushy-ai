@echo off
REM Plushy AI - Waitemata buildings 3D batch V2 (GPU PC).
REM Converts the 18 isometric building images in inputs\waitemata_v2\
REM to spec GLBs at texture resolution 2048 (v2 setting) into
REM outputs\models3d_v2\ - a separate folder, so the discarded v1
REM outputs in models3d\ can never be mistaken for these or cause
REM false resumable skips. Landmark: b09 chief hall (20k budget).
REM Resumable within the v2 folder: finished assets are skipped.
REM At roughly 4-5 min per asset the batch takes about 1.5 hours
REM unattended. Everything is already cached - no downloads, and
REM HF_TOKEN is not needed any more.
title Plushy AI Waitemata V2 3D Batch
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

if not exist "outputs" mkdir outputs
echo Producing 18 Waitemata V2 GLBs into outputs\models3d_v2\ ...
docker run --rm --gpus all -e HF_TOKEN -e PLUSHY_OUTPUT_DIR=/app/outputs -v "%CD%:/app" -v "%CD%\outputs:/app/outputs" -v plushy-hf:/root/.cache/huggingface plushy-ai python run_buildings_3d.py --manifest waitemata_v2_manifest.json --inputs inputs/waitemata_v2 --texture 2048 --out /app/outputs/models3d_v2 %*
echo.
echo Exit code: %ERRORLEVEL%  (0 = all assets done)
pause
