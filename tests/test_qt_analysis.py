"""
The Analysis screen: frequency, co-occurrence, crosstab, kappa, adjudication.

The numbers themselves are the engine's — `analysis/*` are pure functions with
their own tests upstream. What this file guards is the part the view owns: that
the right function is called with the right arguments, that drill-back reaches
the real evidence, and above all that the two methodological invariants survive
the port.

* **Invariant #5** — IRR is per-code binary Cohen's κ, always shown with percent
  agreement, prevalence, and an insufficient-N flag. No other coefficient.
* **Invariant #6** — machine coding must never be mistakable for human coding, so
  coder-vs-coder lists only raters whose id starts with `human`; the engine is
  compared in its own, labelled mode, and its disagreements cannot be reconciled.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6", reason="Qt front end not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QUndoStack  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.documents import add_document  # noqa: E402
from core.model import (  # noqa: E402
    Code, CodeApplication, Descriptor, Excerpt, Rater, Source,
)
from core.project import Project, new_id  # noqa: E402
from qualsafe_qt.models.dataframe_model import NA_DISPLAY, DataFrameModel  # noqa: E402
from qualsafe_qt.services.project_service import ProjectService  # noqa: E402
from qualsafe_qt.views.analysis_view import AnalysisView  # noqa: E402

DOC_TEXT = (
    "Respondent: the tuition was the hard part, and the books on top of it. "
    "Making friends took most of the first term. "
    "My advisor was hard to reach in October. "
    "I commute forty minutes each way."
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def coded_project(tmp_path):
    """A project with two human coders, a model coder, and a descriptor."""
    path = tmp_path / "analysis.qnw"
    with Project.create(path) as proj:
        source_id = add_document(proj, "Interview 01", DOC_TEXT)
        codes = {}
        for name in ("Financial concerns", "Sense of belonging", "Advising"):
            codes[name] = proj.add_code(Code(code_id="", name=name))

        proj.add_rater(Rater(rater_id="human_primary", kind="human", name="A"))
        proj.add_rater(Rater(rater_id="human_secondary", kind="human", name="B"))
        proj.add_rater(Rater(rater_id="transformer", kind="transformer", name="model"))

        spans = [(12, 60), (75, 118), (120, 160)]
        excerpts = []
        for start, end in spans:
            excerpts.append(proj.add_excerpt(Excerpt(
                excerpt_id="", source_id=source_id, text=DOC_TEXT[start:end],
                char_start=start, char_end=end)))

        def apply(excerpt_id, code_name, rater):
            proj.apply_code(CodeApplication(
                application_id="", excerpt_id=excerpt_id,
                code_id=codes[code_name], coder="human", rater_id=rater))

        # Coder A and B agree on the first two, differ on the third.
        apply(excerpts[0], "Financial concerns", "human_primary")
        apply(excerpts[0], "Financial concerns", "human_secondary")
        apply(excerpts[1], "Sense of belonging", "human_primary")
        apply(excerpts[1], "Sense of belonging", "human_secondary")
        apply(excerpts[2], "Advising", "human_primary")
        apply(excerpts[2], "Sense of belonging", "human_secondary")
        # A passage carrying two codes, so co-occurrence has something to find.
        apply(excerpts[0], "Sense of belonging", "human_primary")
        # The model codes too — it must never appear as a comparable coder.
        proj.apply_code(CodeApplication(
            application_id="", excerpt_id=excerpts[0], code_id=codes["Advising"],
            coder="transformer", rater_id="transformer"))

        proj.set_descriptor(Descriptor(source_id=source_id, key="Program",
                                       value="Nursing"))
    return path


@pytest.fixture
def service(qapp, coded_project):
    svc = ProjectService()
    svc.open(coded_project)
    yield svc
    svc.close()


@pytest.fixture
def view(qapp, service):
    return AnalysisView(service, QUndoStack())


# -- empty states ------------------------------------------------------------
def test_an_uncoded_project_says_so_rather_than_showing_empty_charts(qapp, tmp_path):
    path = tmp_path / "bare.qnw"
    with Project.create(path) as proj:
        add_document(proj, "Uncoded", DOC_TEXT)
    service = ProjectService()
    service.open(path)
    try:
        view = AnalysisView(service, QUndoStack())
        assert not view.empty_label.isHidden()
        assert "No coding" in view.empty_label.text()
    finally:
        service.close()


# -- frequency ---------------------------------------------------------------
def test_frequency_counts_match_the_engine(view, service):
    from analysis.frequency import code_frequency

    expected = code_frequency(service.coding_table())
    shown = view.freq_model.frame
    assert list(shown["code_name"]) == list(expected["code_name"])
    assert list(shown["n"]) == list(expected["n"])


def test_clicking_a_code_shows_the_passages_behind_it(view):
    view._drill_frequency("Financial concerns")
    html = view.freq_evidence.toHtml()
    assert "tuition was the hard part" in html
    assert "passage(s) coded 'Financial concerns'" in html


def test_drill_back_escapes_document_text(qapp, tmp_path):
    """A transcript containing markup must render as characters, not markup."""
    path = tmp_path / "markup.qnw"
    with Project.create(path) as proj:
        source_id = add_document(proj, "D", "He said <script>alert(1)</script> loudly.")
        code_id = proj.add_code(Code(code_id="", name="Quote"))
        proj.add_rater(Rater(rater_id="human_primary", kind="human"))
        excerpt_id = proj.add_excerpt(Excerpt(
            excerpt_id="", source_id=source_id,
            text="<script>alert(1)</script>", char_start=8, char_end=33))
        proj.apply_code(CodeApplication(
            application_id="", excerpt_id=excerpt_id, code_id=code_id,
            coder="human", rater_id="human_primary"))
    service = ProjectService()
    service.open(path)
    try:
        view = AnalysisView(service, QUndoStack())
        view._drill_frequency("Quote")
        html = view.freq_evidence.toHtml()
        assert "&lt;script&gt;" in html or "alert(1)" in view.freq_evidence.toPlainText()
        assert "<script>alert(1)</script>" not in html
    finally:
        service.close()


# -- co-occurrence -----------------------------------------------------------
def test_cooccurrence_finds_codes_sharing_a_passage(view):
    labels = view.cooc_heatmap._labels
    assert "Financial concerns" in labels and "Sense of belonging" in labels
    pairs = set(view._cooc_drill)
    assert ("Financial concerns", "Sense of belonging") in pairs


def test_the_diagonal_is_excluded_from_the_colour_scale(view):
    """A code's own total dwarfs every real co-occurrence; scaling to it would
    flatten the whole matrix to the bottom of the ramp."""
    heatmap = view.cooc_heatmap
    diagonal = max(heatmap._values[(i, i)] for i in range(len(heatmap._labels)))
    assert heatmap._largest < diagonal or len(heatmap._labels) == 1


def test_clicking_a_cell_drills_to_the_shared_passage(view):
    view._drill_cooccurrence("Financial concerns", "Sense of belonging")
    assert "tuition" in view.cooc_evidence.toPlainText()


def test_a_pair_that_never_co_occurs_says_so(qapp, tmp_path):
    path = tmp_path / "apart.qnw"
    with Project.create(path) as proj:
        source_id = add_document(proj, "D", DOC_TEXT)
        proj.add_rater(Rater(rater_id="human_primary", kind="human"))
        for name, (start, end) in (("Alpha", (0, 20)), ("Beta", (40, 60))):
            code_id = proj.add_code(Code(code_id="", name=name))
            excerpt_id = proj.add_excerpt(Excerpt(
                excerpt_id="", source_id=source_id, text=DOC_TEXT[start:end],
                char_start=start, char_end=end))
            proj.apply_code(CodeApplication(
                application_id="", excerpt_id=excerpt_id, code_id=code_id,
                coder="human", rater_id="human_primary"))
    service = ProjectService()
    service.open(path)
    try:
        view = AnalysisView(service, QUndoStack())
        view._drill_cooccurrence("Alpha", "Beta")
        assert "never co-occur" in view.cooc_evidence.toPlainText()
    finally:
        service.close()


def test_cooccurrence_counts_every_rater_including_the_model(view, service):
    """Documents upstream behaviour rather than asserting it is ideal.

    `app/analysis_page._render_cooc_tab` builds the matrix from the whole
    `coding_table()`, so a passage the analyst coded 'Financial concerns' and the
    model coded 'Advising' registers as a co-occurrence of the two. The Qt screen
    does the same, deliberately, so both front ends report the same number — but
    it means co-occurrence is *not* a human-only statistic, unlike kappa.
    """
    coding = service.coding_table()
    assert "transformer" in set(coding["rater_id"]), "the fixture has a model coder"
    # Advising (model) and Financial concerns (human) share excerpt 0.
    assert ("Advising", "Financial concerns") in view._cooc_drill \
        or ("Financial concerns", "Advising") in view._cooc_drill


def test_switching_to_per_document_regroups(view):
    view.cooc_unit.setCurrentIndex(1)          # per document
    assert view.cooc_unit.currentData() == "source_id"
    assert "same document" in view.cooc_caption.text()


# -- code x descriptor -------------------------------------------------------
def test_crosstab_lists_the_projects_descriptors(view):
    assert view.ct_key.currentText() == "Program"
    assert not view.ct_model.frame.empty


def test_group_by_shows_readable_names_but_groups_by_the_stored_one(view):
    """The list said first_generation and class_year (the web was fixed first); the stored key is still what is used."""
    from core.ux.fields import friendly

    keys = [view.ct_key.itemData(i) for i in range(view.ct_key.count())]
    assert keys and all("_" not in view.ct_key.itemText(i) for i in range(view.ct_key.count()))
    for i, key in enumerate(keys):
        assert view.ct_key.itemText(i) == friendly(key)
    assert view._group_key() == view.ct_key.currentData() == "Program"
    assert not view.ct_model.frame.empty


def test_crosstab_drill_reaches_the_source(view):
    frame = view.ct_model.frame
    code_name = str(frame.index[0])
    value = str(frame.columns[0])
    ids = view._crosstab_drill.get((code_name, value), [])
    assert ids, "the fixture should produce at least one drillable cell"


def test_a_project_without_descriptors_explains_itself(qapp, tmp_path):
    path = tmp_path / "nodesc.qnw"
    with Project.create(path) as proj:
        source_id = add_document(proj, "D", DOC_TEXT)
        code_id = proj.add_code(Code(code_id="", name="X"))
        proj.add_rater(Rater(rater_id="human_primary", kind="human"))
        excerpt_id = proj.add_excerpt(Excerpt(
            excerpt_id="", source_id=source_id, text=DOC_TEXT[:20],
            char_start=0, char_end=20))
        proj.apply_code(CodeApplication(
            application_id="", excerpt_id=excerpt_id, code_id=code_id,
            coder="human", rater_id="human_primary"))
    service = ProjectService()
    service.open(path)
    try:
        view = AnalysisView(service, QUndoStack())
        assert "No respondent details" in view.ct_caption.text()
    finally:
        service.close()


# -- agreement: the invariants ----------------------------------------------
def test_only_human_raters_can_be_compared(view, service):
    """Invariant #6. The project contains a `transformer` rater; it must not be
    selectable as a second coder."""
    offered = [view.rater_a.itemText(i) for i in range(view.rater_a.count())]
    assert set(offered) == {"human_primary", "human_secondary"}
    assert "transformer" not in offered
    assert "transformer" in service.project.rater_ids(), \
        "the model rater should exist in the store — it is filtered, not absent"


def test_kappa_is_reported_with_percent_agreement_and_prevalence(view):
    """Invariant #5. The kappa paradox is only legible when these travel
    together, so they are never separated."""
    columns = set(view.kappa_model.frame.columns)
    assert {"code", "kappa", "percent_agreement", "prevalence_human",
            "prevalence_model", "reliable", "note"} <= columns


def test_no_coefficient_other_than_kappa_is_offered(view):
    """Invariant #5 again, stated as an absence."""
    frame_columns = " ".join(str(c) for c in view.kappa_model.frame.columns).lower()
    for forbidden in ("alpha", "krippendorff", "ac1", "gwet", "scott", "pi_"):
        assert forbidden not in frame_columns
    summary = view.kappa_summary.text().lower()
    for forbidden in ("krippendorff", "gwet", "ac1"):
        assert forbidden not in summary


