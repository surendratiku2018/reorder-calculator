@echo off
REM Reorder Calculator - double-click launcher for Windows.
REM First run sets everything up (1-2 min); after that it just starts the app.
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo Python 3 is not installed.
  echo Install it from https://www.python.org/downloads/  -- tick "Add python.exe to PATH" during install --
  echo then double-click this file again.
  pause
  exit /b 1
)

if not exist ".venv" (
  echo First-time setup: creating the environment and installing components ^(1-2 minutes^)...
  %PY% -m venv .venv || (echo Setup failed. & pause & exit /b 1)
  .venv\Scripts\python -m pip install --upgrade pip >nul
  .venv\Scripts\pip install -r requirements.txt || (echo Install failed. & pause & exit /b 1)
)

echo.
echo Starting the Reorder Calculator - your browser will open at http://localhost:8501
echo Leave this window open while you use the app. Close it (or press Ctrl-C) to stop.
echo.
.venv\Scripts\streamlit run app.py
