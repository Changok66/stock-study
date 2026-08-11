@echo off
rem Registers a Windows Task Scheduler task that runs watch_trades.py
rem every 15 minutes on weekdays between 09:00 and 15:30.
rem watch_trades_task.xml already defines the trigger (Mon-Fri 09:00-15:30,
rem repeating every 15 minutes), the run-as account (S4U, no password
rem required), and the "run task as soon as possible after a scheduled
rem start is missed" (StartWhenAvailable) option, so this batch file only
rem imports that XML via schtasks.
rem
rem Usage: double-click this file, or "Run as administrator".
rem (It can also be registered with a standard user account, but running as
rem administrator is more reliable.)

setlocal

set "TASK_NAME=StockTradeWatcher"
set "SCRIPT_DIR=%~dp0"
set "XML_PATH=%SCRIPT_DIR%watch_trades_task.xml"

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
