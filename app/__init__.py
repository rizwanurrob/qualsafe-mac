"""
Page modules for the Streamlit UI (v4, Phase 0.1).

`streamlit_app.py` grew to ~3,700 lines and is the project's biggest
maintainability liability: the v4 corpus features (a document library, a reader
with coding stripes, this search workbench) cannot responsibly be added to it.

Rather than one risky big-bang split, this package is introduced *with the first
new page* and existing pages migrate into it one at a time, with the render-smoke
suite green at every step.

The rule that keeps these modules independent — and the whole UI layer swappable
later — is: **a page module imports only from `core/`, `analysis/`, `exports/`,
and Streamlit. It never imports `streamlit_app`.** Anything it needs from the
shell (the active project path, a shared widget) is passed in as an argument.
That one constraint is what prevents the circular imports that make a monolith
impossible to break up afterwards.
"""

# Offline mode must be armed before anything imports transformers /
# sentence-transformers, which several page modules pull in transitively (via
# analyze_survey). Doing it here — in the package every page import goes through
# — makes the guarantee independent of the order the shell imports pages in.
from core.offline import enforce_local_mode  # noqa: E402

enforce_local_mode()

# The analysis engine, if it was installed from inside the program (core/engine_install.py), lives in a
# per-user folder: put it on the import path before any page looks for torch.
from core.engine_install import activate as _activate_engine  # noqa: E402

_activate_engine()

from core.model_readiness import set_remedy  # noqa: E402

set_remedy(
    "Open Settings, then Models. Press 'Install the analysis engine' first if it is missing, then "
    "download the models. Each runs once, only when you press its button, and sends none of your text."
)
