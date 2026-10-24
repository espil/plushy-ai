@echo off
REM Plushy AI Studio - REAL generation GUI launcher (GPU PC, Windows).
REM Unlike start.bat (mock placeholders, no GPU), this runs the Docker
REM image with the GPU so the Studio generates real sprites.
REM
REM   This PC:      http://localhost:8000/studio
REM   Laptop/other: http://<this PC's LAN IP>:8000/studio   (same Wi-Fi/LAN)
REM                 The laptop can send prompts from its browser while
REM                 this PC stays on. The gallery shows everything in
REM                 the shared output folder.
REM
REM Outputs: by default PNGs are written to
REM   %OneDrive%\Plushy AI\outputs
REM so they sync to OneDrive and can be shared with the Muse team.
REM Set PLUSHY_OUTPUT_DIR before running to use a different folder.
REM
REM The repo folder is mounted into the container, so after a git pull
REM the new code and prompt files are live on the next start without a
REM rebuild. Rebuild only when Dockerfile or requirements.txt changed.
REM
REM If the laptop cannot connect, allow Docker Desktop / port 8000
REM through Windows Firewall on this PC (Private network).
title Plushy AI Studio (GPU + LAN)
cd /d "%~dp0"

echo [1/4] Checking Docker...
docker --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo   Docker not found. Start Docker Desktop first, then run this again.
    echo.
    pause
    exit /b 1
)

docker image inspect plushy-ai >nul 2>&1
if errorlevel 1 (
    echo [2/4] Building image ^(first run only, a few minutes^)...
    docker build -t plushy-ai .
    if errorlevel 1 (
        echo   Image build failed - send the error above to Roman.
        pause
        exit /b 1
    )
) else (
    echo [2/4] Image found. Repo is mounted live, so git pull updates apply on restart.
)

if defined PLUSHY_OUTPUT_DIR (
    set "HOST_OUTPUT_DIR=%PLUSHY_OUTPUT_DIR%"
) else if defined OneDrive (
    set "HOST_OUTPUT_DIR=%OneDrive%\Plushy AI\outputs"
) else (
    set "HOST_OUTPUT_DIR=%CD%\outputs"
)
if not exist "%HOST_OUTPUT_DIR%" mkdir "%HOST_OUTPUT_DIR%"
echo [3/4] Output folder: %HOST_OUTPUT_DIR%

echo [4/4] Starting Plushy AI Studio on port 8000 for this PC and the LAN...
echo.
echo   On this PC:    http://localhost:8000/studio
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do echo   On a laptop:   http://%%a:8000/studio  (same LAN)
echo.
echo   Keep this window and Docker Desktop running while the laptop works.
echo   Generated PNGs are saved to the output folder above. If it is the
echo   OneDrive folder, keep OneDrive signed in and syncing to share them.
echo   Press CTRL+C here to stop the server.
echo.
timeout /t 3 >nul
start http://localhost:8000/studio
docker run --rm --name plushy-gui --gpus all -p 0.0.0.0:8000:8000 -e PLUSHY_OUTPUT_DIR=/app/outputs -v "%CD%:/app" -v "%HOST_OUTPUT_DIR%:/app/outputs" -v plushy-hf:/root/.cache/huggingface plushy-ai
echo.
echo Server stopped.
pause