def test_insufficient_support_is_flagged_not_silently_numbered(view):
    view.min_support.setValue(15)              # nothing in the fixture clears this
    frame = view.kappa_model.frame
    assert not frame.empty
    assert (~frame["reliable"]).all()
    assert frame["note"].str.contains("insufficient_support").all()
    assert frame["kappa"].isna().all(), \
        "an unreliable code must not carry a number that looks trustworthy"


def test_low_agreement_codes_are_routed_to_review(view):
    view.min_support.setValue(2)
    assert "Route to human review" in view.routed_label.text()


def test_kappa_needs_two_different_coders(view):
    view.rater_b.setCurrentText(view.rater_a.currentText())
    assert "two different coders" in view.kappa_summary.text()


def test_a_project_with_one_human_coder_explains_what_is_missing(qapp, tmp_path):
    path = tmp_path / "solo.qnw"
    with Project.create(path) as proj:
        source_id = add_document(proj, "D", DOC_TEXT)
        code_id = proj.add_code(Code(code_id="", name="X"))
        proj.add_rater(Rater(rater_id="human_primary", kind="human"))
        excerpt_id = proj.add_excerpt(Excerpt(
            excerpt_id="", source_id=source_id, text=DOC_TEXT[:20],
            char_start=0, char_end=20))
        proj.apply_code(CodeApplication(
            application_id="", excerpt_id=excerpt_id, code_id=code_id,
            coder="human", rater_id="human_primary"))
    service = ProjectService()
    service.open(path)
    try:
        view = AnalysisView(service, QUndoStack())
        assert "two human coders" in view.kappa_summary.text()
    finally:
        service.close()


