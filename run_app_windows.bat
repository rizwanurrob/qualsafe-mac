@echo off
REM Launch the QualSafe (Windows). Run install_windows.bat first.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo The app is not installed yet.
  echo Please double-click  install_windows.bat  first.
  pause
  exit /b 1
)
echo Starting the app... a browser tab will open at http://localhost:8501
echo Close this window to stop the app.
".venv\Scripts\python.exe" -m streamlit run streamlit_app.py
pause
