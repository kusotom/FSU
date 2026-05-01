@echo off
chcp 65001 >nul
set "PROJECT_ROOT=C:\Users\测试\Desktop\动环\fsu-platform"
set "LOG_FILE=%PROJECT_ROOT%\backend\logs\fsu_raw_packets\readonly-observation-scheduler.log"
cd /d "%PROJECT_ROOT%"
echo [%DATE% %TIME%] Starting FSU readonly observation >> "%LOG_FILE%"
node backend\scripts\run-fsu-readonly-observation.js >> "%LOG_FILE%" 2>&1
echo [%DATE% %TIME%] Finished FSU readonly observation with exit code %ERRORLEVEL% >> "%LOG_FILE%"