def test_overlap_caveat_appears_when_coders_did_not_code_the_same_items(view, service):
    """κ on a partial intersection is correct but needs its N stated."""
    from core.model import CodeApplication

    proj = service.project
    source_id = service.document_table()["source_id"].iloc[0]
    extra = proj.add_excerpt(Excerpt(
        excerpt_id="", source_id=source_id, text=DOC_TEXT[160:190],
        char_start=160, char_end=190))
    proj.apply_code(CodeApplication(
        application_id="", excerpt_id=extra,
        code_id=proj.find_code_by_name("Advising").code_id,
        coder="human", rater_id="human_primary"))
    service.notify_changed()

    assert "overlap on" in view.kappa_summary.text()


# -- adjudication ------------------------------------------------------------
def test_disagreements_are_listed(view):
    assert view._disagreements, "the fixture has one disagreeing item"
    assert view.disagreement_list.count() == len(view._disagreements)


def test_resolving_a_disagreement_writes_a_separate_adjudicated_rater(view, service):
    """The reconciled set must never overwrite either coder's original codings —
    kappa depends on them, and a resolution that rewrote history would make the
    reported agreement unreproducible."""
    from core.adjudication import ADJUDICATED_RATER

    before_a = dict(service.rater_labels("human_primary"))
    before_b = dict(service.rater_labels("human_secondary"))

    item = view._disagreements[0]
    view._save_adjudication(item["excerpt_id"], ["Advising"])

    adjudicated = service.rater_labels(ADJUDICATED_RATER)
    assert adjudicated.get(item["excerpt_id"]) == {"Advising"}
    assert service.rater_labels("human_primary") == before_a
    assert service.rater_labels("human_secondary") == before_b


def test_the_adjudicated_rater_becomes_a_comparable_coder(view, service):
    """It starts with `human`, so it is a legitimate coder to compare against —
    which is how an analyst checks themselves against the reconciled set."""
    item = view._disagreements[0]
    view._save_adjudication(item["excerpt_id"], ["Advising"])
    view.refresh()
    offered = [view.rater_a.itemText(i) for i in range(view.rater_a.count())]
    assert "human_adjudicated" in offered


