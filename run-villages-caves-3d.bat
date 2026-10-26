@echo off
REM Plushy AI - village buildings + dungeon entrances 3D batch (GPU PC).
REM Converts the 43 images in inputs\villages_caves\ (six ruin
REM villages' buildings v01-v31 + dungeon entrances d01-d12) to spec
REM GLBs (low-poly + textures + gltfpack; village halls, the Leluh
REM royal court and the Pulemelei mound at the 20k landmark budget)
REM in outputs\models3d\, next to the Waitemata buildings.
REM Resumable: finished assets are skipped on re-run. Extra args are
REM passed through, e.g.  run-villages-caves-3d.bat --only d04_emberdeep_entrance
REM At the measured ~4 min per asset the full batch takes ~3 hours
REM unattended. Everything is already cached - no downloads, and
REM HF_TOKEN is not needed any more.
title Plushy AI Villages + Caves 3D Batch
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
echo Producing 43 village + cave GLBs into outputs\models3d\ ...
docker run --rm --gpus all -e HF_TOKEN -e PLUSHY_OUTPUT_DIR=/app/outputs -v "%CD%:/app" -v "%CD%\outputs:/app/outputs" -v plushy-hf:/root/.cache/huggingface plushy-ai python run_buildings_3d.py --manifest villages_caves_3d_manifest.json --inputs inputs/villages_caves %*
echo.
echo Exit code: %ERRORLEVEL%  (0 = all assets done)
pause
