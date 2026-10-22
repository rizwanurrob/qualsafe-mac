"""
Surveys, step 2 (Themes): write or pick the list of themes you want answers coded against.

Update 3 (phase 4b, item 4b.5b): the same screen as the desktop's Themes step. On the page: a
ready-made set to start from, the list itself, and one button to go on. Folded under More
options: saving the list as a set of your own, how sure QualSafe must be before it suggests a
code, settings for how groups of similar answers are found, and different themes for one question.

Per `app/__init__`, this module imports only from `core/`, `analysis/`, `exports/`, `app.shared`
and Streamlit, never from `streamlit_app`.
"""

from __future__ import annotations

import streamlit as st

from app.shared import help_ui
from app.shared.data import make_suggested_labels, parse_labels_from_text
from app.shared.state import _nav_cb

EMBEDDING_MODELS = [
    "sentence-transformers/all-MiniLM-L6-v2",
    "sentence-transformers/all-mpnet-base-v2",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
]


def render_theme_setup() -> None:
    from core.label_packs import load_custom_packs

    packs = make_suggested_labels()
    custom = load_custom_packs()
    # The analyst's own saved sets come first: they outrank the built-in ones.
    all_packs = {**{f"★ {k}": v for k, v in custom.items()}, **packs}

    st.subheader("Your themes")
    chosen = st.selectbox(
        "Start from a ready-made set", list(all_packs), key="theme_pack_choice",
        help="Starter themes for common kinds of survey, and your own saved sets (★). A place to "
             "start, not a fixed list. The Education set matches the sample.")
    if st.button("Use this set", key="theme_use_pack",
                 help="Puts this set's themes in the box below. Change them freely: they are yours."):
        st.session_state["theme_labels_text"] = "\n".join(all_packs[chosen])

    st.session_state["theme_labels_text"] = st.text_area(
        "Your themes, one on each line", value=st.session_state.get("theme_labels_text", ""), height=200,
        help="Short, separate phrases work best, such as 'Money worries', not 'Anything about money, "
             "aid, tuition or costs'. You can add definitions later, under More tools.")
    themes = parse_labels_from_text(st.session_state["theme_labels_text"])
    st.caption(f"{len(themes)} theme{'s' if len(themes) != 1 else ''}." if themes
               else "No themes yet. Pick a set or type your own.")

    with st.expander("More options"):
        _render_more(themes)

    if themes:
        st.button("Next: code the answers", key="next_run_analysis", type="primary",
                  on_click=_nav_cb, args=("Run Analysis",))
    else:
        st.caption("Without themes QualSafe can still find groups of similar answers, but it cannot "
                   "suggest codes. Add at least one theme to go on.")
        st.button("Next: code the answers", key="next_run_analysis", on_click=_nav_cb, args=("Run Analysis",))


def _render_more(themes: list) -> None:
    state = st.session_state
    st.markdown("**Keep this list for next time**")
    name = st.text_input("Name for this set", key="pack_save_name", placeholder="Our first-year survey",
                         help="Saved sets appear in the list above (★) and are still there next time.")
    if st.button("Save this set", key="pack_save_btn") and name.strip() and themes:
        from core.label_packs import save_custom_pack

        try:
            save_custom_pack(name.strip(), themes)
            st.success(f"Saved '{name.strip()}'.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    st.markdown("**How sure QualSafe must be before it suggests a code**")
    st.caption("When it is not sure enough, the answer is marked Needs your review instead.")
    state["use_strict_global"] = st.checkbox(
        "Mark unsure answers for review", value=state.get("use_strict_global", False),
        help="Instead of always choosing the best guess, answers it is unsure about wait for you. "
             "Recommended for anything you will report.")
    state["strict_top1_global"] = st.slider(
        "The best theme must score at least", 0.30, 0.95, float(state.get("strict_top1_global", 0.55)), 0.01,
        help="Higher means fewer, more trustworthy suggestions and more answers to review.")
    state["strict_margin_global"] = st.slider(
        "and must beat the next theme by at least", 0.01, 0.40,
        float(state.get("strict_margin_global", 0.10)), 0.01,
        help="A close race between two themes means QualSafe is not sure which applies.")
    state["use_strict_question"] = st.checkbox(
        "Do the same for each question's own themes", value=state.get("use_strict_question", True),
        help="Applies when a question has its own list of themes (below).")
    state["strict_top1_question"] = st.slider(
        "A question's best theme must score at least", 0.30, 0.95,
        float(state.get("strict_top1_question", 0.60)), 0.01,
        help="A question's own list is shorter, so a slightly higher bar is sensible.")
    state["strict_margin_question"] = st.slider(
        "and must beat the next one by at least", 0.01, 0.40,
        float(state.get("strict_margin_question", 0.12)), 0.01)

    st.markdown("**Different themes for one question**")
    st.caption("One question on each line, then its themes: `Question text :: Theme A | Theme B`")
    state["adv_per_question_labels_text"] = st.text_area(
        "Themes for particular questions (optional)", value=state.get("adv_per_question_labels_text", ""),
        height=120, help=help_ui.tip("themes.per_question"))

    st.markdown("**Finding groups of similar answers**")
    st.caption("Leave these alone unless you have a reason to change them.")
    state["adv_min_k"] = st.slider("Fewest groups to try", 2, 6, int(state.get("adv_min_k", 3)), 1,
                                   help="QualSafe tries a range of group counts and keeps the best.")
    state["adv_max_k"] = st.slider("Most groups to try", 3, 12, int(state.get("adv_max_k", 8)), 1,
                                   help="More takes longer on a large file.")
    state["adv_embedding_model"] = st.selectbox(
        "Model that measures how alike two answers are", EMBEDDING_MODELS,
        index=EMBEDDING_MODELS.index(state["adv_embedding_model"])
        if state.get("adv_embedding_model") in EMBEDDING_MODELS else 0,
        help="The first is the fastest on an ordinary computer. The second is stronger and about three "
             "times slower.")
    state["adv_embedding_batch"] = st.slider(
        "Answers read at once (similarity)", 8, 64, int(state.get("adv_embedding_batch", 32)), 8,
        help="Lower it if the computer runs out of memory.")
    state["adv_inference_batch"] = st.slider(
        "Answers read at once (coding)", 4, 32, int(state.get("adv_inference_batch", 16)), 4)
