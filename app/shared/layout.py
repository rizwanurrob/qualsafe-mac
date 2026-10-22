"""How wide a widget is, in the words the installed Streamlit uses.

Streamlit 1.51 and later take `width="stretch"` (fill the column) or `width="content"` (as wide as it is),
and print a deprecation warning for the old `use_container_width=True/False`. Streamlit before that knows only
the old argument. This app supports both (`requirements.txt` allows Streamlit from 1.38, and Python 3.9 has
nothing newer than 1.50), so each call says what it means and this module says it the way the installed
Streamlit understands:

    st.dataframe(frame, **stretch(), hide_index=True)
    st.altair_chart(chart, **content())

`stretch()` is `use_container_width=True`; `content()` is `use_container_width=False`. The names are the new
API's, so when the floor moves to 1.51 the two helpers can be replaced by plain `width=` arguments.
"""

from __future__ import annotations

import re
from typing import Dict, Tuple

import streamlit as st

#: The first Streamlit whose buttons, tables, pictures and charts all accept `width="stretch" / "content"`
#: (buttons and tables 1.48 to 1.50, pictures 1.50, altair and vega-lite charts 1.51; checked against the
#: released packages).
FIRST_WITH_WIDTH = (1, 51)


def _version_tuple(text: str) -> Tuple[int, ...]:
    parts = []
    for piece in str(text).split(".")[:3]:
        found = re.match(r"\d+", piece)
        parts.append(int(found.group()) if found else 0)
    return tuple(parts)


def takes_width(version: str = "") -> bool:
    """True when this Streamlit (or the version given) understands `width="stretch"`."""
    return _version_tuple(version or st.__version__) >= FIRST_WITH_WIDTH


def stretch(version: str = "") -> Dict[str, object]:
    """Keyword arguments that make a widget fill its column."""
    return {"width": "stretch"} if takes_width(version) else {"use_container_width": True}


def content(version: str = "") -> Dict[str, object]:
    """Keyword arguments that make a widget only as wide as it is."""
    return {"width": "content"} if takes_width(version) else {"use_container_width": False}
