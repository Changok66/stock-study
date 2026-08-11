@echo off
rem Registers a Windows Task Scheduler task that runs send_daily_ranking.py
rem on weekdays at 09:30 and 15:30.
rem daily_ranking_task.xml already defines the triggers (Mon-Fri 09:30, 15:30),
rem the run-as account (S4U, no password required), and the "run task as soon
rem as possible after a scheduled start is missed" (StartWhenAvailable) option,
rem so this batch file only imports that XML via schtasks.
rem
rem Usage: double-click this file, or "Run as administrator".
rem (It can also be registered with a standard user account, but running as
rem administrator is more reliable.)

setlocal

set "TASK_NAME=StockDailyRanking"
set "SCRIPT_DIR=%~dp0"
set "XML_PATH=%SCRIPT_DIR%daily_ranking_task.xml"

echo [INFO] Registering task "%TASK_NAME%"...
echo [INFO] XML definition file: %XML_PATH%
echo.

schtasks /create /tn "%TASK_NAME%" /xml "%XML_PATH%" /f

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [FAIL] Failed to register the task. ^(Error code: %ERRORLEVEL%^)
    echo [FAIL] Try running this file as administrator.
    goto :end
)

echo.
echo [INFO] Task registered successfully. Task details:
echo.
schtasks /query /tn "%TASK_NAME%" /v /fo LIST

echo.
echo [INFO] To delete the task, use the following command:
echo   schtasks /delete /tn "%TASK_NAME%" /f
echo [INFO] To run it once right now for testing, use the following command:
echo   schtasks /run /tn "%TASK_NAME%"

:end
endlocal
pause
