"""
QualSafe desktop UI — a native PySide6/Qt view over the existing engine.

This package is a **view layer only**. It reads from and writes to the same
`core/`, `analysis/`, `engines/`, `interview/`, `exports/`, and `privacy/`
modules the Streamlit build uses, and it changes none of them. A `.qnw` written
here opens in the Streamlit build and vice versa.

The rule inherited from `app/__init__` still holds, one level stricter: **a view
module imports only from `core/`, `analysis/`, `exports/`, `qualsafe_qt.*`, and
Qt.** It never imports `streamlit_app`, `app.*`, or Streamlit. That is what keeps
the two front ends independent and the engine swappable under either.

Why Qt at all: Streamlit has no widget that returns the character offsets of a
mouse text selection, and offsets are what tie a code to its evidence. Qt gives
them for free (`QTextCursor.selectionStart/selectionEnd`), which is the whole
justification for this fork — see `widgets/document_view.py`.
"""

# Offline mode must be armed before anything imports transformers /
# sentence-transformers, which some views pull in transitively (via
# analyze_survey / analysis.code_similarity). Arming it here — in the package
# every view import goes through — makes the guarantee independent of import
# order. `main.py` arms it again at the top of the entry point; the call is
# idempotent (os.environ.setdefault), so doing both is free insurance.
from core.offline import enforce_local_mode  # noqa: E402

enforce_local_mode()

__all__ = ["enforce_local_mode"]
