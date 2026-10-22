"""
Keyboard-shortcut wording for the platform the app is running on.

Qt already *binds* the right keys per platform: `QKeySequence("Ctrl+E")` is
Command+E on a Mac, and `QKeySequence.StandardKey.Redo` is Ctrl+Y on Windows but
Shift+Command+Z on macOS. What Qt does not do is rewrite the sentences we write
about those keys. A tooltip saying "Undoable with Ctrl+Z" on a Mac keyboard that
has no Ctrl key in the place the user expects sends them looking for the wrong
modifier, and "Ctrl+Y to redo" names a shortcut that does nothing there.

So user-facing text is written once, in Windows wording (the form the rest of the
codebase, the tests, and the docs already use), and passed through `native()` at
the point it is shown. On Windows and Linux `native()` returns its input
unchanged, so this cannot alter the existing build's behaviour.

Only the wording changes. Nothing here creates or rebinds a shortcut.
"""

from __future__ import annotations

import sys
from typing import Optional

# Longest patterns first: "Ctrl+Y" must be handled as a whole, because on macOS
# redo is Shift+Command+Z and rewriting only the modifier would print "⌘Y",
# which is Command+Y -- "Show History" in most Mac apps, not redo.
_MAC_REWRITES = (
    ("Ctrl+Shift+Z", "⇧⌘Z"),
    ("Ctrl+Y", "⇧⌘Z"),
    ("Ctrl+", "⌘"),
)


def is_mac(platform: Optional[str] = None) -> bool:
    """True on macOS. `platform` is injectable so this is testable anywhere."""
    return (platform or sys.platform) == "darwin"


def native(text: str, platform: Optional[str] = None) -> str:
    """Rewrite Windows-style shortcut wording for the running platform."""
    if not is_mac(platform):
        return text
    for windows, mac in _MAC_REWRITES:
        text = text.replace(windows, mac)
    return text
