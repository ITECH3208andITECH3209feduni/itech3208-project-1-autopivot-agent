@echo off
REM ===========================================================================
REM AutoPivot - one-time setup for Windows
REM
REM Double-click this file, or run it from a terminal in this folder.
REM Safe to run again: every step skips work that is already done.
REM ===========================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ============================================
echo   AutoPivot - setup
echo ============================================
echo.

REM --- Python ---------------------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not on your PATH.
    echo.
    echo Install Python 3.11 or 3.12 from https://www.python.org/downloads/
    echo During installation, tick "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo Python %PYVER% found.

REM --- Virtual environment --------------------------------------------------
if exist ".venv\Scripts\python.exe" (
    echo Virtual environment already exists.
) else (
    echo Creating virtual environment in .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: could not create the virtual environment.
        pause
        exit /b 1
    )
)

call .venv\Scripts\activate.bat
echo Using:
python -c "import sys; print('  ' + sys.executable)"

echo.
echo Updating pip ...
python -m pip install --upgrade pip --quiet

REM --- .env -----------------------------------------------------------------
echo.
if exist ".env" (
    echo .env already exists - leaving it alone.
) else (
    echo Creating .env from .env.example ...
    copy /y ".env.example" ".env" >nul
    REM A real signing key, so logins survive a restart. Written straight into
    REM .env rather than printed, because nobody copies it across by hand.
    python -c "import secrets, pathlib; p = pathlib.Path('.env'); t = p.read_text(encoding='utf-8'); p.write_text(t.replace('JWT_SECRET=', 'JWT_SECRET=' + secrets.token_urlsafe(48), 1), encoding='utf-8')"
    echo   A signing key was generated and written to .env.
    echo.
    echo   NOTE: to use the best background-removal model, put a Hugging Face
    echo         token in .env as HF_TOKEN. Without one the fallback model is
    echo         used, which still works. See the README.
)

REM --- PyTorch (GPU) --------------------------------------------------------
echo.
echo ============================================
echo   Installing PyTorch
echo ============================================
echo.
echo On Windows, a plain "pip install torch" installs a build that cannot
echo use your GPU. This step picks the right one for your driver.
echo.
python scripts\install_torch.py
if errorlevel 1 (
    echo.
    echo ERROR: installing PyTorch failed. See the message above.
    pause
    exit /b 1
)

REM --- Python packages ------------------------------------------------------
echo.
echo ============================================
echo   Installing Python packages
echo ============================================
echo.
python -m pip install -r requirements-ml.txt
if errorlevel 1 (
    echo.
    echo ERROR: installing Python packages failed.
    pause
    exit /b 1
)

REM --- Frontend -------------------------------------------------------------
echo.
echo ============================================
echo   Installing the website
echo ============================================
echo.
where npm >nul 2>&1
if errorlevel 1 (
    echo WARNING: Node.js is not on your PATH, so the website was skipped.
    echo Install the LTS version from https://nodejs.org/ and run this again.
    set FRONTEND_SKIPPED=1
) else (
    call npm install --prefix frontend
    if errorlevel 1 (
        echo.
        echo ERROR: npm install failed.
        pause
        exit /b 1
    )
)

REM --- Database -------------------------------------------------------------
echo.
echo ============================================
echo   Setting up the database
echo ============================================
echo.
python -m scripts.init_db
if errorlevel 1 (
    echo.
    echo ERROR: creating the database failed.
    pause
    exit /b 1
)

echo.
python -m scripts.seed_dealership
if errorlevel 1 (
    echo.
    echo ERROR: creating the sign-in account failed.
    pause
    exit /b 1
)

REM --- Check ----------------------------------------------------------------
echo.
echo ============================================
echo   Checking the setup
echo ============================================
python -m scripts.check_setup

echo.
echo ============================================
echo   Setup finished
echo ============================================
echo.
echo   Start the site:   run.bat
echo   Then open:        http://localhost:5173
echo.
echo   Sign in with the email and password printed above.
echo   Copy the password now - it is only shown once.
echo.
if defined FRONTEND_SKIPPED (
    echo   NOTE: install Node.js and run setup.bat again before using run.bat.
    echo.
)
pause
