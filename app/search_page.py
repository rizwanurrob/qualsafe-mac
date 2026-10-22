#!/usr/bin/env python
"""
Search (Surveys and Interviews, Explore), simplified in Update 3, phase 4b (item 4b.5d).

On the page: a box to search for, and what it finds in context. How to match (whole word, regular
expression, case), which sources, and how many hits are folded under More options; so are the
settings for the word counts.

Search & lexical exploration page (v4, Phase 1).

Find a phrase anywhere in the corpus and read it in context, see what words the
data actually uses, and turn a query into codings in one action. This is what an
analyst does in the first hour, before a codebook exists.

Per `app/__init__`, this module imports only from `core/`, `analysis/`, and
Streamlit — never from `streamlit_app`. The shell passes in the active project and
any shared widget it wants reused.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import altair as alt
import pandas as pd
import streamlit as st
from app.shared.layout import stretch

from analysis.lexical import DEFAULT_STOPWORDS, context_profile, word_frequency
from core.autocode import AUTOCODE_RATER, autocode_hits, remove_autocoded
from core.project import Project
from core.search import search

# Cap the corpus read for word frequency so a huge project can't hang the page.
_FREQ_SOURCE_CAP = 2000


def render_search_page(
    store_path: Optional[Path],
    *,
    chart_export: Optional[Callable] = None,
) -> None:
    """Render the Search page for the active project store."""
    st.caption("Search the text of everything in this project, answers and transcripts, and read each "
               "hit in its context. It all happens on this computer.")

    if store_path is None or not Path(store_path).exists():
        st.info("There is no project yet. Run the analysis with 'Also save a project file (.qnw)' ticked, "
                "or choose one under Settings, Project and backups.")
        return

    with Project.open(store_path) as proj:
        total = proj.count_sources()
        if total == 0:
            st.info("This project has no text in it yet.")
            return
        types = proj.source_types()
        cases = proj.list_cases()
        codes = [c.name for c in proj.get_codebook()]
        if not proj.fts_available():
            st.caption("Note: this SQLite has no FTS5 index, so searches scan the "
                       "text directly. Results are identical, just slower.")

        tab_search, tab_words = st.tabs(["Search", "Word counts"])

        with tab_search:
            _render_search_tab(proj, store_path, types, cases, codes, total,
                               chart_export=chart_export)
        with tab_words:
            _render_words_tab(proj, types, total, chart_export=chart_export)


# ── Search tab ──────────────────────────────────────────────────────────────
def _render_search_tab(proj, store_path, types, cases, codes, total, *, chart_export) -> None:
    query = st.text_input("Search for", key="search_query",
                          placeholder="tuition",
                          help="A word or phrase. Open More options to match part of a word or to use "
                               "a pattern.")
    with st.expander("More options"):
        mode_label = st.radio("How to read what you typed", ["Text", "Pattern (regex)"], key="search_mode",
                              horizontal=True, help="Text finds the words as typed. A pattern can find "
                                                    "many spellings at once.")
        mode = "regex" if mode_label.startswith("Pattern") else "text"
        o1, o2, o3, o4 = st.columns(4)
        whole_word = o1.checkbox(
            "Whole words only", value=True, key="search_whole",
            help="On: 'cost' finds the word cost, not 'costume', and is fast. Off: it also finds 'advis' "
                 "inside 'advisor', which has to read all the text.")
        case_sensitive = o2.checkbox("Match capital letters", value=False, key="search_case")
        type_filter = o3.selectbox("Look in", ["(all)"] + list(types), key="search_type")
        limit = o4.number_input("Most hits to show", 10, 2000, 200, step=10, key="search_limit")

        f1, f2 = st.columns(2)
        case_names = {c.name: c.case_id for c in cases}
        case_pick = f1.selectbox("Person or group", ["(all)"] + list(case_names), key="search_case_pick",
                                 help="Only text that belongs to one person or group.") if cases else "(all)"
        code_pick = f2.selectbox("Only where this code is applied", ["(all)"] + codes,
                                 key="search_code_pick",
                                 help="Only text that already carries this code.") if codes else "(all)"

    if not query.strip():
        st.caption(f"{total:,} piece(s) of text in this project. Type something to search for.")
        return

    try:
        hits = search(
            proj, query, mode=mode, case_sensitive=case_sensitive, whole_word=whole_word,
            source_type=None if type_filter == "(all)" else type_filter,
            case_id=None if case_pick == "(all)" else case_names.get(case_pick),
            code_name=None if code_pick == "(all)" else code_pick,
            limit=int(limit),
        )
    except ValueError as exc:
        st.error(str(exc))
        return

    if not hits:
        st.warning("No matches.")
        return

    n_sources = len({h.source_id for h in hits})
    st.success(f"**{len(hits)}** hit(s) in **{n_sources}** source(s)"
               + (f" — capped at {limit}" if len(hits) >= limit else ""))

    # KWIC results, grouped by source.
    st.markdown("**In context**")
    by_source: dict = {}
    for hit in hits:
        by_source.setdefault((hit.source_id, hit.source_label, hit.source_type), []).append(hit)
    for (sid, label, stype), shits in by_source.items():
        title = label or (shits[0].metadata or {}).get("title") or sid
        with st.expander(f"{title}  ·  {stype}  ·  {len(shits)} hit(s)", expanded=len(by_source) <= 3):
            for hit in shits:
                st.markdown(
                    f"…{hit.left.strip()} **:red[{hit.match_text}]** {hit.right.strip()}…  \n"
                    f"<span style='opacity:.6;font-size:0.8em'>chars {hit.char_start}–{hit.char_end}</span>",
                    unsafe_allow_html=True)

    # Words around the term — the legible core of a word tree.
    st.subheader("Words around the term")
    st.caption("What immediately precedes and follows your term across all hits.")
    profile = context_profile([(h.left, h.right) for h in hits])
    p1, p2 = st.columns(2)
    p1.caption("**Before**")
    p1.dataframe(profile["before"], **stretch(), hide_index=True)
    p2.caption("**After**")
    p2.dataframe(profile["after"], **stretch(), hide_index=True)

    _render_autocode(proj, store_path, hits, query)


def _render_autocode(proj, store_path, hits, query) -> None:
    """Turn the current result set into codings, reversibly."""
    st.subheader("Code these hits")
    st.caption(
        "Apply a code to every hit above. Each becomes an passage covering exactly "
        f"the matched words, saved under the `{AUTOCODE_RATER}` coder — kept "
        "separate from your own coding, so it never counts toward between-coder "
        "reliability. Reversible below."
    )
    existing = [c.name for c in proj.get_codebook()]
    a1, a2 = st.columns([3, 1])
    code_name = a1.text_input("Code to apply", key="autocode_name",
                              placeholder="e.g. Cost" if not existing else existing[0],
                              help="An existing code name, or a new one to create.")
    if a2.button("Code all hits", key="autocode_btn", disabled=not code_name.strip()):
        try:
            result = autocode_hits(proj, hits, code_name.strip(), query=query)
            st.success(
                f"Applied **{code_name.strip()}** to {result['applications']} hit(s) "
                f"({result['excerpts_created']} new passage(s), "
                f"{result['skipped']} already coded).")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Auto-coding failed: {exc}")

    with st.expander("Undo auto-coding"):
        st.caption("Removes codings made by text search only — your own coding and the "
                   "model's are untouched.")
        u1, u2 = st.columns([3, 1])
        undo_code = u1.selectbox("Which code", ["(all auto-coded)"] + existing, key="autocode_undo_pick")
        if u2.button("Remove", key="autocode_undo_btn"):
            removed = remove_autocoded(
                proj, code_name=None if undo_code == "(all auto-coded)" else undo_code)
            st.success(f"Removed {removed} auto-coded application(s).")


# ── Word frequency tab ──────────────────────────────────────────────────────
def _render_words_tab(proj, types, total, *, chart_export) -> None:
    st.caption("The words your text uses most: a first look before you have any themes.")
    with st.expander("More options"):
        c1, c2, c3 = st.columns(3)
        type_filter = c1.selectbox("Look in", ["(all)"] + list(types), key="wf_type")
        top_n = c2.slider("How many words", 10, 100, 30, key="wf_topn")
        min_len = c3.slider("Shortest word", 1, 8, 3, key="wf_minlen")
        use_stops = st.checkbox(
            "Leave out everyday words", value=True, key="wf_stops",
            help="Leaves out 'the', 'and', 'is' and so on. Turn it off to see every word.")
        extra = st.text_input("Also leave out these words (separated by commas)", key="wf_extra",
                              placeholder="student, course, survey")

    texts = _corpus_texts(proj, None if type_filter == "(all)" else type_filter)
    if not texts:
        st.info("No text for this filter.")
        return
    stops = set(DEFAULT_STOPWORDS) if use_stops else set()
    stops |= {w.strip().lower() for w in (extra or "").split(",") if w.strip()}

    freq = word_frequency(texts, stopwords=stops, min_length=int(min_len), top_n=int(top_n))
    if freq.empty:
        st.info("No words left after filtering.")
        return
    st.caption(f"Across {len(texts):,} source(s)."
               + ("  Showing the first 2,000 sources." if len(texts) >= _FREQ_SOURCE_CAP else ""))

    bar = (alt.Chart(freq).mark_bar()
           .encode(x=alt.X("count:Q", title="occurrences"),
                   y=alt.Y("term:N", sort="-x", title=None),
                   tooltip=["term", "count", "documents"]))
    st.altair_chart(bar, **stretch())
    if chart_export:
        chart_export(bar, "word_frequency", data_df=freq, key_prefix="wordfreq")

    st.markdown("**Word cloud**")
    cloud = _word_cloud_chart(freq)
    st.altair_chart(cloud, **stretch())
    if chart_export:
        chart_export(cloud, "word_cloud", data_df=freq, key_prefix="wordcloud")

    st.dataframe(freq, **stretch(), hide_index=True)
    st.caption("`documents` is how many pieces of text use the word at least once. It tells a word one "
               "person repeated from a word everyone used.")


def _corpus_texts(proj, source_type: Optional[str]) -> list:
    """Read source text a page at a time, capped, so a big corpus stays responsive."""
    texts: list = []
    offset = 0
    while len(texts) < _FREQ_SOURCE_CAP:
        page = proj.iter_sources(source_type=source_type, limit=200, offset=offset)
        if not page:
            break
        texts.extend(s.raw_text or "" for s in page)
        offset += 200
    return texts[:_FREQ_SOURCE_CAP]


def _word_cloud_chart(freq: pd.DataFrame) -> alt.Chart:
    """A deterministic 'cloud': terms laid out in rows, sized by frequency.

    Not a packed cloud — a real packing algorithm needs a layout library, and the
    honest trade is that a deterministic grid is reproducible, exportable, and
    readable, which a random packing is not. Size still carries frequency, which
    is the only thing a cloud actually communicates.
    """
    df = freq.copy().reset_index(drop=True)
    per_row = 6
    df["col"] = df.index % per_row
    df["row"] = df.index // per_row
    return (alt.Chart(df).mark_text()
            .encode(
                x=alt.X("col:O", axis=None),
                y=alt.Y("row:O", axis=None),
                text="term:N",
                size=alt.Size("count:Q", scale=alt.Scale(range=[12, 46]), legend=None),
                color=alt.Color("count:Q", legend=None),
                tooltip=["term", "count", "documents"])
            .properties(height=max(120, 42 * (len(df) // per_row + 1))))
