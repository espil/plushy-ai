@echo off
REM Plushy AI Studio - REAL generation GUI launcher (GPU PC, Windows).
REM Unlike start.bat (mock placeholders, no GPU), this runs the Docker
REM image with the GPU so the Studio generates real sprites.
REM
REM   This PC:      http://localhost:8000/studio
REM   Another PC:   http://<this PC's LAN IP>:8000/studio   (same Wi-Fi/LAN)
REM                 -> the gallery shows everything generated so far,
REM                    served from the outputs folder mounted below.
REM If the other PC cannot connect, allow Docker Desktop / port 8000
REM through Windows Firewall on this PC (Private network prompt).
title Plushy AI Studio (GPU)
cd /d "%~dp0"

echo [1/3] Checking Docker...
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
    echo [2/3] Building image ^(first run only, a few minutes^)...
    docker build -t plushy-ai .
    if errorlevel 1 (
        echo   Image build failed - send the error above to Roman.
        pause
        exit /b 1
    )
) else (
    echo [2/3] Image found. ^(After a git pull, rebuild with: docker build -t plushy-ai .^)
)

if not exist "outputs" mkdir outputs

echo [3/3] Starting Plushy AI Studio on port 8000...
echo.
echo   On this PC:    http://localhost:8000/studio
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do echo   On another PC: http://%%a:8000/studio  (same LAN)
echo.
echo   Generated PNGs are saved in this folder's outputs\ - they stay
echo   on disk after the server stops. Press CTRL+C here to stop.
echo.
timeout /t 3 >nul
start http://localhost:8000/studio
docker run --rm --name plushy-gui --gpus all -p 8000:8000 -v "%CD%\outputs:/app/outputs" -v plushy-hf:/root/.cache/huggingface plushy-ai
echo.
echo Server stopped.
pause
