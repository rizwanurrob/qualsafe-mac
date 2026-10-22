#!/usr/bin/env bash
# Launch the QualSafe (macOS / Linux). Run install_mac_linux.sh first.
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  echo "The app is not installed yet. Please run:  bash install_mac_linux.sh"
  exit 1
fi
echo "Starting the app... a browser tab will open at http://localhost:8501"
echo "Press Ctrl+C to stop the app."
.venv/bin/python -m streamlit run streamlit_app.py