def test_the_adjudication_panel_preselects_what_both_coders_agreed(view):
    view.disagreement_list.setCurrentRow(0)
    panel = view.adjudication_panel
    assert panel._excerpt_id == view._disagreements[0]["excerpt_id"]
    selected = {i.text() for i in panel.options.selectedItems()}
    assert selected == set(view._disagreements[0]["agreed"])


# -- the DataFrame adapter ---------------------------------------------------
def test_nan_renders_as_a_dash_not_the_word_nan():
    """An uncomputable kappa is a real state; "nan" in a results table reads
    like a bug to someone about to quote the number."""
    model = DataFrameModel(pd.DataFrame({"kappa": [float("nan"), 0.5]}))
    assert model.data(model.index(0, 0)) == NA_DISPLAY
    assert model.data(model.index(1, 0)) == "0.500"


def test_floats_are_formatted_not_repr_d():
    model = DataFrameModel(pd.DataFrame({"k": [0.6234000000000001]}),
                           precision={"k": 3})
    assert model.data(model.index(0, 0)) == "0.623"


def test_sorting_uses_values_not_display_strings():
    model = DataFrameModel(pd.DataFrame({"n": [2, 10, 1]}))
    model.sort(0)
    assert list(model.frame["n"]) == [1, 2, 10]


def test_booleans_read_as_yes_and_no():
    model = DataFrameModel(pd.DataFrame({"reliable": [True, False]}))
    assert model.data(model.index(0, 0)) == "yes"
    assert model.data(model.index(1, 0)) == "no"


def test_row_dict_and_column_index_support_drill_back():
    model = DataFrameModel(pd.DataFrame({"code_name": ["A"], "n": [3]}))
    assert model.column_index("n") == 1
    assert model.row_dict(0) == {"code_name": "A", "n": 3}
    assert model.column_index("missing") == -1


def test_the_kappa_table_keeps_every_column_the_engine_returns(view):
    """Reordering for readability must not drop a column.

    Invariant #5 requires κ to travel with percent agreement, prevalence, and
    the insufficient-N flag — so the display order is a permutation, never a
    subset.
    """
    from analysis.agreement import per_code_kappa
    from qualsafe_qt.views.analysis_view import _KAPPA_COLUMN_ORDER

    engine = per_code_kappa(
        view._service.rater_labels("human_primary"),
        view._service.rater_labels("human_secondary"),
        min_support=view.min_support.value())
    assert set(_KAPPA_COLUMN_ORDER) == set(engine.columns), \
        "the display order must be a permutation of the engine's columns"
    assert set(view.kappa_model.frame.columns) == set(engine.columns)
    assert list(view.kappa_model.frame.columns)[:2] == ["code", "kappa"], \
        "kappa should lead — it is the number the reader came for"


def test_coder_columns_are_labelled_with_the_real_coder_ids(view):
    """`per_code_kappa` names its raters `human` and `model`. Showing a second
    *person* under a column headed "model" is the exact confusion invariant #6
    exists to prevent."""
    model = view.kappa_model
    headers = [model.headerData(i, Qt.Orientation.Horizontal)
               for i in range(model.columnCount())]
    joined = " ".join(str(h) for h in headers)
    assert "human_primary" in joined and "human_secondary" in joined
    assert "model" not in joined.lower(), \
        "no column may be labelled 'model' when both coders are human"


# -- the two corrections -----------------------------------------------------
def test_cooccurrence_warns_when_it_is_mixing_coders(view):
    """A matrix built over several raters pairs codes nobody paired.

    `app/analysis_page` builds co-occurrence from the whole coding table, so in
    a project with both hand and machine coding a passage one coder marked *A*
    and another marked *B* counts as an A+B co-occurrence. The default still
    matches upstream — a project must not read differently in the two front
    ends — but the mixing has to be stated, not silent.
    """
    assert view.cooc_rater.currentData() is None, "default is all coders"
    # isHidden(), not isVisible(): a widget whose parent was never shown reports
    # isVisible() == False no matter what was set on it.
    assert not view.cooc_warning.isHidden()
    text = view.cooc_warning.text()
    assert "mixes" in text
    assert "human_primary" in text and "transformer" in text


def test_filtering_co_occurrence_to_one_coder_drops_the_cross_rater_pair(view):
    """The correction itself: one coder's matrix contains only pairings that
    coder actually asserted."""
    all_pairs = set(view._cooc_drill)
    assert ("Advising", "Financial concerns") in all_pairs \
        or ("Financial concerns", "Advising") in all_pairs, \
        "the mixed matrix pairs a human code with the model's"

    index = view.cooc_rater.findData("human_primary")
    assert index > 0
    view.cooc_rater.setCurrentIndex(index)

    mine = set(view._cooc_drill)
    assert ("Advising", "Financial concerns") not in mine \
        and ("Financial concerns", "Advising") not in mine, \
        "the human-only matrix must not carry the model's pairing"
    # The human's own genuine pairing survives.
    assert ("Financial concerns", "Sense of belonging") in mine
    assert view.cooc_warning.isHidden()
    assert "human_primary" in view.cooc_caption.text()


