#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

if [[ ! -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  echo "Virtual environment not found at .venv/bin/python"
  echo "Create it with: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

"$PROJECT_ROOT/.venv/bin/python" -m streamlit run "$PROJECT_ROOT/streamlit_app.py"
