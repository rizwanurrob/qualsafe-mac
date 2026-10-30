"""
The desktop app's own identity.

Kept separate from `core.manifest.PACKAGE_VERSION` on purpose. That number
versions the *analysis engine* — the code under `core/`, `analysis/`,
`engines/`, `exports/`, and `privacy/` that this app shares, byte for byte, with
the other program built on it. This app is a different artefact with a different
interface and its own release cadence, so it carries its own number. Reporting
the engine's version as though it were the app's would claim the two ship
together, which they do not.

Both are worth showing a user. The engine version is what a methods appendix
needs in order to say which code produced a result; the app version is what a
bug report needs. `version_line()` renders the pair.

**0.9.x is deliberately pre-1.0.** No real research project has been carried
through this program end to end yet, and the survey pipeline has never executed
against live models here. 1.0.0 is for when that is no longer true — see
`RELEASE_READINESS.md` §1.1.

This module imports nothing. The build script reads `__version__` out of it with
a regex, so it must stay a plain literal assignment on one line.
"""

from __future__ import annotations

__version__ = "0.99.11-ux11"

#: Shown in the title bar, the About box, and the installer's own metadata.
APP_NAME = "QualSafe Desktop"

#: Registry/`QSettings` scope, and the installer's publisher field.
PUBLISHER = "QualSafe"


def engine_version() -> str:
    """The version of the shared analysis code, or ``"unknown"``.

    Imported lazily and defensively: this must never be the reason the About
    box fails to open.
    """
    try:
        from core.manifest import PACKAGE_VERSION
    except Exception:  # pragma: no cover - defensive
        return "unknown"
    return str(PACKAGE_VERSION)


def store_format() -> str:
    """The `.qnw` schema this build writes and can open, or ``"unknown"``.

    The third number a user needs and the one usually left out. Neither the app
    version nor the engine version tells someone handed a project by a colleague
    whether their install can open it — a store written by a newer schema raises
    rather than degrading, and this is the number that says so.

    Lazy and defensive for the same reason as `engine_version`.
    """
    try:
        from core.project import SCHEMA_VERSION
    except Exception:  # pragma: no cover - defensive
        return "unknown"
    return str(SCHEMA_VERSION)


def version_line() -> str:
    """``"0.99.3 (analysis engine 4.8.1)"`` — for display to a user."""
    return f"{__version__} (analysis engine {engine_version()})"


__all__ = ["__version__", "APP_NAME", "PUBLISHER", "engine_version",
           "store_format", "version_line"]
