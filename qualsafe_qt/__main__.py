"""
So the app can be started as `python -m qualsafe_qt`.

The installed shortcut runs `pythonw.exe -m qualsafe_qt`, and the shorter form
is what a user is asked to type if they ever need to start it by hand. The
longer `python -m qualsafe_qt.main` still works and is what the developer docs
use.

`pythonw.exe` is the console-less interpreter: launched through it, no terminal
window sits behind the app for its whole life (RELEASE_READINESS.md §1.3). It
also means `sys.stdout` and `sys.stderr` may be None, so nothing on the startup
path may assume it can print.
"""

from __future__ import annotations

from qualsafe_qt.main import main

if __name__ == "__main__":
    raise SystemExit(main())
