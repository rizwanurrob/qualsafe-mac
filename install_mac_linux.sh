#!/usr/bin/env bash
# ============================================================
#  QualSafe - macOS / Linux installer
#  Creates a local Python environment and installs everything.
#
#  Run from a Terminal:   bash install_mac_linux.sh
#  (or, if it is marked executable:   ./install_mac_linux.sh )
# ============================================================
set -e
cd "$(dirname "$0")"

echo
echo "============================================================"
echo "  QualSafe - installing (macOS / Linux)"
echo "============================================================"
echo

# --- Locate a SUPPORTED Python (3.9-3.12), preferring the newest supported ---
#  The ML stack (numpy<2.0, torch) has no installable builds for Python 3.13+,
#  so if this machine has both (say) 3.14 and 3.12 we deliberately pick 3.12.
PY=""
for c in python3.12 python3.11 python3.10 python3.9 python3; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "[ERROR] python3 was not found."
  echo "  macOS:  install from https://www.python.org/downloads/  (or: brew install python@3.12)"
  echo "  Linux:  e.g.  sudo apt install python3.12 python3.12-venv python3-pip"
  echo "  Need Python 3.9-3.12. Then run this installer again."
  exit 1
fi

# --- Require Python 3.9+ ----------------------------------------------------
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 9) else 1)'; then
  echo "[ERROR] Your Python is too old for the machine-learning libraries:"
  "$PY" --version
  echo "  Please install Python 3.12 (or 3.11) and re-run."
  exit 1
fi

# --- Refuse Python 3.13+ (no numpy<2.0 / torch wheels yet) ------------------
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info[:2] <= (3, 12) else 1)'; then
  echo "[ERROR] Your Python is too NEW for this tool's libraries:"
  "$PY" --version
  echo
  echo "  NumPy 1.x and PyTorch do not yet publish installable packages for"
  echo "  Python 3.13 / 3.14. Installing on them forces pip to COMPILE NumPy from"
  echo "  source, producing crash-prone builds and runtime warnings."
  echo "  Please install Python 3.12 (or 3.11) and re-run. You can keep your newer"
  echo "  Python; this tool will use 3.12."
  echo "    macOS:  brew install python@3.12   (or python.org)"
  echo "    Linux:  sudo apt install python3.12 python3.12-venv"
  exit 1
fi

echo "Using Python: $("$PY" --version 2>&1)"
echo

echo "[1/5] Creating a private virtual environment (.venv)..."
"$PY" -m venv .venv
VPY=".venv/bin/python"

echo "[2/5] Upgrading pip..."
"$VPY" -m pip install --upgrade pip

echo "[3/5] Installing PyTorch (CPU build; no GPU needed)..."
OS="$(uname -s)"
if [ "$OS" = "Darwin" ]; then
  # macOS wheels on PyPI are already CPU/Metal builds.
  "$VPY" -m pip install "torch>=1.13" || true
else
  # Linux: use the CPU index so we don't download the large CUDA build.
  "$VPY" -m pip install torch --index-url https://download.pytorch.org/whl/cpu \
    || "$VPY" -m pip install "torch>=1.13"
fi

echo "[4/5] Installing the rest of the libraries (several minutes on first run)..."
if ! "$VPY" -m pip install -r requirements.txt; then
  echo
  echo "[WARN] Standard requirements did not install cleanly."
  echo "       Trying the compatibility set for older systems..."
  "$VPY" -m pip install -r requirements-compat.txt
fi

# --- Model download is a SEPARATE, EXPLICIT step -----------------------------
#  Analysis runs with the model hub switched off, so the models must be fetched
#  here, once, on purpose. This is the only step that reaches the internet for
#  models -- your survey data never does.
echo
echo "[5/5] Downloading the language models (one-time, ~1.6 GB)..."
echo "      This is the only step that downloads models. Your data is never uploaded."
if ! "$VPY" tools/download_models.py; then
  echo
  echo "[WARN] Model download did not complete. The app is installed, but analysis"
  echo "       will not run until the models are present."
  echo "       Re-run this later:   .venv/bin/python tools/download_models.py"
  echo "       (or use the 'Model status' panel on the Run Analysis page)"
fi

# --- Let the app open a browser tab without a first-run email prompt ---------
#  With server.headless=false (see .streamlit/config.toml) Streamlit opens the
#  browser itself. On a machine that has never run Streamlit it would first
#  prompt for an email in the terminal and wait; pre-seeding an empty global
#  credentials file skips that prompt. We never overwrite an existing one.
mkdir -p "$HOME/.streamlit"
if [ ! -f "$HOME/.streamlit/credentials.toml" ]; then
  printf '[general]\nemail = ""\n' > "$HOME/.streamlit/credentials.toml"
fi

echo
echo "============================================================"
echo "  Done. Start the app with:   ./run_app_mac_linux.sh"
echo "  (or:  .venv/bin/python -m streamlit run streamlit_app.py )"
echo "============================================================"