def test_a_single_coder_project_shows_no_mixing_warning(qapp, tmp_path):
    path = tmp_path / "solo_cooc.qnw"
    with Project.create(path) as proj:
        source_id = add_document(proj, "D", DOC_TEXT)
        proj.add_rater(Rater(rater_id="human_primary", kind="human"))
        excerpt_id = proj.add_excerpt(Excerpt(
            excerpt_id="", source_id=source_id, text=DOC_TEXT[:40],
            char_start=0, char_end=40))
        for name in ("Alpha", "Beta"):
            code_id = proj.add_code(Code(code_id="", name=name))
            proj.apply_code(CodeApplication(
                application_id="", excerpt_id=excerpt_id, code_id=code_id,
                coder="human", rater_id="human_primary"))
    service = ProjectService()
    service.open(path)
    try:
        view = AnalysisView(service, QUndoStack())
        assert view.cooc_warning.isHidden()
        assert ("Alpha", "Beta") in view._cooc_drill
    finally:
        service.close()


def test_the_model_in_the_store_is_pointed_to_not_silently_omitted(view):
    """Coder-vs-coder never lists the engine (invariant #6), but its absence is
    explained: the analyst can see the model's codings in the reader, so
    silence would look like a bug. The note says where it can be compared."""
    note = view.model_note.text()
    assert note, "a project containing machine coding should say where it is compared"
    assert "coder vs engine" in note
    assert "transformer" not in [view.rater_a.itemText(i) for i in range(view.rater_a.count())]


def test_the_note_no_longer_gives_the_false_training_reason(view):
    """The refusal said the model 'was fitted on some of what it coded'. No
    engine that writes to the store is trained on the project's human coding,
    so that reason was wrong; it must not come back."""
    text = view.model_note.text() + view.rater_a.toolTip()
    assert "fitted" not in text and "training" not in text


def test_no_model_note_when_the_project_has_only_human_coding(qapp, tmp_path):
    path = tmp_path / "human_only.qnw"
    with Project.create(path) as proj:
        source_id = add_document(proj, "D", DOC_TEXT)
        code_id = proj.add_code(Code(code_id="", name="Alpha"))
        for rater in ("human_primary", "human_secondary"):
            proj.add_rater(Rater(rater_id=rater, kind="human"))
            excerpt_id = proj.add_excerpt(Excerpt(
                excerpt_id="", source_id=source_id, text=DOC_TEXT[:40],
                char_start=0, char_end=40))
            proj.apply_code(CodeApplication(
                application_id="", excerpt_id=excerpt_id, code_id=code_id,
                coder="human", rater_id=rater))
    service = ProjectService()
    service.open(path)
    try:
        view = AnalysisView(service, QUndoStack())
        assert not view.model_note.text()
    finally:
        service.close()


def test_the_default_matrix_still_matches_the_streamlit_build(view, service):
    """The caveat is added; the number is not changed. A project must report the
    same co-occurrence in both front ends."""
    from analysis.cooccurrence import cooccurrence_matrix

    expected, _drill = cooccurrence_matrix(service.coding_table(),
                                           group_col="excerpt_id")
    heatmap = view.cooc_heatmap
    assert heatmap._labels == [str(c) for c in expected.columns]
    for r in range(len(expected.index)):
        for c in range(len(expected.columns)):
            assert heatmap._values[(r, c)] == float(expected.iat[r, c])


# -- span coding compared on a unit (review F4) ----------------------------------
def test_two_coders_span_coding_is_compared_on_sentences(qapp, tmp_path):
    """Yours and a colleague's imported coding of one document, compared
    sentence by sentence once the document is ticked as finished by both."""
    from core.model import Code, Rater, Source
    from core.span_coding import apply_codes_to_span

    path = tmp_path / "spans.qnw"
    text = "Money is tight. I work a lot. Friends help me."
    with Project.create(path) as proj:
        proj.add_code(Code(code_id="", name="Cost"))
        proj.add_source(Source(source_id="d1", type="document", raw_text=text,
                               label="Interview 1", metadata={"title": "Interview 1"}))
        proj.add_rater(Rater(rater_id="imported_alex", kind="human", name="Alex"))
        apply_codes_to_span(proj, "d1", 0, 15, ["Cost"], rater_id="human_primary")
        apply_codes_to_span(proj, "d1", 6, 20, ["Cost"], rater_id="imported_alex")
    service = ProjectService()
    service.open(path)
    try:
        view = AnalysisView(service, QUndoStack())
        view.compare_on.setCurrentText("Document sentences")
        view.rater_a.setCurrentText("human_primary")
        view.rater_b.setCurrentText("imported_alex")
        assert view.span_documents.count() == 1
        assert "finished" in view.kappa_summary.text()

        view.span_documents.item(0).setCheckState(Qt.CheckState.Checked)
        assert "sentence(s)" in view.kappa_summary.text()
        assert view.kappa_model.rowCount() == 1
        assert "d1" in service.project.documents_coded_by("imported_alex")
    finally:
        service.close()


# -- prevalence with intervals (V7 Update 2, U1) ----------------------------------
def _two_group_project(path):
    from core.model import Code, CodeApplication, Descriptor, Source
    with Project.create(path) as proj:
        proj.add_rater(Rater(rater_id="human_primary", kind="human"))
        cost = proj.add_code(Code(code_id="", name="Cost"))
        for i in range(40):
            src = Source(source_id=f"s{i}", type="survey_response", raw_text=f"text {i}")
            proj.add_source(src)
            excerpt = proj.add_whole_response_excerpt(src)
            proj.set_descriptor(Descriptor(source_id=src.source_id, key="Aid",
                                           value="Pell" if i < 20 else "Other"))
            if (i < 20 and i < 12) or (i >= 20 and i < 24):
                proj.apply_code(CodeApplication(application_id="", excerpt_id=excerpt,
                                                code_id=cost, coder="human",
                                                rater_id="human_primary"))
    return path


