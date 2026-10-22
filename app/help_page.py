"""
Help (Update 3, phase 4b, item 4b.6): the same articles as the desktop, read from `core/ux/help/`.

A short article for each step, how-to tasks, the plain-words glossary and troubleshooting, with the
clips that belong to an article played below it and a way to see an activity's tour again. Search
looks through every title and body. Per `app/__init__`, this module imports only from `core/`,
`analysis/`, `exports/`, `app.shared`, and Streamlit, never from `streamlit_app`.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import streamlit as st

from app.shared import nav
from app.shared.help_ui import render_clips
from core.ux import activities
from core.ux import help as shared_help

TROUBLESHOOTING = "troubleshooting"
GLOSSARY = "words"


def _entries() -> List[Tuple[str, str, str]]:
    """(id, label, markdown) for everything Help can open, in the order of the contents."""
    rows: List[Tuple[str, str, str]] = []
    for activity_key, step_key in shared_help.steps():
        text = shared_help.article(activity_key, step_key)
        if text:
            rows.append((shared_help.article_id(activity_key, step_key), shared_help.title_of(text), text))
    for task_id in shared_help.task_ids():
        text = shared_help.task(task_id) or ""
        rows.append((task_id, shared_help.title_of(text), text))
    glossary = shared_help.glossary()
    rows.append((GLOSSARY, shared_help.title_of(glossary) or "Words used here", glossary))
    trouble = shared_help.troubleshooting()
    rows.append((TROUBLESHOOTING, shared_help.title_of(trouble) or "Troubleshooting", trouble))
    return rows


def _opening(known: Dict[str, str]) -> str:
    state = st.session_state
    wanted = state.get("help_article", "")
    if wanted in known:
        return wanted
    back = state.get("help_back")
    if back:
        step_id = shared_help.article_id(*back)
        if step_id in known:
            return step_id
    return next(iter(known))


def _back_to_step() -> None:
    activity_key, step_key = st.session_state.get("help_back", ("", ""))
    if activity_key:
        nav.go_activity(activity_key, step_key)
    else:
        nav.go_home()


def _pick_article(article_id: str) -> None:
    st.session_state["help_article"] = article_id


def _replay_tour(activity_key: str) -> None:
    st.session_state["tour_replay"] = activity_key
    st.session_state[f"tour_card_{activity_key}"] = 0
    nav.go_activity(activity_key)


def render_qualitative_guide() -> None:
    """The beginner's guide, one expander per section.

    The text is shared with the desktop app (`core/ux/guide.py`), so the two
    cannot drift. The first section opens by default; the rest stay closed so the
    page is a contents list before it is a wall of text.
    """
    from core.ux.guide import all_sections

    st.subheader("New to qualitative research? A short guide")
    st.caption(
        "Plain-language outlines, hints and a glossary, with page references to "
        "Saldaña (2013), Creswell (2013) and Silverman (2017).")
    for index, (title, body) in enumerate(all_sections()):
        with st.expander(title.replace("New to this · ", ""), expanded=index == 0):
            st.markdown(body)


def render_help_and_troubleshooting() -> None:
    st.header("Help")
    state = st.session_state
    entries = _entries()
    label = {i: lab for i, lab, _t in entries}
    body = {i: text for i, _l, text in entries}

    if state.get("help_back"):
        st.button("Back to your step", key="help_back_btn", on_click=_back_to_step)

    query = st.text_input("Search Help", key="help_query", placeholder="A word or a question").strip().lower()
    shown = [i for i, lab, text in entries if not query or query in lab.lower() or query in text.lower()]
    if not shown:
        st.info("Nothing in Help mentions that. Try a shorter or plainer word.")
        shown = [i for i, _l, _t in entries]

    start = _opening(body)
    if state.get("help_pick") not in shown:
        state["help_pick"] = start if start in shown else shown[0]
    chosen = st.selectbox("Read about", shown, format_func=label.get, key="help_pick",
                          on_change=lambda: _pick_article(st.session_state["help_pick"]))
    state["help_article"] = chosen

    st.markdown(body[chosen])
    render_clips(chosen)

    with st.expander("New to qualitative research? A short guide"):
        render_qualitative_guide()

    with st.expander("Show a tour again"):
        for activity in activities.ACTIVITIES:
            st.button(f"{activity.title}: show the tour", key=f"tour_again_{activity.key}",
                      on_click=_replay_tour, args=(activity.key,))

    if state.get("last_error"):
        st.subheader("The last error")
        st.code(state["last_error"])
