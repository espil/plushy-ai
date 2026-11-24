@echo off
rem Plushy-AI 2.0 first sample run + real-GPU verification.
rem Double-click this file, wait for it to finish, then send back
rem sample-v2-log.txt from this same folder. Nothing to type.
cd /d %~dp0
python run_sample_v2.py
echo.
echo ============================================================
echo  Finished. Please send back this file:
echo  %~dp0sample-v2-log.txt
echo ============================================================
pause