def test_prevalence_is_shown_with_intervals_and_a_comparison(qapp, tmp_path):
    service = ProjectService()
    service.open(_two_group_project(tmp_path / "prev.qnw"))
    try:
        view = AnalysisView(service, QUndoStack())
        view.ct_mode.setCurrentIndex(view.ct_mode.findData("intervals"))
        frame = view.ct_model.frame
        assert "95% interval" in frame.columns
        row = frame[(frame["code"] == "Cost") & (frame["group"] == "Pell")].iloc[0]
        assert row["coded / group"] == "12 / 20" and row["prevalence"] == "60.0%"
        assert "Wilson" in view.ct_note.text()
        view.ct_compare_a.setCurrentText("Pell")
        view.ct_compare_b.setCurrentText("Other")
        assert "difference of +40.0 points" in view.ct_evidence.toPlainText()
    finally:
        service.close()


# -- coder vs engine (the figure the reports print) -------------------------------
LABELS = ["Belonging", "Cost"]


def _engine_project(path, *, coded_ids):
    """A pipeline run over 40 responses, a quarter left UNCERTAIN, and a person
    who coded `coded_ids` (recorded as reviewed, v8)."""
    from core.populate import populate_project_store, record_human_codings

    rows = []
    for i in range(40):
        label = "UNCERTAIN_REVIEW" if i % 4 == 0 else LABELS[i % 2]
        rows.append({"response_id": f"r{i}", "question_text": "Q1",
                     "response_text": f"response {i}",
                     "zshot_top_label": LABELS[i % 2], "zshot_top_score": 0.8,
                     "zshot_strict_label": label,
                     "zshot_strict_confident": label != "UNCERTAIN_REVIEW",
                     "zshot_strict_margin": 0.3})
    config = {"input": {}, "output": {},
              "models": {"zero_shot_model": "facebook/bart-large-mnli"},
              "zero_shot": {"labels": LABELS, "strict_coding": {
                  "enabled": True, "uncertain_label": "UNCERTAIN_REVIEW"}}}
    store = populate_project_store(pd.DataFrame(rows), config, path)
    record_human_codings(store, {f"r{i}": [LABELS[i % 2]] for i in coded_ids},
                         question_text="Q1")
    return store


def _engine_view(qapp, path):
    service = ProjectService()
    service.open(path)
    view = AnalysisView(service, QUndoStack())
    view.compare_on.setCurrentText("Survey responses: coder vs engine")
    return service, view


def test_coder_vs_engine_shows_the_same_kappa_the_reports_print(qapp, tmp_path):
    from core.agreement_pairs import human_vs_engine, kappa_table

    store = _engine_project(tmp_path / "e.qnw", coded_ids=range(0, 40, 2))
    service, view = _engine_view(qapp, store)
    try:
        assert view.rater_a.currentText() == "human_primary"
        assert view.rater_b.currentText().startswith("rater_")
        assert view.kappa_model.rowCount() >= 1
        report = kappa_table(human_vs_engine(service.project),
                             min_support=view.min_support.value())
        shown = view.kappa_model.frame.set_index("code")["kappa"]
        printed = report.set_index("code")["kappa"]
        pd.testing.assert_series_equal(shown.sort_index(), printed.sort_index())
        summary = view.kappa_summary.text()
        assert "vs the analysis engine" in summary
        assert "does not record how the responses" in summary
    finally:
        service.close()


def test_a_hard_case_sample_is_called_out(qapp, tmp_path):
    """The person coded only the responses the engine left UNCERTAIN (a review
    queue): the check must say they are not a random sample."""
    store = _engine_project(tmp_path / "q.qnw", coded_ids=range(0, 40, 4))
    service, view = _engine_view(qapp, store)
    try:
        assert "harder than the rest" in view.kappa_summary.text()
    finally:
        service.close()


def test_engine_disagreements_can_be_read_but_not_reconciled(qapp, tmp_path):
    store = _engine_project(tmp_path / "d.qnw", coded_ids=range(0, 40, 4))
    service, view = _engine_view(qapp, store)
    try:
        assert view._disagreements, "the uncertain responses are disagreements"
        view.disagreement_list.setCurrentRow(0)
        panel = view.adjudication_panel
        assert not panel.save_button.isEnabled()
        assert not panel.options.isEnabled()
        assert "between two people" in panel.resolved_label.text()

        view.compare_on.setCurrentText("Survey responses")
        assert panel.options.isEnabled(), "coder-vs-coder reconciles as before"
    finally:
        service.close()


def test_coder_vs_engine_never_offers_the_auto_coder(qapp, tmp_path):
    store = _engine_project(tmp_path / "a.qnw", coded_ids=range(0, 40, 2))
    with Project.open(store) as proj:
        proj.add_rater(Rater(rater_id="auto_textsearch", kind="transformer"))
    service, view = _engine_view(qapp, store)
    try:
        engines = [view.rater_b.itemText(i) for i in range(view.rater_b.count())]
        assert "auto_textsearch" not in engines and len(engines) == 1
        humans = [view.rater_a.itemText(i) for i in range(view.rater_a.count())]
        assert all(h.startswith("human") for h in humans)
    finally:
        service.close()


