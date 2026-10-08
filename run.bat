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

REM An old API window left open keeps serving the OLD code on port 8000, and a
REM new one cannot start - the website then shows results from the old code.
powershell -NoProfile -Command "if (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue) { exit 1 }; exit 0"
if errorlevel 1 (
    echo ERROR: port 8000 is already in use - an old AutoPivot API is still running.
    echo Close the old "AutoPivot API" window ^(or end python.exe in Task Manager^),
    echo then run this file again.
    echo.
    pause
    exit /b 1
)
powershell -NoProfile -Command "if (Get-NetTCPConnection -State Listen -LocalPort 5173 -ErrorAction SilentlyContinue) { exit 1 }; exit 0"
if errorlevel 1 (
    echo ERROR: port 5173 is already in use - an old AutoPivot Website is still running.
    echo Close the old "AutoPivot Website" window, then run this file again.
    echo.
    pause
    exit /b 1
)

REM Login tokens need a fixed signing key, or every restart logs you out.
.venv\Scripts\python.exe -m scripts.ensure_env

set "AP_REVISION=unknown"
for /f "usebackq delims=" %%R in (`.venv\Scripts\python.exe -c "import compositing; print(compositing.COMPOSITOR_REVISION)" 2^>nul`) do set "AP_REVISION=%%R"

echo.
echo Starting AutoPivot ...
echo   Compositor version: %AP_REVISION%
echo   ^(each processed photo records this version - check it after an update^)
echo.
echo   API      http://127.0.0.1:8000
echo   Website  http://localhost:5173      ^<- open this one
echo.
echo Two new windows will open. Close them to stop the servers.
echo.

REM The API loads several gigabytes of vision models on its first request, so
REM it is started first and given a moment before the browser can reach it.
REM The venv's python.exe is called directly rather than through activate.bat:
REM activate.bat hard-codes the folder the venv was created in, so after the
REM project is moved it silently runs a different Python with no packages.
start "AutoPivot API" cmd /k "cd /d "%~dp0" && .venv\Scripts\python.exe autopivot_backend.py"

timeout /t 3 /nobreak >nul

start "AutoPivot Website" cmd /k "cd /d "%~dp0" && npm run dev --prefix frontend"

timeout /t 4 /nobreak >nul
start "" http://localhost:5173

echo Done. This window can be closed.
timeout /t 5 /nobreak >nul
