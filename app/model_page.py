#!/usr/bin/env python
"""
Model an outcome (Surveys and Interviews, Explore), simplified in Update 3, phase 4b (item 4b.5d).

On the page: what you want to do (three plain goals, as on the desktop), what you want to explain,
and for an effect, the one thing whose effect you want. One main button fits the model. The method,
the seed, the number of folds, the predictors and the controls are under More options, and so is
how a case is built. The results and the caveats are not behind anything.

The model builder (`V6_PLAN.md` §3 and Phase C).

Shelves for a statistical model, the way `app/charts_page.py` is shelves for a
figure. `core/model_spec.py` holds the grammar, `analysis/design_matrix.py`
builds the table, `analysis/models.py` and `analysis/double_lasso.py` do the
fitting. This page is a skin over all four and decides nothing.

The step every mixed-methods researcher currently takes outside the program is
export to SPSS, Stata or R, run a model, and paste the result into a paper where
nothing connects it to the coding that produced the variables. This is that step,
in the project file, with the provenance attached.

Three interface decisions carry the methodology
------------------------------------------------
**Treatment is a shelf, and filling it changes the question.** Empty, the page
predicts and shows no interval. Filled — which only double lasso accepts — it
estimates one effect and reports a confidence interval. Making that a drag
rather than a checkbox means the analyst states a hypothesis before the program
will give them an interval, which is what the method demands anyway.

**Problems are shown before the run button, not after.** `problems()` returns
sentences; blocking ones disable the button and advisory ones do not. An analyst
should find out that their project is too small *before* they wait for a fit.

**The caveats are not collapsible.** They come from the design matrix and the
fitter, they travel into the export, and they are the difference between a
coefficient table and a coefficient table somebody can trust. A table of numbers
looks authoritative whatever produced it, which is exactly why the qualifications
cannot be behind a toggle.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

import pandas as pd
import streamlit as st
from app.shared.layout import stretch

from app.shared import help_ui
from analysis.design_matrix import CODE_PREFIX, DESC_PREFIX, matrix_from_project
from core.model_spec import (
    METHODS, ModelRequest, Shelf, can_run, describe, problems)
from core.project import Project
from core.ux import model_goals
from core.ux.fields import model_field_label

#: Shown when the analyst has not opened a project.
_NO_PROJECT = (
    "Open or create a project first. Modelling works from the project's codes and respondent details.")


def render_model_page(store_path: Optional[Path]) -> None:
    """Render the model builder for the active project store."""
    st.caption("Find out which themes and respondent details go with an outcome. It is the step usually done "
               "in SPSS, Stata or R, done here so the model stays with the coding that made its variables.")

    if not store_path or not Path(store_path).exists():
        st.info(_NO_PROJECT)
        return

    with Project.open(store_path) as project:
        matrix = _build_matrix(project)

    if not matrix.usable:
        st.info(matrix.refusal)
        return

    st.caption(matrix.describe())
    _render_goal()
    request = _render_shelves(matrix)
    _render_problems(matrix, request)


def _render_goal() -> None:
    """What you want to do. Choosing one sets the method; the method can still be changed under More
    options, and the goal then says so rather than pretending."""
    state = st.session_state
    method = state.get("model_method") or next(iter(METHODS))
    current = model_goals.goal_for_method(method)
    if "model_goal" not in state:
        state["model_goal"] = current or model_goals.GOAL_KEYS[0]
    goal = st.radio(
        "What do you want to do?", model_goals.GOAL_KEYS, key="model_goal",
        format_func=lambda k: next(t for g, _m, t in model_goals.GOALS if g == k))
    if state.get("_model_goal_applied") != goal:
        state["_model_goal_applied"] = goal
        state["model_method"] = model_goals.METHOD_FOR_GOAL[goal]      # before the method box is drawn


def _build_matrix(project):
    """The design matrix, with the unit and coder the analyst chose.

    Both choices are on the page rather than assumed, because both change the
    answer: the unit decides what a case is, and pooling coders builds variables
    neither of them asserted.
    """
    with st.expander("More options: how cases are built", expanded=False):
        left, right = st.columns(2)
        with left:
            unit_label = st.radio(
                "One case is", ["A document", "A respondent (across documents)"],
                key="model_unit", horizontal=False,
                help="Per respondent only means something for wide-form survey "
                     "data, where one person answered several questions.")
            unit = ("source_id" if unit_label.startswith("A document")
                    else "respondent_id")
            encoding_label = st.radio(
                "A code counts as", ["Applied or not (0/1)", "How many times"],
                key="model_encoding",
                help="0/1 is usually right in survey mode, where an passage is "
                     "the whole response: a count would mostly measure how many "
                     "pieces the response was split into.")
        with right:
            raters = _rater_options(project)
            rater = st.selectbox(
                "Count codings by", raters, key="model_rater",
                format_func=lambda r: "All coders" if r is None else r,
                help="Pooling coders builds variables neither of them asserted. "
                     "A regression will report a coefficient for one anyway.")

    encoding = ("binary" if encoding_label.startswith("Applied") else "count")
    return matrix_from_project(project, unit=unit, rater_id=rater,
                               encoding=encoding)


def _rater_options(project) -> List[Optional[str]]:
    coding = project.coding_table()
    if coding.empty or "rater_id" not in coding.columns:
        return [None]
    found = sorted({str(r) for r in coding["rater_id"].dropna() if str(r)})
    return [None] + found


def _render_shelves(matrix) -> ModelRequest:
    """What to explain (and, for an effect, the one thing whose effect you want) on the page; the
    method, seed, folds, predictors and controls under More options."""
    columns = [c for c in matrix.frame.columns if c != "case_id"]
    method_keys = list(METHODS)
    state = st.session_state
    label = model_field_label

    outcome = st.selectbox(
        "What do you want to explain?", [""] + columns, key="model_outcome",
        format_func=lambda f: "Choose…" if f == "" else label(f),
        help="One thing, such as a respondent detail or a theme.")
    method = state.get("model_method") if state.get("model_method") in METHODS else method_keys[0]
    inferential = METHODS[method].inferential
    treatment = ""
    if inferential:
        treatment = st.selectbox(
            "The one thing whose effect you want", [""] + columns, key="model_treatment",
            format_func=lambda f: "Choose…" if f == "" else label(f),
            help="The thing you want a defensible number for.")

    with st.expander("More options"):
        method = st.selectbox(
            "Method", method_keys, key="model_method",
            format_func=lambda k: METHODS[k].display_label,
            help=help_ui.tip("model.method"))
        inferential = METHODS[method].inferential
        st.caption(METHODS[method].blurb)
        left, right = st.columns(2)
        seed = left.number_input("Seed", value=20260829, step=1, key="model_seed",
                                 help=help_ui.tip("model.seed"))
        folds = right.number_input("Parts to test on", min_value=2, max_value=20, value=5, key="model_folds",
                                   help=help_ui.tip("model.folds"))
        predictors = st.multiselect(
            "What the model may use", columns, key="model_predictors",
            default=model_goals.without(_default_predictors(columns), outcome, treatment),
            format_func=label, help="The outcome, and the thing whose effect you want, are left out for you.")
        controls = st.multiselect(
            "Always allow for", columns, key="model_controls", format_func=label,
            help="Kept in the final model and never dropped.")

    return ModelRequest(
        method=method,
        outcome=Shelf((outcome,) if outcome else ()),
        treatment=Shelf((treatment,) if treatment and inferential else ()),
        predictors=Shelf(tuple(model_goals.without(predictors, outcome, treatment))),
        controls=Shelf(tuple(controls)),
        seed=int(seed), folds=int(folds))


def _default_predictors(columns: List[str]) -> List[str]:
    """Every code, and nothing else.

    A sensible opening position rather than an empty page: the codes are what
    this program has that a statistics package does not, and the analyst
    removes what they do not want.
    """
    return [c for c in columns if c.startswith(CODE_PREFIX)][:20]


def _render_problems(matrix, request: ModelRequest) -> None:
    """What is wrong, then the button, then the result."""
    columns = [c for c in matrix.frame.columns if c != "case_id"]
    outcome = request.outcome.first
    levels = (int(matrix.frame[outcome].nunique())
              if outcome in matrix.frame.columns else None)

    found = problems(request, columns, n_cases=matrix.n_cases,
                     outcome_levels=levels)
    runnable = can_run(request, columns, n_cases=matrix.n_cases,
                       outcome_levels=levels)

    for problem in found:
        text = model_goals.plain(problem, columns)
        st.warning(text) if runnable else st.error(text)

    st.caption(model_goals.plain(describe(request), columns))
    if not st.button("Fit the model", disabled=not runnable, type="primary",
                     key="model_fit"):
        return

    from analysis.models import fit

    with st.spinner("Fitting the model…"):
        result = fit(matrix, request)

    # Kept so the download buttons can rebuild the report: an export needs the
    # spec and the matrix, not only the result.
    st.session_state["model_last_request"] = request
    st.session_state["model_last_matrix"] = matrix

    if not result.usable:
        st.error(result.refusal)
        return

    _render_result(result)


def _render_result(result) -> None:
    """The estimate, the table, and the caveats — in that order, none hidden."""
    st.subheader("What it found")

    if result.effect is not None:
        _render_effect(result.effect)

    left, right = st.columns([1, 1])
    left.metric("Cases modelled", result.n_cases)
    if result.score is not None:
        right.metric(result.score_name, f"{result.score:.3f}")

    frame = result.frame()
    st.dataframe(frame, **stretch(), hide_index=True)

    if result.kind == "importance":
        st.caption("*Importances have no direction: they say how much worse the "
                   "model predicted when a column was shuffled, not whether the "
                   "code makes the outcome more or less likely.*")

    _render_downloads(result, frame)

    st.markdown("#### How to read this")
    for note in result.notes:
        st.caption(f"· {note}")
    st.caption(f"· Seed {result.seed}. The same project and the same seed give "
               "the same numbers.")



def _render_downloads(result, frame) -> None:
    with st.expander("Save the result"):
        _downloads_body(result, frame)


def _downloads_body(result, frame) -> None:
    """The table, the report, and the matrix.

    Three buttons rather than one because they are for three different moments:
    the CSV for a spreadsheet now, the Word report for a chapter later, and the
    design matrix for somebody who wants to redo this in R. `V6_PLAN.md`
    Phase D.
    """
    import tempfile

    from exports.model_export import build_model_docx, export_design_matrix

    columns = st.columns(3)
    columns[0].download_button(
        "Table (CSV)", frame.to_csv(index=False).encode("utf-8"),
        file_name=f"model_{result.method}_{result.outcome}.csv",
        mime="text/csv", key="model_csv")

    request = st.session_state.get("model_last_request")
    matrix = st.session_state.get("model_last_matrix")
    if request is None:
        return

    with tempfile.TemporaryDirectory() as directory:
        report = Path(directory) / "model.docx"
        build_model_docx(result, request, report, matrix=matrix)
        columns[1].download_button(
            "Report (Word)", report.read_bytes(),
            file_name=f"model_{result.method}.docx",
            mime=("application/vnd.openxmlformats-officedocument"
                  ".wordprocessingml.document"),
            key="model_docx",
            help="The table with its specification and caveats, ready for a "
                 "chapter.")

        if matrix is not None:
            csv_path = Path(directory) / "design_matrix.csv"
            export_design_matrix(matrix, csv_path)
            columns[2].download_button(
                "Design matrix (CSV)", csv_path.read_bytes(),
                file_name="design_matrix.csv", mime="text/csv",
                key="model_matrix_csv",
                help="The modelling table itself, for R or Stata. The encoding "
                     "decisions are in the .json written beside it.")

def _render_effect(effect) -> None:
    """The number double lasso exists to produce."""
    low, high = effect.interval
    st.markdown(f"**Effect of `{effect.treatment}`**")
    columns = st.columns(3)
    columns[0].metric("Estimate", f"{effect.coefficient:.3f}")
    columns[1].metric("95% interval", f"[{low:.3f}, {high:.3f}]")
    columns[2].metric("Std. error", f"{effect.std_error:.3f}")

    if effect.only_from_treatment:
        st.caption(
            "*Controls kept only because they predict the treatment: "
            + ", ".join(f"`{name}`" for name in effect.only_from_treatment[:6])
            + " — a single-selection lasso would have dropped these, and "
              "dropping them is what biases the estimate.*")
