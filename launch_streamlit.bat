@echo off
setlocal
set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"

if not exist "%PROJECT_ROOT%\.venv\Scripts\python.exe" (
  echo Virtual environment not found.
  echo Run: powershell -ExecutionPolicy Bypass -File "%PROJECT_ROOT%run_streamlit.ps1" -InstallDeps
  exit /b 1
)

"%PROJECT_ROOT%\.venv\Scripts\python.exe" -m streamlit run "%PROJECT_ROOT%streamlit_app.py"
