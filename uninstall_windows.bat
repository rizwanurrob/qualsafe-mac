@echo off
REM ============================================================
REM  QualSafe - Windows uninstaller
REM  Removes the environment and generated data for a clean slate.
REM  Run this from a Command Prompt (double-click also works).
REM ============================================================
setlocal
cd /d "%~dp0"

echo(
echo ============================================================
echo   QualSafe - uninstall
echo ============================================================
echo(
echo   What do you want to remove?
echo     1. Caches and outputs only (keeps the .venv and models)
echo     2. + the virtual environment (.venv)
echo     3. Everything: .venv, downloaded models, caches, outputs
echo     4. Cancel
echo(
set /p CHOICE="Enter 1, 2, 3, or 4: "

if "%CHOICE%"=="1" set SCOPE=caches
if "%CHOICE%"=="2" set SCOPE=env
if "%CHOICE%"=="3" set SCOPE=all
if "%CHOICE%"=="4" ( echo Cancelled. & pause & exit /b 0 )
if not defined SCOPE ( echo Invalid choice. & pause & exit /b 1 )

REM Use the SYSTEM Python, never .venv's — we may be deleting .venv, and Windows
REM won't let a running interpreter delete its own folder. uninstall.py is stdlib-only.
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY ( python --version >nul 2>nul && set "PY=python" )
if not defined PY (
  echo [ERROR] Python not found on PATH. Install Python or delete the folders manually.
  pause
  exit /b 1
)

%PY% tools\uninstall.py --scope %SCOPE%

echo(
echo Done. To reinstall, run install_windows.bat
pause
