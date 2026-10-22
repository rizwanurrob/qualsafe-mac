"""Help on the web (Update 3, phase 4b, item 4b.6): the same words as the desktop, from `core/ux/help/`.

* `tip(id_or_label)`   the short tip behind a control, for a widget's `help=` (the small ? beside it)
* `clip_html(clip_id)` a help clip as an `<img>` that the browser animates (the SVG rules in
  `core/ux/help/media.py` keep it playable in any browser as well as in Qt)
* `render_tour(activity_key)`  the first-visit tour: four cards, Next and Skip, shown once
* `tours_seen` / `mark_tour_seen` kept in `st.session_state["tours_seen"]` and saved with the other
  preferences (a list of activity keys, never anything about a response)

Imports only `core/` and Streamlit, like the other `app/shared` modules.
"""

from __future__ import annotations

import base64
import os
from typing import Optional, Set

import streamlit as st

from core.ux import activities
from core.ux.help import article, media, title_of, tips, tours


def tip(tip_or_label: str) -> Optional[str]:
    """The tip text for a tip id or a control's label, with where to read more; None if there is none."""
    found = tips.get(tip_or_label) or tips.get(tips.for_label(tip_or_label) or "")
    if found is None:
        return None
    text = article(*found.article.split("-", 1)) or ""
    more = f" More: Help, {title_of(text)}." if title_of(text) else ""
    return found.text + more


def clip_html(clip_id: str) -> str:
    text = media.read(clip_id)
    clip = media.get(clip_id)
    if not text or clip is None:
        return ""
    data = base64.b64encode(text.encode("utf-8")).decode("ascii")
    alt = clip.summary.replace('"', "&quot;")
    return (f'<img alt="{alt}" style="width:100%;max-width:640px;border-radius:8px" '
            f'src="data:image/svg+xml;base64,{data}"/>')


def render_clips(article_id: str) -> None:
    for clip in media.for_article(article_id):
        st.markdown(f"**{clip.title}** ({clip.seconds} seconds)")
        st.markdown(clip_html(clip.clip_id), unsafe_allow_html=True)
        st.caption(clip.summary)


# -- the first-visit tour -----------------------------------------------------------------------

def tours_seen() -> Set[str]:
    return tours.parse(st.session_state.get("tours_seen", ""))


def mark_tour_seen(activity_key: str) -> None:
    st.session_state["tours_seen"] = tours.dump(tours.mark_seen(tours_seen(), activity_key))


def tour_due(activity_key: str) -> bool:
    return not os.environ.get("QUALSAFE_NO_TOUR") and tours.is_due(tours_seen(), activity_key)


def _tour_step(activity_key: str, delta: int) -> None:
    key = f"tour_card_{activity_key}"
    cards = tours.tour(activity_key)
    now = st.session_state.get(key, 0) + delta
    if now >= len(cards):
        _end_tour(activity_key)
    else:
        st.session_state[key] = max(0, now)


def _end_tour(activity_key: str) -> None:
    mark_tour_seen(activity_key)
    st.session_state.pop(f"tour_card_{activity_key}", None)
    st.session_state.pop("tour_replay", None)


def render_tour(activity_key: str, force: bool = False) -> None:
    """The tour card, above the step. Skip ends it for good; Next on the last card ends it too."""
    if not force and not tour_due(activity_key):
        return
    cards = tours.tour(activity_key)
    n = min(st.session_state.get(f"tour_card_{activity_key}", 0), len(cards) - 1)
    card = cards[n]
    pointer = {"rail": "Look at the list of steps on the left.", "main": "Look for the filled button.",
               "more": "Look for the folded More options.", "help": "Look for Help for this step on the left."}
    with st.container(border=True):
        st.markdown(f"**{card.title}**  ({n + 1} of {len(cards)})")
        st.write(card.text)
        st.caption(pointer.get(card.target, ""))
        left, right = st.columns(2)
        left.button("Skip the tour", key=f"tour_skip_{activity_key}", on_click=_end_tour, args=(activity_key,))
        right.button("Done" if n == len(cards) - 1 else "Next", key=f"tour_next_{activity_key}",
                     type="primary", on_click=_tour_step, args=(activity_key, 1))
