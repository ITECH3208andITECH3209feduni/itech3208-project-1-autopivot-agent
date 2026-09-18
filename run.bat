@echo off
REM ===========================================================================
REM AutoPivot - start the site
REM
REM Opens two windows: the API (port 8000) and the website (port 5173).
REM Close either window to stop that half. Run setup.bat first.
REM ===========================================================================

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: no virtual environment found.
    echo Run setup.bat first.
    echo.
    pause
    exit /b 1
)

if not exist "frontend\node_modules" (
    echo ERROR: the website's dependencies are not installed.
    echo Run setup.bat first.
    echo.
    pause
    exit /b 1
)

echo.
echo Starting AutoPivot ...
echo.
echo   API      http://127.0.0.1:8000
echo   Website  http://localhost:5173      ^<- open this one
echo.
echo Two new windows will open. Close them to stop the servers.
echo.

REM The API loads several gigabytes of vision models on its first request, so
REM it is started first and given a moment before the browser can reach it.
start "AutoPivot API" cmd /k "cd /d "%~dp0" && call .venv\Scripts\activate.bat && python autopivot_backend.py"

timeout /t 3 /nobreak >nul

start "AutoPivot Website" cmd /k "cd /d "%~dp0" && npm run dev --prefix frontend"

timeout /t 4 /nobreak >nul
start "" http://localhost:5173

echo Done. This window can be closed.
timeout /t 5 /nobreak >nul
