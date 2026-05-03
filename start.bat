@echo off
setlocal enabledelayedexpansion

:: ========================================================================
:: Techie Backtester - Start Script (Windows dev)
::
:: Inc 0: backend only. The frontend folder is added in Inc 1; once it
:: exists this script will also start Vite on FRONTEND_PORT.
::
:: First-time setup:
::   poetry install
:: ========================================================================

set BACKEND_PORT=8103
set FRONTEND_PORT=5177
set PROJECT_DIR=%~dp0

echo.
echo === Techie Backtester Startup ===
echo.

:: --------------------------------------------------------------------
:: 1. Kill previous instances
:: --------------------------------------------------------------------
echo [1/3] Clearing previous instances...

taskkill /FI "WINDOWTITLE eq TechieBacktester-Backend" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq TechieBacktester-Frontend" /F >nul 2>&1

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%BACKEND_PORT% ^| findstr LISTENING') do (
    echo   Killing PID %%a on port %BACKEND_PORT%
    taskkill /PID %%a /F >nul 2>&1
)

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%FRONTEND_PORT% ^| findstr LISTENING') do (
    echo   Killing PID %%a on port %FRONTEND_PORT%
    taskkill /PID %%a /F >nul 2>&1
)

timeout /t 2 /nobreak >nul
echo   Ports cleared.

:: --------------------------------------------------------------------
:: 2. Start the backend
:: --------------------------------------------------------------------
echo [2/3] Starting backend on port %BACKEND_PORT%...
start "TechieBacktester-Backend" cmd /c "cd /d "%PROJECT_DIR%" && poetry run uvicorn techie_backtester.server:app --reload --host 127.0.0.1 --port %BACKEND_PORT%"

echo   Waiting for backend...
set BACKEND_READY=0
for /L %%i in (1,1,30) do (
    if !BACKEND_READY! == 0 (
        timeout /t 1 /nobreak >nul
        curl -s -o nul -w "%%{http_code}" http://127.0.0.1:%BACKEND_PORT%/api/health >"%TEMP%\tbt_health.txt" 2>nul
        set /p HEALTH_CODE=<"%TEMP%\tbt_health.txt"
        if "!HEALTH_CODE!" == "200" (
            set BACKEND_READY=1
            echo.
            echo   Backend ready.
        ) else (
            <nul set /p =.
        )
    )
)

if !BACKEND_READY! == 0 (
    echo.
    echo   WARNING: Backend did not respond after 30s. Continuing anyway...
)

:: --------------------------------------------------------------------
:: 3. Open browser to backend docs (no frontend yet in Inc 0)
:: --------------------------------------------------------------------
echo [3/3] Opening browser to API docs...
start "" http://127.0.0.1:%BACKEND_PORT%/docs

echo.
echo === Running ===
echo   Backend:  http://127.0.0.1:%BACKEND_PORT%
echo   Health:   http://127.0.0.1:%BACKEND_PORT%/api/health
echo   Docs:     http://127.0.0.1:%BACKEND_PORT%/docs
echo.
echo   (Frontend on port %FRONTEND_PORT% will be added in Inc 1.)
echo.
echo Close the Backend window to stop, or run start.bat again to restart.
echo.

endlocal
