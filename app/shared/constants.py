"""
Paths, titles, and tunables shared by every page.

Extracted from the former monolithic `streamlit_app.py` (v4, Phase 0.1).
Per `app/__init__`, this module imports only from `core/`, `analysis/`,
`exports/`, `app.shared`, and Streamlit — never from `streamlit_app`.
"""

from __future__ import annotations

from pathlib import Path


APP_TITLE = "QualSafe (Local)"


PROJECT_ROOT = Path(__file__).resolve().parents[2]      # the program folder (this file is app/shared/constants.py)


# v3.7.1: the built-in sample is a 40-row, single-question education survey that
# pairs with the default "Education / Student Experience" label pack. The older
# customer-experience CSV remains in data/ for anyone who prefers it.
SYNTHETIC_FILE = PROJECT_ROOT / "data" / "sample_survey_education.csv"


SESSION_INPUT_DIR = PROJECT_ROOT / "data" / "session_inputs"


STREAMLIT_OUTPUT_DIR = PROJECT_ROOT / "output_streamlit"


PUBLIC_DATA_DIR = PROJECT_ROOT / "data" / "public_datasets"


LABEL_DELIMITER = "|"


MIN_ITERATIVE_LABELED_ROWS = 6


PREVIEW_ROWS = 50  # quick-preview sample size (Phase 5)
