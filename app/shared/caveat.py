"""A caveat beside the number it qualifies: one sentence, with *Why?* for the rest (design rule 5).

The web counterpart of the desktop's `CaveatNote`. The text is kept whole: only its first sentence shows until
*Why?* is opened, and a caveat is never dropped. It always carries an icon and a word, so it never relies on
colour, and a warning is never green.
"""

from __future__ import annotations

import streamlit as st

from core.ux import caveats

#: Kind -> (the Streamlit box, its icon, its word). Same words as the desktop.
_KINDS = {
    "warning": (st.warning, "⚠️", "Warning"),
    "note": (st.info, "ℹ️", "Note"),
}


def _plain_markdown(text: str) -> str:
    """The short form is a sentence cut from markdown: drop the marks so a cut never leaves one open."""
    return text.replace("**", "").replace("`", "").replace("*", "")


def caveat(text: str, kind: str = "warning") -> None:
    """Show `text` as a short box (icon, word, first sentence) with a *Why?* fold holding all of it."""
    box, icon, word = _KINDS.get(kind, _KINDS["note"])
    short, more = caveats.short_form(text)
    if not short:
        return
    box(f"**{word}:** {_plain_markdown(short)}", icon=icon)
    if more:
        with st.expander("Why?"):
            st.markdown(text)
