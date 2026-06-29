#!/bin/bash
# Reorder Calculator — double-click launcher for macOS.
# First run sets everything up (1-2 min); after that it just starts the app.
cd "$(dirname "$0")" || exit 1

PY="$(command -v python3.11 || command -v python3.12 || command -v python3 || command -v python)"
if [ -z "$PY" ]; then
  echo "Python 3 is not installed."
  echo "Install it from https://www.python.org/downloads/  then double-click this file again."
  read -r -p "Press Enter to close..."
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "First-time setup: creating the environment and installing components (1-2 minutes)…"
  "$PY" -m venv .venv || { echo "Setup failed."; read -r -p "Press Enter..."; exit 1; }
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/pip install -r requirements.txt || { echo "Install failed."; read -r -p "Press Enter..."; exit 1; }
fi

echo ""
echo "Starting the Reorder Calculator — your browser will open at http://localhost:8501"
echo "Leave this window open while you use the app. Close it (or press Ctrl-C) to stop."
echo ""
.venv/bin/streamlit run app.py
