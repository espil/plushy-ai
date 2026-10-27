@echo off
REM Plushy AI - Villages + Caves V2 3D batch (43 assets).
REM New isometric source art (v2 standard), texture 2048, outputs to
REM outputs\models3d_v2\ beside the Waitemata V2 results. Each asset
REM produces a compressed GLB plus an uncompressed twin for Unity.
REM Finished assets (GLB + sidecar + twin all present) are skipped,
REM so this can be re-run safely at any time.
title Plushy AI Villages V2 3D Batch
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

docker run --rm --gpus all -e HF_TOKEN -e PLUSHY_OUTPUT_DIR=/app/outputs -v "%CD%:/app" -v "%CD%\outputs:/app/outputs" -v plushy-hf:/root/.cache/huggingface plushy-ai python run_buildings_3d.py --manifest villages_v2_manifest.json --inputs inputs/villages_v2 --texture 2048 --out /app/outputs/models3d_v2

echo.
echo Villages V2 batch finished with exit code %ERRORLEVEL%.
echo Results are in outputs\models3d_v2\
pause
