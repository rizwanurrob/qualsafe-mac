#!/usr/bin/env bash
# ============================================================
#  QualSafe - macOS / Linux uninstaller
#  Removes the environment and generated data for a clean slate.
#  Run from a Terminal:   bash uninstall_mac_linux.sh
# ============================================================
cd "$(dirname "$0")"

echo
echo "============================================================"
echo "  QualSafe - uninstall"
echo "============================================================"
echo
echo "  What do you want to remove?"
echo "    1. Caches and outputs only (keeps the .venv and models)"
echo "    2. + the virtual environment (.venv)"
echo "    3. Everything: .venv, downloaded models, caches, outputs"
echo "    4. Cancel"
echo
read -r -p "Enter 1, 2, 3, or 4: " CHOICE

case "$CHOICE" in
  1) SCOPE=caches ;;
  2) SCOPE=env ;;
  3) SCOPE=all ;;
  4) echo "Cancelled."; exit 0 ;;
  *) echo "Invalid choice."; exit 1 ;;
esac

# Use the SYSTEM python3, not .venv's — we may be deleting .venv. uninstall.py is
# stdlib-only, so any python3 works.
if command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  echo "[ERROR] python3 not found. Install it or delete the folders manually."
  exit 1
fi

"$PY" tools/uninstall.py --scope "$SCOPE"

echo
echo "Done. To reinstall, run:  bash install_mac_linux.sh"
