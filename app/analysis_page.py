"""
Frequency, co-occurrence, crosstabs, agreement, and adjudication.

Extracted from the former monolithic `streamlit_app.py` (v4, Phase 0.1).
Per `app/__init__`, this module imports only from `core/`, `analysis/`,
`exports/`, `app.shared`, and Streamlit — never from `streamlit_app`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import altair as alt
import pandas as pd
import streamlit as st
from app.shared.caveat import caveat
from app.shared.layout import stretch
from analysis.agreement import agreement_summary, labels_from_delimited, low_agreement_codes, per_code_kappa
from analysis.cooccurrence import cooccurrence_matrix
from analysis.crosstab import code_by_descriptor
from analysis.frequency import code_frequency
from core.project import Project

from app.shared.data import load_coding_sample_df
from app.shared.projects import active_project_path, list_project_runs
from app.shared.state import _nav_cb
from core.ux.fields import friendly
from app.shared.widgets import _show_excerpts, render_chart_export, render_memo_section


def _rater_filtered(coding, *, key_prefix: str, pooled_is_misleading: bool = True):
    """A coder picker, plus a warning when a pooled selection is in force.

    Returns the filtered frame. With one contributing rater there is nothing to
    choose and nothing to warn about, so no widget is drawn.

    `pooled_is_misleading=False` offers the same choice without the banner, for
    views where pooling is merely unhelpful rather than wrong.
    """
    if "rater_id" not in coding.columns:
        return coding
    raters = sorted(r for r in coding["rater_id"].dropna().unique())
    if len(raters) < 2:
        return coding

    choice = st.selectbox(
        "Coder", ["All coders"] + raters, key=f"{key_prefix}_rater",
        help=("Which coder's applications to count. 'All coders' pools them, "
              "which mixes human and machine judgements into pairings neither "
              "coder made."))
    if choice != "All coders":
        return coding[coding["rater_id"] == choice]
    if not pooled_is_misleading:
        return coding

    caveat(
        f"**{len(raters)} coders contributed** ({', '.join(f'`{r}`' for r in raters)}), "
        "and this view pools them. A pair where one coder applied one code and "
        "another applied the other counts here, though neither of them claimed "
        "it — and the result will move if the model is re-run. Pick a single "
        "coder for an attributable finding.")
    return coding


def _render_freq_tab(coding, excerpt_lookup) -> None:
    # A count of applications is honest about being a count of applications, so
    # this is less misleading than the pooled co-occurrence matrix. The filter is
    # here anyway: an analyst asking "how much did *I* code" should not have to
    # subtract the model's work in their head.
    coding = _rater_filtered(coding, key_prefix="freq", pooled_is_misleading=False)
    freq = code_frequency(coding)
    st.caption("How often each code was applied. Click a code to see the responses behind it.")
    bar = (alt.Chart(freq).mark_bar()
           .encode(x=alt.X("n:Q", title="applications"),
                   y=alt.Y("code_name:N", sort="-x", title=None),
                   tooltip=["code_name", "n"]))
    st.altair_chart(bar, **stretch())
    render_chart_export(bar, "code_frequency", data_df=freq[["code_name", "n"]], key_prefix="freq")
    st.dataframe(freq[["code_name", "n"]], **stretch(), hide_index=True)
    pick = st.selectbox("Drill into a code", freq["code_name"].tolist(), key="freq_drill")
    row = freq[freq["code_name"] == pick].iloc[0]
    _show_excerpts(row["excerpt_ids"], excerpt_lookup)


def _render_cooc_tab(coding, excerpt_lookup) -> None:
    # Whose co-occurrences? The matrix was built from every rater's applications
    # together, which was harmless when one pipeline run populated the store and
    # became misleading the moment human coding entered it: a passage the analyst
    # marked *Financial concerns* and the model marked *Advising* counted as an
    # "A co-occurs with B" event neither of them asserted. Two consequences —
    # the finding is not attributable, and it moves when the model version
    # changes though no human changed their mind.
    #
    # "All coders" stays the default so a project reads the same in this build
    # and the desktop one, but the mixing is now stated instead of silent. Same
    # pattern as the kappa caveats: the caveat travels with the number.
    coding = _rater_filtered(coding, key_prefix="cooc")

    # Feature B: when respondent_id is present (wide-form), offer a respondent-level
    # view — codes co-occur if the same *person* raised both, even across questions.
    has_respondent = ("respondent_id" in coding.columns
                      and coding["respondent_id"].notna().any())
    group_col = "excerpt_id"
    if has_respondent:
        unit = st.radio(
            "Co-occurrence unit", ["Per response (passage)", "Per respondent (across questions)"],
            horizontal=True, key="cooc_unit",
            help="Per respondent groups a person's answers across questions — a wider "
                 "'these themes travel together in the same person' view.")
        group_col = "respondent_id" if unit.startswith("Per respondent") else "excerpt_id"

    matrix, drill = cooccurrence_matrix(coding, group_col=group_col)
    if group_col == "respondent_id":
        st.caption("Codes raised by the same **respondent**, across all their answers. "
                   "Drill-back lists respondent ids.")
    else:
        st.caption("Codes applied to the same response. NOTE: with whole-response passages this is "
                   "*within-respondent co-mention* (themes a person raised together), not same-sentence overlap.")
    from core.theme import HEATMAP_SCHEMES, heatmap_range
    scheme = st.selectbox(
        "Heatmap colors", list(HEATMAP_SCHEMES.keys()), key="heatmap_scheme",
        help="Pick a color ramp. Low counts use the left (lightest/darkest) end; "
             "all ramps keep low cells visible rather than fading to the background.")
    long = (matrix.reset_index().melt(id_vars="index", var_name="code_b", value_name="count")
            .rename(columns={"index": "code_a"}))
    chart = (alt.Chart(long).mark_rect()
             .encode(x=alt.X("code_b:N", title=None), y=alt.Y("code_a:N", title=None),
                     color=alt.Color("count:Q", title="co-occurrences",
                                     scale=alt.Scale(range=heatmap_range(scheme))),
                     tooltip=["code_a", "code_b", "count"]))
    st.altair_chart(chart, **stretch())
    render_chart_export(chart, "cooccurrence", data_df=long, key_prefix="cooc")
    pairs = sorted(drill.keys())
    if pairs:
        labels = [f"{a}  +  {b}" for (a, b) in pairs]
        i = st.selectbox("Drill into a co-occurring pair", range(len(pairs)),
                         format_func=lambda k: labels[k], key="cooc_drill")
        if group_col == "respondent_id":
            ids = drill[pairs[i]]
            st.caption(f"{len(ids)} respondent(s) raised both:")
            st.write(", ".join(f"`{r}`" for r in ids[:50]))
        else:
            _show_excerpts(drill[pairs[i]], excerpt_lookup)
    else:
        st.info("No pairs of codes co-occur in the same unit.")

    _render_code_network(coding, group_col)


def _render_code_network(coding, group_col: str) -> None:
    """The same relationships as the heatmap above, drawn as a map.

    A heatmap answers "how often do these two co-occur"; it does not show the
    shape of a codebook — which codes form a cluster, which sits on its own,
    which one bridges two groups. That picture is what ATLAS.ti, MAXQDA and
    NVivo all ship and this program did not.

    Built from the same coding table and the same unit as the heatmap, so the
    two can never disagree about one project.
    """
    from analysis.code_network import DEFAULT_MIN_STRENGTH, build_code_network

    st.markdown("---")
    st.markdown("#### Code network")
    st.caption(
        "Which codes travel together, as a map. Edge thickness is Jaccard "
        "strength, not raw count, so a code applied to half the documents does not "
        "come out joined to everything. **The layout is deterministic** — the "
        "same project always draws the same picture, so a figure in a paper can "
        "be reproduced.")

    strength = st.slider(
        "Minimum relationship strength", min_value=0.0, max_value=1.0,
        value=float(DEFAULT_MIN_STRENGTH), step=0.05, key="network_strength",
        help="Jaccard: of the units carrying either code, the share carrying "
             "both. Raise it to see only the strongest structure; lower it to "
             "see everything, including the noise.")

    network = build_code_network(coding, unit=group_col, min_strength=strength)
    if not network.usable:
        st.info(network.refusal)
        return

    frames = network.to_frames()
    nodes, edges = frames["nodes"], frames["edges"]

    lines = (alt.Chart(edges).mark_rule(opacity=0.55)
             .encode(x=alt.X("x:Q", axis=None, scale=alt.Scale(domain=[-0.1, 1.1])),
                     y=alt.Y("y:Q", axis=None, scale=alt.Scale(domain=[-0.1, 1.1])),
                     x2="x2:Q", y2="y2:Q",
                     strokeWidth=alt.StrokeWidth(
                         "strength:Q", title="strength",
                         scale=alt.Scale(range=[0.5, 6])),
                     tooltip=["source", "target", "strength", "count"]))
    points = (alt.Chart(nodes).mark_circle(opacity=0.85)
              .encode(x=alt.X("x:Q", axis=None), y=alt.Y("y:Q", axis=None),
                      size=alt.Size("count:Q", title="units coded",
                                    scale=alt.Scale(range=[80, 900])),
                      color=alt.Color("isolated:N", title="unconnected",
                                      scale=alt.Scale(domain=[False, True])),
                      tooltip=["code", "count"]))
    labels = (alt.Chart(nodes).mark_text(dy=-14, fontSize=11)
              .encode(x="x:Q", y="y:Q", text="code:N"))

    chart = (lines + points + labels).properties(height=460).configure_view(stroke=None)
    st.altair_chart(chart, **stretch())
    render_chart_export(chart, "code_network", data_df=nodes,
                        key_prefix="network")

    for note in network.caveats():
        caveat(note, "note")


def _render_crosstab_tab(coding, desc, source_lookup) -> None:
    if desc.empty:
        st.info("No respondent details in this project. Designate respondent detail columns in Data Setup and re-run.")
        return
    keys = sorted(desc["key"].unique().tolist())
    key = st.selectbox("Group by", keys, key="ct_key", format_func=friendly,
                       help="A detail about each respondent (class year, first-generation status…) chosen "
                            "on the Load step. The table breaks each theme down by it.")
    mode = st.radio("Show", ["Counts (distinct respondents)", "% within group (normalized)"],
                    horizontal=True, key="ct_norm",
                    help="Use % within group when subgroups differ in size — 10 of 20 "
                         "first-gen students is a bigger deal than 15 of 200 others.")
    normalize = "group_size" if mode.startswith("%") else None
    table, drill = code_by_descriptor(coding, desc, key, normalize=normalize)
    if table.empty:
        st.info("No overlap between codes and this respondent detail.")
        return
    st.caption("Theme prevalence by subgroup. Normalized view = % of each group's respondents coded with the theme.")
    st.dataframe(table.rename_axis("Theme"), **stretch())
    c1, c2 = st.columns(2)
    dcode = c1.selectbox("Theme", table.index.tolist(), key="ct_code")
    dval = c2.selectbox("Group", list(table.columns), key="ct_val")
    sids = drill.get((dcode, dval), [])
    st.caption(f"{len(sids)} respondent(s) with '{dcode}' where {friendly(key).lower()} = {dval}:")
    for sid in sids[:40]:
        src = source_lookup.get(sid)
        if src is not None:
            with st.container(border=True):
                st.write(src.raw_text)

    _render_prevalence_intervals(coding, desc, key)


def _render_prevalence_intervals(coding, desc, key) -> None:
    """Prevalence per group with 95% intervals, and one group-vs-group comparison.

    Groups of 30-300 respondents make a 5-point gap mostly noise; the interval
    says how much (analysis.prevalence, V7 Update 2).
    """
    from analysis.prevalence import (CAVEATS, compare_groups, describe_difference,
                                     display_table, pooling_caveat, prevalence_table)

    st.divider()
    st.subheader("Prevalence with 95% intervals")
    raters = sorted(coding["rater_id"].dropna().unique()) if "rater_id" in coding.columns else []
    rater = None
    if len(raters) > 1:
        choice = st.selectbox("Coder", ["All coders (pooled)"] + raters, key="prev_rater",
                              help="Report the prevalence one coder asserted, not a pool.")
        rater = None if choice.startswith("All") else choice
    shown = coding if rater is None else coding[coding["rater_id"] == rater]
    note = pooling_caveat(shown)
    if note:
        caveat(note)
    table = prevalence_table(coding, desc, key, rater_id=rater)
    if table.empty:
        st.info("No respondents carry this respondent detail.")
        return
    st.dataframe(display_table(table), **stretch(), hide_index=True)
    for caveat_text in CAVEATS:
        caveat(caveat_text, "note")

    groups = list(dict.fromkeys(table["group"].tolist()))
    if len(groups) < 2:
        return
    c1, c2, c3 = st.columns(3)
    code = c1.selectbox("Compare, for code", sorted(table["code"].unique()), key="prev_code")
    group_a = c2.selectbox("Group A", groups, index=0, key="prev_a")
    group_b = c3.selectbox("Group B", groups, index=1, key="prev_b")
    if group_a != group_b:
        st.write(describe_difference(compare_groups(table, code, group_a, group_b)))


def _render_joint_display_tab(coding, desc, store_path) -> None:
    """The mixed-methods deliverable: quant, qual, and the inference between them.

    The Code × Descriptor tab answers the question. This tab is the *publishable
    form* of the answer — the named artifact of mixed-methods research, which
    puts the numbers and the words side by side and leaves a column for what the
    analyst concludes from reading them together.

    The integration column stays empty until the analyst writes it. Pre-filling
    it would be the software writing the finding.
    """
    from analysis.joint_display import build_joint_display, display_caveats

    if desc.empty:
        st.info(
            "A joint display needs a respondent detail — a respondent attribute like "
            "class year or program — to form its quantitative half. Designate "
            "respondent detail columns in Data Setup and re-run.")
        return

    st.caption(
        "Themes down the side, subgroups across the top, an illustrative quote, "
        "and your integration statement. This is the table a mixed-methods "
        "findings chapter prints."
    )

    keys = sorted(desc["key"].unique().tolist())
    left, right = st.columns([2, 1])
    key = left.selectbox("Quantitative axis (respondent detail)", keys, key="jd_key")
    normalize = right.checkbox(
        "% within subgroup", value=True, key="jd_norm",
        help="On, because subgroups are rarely equal: 10 of 20 first-generation "
             "students is a bigger deal than 15 of 200 others, and raw counts "
             "invert that comparison.")

    with Project.open(store_path) as project:
        display = build_joint_display(
            coding, desc, key, project=project, normalize=normalize,
            inferences=_saved_inferences(project, key))

    if not display.codes:
        st.info("No themes overlap this respondent detail.")
        return

    st.dataframe(display.to_frame(), **stretch())

    for caveat_text in display_caveats(display):
        caveat(caveat_text)

    st.markdown("**Integration** — what does putting the two halves together say?")
    st.caption(
        "One line per theme, in your words. It is saved with the project and "
        "travels into the export."
    )
    edited: Dict[str, str] = {}
    for code in display.codes:
        edited[code] = st.text_input(
            code, value=display.inferences.get(code, ""),
            key=f"jd_inf_{key}_{code}",
            placeholder="e.g. the gap is concentrated in first-year commuters")

    if st.button("Save integration statements", key="jd_save"):
        with Project.open(store_path) as project:
            for code, text in edited.items():
                _save_inference(project, key, code, text.strip())
        st.success("Saved with the project.")

    _render_joint_display_downloads(display, key)


def _inference_target(descriptor_key: str, code_name: str) -> str:
    return f"{descriptor_key}::{code_name}"


def _saved_inferences(project, descriptor_key: str) -> Dict[str, str]:
    """The analyst's integration statements for this descriptor."""
    out: Dict[str, str] = {}
    try:
        memos = project.list_memos(target_type="joint_display")
    except Exception:  # noqa: BLE001 - a display must render without its memos
        return out
    prefix = f"{descriptor_key}::"
    for memo in memos:
        target = getattr(memo, "target_id", "") or ""
        if target.startswith(prefix):
            out[target[len(prefix):]] = memo.text
    return out


