@echo off
rem send_daily_ranking.py를 평일 09:30/15:30에 실행하는 Windows 작업 스케줄러 작업을 등록한다.
rem daily_ranking_task.xml에 트리거(월~금 09:30, 15:30) / 실행 계정(S4U, 비밀번호 불필요) /
rem "놓친 작업 실행"(StartWhenAvailable) 설정이 모두 정의되어 있으므로,
rem 이 배치 파일은 그 XML을 schtasks로 가져오기만 한다.
rem
rem 사용법: 이 파일을 더블클릭하거나 "관리자 권한으로 실행"한다.
rem (일반 사용자 권한으로도 등록 가능하지만, 관리자 권한이 더 안정적으로 동작한다)

chcp 65001 >nul
setlocal

set "TASK_NAME=StockDailyRanking"
set "SCRIPT_DIR=%~dp0"
set "XML_PATH=%SCRIPT_DIR%daily_ranking_task.xml"

echo [INFO] 작업 "%TASK_NAME%"을(를) 등록합니다...
echo [INFO] XML 정의 파일: %XML_PATH%
echo.

schtasks /create /tn "%TASK_NAME%" /xml "%XML_PATH%" /f

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [FAIL] 작업 등록에 실패했습니다. ^(오류 코드: %ERRORLEVEL%^)
    echo [FAIL] 관리자 권한으로 다시 실행해보세요.
    goto :end
)

echo.
echo [INFO] 작업 등록 완료. 등록된 작업 정보:
echo.
schtasks /query /tn "%TASK_NAME%" /v /fo LIST

echo.
echo [INFO] 작업을 삭제하려면 다음 명령을 사용하세요:
echo   schtasks /delete /tn "%TASK_NAME%" /f
echo [INFO] 지금 바로 한 번 실행해서 테스트하려면 다음 명령을 사용하세요:
echo   schtasks /run /tn "%TASK_NAME%"

:end
endlocal
pause
