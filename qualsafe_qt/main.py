"""
Entry point for the QualSafe desktop app.

    python -m qualsafe_qt.main

**The first statement that runs matters.** `enforce_local_mode()` sets the
Hugging Face offline flags with `os.environ.setdefault`, which only takes effect
if it happens before `transformers` / `sentence-transformers` are imported --
those libraries read the environment at import time. Several views pull that
stack in transitively, so the call sits at the top of this file, above every
other project import. `qualsafe_qt/__init__` arms it a second time for anyone who
imports the package without going through here; the call is idempotent.

Model *downloads* remain a separate, explicit step run in a subprocess
(`core/model_manager.py` -> `tools/download_models.py`), precisely so this
process never has the offline flags lifted out from under it.
"""

from __future__ import annotations

# ── must precede every other project import ─────────────────────────────────
from core.offline import enforce_local_mode

enforce_local_mode()

# An analysis engine installed from inside the program lives in a per-user folder (core/engine_install.py);
# put it on the import path before anything looks for torch. Cheap, and harmless when there is none.
from core.engine_install import activate as _activate_engine  # noqa: E402

_activate_engine()

# What *this* build's user does about a missing model. The generic advice named
# a shell command, a page called "Run Analysis" and a README -- none of which
# exists for somebody who installed the .exe, and that is the build a first user
# is most likely to be holding.
from core.model_readiness import set_remedy  # noqa: E402

set_remedy(
    "Open Settings, then Models. Press Install the analysis engine first if it is missing, then "
    "Download. Each runs once, only when you press its button, and sends none of your text."
)
# ────────────────────────────────────────────────────────────────────────────

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from qualsafe_qt.version import __version__  # noqa: E402
from qualsafe_qt.windows.main_window import (  # noqa: E402
    APPLICATION, ORGANIZATION, MainWindow,
)

ICON_PATH = Path(__file__).resolve().parent / "resources" / "qualsafe.ico"


def application_icon() -> QIcon:
    """The window / taskbar icon, or an empty one if the file is missing.

    A missing icon is a packaging mistake, not a reason to refuse to start:
    the program is still perfectly usable with the default Windows icon.
    Regenerate with `python packaging/make_icon.py`.
    """
    return QIcon(str(ICON_PATH)) if ICON_PATH.is_file() else QIcon()


#: Identifies this app to the Windows shell. Any stable, unique string works;
#: it must match the AppUserModelID the installer stamps on its shortcuts.
APP_USER_MODEL_ID = "QualSafe.Desktop"


def set_app_user_model_id() -> bool:
    """Tell Windows this process is QualSafe, not "some Python".

    Without it the shell groups the taskbar button under `pythonw.exe`: the
    window shows the generic Python icon rather than ours, buttons from
    unrelated Python programs share one group, and "Pin to taskbar" pins a bare
    interpreter that launches nothing.

    Must run before the first window is created -- the shell reads it when the
    window is realised. No-op off Windows, and never fatal: a wrong taskbar
    grouping is not a reason to refuse to start.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            APP_USER_MODEL_ID)
        return True
    except Exception:  # pragma: no cover - defensive
        return False


def main(argv: list[str] | None = None) -> int:
    set_app_user_model_id()
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APPLICATION)
    app.setOrganizationName(ORGANIZATION)
    # Reported by Qt itself in places we do not render (native dialogs, some
    # crash paths), so it must be the app's version, not the engine's.
    app.setApplicationVersion(__version__)
    app.setWindowIcon(application_icon())

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
