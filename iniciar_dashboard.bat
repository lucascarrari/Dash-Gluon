@echo off
setlocal
cd /d "%~dp0soilframe-dashboard"
if not exist ".venv\Scripts\python.exe" (
  echo Prepare o ambiente conforme o README.md desta pasta.
  pause
  exit /b 1
)
set "PYTHONPATH=%CD%"
".venv\Scripts\python.exe" -m streamlit run app.py
if errorlevel 1 pause
endlocal