def test_without_an_engine_run_the_mode_says_what_it_needs(view):
    view._service.engine_rater_ids = lambda: []
    view.compare_on.setCurrentText("Survey responses: coder vs engine")
    assert "needs a person's coding and an analysis run" in view.kappa_summary.text()


# -- deviant cases and saturation (audit G4 / F1) -----------------------------
def _fake_embed(texts):
    """Two directions: ordinary answers lean one way, 'ZZ' answers the other."""
    return [[0.0, 1.0] if t.startswith("ZZ") else [1.0, 0.05 * (i % 3)]
            for i, t in enumerate(texts)]


def _survey_coded(path, n=10, outlier_at=4, rater="human_primary"):
    """n one-response sources all coded 'Money'; one of them reads differently."""
    with Project.create(path) as proj:
        code = proj.add_code(Code(code_id="", name="Money", origin="emergent"))
        proj.add_rater(Rater(rater_id=rater, kind="human", name="A"))
        ids = []
        for i in range(n):
            text = (f"ZZ my cat is called Biscuit {i}" if i == outlier_at
                    else f"The fees were too high for me, case {i}")
            source_id = proj.add_source(Source(
                source_id="", type="survey_response", raw_text=text, label=f"R{i}",
                metadata={"response_id": f"r{i}"}))
            excerpt = proj.add_excerpt(Excerpt(
                excerpt_id="", source_id=source_id, text=text,
                char_start=0, char_end=len(text)))
            proj.apply_code(CodeApplication(
                application_id="", excerpt_id=excerpt, code_id=code,
                coder="human", rater_id=rater))
            ids.append(source_id)
    return ids


def _wait_for_deviants(qapp, view):
    from PySide6.QtCore import QThreadPool

    for _ in range(200):
        QThreadPool.globalInstance().waitForDone(50)
        qapp.processEvents()
        if view.dev_run.isEnabled():
            return
    raise AssertionError("the reading never finished")


def _open_view(qapp, path):
    service = ProjectService()
    service.open(path)
    view = AnalysisView(service, QUndoStack())
    view._embed = _fake_embed
    return service, view


def test_deviant_cases_offer_a_reading_order_for_survey_responses(qapp, tmp_path):
    path = tmp_path / "survey.qnw"
    ids = _survey_coded(path)
    service, view = _open_view(qapp, path)
    try:
        assert view.dev_code.currentData() == "Money"
        view.dev_run.click()
        _wait_for_deviants(qapp, view)
        first = view.dev_list.item(0).data(Qt.ItemDataRole.UserRole)
        assert "Biscuit" in first.text, "the response that reads differently leads"
        assert view.dev_list.count() == 5
        assert "Biscuit" in view.dev_passage.toPlainText()
        assert not view.dev_caveats.isHidden()
        shown = view.dev_caveats.text()
        assert "re-read" in shown and "not responses the program has judged" in shown

        seen = []
        view.open_in_reader.connect(lambda *a: seen.append(a))
        view.dev_open.click()
        assert seen == [(ids[4], 0, len(first.text))]
    finally:
        service.close()


def test_deviant_cases_work_on_hand_coded_document_passages(qapp, tmp_path):
    path = tmp_path / "doc.qnw"
    sentences = [f"Tuition worry number {i} kept me up at night." for i in range(9)]
    sentences.append("ZZ The library cat sat on my notes.")
    text = " ".join(sentences)
    with Project.create(path) as proj:
        source_id = add_document(proj, "Interview 02", text)
        code = proj.add_code(Code(code_id="", name="Money"))
        proj.add_rater(Rater(rater_id="human_primary", kind="human", name="A"))
        spans = []
        cursor = 0
        for sentence in sentences:
            start = text.index(sentence, cursor)
            end = start + len(sentence)
            cursor = end
            spans.append((start, end))
            excerpt = proj.add_excerpt(Excerpt(
                excerpt_id="", source_id=source_id, text=sentence,
                char_start=start, char_end=end))
            proj.apply_code(CodeApplication(
                application_id="", excerpt_id=excerpt, code_id=code,
                coder="human", rater_id="human_primary"))
    service, view = _open_view(qapp, path)
    try:
        view.dev_run.click()
        _wait_for_deviants(qapp, view)
        seen = []
        view.open_in_reader.connect(lambda *a: seen.append(a))
        view.dev_list.itemActivated.emit(view.dev_list.item(0))
        assert seen == [(source_id, *spans[-1])], "it opens the span, not the document"
    finally:
        service.close()


def test_deviant_cases_refuse_a_code_with_too_few_passages(qapp, tmp_path):
    from analysis.deviant_cases import MIN_APPLICATIONS

    path = tmp_path / "few.qnw"
    _survey_coded(path, n=MIN_APPLICATIONS - 1, outlier_at=0)
    service, view = _open_view(qapp, path)
    try:
        assert not view.dev_run.isEnabled()
        assert f"Below {MIN_APPLICATIONS}" in view.dev_message.text()
        assert view.dev_list.count() == 0
    finally:
        service.close()