def _save_inference(project, descriptor_key: str, code_name: str, text: str) -> None:
    """Write one integration statement, replacing rather than appending.

    `add_memo` appends, and a statement the analyst edits four times would
    otherwise leave four memos with no reliable way to tell which is current —
    memo ids are not ordered by time. So this updates in place, and clearing the
    box deletes rather than storing an empty note.
    """
    from core.model import Memo

    target = _inference_target(descriptor_key, code_name)
    existing = [m for m in project.list_memos(target_type="joint_display")
                if (getattr(m, "target_id", "") or "") == target]
    if not text:
        for memo in existing:
            project.delete_memo(memo.memo_id)
        return
    if existing:
        project.update_memo(existing[0].memo_id, text)
        for extra in existing[1:]:  # tidy any duplicates an older build left
            project.delete_memo(extra.memo_id)
        return
    project.add_memo(Memo(memo_id="", target_type="joint_display",
                          target_id=target, text=text))


def _render_joint_display_downloads(display, descriptor_key: str) -> None:
    """Word for the chapter, Excel for the working file."""
    from exports.joint_display_export import (
        build_joint_display_docx, build_joint_display_workbook)

    with st.expander("Download this display"):
        include_quotes = st.checkbox(
            "Include verbatim quotes in the Word table", value=True,
            key="jd_quotes",
            help="Quotes are response text. The Excel workbook never contains "
                 "them, so it stays safe to email.")
        if st.button("Build the files", key="jd_build"):
            import tempfile

            with tempfile.TemporaryDirectory() as tmp:
                docx_path = build_joint_display_docx(
                    display, Path(tmp) / "joint_display.docx",
                    include_quotes=include_quotes,
                    title=f"Joint Display — themes by {descriptor_key}")
                xlsx_path = build_joint_display_workbook(
                    display, Path(tmp) / "joint_display.xlsx")
                st.session_state["jd_docx"] = docx_path.read_bytes()
                st.session_state["jd_xlsx"] = xlsx_path.read_bytes()

        if st.session_state.get("jd_docx"):
            cols = st.columns(2)
            cols[0].download_button(
                "Word (.docx)", data=st.session_state["jd_docx"],
                file_name=f"joint_display_{descriptor_key}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key="jd_dl_docx")
            cols[1].download_button(
                "Excel (.xlsx)", data=st.session_state["jd_xlsx"],
                file_name=f"joint_display_{descriptor_key}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="jd_dl_xlsx")


def _render_saturation_tab(coding, store_path) -> None:
    """New codes against sources coded — and every reason not to over-read it.

    "Was saturation reached?" is the commonest challenge to a qualitative study
    and no other package computes an answer. The curve is easy; the caveats are
    the feature. They are rendered *above* the chart deliberately, because a
    figure quoted in a Methods section travels without whatever sat below it.
    """
    import altair as alt

    from analysis.saturation import (
        saturation_caveats, saturation_curve, saturation_summary)

    st.caption(
        "How many new codes each source added, in order. A curve that flattens "
        "means later sources stopped producing new labels."
    )

    left, right = st.columns(2)
    humans_only = left.checkbox(
        "Human coding only", value=True, key="sat_humans",
        help="A model applying a fixed label set saturates immediately and has "
             "discovered nothing, so including it flatters the curve.")
    real_order = right.checkbox(
        "Sources are in collection order", value=False, key="sat_order",
        help="Tick only if the ingestion order really is the order the data was "
             "collected. Saturation is a claim about sequence.")

    with Project.open(store_path) as project:
        source_order = project.source_ids_in_ingestion_order()
        codebook = project.get_codebook()

    curve = saturation_curve(coding, source_order=source_order,
                             humans_only=humans_only)
    if curve.empty:
        st.info(
            "No human coding yet, so there is no discovery to plot. Code some "
            "passages by hand and the curve appears."
            if humans_only else "Nothing coded yet.")
        return

    summary = saturation_summary(curve)

    for caveat_text in saturation_caveats(curve, codes=codebook,
                                     order_is_collection_order=real_order):
        caveat(caveat_text)

    cols = st.columns(3)
    cols[0].metric("Codes found", summary.codes_found)
    cols[1].metric("Last new code at", f"#{summary.last_new_code_at}")
    cols[2].metric("Sources since", summary.plateau_length)

    chart = (alt.Chart(curve)
             .mark_line(point=True)
             .encode(x=alt.X("position:Q", title="Sources coded"),
                     y=alt.Y("cumulative_codes:Q", title="Codes discovered"),
                     tooltip=["position", "source_id", "new_codes",
                              "cumulative_codes"]))
    st.altair_chart(chart, **stretch())
    render_chart_export(chart, "saturation", data_df=curve, key_prefix="sat")

    st.markdown("**For your methods section**")
    st.code(summary.as_sentence(), language=None)
    st.caption(
        "Copy this, then add which of the cautions above apply to your study. "
        "The tool deliberately does not say whether saturation was reached — "
        "that is a judgement about your design, not a number."
    )


def _render_deviant_tab(coding, store_path) -> None:
    """The responses that carry a code but do not read like it.

    This proposes cases to re-read. It does not decide that any of them is
    deviant, and the wording on the page has to keep saying so: distance from a
    centroid is a property of the embedding, not a finding about the data.
    """
    from analysis.deviant_cases import (
        MIN_APPLICATIONS, coded_responses, find_deviant_cases)

    st.caption(
        "For one code, the responses sitting furthest from how you have used "
        "that code elsewhere. They are worth re-reading: some will be genuine "
        "outliers that sharpen the analysis, and some will be miscodings."
    )

    if coding.empty:
        st.info("Nothing is coded yet.")
        return

    counts = coding["code_name"].value_counts()
    left, right = st.columns([3, 1])
    code = left.selectbox("Code", counts.index.tolist(), key="dev_code",
                          format_func=lambda name: f"{name}  ({counts[name]})")
    how_many = right.number_input("How many", min_value=3, max_value=20, value=5,
                                  key="dev_n")

    if int(counts[code]) < MIN_APPLICATIONS:
        st.info(
            f"“{code}” is on {int(counts[code])} response(s). Below "
            f"{MIN_APPLICATIONS} the centre of a code sits close to every "
            "response, so distance from it says nothing. Code a few more first.")
        return

    if not st.button("Find them", key="dev_run"):
        st.caption(
            "This reads the responses through the similarity model, so it needs "
            "the analysis engine installed and takes a few seconds the first time."
        )
        return

    with Project.open(store_path) as project:
        collected = coded_responses(project, code)

    try:
        with st.spinner("Reading the responses…"):
            report = find_deviant_cases(
                collected["texts"], collected["identifiers"],
                code_name=code, top_n=int(how_many))
    except ImportError:
        st.warning(
            "This needs the analysis engine (the similarity model), which is not "
            "installed in this environment. Everything else on this page works "
            "without it.")
        return
    except Exception as exc:  # noqa: BLE001 - never blank the page
        st.error(f"Could not read the responses: {exc}")
        return

    if not report.usable:
        st.info(report.refusal)
        return

    for caveat_text in report.caveats():
        caveat(caveat_text)

    for candidate in report.candidates:
        with st.container(border=True):
            st.caption(candidate.why())
            st.write(candidate.text)


def _render_agreement_tab(run_dir: Path) -> None:
    st.caption("Per-code Cohen's kappa. Percent agreement + prevalence sit next to kappa so "
               "rare-code paradoxes stay visible.")

    mode = st.radio(
        "Compare",
        ["Human vs. model", "Human vs. second human", "Two coders on documents"],
        horizontal=True, key="irr_mode",
        help="Human-vs-human needs a second coder's sample imported in Data Management. "
             "Documents compares span coding (yours, or a colleague's imported from "
             ".qdpx) sentence by sentence.",
    )
    min_support = st.slider(
        "Minimum support per code (below this → insufficient-N)", 2, 15, 5, key="irr_minsup",
        help="A kappa computed on a code that appears only 2–3 times is statistical "
             "noise. Codes below this many occurrences are flagged 'insufficient-N' "
             "instead of getting an unstable number.")

    # Both human-vs-human views read the project store, not a Lab sample, so a
    # documents-only project reaches them too.
    if mode == "Human vs. second human":
        _render_human_vs_human(min_support)
        return
    if mode == "Two coders on documents":
        _render_span_agreement(min_support)
        return

    iterative_dir = Path(st.session_state["iterative_output_dir"])

    # Surface how the human sample was selected — an uncertainty-selected sample
    # understates agreement, and that caveat has to travel with the number.
    note_path = iterative_dir / "sampling_note.txt"
    if note_path.exists():
        note = note_path.read_text(encoding="utf-8")
        (st.warning if "uncertainty" in note.lower() else st.caption)(note)

    sample_path = iterative_dir / "coding_sample.csv"
    if not sample_path.exists():
        st.info("No coding_sample.csv found. Create and code a sample in the Iterative Labeling Lab first.")
        return
    # All-text read: keeps response_id stable so the human↔model join actually
    # matches (a float-coerced "101.0" would silently miss the model's "101").
    sample = load_coding_sample_df(iterative_dir)
    human = labels_from_delimited(sample, id_col="response_id", label_col="human_labels")

    scored_path = run_dir / "responses_scored.csv"
    if not scored_path.exists():
        st.info("responses_scored.csv not found for this run.")
        return
    scored = pd.read_csv(scored_path)
    if "zshot_strict_label" not in scored.columns:
        st.info("This run has no strict-coded labels. Enable strict coding (Theme Setup) so the model has "
                "committed labels to compare against, then re-run.")
        return
    # Normalize the model's response_id the same way (float-coerced "101.0" → "101")
    # so it aligns with the human sample's ids.
    from analyze_survey import clean_id_series
    if "response_id" in scored.columns:
        scored["response_id"] = clean_id_series(scored["response_id"])

    # 2.2: the model was fit on training rows (in the iterative flow), so its
    # prediction there is not held-out. Default to excluding them from kappa.
    exclude_training = True
    if "in_training_sample" in scored.columns:
        exclude_training = st.checkbox(
            "Exclude iterative training items from kappa (recommended)", value=True,
            key="irr_excl_train",
            help="Agreement on items the model trained on overstates real performance.")
        if exclude_training:
            held_out_ids = set(scored.loc[~scored["in_training_sample"].astype(bool), "response_id"])
            sample = sample[sample["response_id"].isin(held_out_ids)]
            human = labels_from_delimited(sample, id_col="response_id", label_col="human_labels")

    model = labels_from_delimited(scored, id_col="response_id", label_col="zshot_strict_label")
    kdf = per_code_kappa(human, model, min_support=min_support)
    if kdf.empty:
        if exclude_training and "in_training_sample" in scored.columns:
            st.warning("No held-out coded items yet — every coded response is in the training sample. "
                       "Code additional responses that are *not* in the training set, or untick the "
                       "exclusion above to see agreement on training items (overstated).")
        else:
            st.warning("No overlapping response ids between the human sample and this run.")
        return
    _show_kappa(kdf, overlap_n=len(set(human) & set(model)))


def _render_human_vs_human(min_support: int) -> None:
    """Kappa between two human coders from the active project store (2.5)."""
    store = active_project_path()
    if store is None or not Path(store).exists():
        st.info("No project store selected. Pick one in Data Management.")
        return
    from core.agreement_pairs import compare_raters, selectable_raters

    with Project.open(store) as proj:
        # The adjudicated set is offered last: comparing a coder with it is a
        # gold-standard check, and the caveats below say it is not IRR.
        raters = selectable_raters(proj)
        if len(raters) < 2:
            st.info("Need two human coders in the store. Import a second coder's sample in "
                    "Data Management (it becomes `human_secondary`).")
            return
        col1, col2 = st.columns(2)
        a = col1.selectbox("Coder A", raters, index=0, key="hvh_a")
        b = col2.selectbox("Coder B", raters, index=1, key="hvh_b")
        comparison = compare_raters(proj, a, b)
    if comparison is None:
        st.warning("The two coders reviewed no response in common. Kappa needs items both "
                   "reviewed.")
        return
    labels_a, labels_b = comparison.labels_a, comparison.labels_b
    overlap = set(labels_a) & set(labels_b)
    if overlap != set(labels_a) or overlap != set(labels_b):
        st.warning(f"Coders only overlap on {len(overlap)} item(s); kappa is computed on that "
                   f"intersection (correct, but note the N).")
    for caveat_text in comparison.caveats:
        caveat(caveat_text)
    kdf = per_code_kappa(labels_a, labels_b, min_support=min_support)
    if kdf.empty:
        st.warning("No shared codes between the two coders.")
        return
    _show_kappa(kdf, overlap_n=len(overlap))
    _render_disagreement_adjudication(str(store), a, labels_a, b, labels_b)


def _render_span_agreement(min_support: int) -> None:
    """Two coders' span coding compared on sentences or paragraphs (review F4).

    Their highlights rarely match to the character, so kappa is computed on a
    declared unit over the documents both have finished. A colleague's coding
    usually arrives by .qdpx import and cannot be marked finished inside this
    program, so the analyst records it here, per document, for both coders.
    """
    from core.agreement_pairs import span_comparison, span_raters

    store = active_project_path()
    if store is None or not Path(store).exists():
        st.info("No project store selected. Pick one in Data Management.")
        return
    with Project.open(store) as proj:
        coders = span_raters(proj)
        if len(coders) < 2:
            st.info("Need two coders' span coding in this project: code documents yourself "
                    "on the Documents page, and import a colleague's from NVivo, MAXQDA or "
                    "ATLAS.ti (.qdpx) in Data Management.")
            return
        c1, c2, c3, c4 = st.columns([2, 2, 1, 2])
        a = c1.selectbox("Coder A", coders, index=0, key="span_a")
        b = c2.selectbox("Coder B", coders, index=1, key="span_b")
        unit = c3.radio("Unit", ["sentence", "paragraph"], key="span_unit")
        rule_label = c4.radio(
            "A unit carries a code when",
            ["any coded passage touches it", "coded passages cover half of it"],
            key="span_rule",
            help="The second is stricter: a highlight that runs a few characters into the "
                 "next sentence no longer codes that sentence.")
        rule = "any_overlap" if rule_label.startswith("any") else "majority"
        if a == b:
            st.info("Pick two different coders.")
            return

        spans = proj.coding_spans_table()
        coded_by = {r: set(spans.loc[spans["rater_id"] == r, "source_id"]) for r in (a, b)}
        documents = [s for s in proj.list_sources()
                     if s.type == "document" and s.source_id in coded_by[a] & coded_by[b]]
        if not documents:
            st.warning("These two coders have no document in common.")
            return
        finished_a, finished_b = proj.documents_coded_by(a), proj.documents_coded_by(b)
        st.markdown("**Documents both coders have finished.** Only these are compared: in "
                    "an unfinished document, sentences nobody has reached yet would count as "
                    "\"no code applies\".")
        for doc in documents:
            title = doc.metadata.get("title") or doc.label or doc.source_id
            done = doc.source_id in finished_a and doc.source_id in finished_b
            ticked = st.checkbox(title, value=done, key=f"span_done_{doc.source_id}")
            if ticked != done:
                for coder in (a, b):
                    proj.mark_document_coded(coder, doc.source_id, coded=ticked)
        comparison = span_comparison(proj, a, b, unit=unit, rule=rule)

    if comparison is None:
        st.info("Tick at least one document above that both coders have finished.")
        return
    for caveat in comparison.caveats:
        st.caption(caveat)
    kdf = per_code_kappa(comparison.labels_a, comparison.labels_b, min_support=min_support)
    if kdf.empty:
        st.warning("Neither coder applied a code in the finished documents.")
        return
    _show_kappa(kdf, overlap_n=len(comparison.labels_a))
    st.caption("Reconciling disagreements works on survey responses; for documents, read "
               "the two coders' stripes side by side on the Documents page.")


def _render_disagreement_adjudication(store, name_a, labels_a, name_b, labels_b) -> None:
    """List the items two coders disagreed on and let the analyst adjudicate (F2).

    Resolutions are written as a separate `human_adjudicated` rater, so neither
    coder's original codings (which κ depends on) are touched, and the reconciled
    set can serve as the gold standard.
    """
    from analysis.disagreement import disagreement_summary, disagreements
    from core.adjudication import ADJUDICATED_RATER, record_adjudications

    items = disagreements(labels_a, labels_b)
    summary = disagreement_summary(labels_a, labels_b)

    st.divider()
    st.subheader("Reconcile disagreements")
    st.caption(
        "The items the two coders coded differently. Resolve each to an agreed set — "
        "the decision is saved as a separate `human_adjudicated` coder and never "
        "changes either coder's original codes."
    )
    st.write(f"**{summary['disagree_items']}** disagreement(s) across "
             f"{summary['overlap_items']} shared item(s).")
    if not items:
        st.success("The two coders agree on every shared item.")
        return

    with Project.open(store) as proj:
        texts = {}
        for d in items:
            exc = proj.get_excerpt(d["excerpt_id"])
            texts[d["excerpt_id"]] = exc.text if exc else "(response text unavailable)"
        adjudicated = proj.rater_labels(ADJUDICATED_RATER)

    max_show = 50
    shown = items[:max_show]
    if len(items) > max_show:
        st.caption(f"Showing the first {max_show} of {len(items)}. Resolve these, then reopen.")

    for d in shown:
        eid = d["excerpt_id"]
        with st.container(border=True):
            st.markdown(f"> {texts[eid]}")
            cc1, cc2 = st.columns(2)
            cc1.caption(f"**{name_a}:** {', '.join(d['a_codes']) or '(none)'}")
            cc2.caption(f"**{name_b}:** {', '.join(d['b_codes']) or '(none)'}")
            prior = adjudicated.get(eid, set())
            options = sorted(set(d["a_codes"]) | set(d["b_codes"]) | set(prior))
            default = sorted(prior) if eid in adjudicated else d["agreed"]
            chosen = st.multiselect(
                "Resolve to", options=options,
                default=[o for o in default if o in options], key=f"adj_ms_{eid}")
            rc1, rc2 = st.columns([1, 3])
            if rc1.button("Save resolution", key=f"adj_save_{eid}"):
                try:
                    record_adjudications(store, {eid: chosen})
                    st.success("Resolved.")
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Could not save: {exc}")
            if eid in adjudicated:
                rc2.caption(f"✓ resolved → {', '.join(sorted(prior)) or '(no code)'}")


def _show_kappa(kdf: pd.DataFrame, overlap_n: int) -> None:
    summary = agreement_summary(kdf)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Overlap items", overlap_n)
    c2.metric("Reliable codes", summary["n_reliable"])
    c3.metric("Mean kappa", summary["mean_kappa"])
    c4.metric("Weighted mean kappa", summary["weighted_mean_kappa"])
    st.dataframe(kdf, **stretch(), hide_index=True)
    routed = low_agreement_codes(kdf)
    if routed:
        st.warning("Route to human review (low or insufficient agreement): " + ", ".join(routed))


def render_analysis() -> None:
    st.caption("Read the coded results: how often each theme comes up, by group, together, and how well "
               "coders agree. Every count leads back to the answers behind it.")
    runs = list_project_runs()
    if not runs:
        st.info("There is no coded project to read yet. On Code, keep 'Also save a project file (.qnw)' "
                "ticked, run the analysis, then come back. Or open a project file you already have.")
        st.button("Open a project file", key="an_open_project", on_click=_nav_cb, args=("Data Management",))
        return
    sel = st.selectbox("Project (from a saved run)", [p.name for p in runs], key="an_run")
    run_dir = next(p for p in runs if p.name == sel)
    store_path = run_dir / "project.qnw"
    with Project.open(store_path) as proj:
        coding = proj.coding_table()
        desc = proj.descriptor_table()
        excerpt_lookup = {e.excerpt_id: e for e in proj.list_excerpts()}
        source_lookup = {s.source_id: s for s in proj.list_sources()}
    if coding.empty:
        st.warning("This project has no codes applied yet. Run the analysis with 'Suggest a code for every "
                   "answer' ticked.")
        return

    # Four tabs, as on the desktop; the rarer analyses are under More.
    t_freq, t_desc, t_cooc, t_irr, t_more = st.tabs(
        ["How often", "By group", "Together", "Agreement (Cohen's κ)", "More"])
    with t_freq:
        _render_freq_tab(coding, excerpt_lookup)
        render_memo_section(store_path, "analysis_view", "frequency", title="Memo this view")
    with t_desc:
        _render_crosstab_tab(coding, desc, source_lookup)
    with t_cooc:
        _render_cooc_tab(coding, excerpt_lookup)
        render_memo_section(store_path, "analysis_view", "cooccurrence", title="Memo this view")
    with t_irr:
        _render_agreement_tab(run_dir)
    with t_more:
        which = st.selectbox("More analyses", ["Joint display", "Saturation", "Deviant cases"],
                             key="an_more",
                             help="Joint display: each theme against a group, with your notes. "
                                  "Saturation: whether new answers still bring new themes. "
                                  "Deviant cases: answers that do not fit the pattern.")
        if which == "Joint display":
            _render_joint_display_tab(coding, desc, store_path)
            render_memo_section(store_path, "analysis_view", "joint_display", title="Memo this view")
        elif which == "Saturation":
            _render_saturation_tab(coding, store_path)
            render_memo_section(store_path, "analysis_view", "saturation", title="Memo this view")
        else:
            _render_deviant_tab(coding, store_path)
            render_memo_section(store_path, "analysis_view", "deviant_cases", title="Memo this view")
        st.divider()
        render_memo_section(store_path, "project", None, title="Notes on this whole project")
