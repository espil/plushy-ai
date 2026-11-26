@echo off
rem Plushy-AI quality-mode (Hunyuan3D) verification run.
rem Double-click this file, wait for it to finish, then send back
rem quality-sample-log.txt from this same folder. Nothing to type.
rem First run is long: it may build the Docker image (one-time) and
rem download the quality weights (one-time), then converts three
rem bundled building images on the GPU.
cd /d %~dp0
python run_quality_sample.py
echo.
echo ============================================================
echo  Finished. Please send back this file:
echo  %~dp0quality-sample-log.txt
echo ============================================================
pause