def test_deviant_cases_never_call_a_passage_deviant(qapp, tmp_path):
    """The screen proposes passages to read. No label, and nothing is saved."""
    path = tmp_path / "survey.qnw"
    _survey_coded(path)
    service, view = _open_view(qapp, path)
    try:
        before = service.coding_table().shape
        view.dev_run.click()
        _wait_for_deviants(qapp, view)
        text = " ".join([view.dev_message.text(), view.dev_caveats.text(),
                         view.dev_passage.toPlainText()]
                        + [view.dev_list.item(i).text()
                           for i in range(view.dev_list.count())])
        for verdict in ("is deviant", "are deviant", "deviant case:", "outlier:"):
            assert verdict not in text.lower()
        assert service.coding_table().shape == before
    finally:
        service.close()


def test_deviant_cases_say_so_when_the_engine_is_not_installed(qapp, tmp_path):
    path = tmp_path / "survey.qnw"
    _survey_coded(path)
    service, view = _open_view(qapp, path)

    def missing(_texts):
        raise ImportError("no language model")

    try:
        view._embed = missing
        view.dev_run.click()
        _wait_for_deviants(qapp, view)
        assert "needs the analysis engine" in view.dev_message.text()
        assert view.dev_list.count() == 0
    finally:
        service.close()


def test_a_reading_that_finishes_after_the_code_changed_is_dropped(qapp, tmp_path):
    path = tmp_path / "survey.qnw"
    _survey_coded(path)
    service, view = _open_view(qapp, path)
    try:
        stale = view._deviant_token
        view._clear_deviant_results()           # what changing the code does
        view._deviants_ready((stale, object()))
        assert view.dev_list.count() == 0
    finally:
        service.close()


def test_saturation_counts_people_only_and_prints_the_cautions_with_it(qapp, tmp_path):
    from analysis.saturation import saturation_curve, saturation_summary

    path = tmp_path / "sat.qnw"
    with Project.create(path) as proj:
        proj.add_rater(Rater(rater_id="human_primary", kind="human", name="A"))
        proj.add_rater(Rater(rater_id="transformer", kind="transformer", name="m"))
        codes = {n: proj.add_code(Code(code_id="", name=n, origin="emergent"))
                 for n in ("Money", "Friends", "Advising")}
        plan = [("Money", "human_primary"), ("Friends", "human_primary"),
                ("Money", "human_primary"), ("Advising", "transformer")]
        for i, (name, rater) in enumerate(plan):
            source_id = proj.add_source(Source(
                source_id="", type="survey_response", raw_text=f"answer {i}",
                label=f"S{i}", metadata={"response_id": str(i)}))
            excerpt = proj.add_excerpt(Excerpt(
                excerpt_id="", source_id=source_id, text=f"answer {i}",
                char_start=0, char_end=8))
            proj.apply_code(CodeApplication(
                application_id="", excerpt_id=excerpt, code_id=codes[name],
                coder="human" if rater.startswith("human") else "transformer",
                rater_id=rater))
    service, view = _open_view(qapp, path)
    try:
        expected = saturation_summary(saturation_curve(
            service.coding_table(), humans_only=True))
        assert view.sat_humans.isChecked(), "people only is the default"
        assert expected.codes_found == 2
        assert view.sat_sentence.toPlainText() == expected.as_sentence()
        so_far = list(view.sat_model.frame["Codes so far"])
        assert len(so_far) == 3 and so_far[-1] == 2, "the model's source is left out"
        assert not view.sat_body.isHidden()
        caveats = view.sat_caveats.text()
        assert "code saturation" in caveats.lower()
        assert "ingested" in caveats                      # order is not collection order
        assert "Only 3 source(s) are coded" in caveats

        view.sat_order.setChecked(True)
        assert "ingested" not in view.sat_caveats.text()

        view.sat_humans.setChecked(False)
        so_far = list(view.sat_model.frame["Codes so far"])
        assert len(so_far) == 4 and so_far[-1] == 3, "the model's code joins the count"

        everything = " ".join([view.sat_caveats.text(), view.sat_summary.text(),
                               view.sat_message.text(),
                               view.sat_sentence.toPlainText()]).lower()
        assert "saturated" not in everything and "reached" not in everything
    finally:
        service.close()


def test_saturation_with_no_human_coding_says_there_is_nothing_to_plot(qapp, tmp_path):
    path = tmp_path / "machine.qnw"
    with Project.create(path) as proj:
        proj.add_rater(Rater(rater_id="transformer", kind="transformer", name="m"))
        code = proj.add_code(Code(code_id="", name="Money"))
        source_id = proj.add_source(Source(
            source_id="", type="survey_response", raw_text="fees", label="S",
            metadata={"response_id": "1"}))
        excerpt = proj.add_excerpt(Excerpt(
            excerpt_id="", source_id=source_id, text="fees", char_start=0, char_end=4))
        proj.apply_code(CodeApplication(
            application_id="", excerpt_id=excerpt, code_id=code,
            coder="transformer", rater_id="transformer"))
    service, view = _open_view(qapp, path)
    try:
        assert view.sat_body.isHidden()
        assert "No human coding yet" in view.sat_message.text()
        view.sat_humans.setChecked(False)
        assert not view.sat_body.isHidden()
    finally:
        service.close()


def test_the_new_tabs_are_there(view):
    titles = [view.tabs.tabText(i) for i in range(view.tabs.count())]
    assert "More: Deviant cases" in titles and "More: Saturation" in titles
