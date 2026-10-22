@echo off
REM ============================================================
REM  QualSafe - Windows installer
REM  Creates a local Python environment and installs everything.
REM  Double-click this file, or run it from a Command Prompt.
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo(
echo ============================================================
echo   QualSafe - installing (Windows)
echo ============================================================
echo(

REM --- Locate a SUPPORTED Python (3.9-3.12), preferring the newest supported.
REM  The ML stack (numpy<2.0, torch) has no installable builds for Python 3.13+,
REM  so if this machine has both (say) 3.14 and 3.12, we deliberately pick 3.12.
set "PY="
for %%V in (3.12 3.11 3.10 3.9) do (
  if not defined PY ( py -%%V --version >nul 2>nul && set "PY=py -%%V" )
)
REM  Fall back to whatever 'py -3' / 'python' is, then version-check it below.
if not defined PY ( py -3 --version >nul 2>nul && set "PY=py -3" )
if not defined PY ( python --version >nul 2>nul && set "PY=python" )
if not defined PY (
  echo [ERROR] Python was not found on this computer.
  echo(
  echo   Install Python 3.12 ^(recommended^) from:
  echo     https://www.python.org/downloads/
  echo   During setup, TICK the box "Add Python to PATH".
  echo   Then run this installer again.
  echo(
  pause
  exit /b 1
)

REM --- Require Python 3.9+ (the ML libraries need it) ----------------------
%PY% -c "import sys; sys.exit(0 if sys.version_info[:2]>=(3,9) else 1)"
if errorlevel 1 (
  echo [ERROR] Your Python is too old for the machine-learning libraries.
  %PY% --version
  echo   Please install Python 3.12 ^(or 3.11^) and re-run.
  pause
  exit /b 1
)

REM --- Refuse Python 3.13+ (no numpy<2.0 / torch wheels yet) ---------------
%PY% -c "import sys; sys.exit(0 if sys.version_info[:2]<=(3,12) else 1)"
if errorlevel 1 (
  echo [ERROR] Your Python is too NEW for this tool's libraries.
  %PY% --version
  echo(
  echo   NumPy 1.x and PyTorch do not yet publish installable packages for
  echo   Python 3.13 / 3.14. Installing on them forces pip to COMPILE NumPy with
  echo   MinGW -- you get "Numpy built with MINGW-W64 ... experimental" warnings
  echo   and crashes later. This is not fixable by re-running.
  echo(
  echo   Please install Python 3.12 ^(or 3.11^) from python.org and re-run this
  echo   installer. You can keep your newer Python; this tool will use 3.12.
  echo     https://www.python.org/downloads/
  echo(
  pause
  exit /b 1
)

echo Using Python:
%PY% --version
echo(

echo [1/5] Creating a private virtual environment ^(.venv^)...
%PY% -m venv .venv
if errorlevel 1 ( echo [ERROR] Could not create the virtual environment. & pause & exit /b 1 )
set "VPY=.venv\Scripts\python.exe"

echo [2/5] Upgrading pip...
"%VPY%" -m pip install --upgrade pip

echo [3/5] Installing CPU-only PyTorch ^(smaller download, no GPU needed^)...
"%VPY%" -m pip install torch --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 (
  echo [WARN] CPU-only PyTorch failed; trying the default PyTorch wheel...
  "%VPY%" -m pip install "torch>=1.13"
)

echo [4/5] Installing the rest of the libraries ^(several minutes on first run^)...
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo(
  echo [WARN] Standard requirements did not install cleanly.
  echo        Trying the compatibility set for older systems...
  "%VPY%" -m pip install -r requirements-compat.txt
  if errorlevel 1 (
    echo [ERROR] Install failed. See the messages above. Common causes:
    echo   - No internet connection ^(needed once, to download libraries^).
    echo   - Very old CPU without AVX support.
    echo   - Python older than 3.9.
    pause
    exit /b 1
  )
)

REM --- Model download is a SEPARATE, EXPLICIT step -------------------------
REM  Analysis runs with the model hub switched off, so the models must be
REM  fetched here, once, on purpose. This is the only step that reaches the
REM  internet for models -- your survey data never does.
echo(
echo [5/5] Downloading the language models ^(one-time, ~1.6 GB^)...
echo       This is the only step that downloads models. Your data is never uploaded.
"%VPY%" tools\download_models.py
if errorlevel 1 (
  echo(
  echo [WARN] Model download did not complete. The app is installed, but analysis
  echo        will not run until the models are present.
  echo        Re-run this later:   .venv\Scripts\python.exe tools\download_models.py
  echo        ^(or use the "Model status" panel on the Run Analysis page^)
)

REM --- Let the app open a browser tab without a first-run email prompt -----
REM  With server.headless=false (see .streamlit/config.toml) Streamlit opens the
REM  browser itself. On a machine that has never run Streamlit it would first
REM  prompt for an email in the console and wait; pre-seeding an empty global
REM  credentials file skips that prompt. We never overwrite an existing one.
if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
  > "%USERPROFILE%\.streamlit\credentials.toml" echo [general]
  >> "%USERPROFILE%\.streamlit\credentials.toml" echo email = ""
)

echo(
echo ============================================================
echo   Done. To start the app:  double-click  run_app_windows.bat
echo ============================================================
pause
