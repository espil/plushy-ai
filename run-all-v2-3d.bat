@echo off
REM Plushy AI - ALL V2 3D batches, chained for a full unattended day.
REM Stage 1: Waitemata buildings v2 (18) -> outputs\models3d_v2\
REM Then a git pull refreshes the inputs (with the stale-ref fix
REM applied automatically if the pull fails), and Stage 2 runs the
REM villages + dungeon entrances v2 batch (43) into the same
REM outputs\models3d_v2\ folder when its package has arrived.
REM Every stage is resumable: finished assets are skipped, so this
REM bat can be closed and restarted at any point without loss.
title Plushy AI All V2 3D Batches
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

echo === Stage 1 of 2: Waitemata buildings V2 (18) ===
docker run --rm --gpus all -e HF_TOKEN -e PLUSHY_OUTPUT_DIR=/app/outputs -v "%CD%:/app" -v "%CD%\outputs:/app/outputs" -v plushy-hf:/root/.cache/huggingface plushy-ai python run_buildings_3d.py --manifest waitemata_v2_manifest.json --inputs inputs/waitemata_v2 --texture 2048 --out /app/outputs/models3d_v2
echo Stage 1 exit code: %ERRORLEVEL%

echo.
echo === Refreshing inputs from GitHub ===
git pull
if errorlevel 1 (
    echo   Pull failed - applying the stale remote-ref fix and retrying.
    git update-ref -d refs/remotes/origin/main
    git pull
)

if exist "villages_v2_manifest.json" (
    echo.
    echo === Stage 2 of 2: Villages + Caves V2 (43) ===
    docker run --rm --gpus all -e HF_TOKEN -e PLUSHY_OUTPUT_DIR=/app/outputs -v "%CD%:/app" -v "%CD%\outputs:/app/outputs" -v plushy-hf:/root/.cache/huggingface plushy-ai python run_buildings_3d.py --manifest villages_v2_manifest.json --inputs inputs/villages_v2 --texture 2048 --out /app/outputs/models3d_v2
    echo Stage 2 exit code: %ERRORLEVEL%
) else (
    echo.
    echo Villages V2 package has not arrived in this clone yet - stage 2 skipped.
    echo Run run-villages-v2-3d.bat later, after a git pull.
)
echo.
echo All stages finished.
pause
