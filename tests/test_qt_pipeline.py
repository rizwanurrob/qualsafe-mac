"""
The pipeline path: config construction, the PII gate, and running off the GUI thread.

Two halves, and the first is the important one.

`qualsafe_qt.pipeline_config` is pure — no Qt, no Streamlit — because the config
dict is a **contract with `analyze_survey.run_pipeline`**, and a typo in one of
its forty keys is a silently different analysis. `app/shared/data.build_general_config`
could never be tested at all, since it reads `st.session_state`. This one can, so
it is, key by key.

The second half drives the screen with `run_pipeline` mocked. The suite must stay
offline, torch-free, and fast (upstream convention), so no test here loads a
model — what is checked is that the run happens on a worker, that progress and
failures come back, and that a preview can never become the project of record.
"""

from __future__ import annotations

import os
import threading

import pytest

pytest.importorskip("PySide6", reason="Qt front end not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd  # noqa: E402
from PySide6.QtCore import Qt, QThreadPool  # noqa: E402
from PySide6.QtGui import QUndoStack  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from qualsafe_qt.pipeline_config import (  # noqa: E402
    FALLBACK_LABELS, PREVIEW_ROWS, RunSettings, build_config, label_packs,
    mapping_is_ready, parse_labels, parse_per_question_labels,
    resolve_long_dataframe,
)
from qualsafe_qt.services.project_service import ProjectService  # noqa: E402
from qualsafe_qt.views.pipeline_view import PipelineView  # noqa: E402

LONG = pd.DataFrame({
    "response_id": ["101", "102", "103"],
    "question": ["What was hardest?"] * 3,
    "answer": ["The cost of books.", "Making friends.", "Getting an advisor."],
    "program": ["Nursing", "Business", "Nursing"],
})

WIDE = pd.DataFrame({
    "respondent": ["101", "102"],
    "Q1_hardest": ["The cost of books.", "Making friends."],
    "Q2_best": ["The library.", "My roommate."],
    "program": ["Nursing", "Business"],
})


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# -- the config contract -----------------------------------------------------
def test_the_config_carries_every_section_the_pipeline_reads(tmp_path):
    settings = RunSettings(text_column="answer", question_column="question",
                           id_column="response_id", labels_text="Cost\nBelonging")
    config = build_config(LONG, settings, tmp_path)

    for section in ("input", "preprocessing", "models", "pipeline", "clustering",
                    "sentiment", "zero_shot", "thematic_analysis", "engine",
                    "strict_thresholds", "output"):
        assert section in config, f"run_pipeline reads config[{section!r}]"
    assert config["input"]["text_column"] == "answer"
    assert config["input"]["question_column"] == "question"
    assert config["input"]["id_column"] == "response_id"
    assert config["zero_shot"]["labels"] == ["Cost", "Belonging"]


def test_the_config_points_at_a_snapshot_inside_the_run_directory(tmp_path):
    """The pipeline reads its input from a path, so the working frame is
    snapshotted — into the run's own folder, so it lives and dies with the
    outputs it produced rather than accumulating somewhere nobody looks."""
    settings = RunSettings(text_column="answer", labels_text="Cost")
    config = build_config(LONG, settings, tmp_path)

    snapshot = pd.read_csv(config["input"]["file_path"])
    assert len(snapshot) == len(LONG)
    assert str(tmp_path) in config["input"]["file_path"]


def test_empty_labels_fall_back_rather_than_running_with_none(tmp_path):
    config = build_config(LONG, RunSettings(text_column="answer"), tmp_path)
    assert config["zero_shot"]["labels"] == FALLBACK_LABELS


def test_per_engine_thresholds_are_kept_apart(tmp_path):
    """Transformer scores are NLI entailment; LLM scores are self-report. They
    are not comparable, which is why each engine keeps its own pair."""
    settings = RunSettings(text_column="answer", labels_text="Cost",
                           strict_top1_transformer=0.61, strict_top1_llm=0.82)
    config = build_config(LONG, settings, tmp_path)
    assert config["strict_thresholds"]["transformer"]["top1_min_score"] == 0.61
    assert config["strict_thresholds"]["llm"]["top1_min_score"] == 0.82


def test_descriptors_are_carried_into_the_config(tmp_path):
    settings = RunSettings(text_column="answer", labels_text="Cost",
                           descriptor_columns=["program", "not_a_column"])
    config = build_config(LONG, settings, tmp_path)
    assert config["input"]["descriptor_columns"] == ["program"], \
        "columns that are not in the frame must be dropped, not passed through"


# -- preview must never become the project of record -------------------------
def test_a_preview_caps_rows_and_writes_no_project(tmp_path):
    settings = RunSettings(text_column="answer", labels_text="Cost",
                           save_project_store=True)
    config = build_config(LONG, settings, tmp_path, preview=True)
    assert config["preprocessing"]["max_rows"] == PREVIEW_ROWS
    assert config["output"]["project_store_path"] is None, \
        "a quick look must not quietly become the analysis"


def test_a_full_run_writes_a_project_when_asked(tmp_path):
    config = build_config(LONG, RunSettings(text_column="answer", labels_text="Cost"),
                          tmp_path)
    assert config["output"]["project_store_path"].endswith("project.qnw")


def test_the_project_store_can_be_declined(tmp_path):
    settings = RunSettings(text_column="answer", labels_text="Cost",
                           save_project_store=False)
    config = build_config(LONG, settings, tmp_path)
    assert config["output"]["project_store_path"] is None


# -- reshaping ---------------------------------------------------------------
def test_long_data_passes_through_with_its_columns():
    frame, text, question, ident, descriptors = resolve_long_dataframe(
        LONG, RunSettings(text_column="answer", question_column="question",
                          id_column="response_id", descriptor_columns=["program"]))
    assert (text, question, ident) == ("answer", "question", "response_id")
    assert descriptors == ["program"]
    assert len(frame) == 3


def test_long_data_without_a_question_column_gets_a_stamped_label():
    frame, _text, question, _id, _d = resolve_long_dataframe(
        LONG, RunSettings(text_column="answer",
                          question_text_manual="What was hardest?"))
    assert question == "question_text"
    assert set(frame["question_text"]) == {"What was hardest?"}


def test_wide_data_melts_and_mints_a_unique_id_per_answer():
    """The melt is where this project's worst shipped bug lived: a per-answer id
    that collides detaches coding from responses."""
    frame, text, question, ident, _d = resolve_long_dataframe(
        WIDE, RunSettings(ingestion_mode="wide",
                          text_columns=["Q1_hardest", "Q2_best"],
                          id_column="respondent", descriptor_columns=["program"]))
    assert (text, question, ident) == ("response_text", "question_text", "response_id")
    assert len(frame) == 4, "two respondents x two questions"
    assert frame["response_id"].nunique() == 4, "every answer needs its own id"
    assert frame["respondent_id"].nunique() == 2, "grouping stays per person"


def test_wide_mode_without_question_columns_is_refused():
    with pytest.raises(ValueError, match="at least one question column"):
        resolve_long_dataframe(WIDE, RunSettings(ingestion_mode="wide"))


def test_a_missing_text_column_is_refused():
    with pytest.raises(ValueError, match="valid text column"):
        resolve_long_dataframe(LONG, RunSettings(text_column="nope"))


def test_one_question_mode_filters(tmp_path):
    settings = RunSettings(text_column="answer", question_column="question",
                           labels_text="Cost", analyze_one_question=True,
                           question_filter_value="What was hardest?")
    config = build_config(LONG, settings, tmp_path)
    assert len(pd.read_csv(config["input"]["file_path"])) == 3

    settings.question_filter_value = "Not a question"
    with pytest.raises(ValueError, match="No rows left"):
        build_config(LONG, settings, tmp_path)


# -- ids stay text -----------------------------------------------------------
def test_response_ids_survive_the_snapshot_as_text(tmp_path):
    """HANDOFF §7.1: a numeric id column read back as float becomes "101.0" —
    a different join key than the one the coding widgets used."""
    settings = RunSettings(text_column="answer", id_column="response_id",
                           labels_text="Cost")
    config = build_config(LONG, settings, tmp_path)
    reread = pd.read_csv(config["input"]["file_path"], dtype=str,
                         keep_default_na=False)
    assert list(reread["response_id"]) == ["101", "102", "103"]


# -- small helpers -----------------------------------------------------------
def test_labels_parse_one_per_line_without_duplicates():
    assert parse_labels("Cost\n\n Belonging \nCost\n") == ["Cost", "Belonging"]


def test_per_question_labels_parse():
    parsed = parse_per_question_labels(
        "What was hardest? :: Cost | Belonging\nrubbish line\n")
    assert parsed == {"What was hardest?": ["Cost", "Belonging"]}


def test_mapping_readiness():
    assert not mapping_is_ready(None, RunSettings())
    assert not mapping_is_ready(LONG, RunSettings())
    assert mapping_is_ready(LONG, RunSettings(text_column="answer"))
    assert mapping_is_ready(WIDE, RunSettings(ingestion_mode="wide",
                                              text_columns=["Q1_hardest"]))


def test_label_packs_include_the_education_starter():
    packs = label_packs()
    assert "Education / Student Experience" in packs
    assert "Financial concerns" in packs["Education / Student Experience"]


# -- the screen --------------------------------------------------------------
@pytest.fixture
def view(qapp, tmp_path):
    service = ProjectService()
    widget = PipelineView(service, QUndoStack())
    yield widget
    service.close()


def _load(view, tmp_path, frame=LONG, name="data.csv"):
    path = tmp_path / name
    frame.to_csv(path, index=False)
    view._load(path)
    return path


def test_the_run_is_blocked_until_data_mapping_themes_and_the_gate(view, tmp_path):
    assert "load a data file" in view.blockers()

    _load(view, tmp_path)
    assert not view.run_button.isEnabled()
    blockers = view.blockers()
    assert any("text column" in b for b in blockers)
    assert any("confirm" in b for b in blockers)
    assert any("theme" in b for b in blockers)

    view.text_column.setCurrentIndex(view.text_column.findData("answer"))
    view.labels_edit.setPlainText("Cost\nBelonging")
    view.pii_confirm.setChecked(True)
    assert view.blockers() == []
    assert view.run_button.isEnabled()


def test_loading_different_data_re_arms_the_pii_gate(view, tmp_path):
    """The attestation is per dataset and is never persisted — a remembered
    attestation is not an attestation."""
    _load(view, tmp_path, name="first.csv")
    view.text_column.setCurrentIndex(view.text_column.findData("answer"))
    view.labels_edit.setPlainText("Cost")
    view.pii_confirm.setChecked(True)
    assert view.blockers() == []

    _load(view, tmp_path, name="second.csv")
    assert not view.pii_confirm.isChecked()
    assert any("confirm" in b for b in view.blockers())
    assert not view.run_button.isEnabled()


def test_the_pii_scan_runs_on_load_and_reports_what_it_found(view, tmp_path):
    identified = pd.DataFrame({
        "answer": ["Reach me at jane.doe@example.edu about the cost."],
        "email": ["jane.doe@example.edu"],
    })
    _load(view, tmp_path, identified, name="identified.csv")
    summary = view.pii_summary.text()
    assert "email address" in summary
    assert "jane.doe@example.edu" not in summary, \
        "the gate must show a masked example, never the value it matched"


def test_the_run_happens_on_a_worker_thread(view, qapp, tmp_path, monkeypatch):
    """The whole reason this screen exists in the fork: `run_pipeline` takes
    minutes, and the window must stay usable while it works."""
    import qualsafe_qt.views.pipeline_view as module

    gui_thread = threading.get_ident()
    seen = {}

    def fake_pipeline(config, progress_callback=None):
        seen["thread"] = threading.get_ident()
        seen["config"] = config
        if progress_callback:
            progress_callback(0.5, "Embedding responses…")
            progress_callback(1.0, "Done")
        return {"total_responses": 3, "clusters_found": 2, "questions_coded": 1,
                "questions_total": 1, "possible_outliers": 0,
                "project_store": str(tmp_path / "project.qnw")}

    monkeypatch.setattr(module, "_run_pipeline", fake_pipeline)
    _prepare(view, tmp_path)

    progress = []
    view._on_progress = lambda f, m: progress.append((f, m))
    written = []
    view.project_written.connect(written.append)

    view._run(preview=False)
    _drain(qapp)

    assert seen["thread"] != gui_thread, "the pipeline must not run on the GUI thread"
    assert progress and progress[-1][0] == 1.0
    assert written, "a finished run should hand its project to the shell"
    assert "Run complete" in view.summary_label.text()


def test_a_preview_run_does_not_hand_a_project_to_the_shell(view, qapp, tmp_path,
                                                            monkeypatch):
    import qualsafe_qt.views.pipeline_view as module

    captured = {}

    def fake_pipeline(config, progress_callback=None):
        captured["config"] = config
        return {"total_responses": 3, "project_store": None}

    monkeypatch.setattr(module, "_run_pipeline", fake_pipeline)
    _prepare(view, tmp_path)

    written = []
    view.project_written.connect(written.append)
    view._run(preview=True)
    _drain(qapp)

    assert captured["config"]["output"]["project_store_path"] is None
    assert captured["config"]["preprocessing"]["max_rows"] == PREVIEW_ROWS
    assert not written
    assert "preview" in view.summary_label.text().lower()


def test_a_missing_model_is_explained_not_reported_as_a_crash(view, qapp, tmp_path,
                                                              monkeypatch):
    """Model downloads are a separate, explicit step by design, so a missing
    model is an ordinary state rather than a failure to apologise for."""
    import qualsafe_qt.views.pipeline_view as module

    shown = []
    monkeypatch.setattr(module.QMessageBox, "information",
                        staticmethod(lambda *a, **k: shown.append(a)))
    monkeypatch.setattr(module.QMessageBox, "critical",
                        staticmethod(lambda *a, **k: shown.append(("critical",) + a)))

    view._on_failed("The model 'facebook/bart-large-mnli' is not in your local cache",
                    "ModelNotDownloadedError: ...")
    assert shown and shown[0][0] != "critical", \
        "a missing model should be explained, not shown as a crash"


def test_a_real_failure_is_reported(view, monkeypatch):
    import qualsafe_qt.views.pipeline_view as module

    shown = []
    monkeypatch.setattr(module.QMessageBox, "critical",
                        staticmethod(lambda *a, **k: shown.append(a)))
    view._on_failed("disk full", "OSError: disk full")
    assert shown


def test_the_run_button_is_disabled_while_a_run_is_in_flight(view, qapp, tmp_path,
                                                             monkeypatch):
    import qualsafe_qt.views.pipeline_view as module

    monkeypatch.setattr(module, "_run_pipeline",
                        lambda config, progress_callback=None: {"total_responses": 1})
    _prepare(view, tmp_path)
    assert view.run_button.isEnabled()

    view._running = True
    view._refresh_enabled()
    assert not view.run_button.isEnabled()
    assert not view.preview_button.isEnabled()


def test_switching_to_the_llm_engine_resets_the_thresholds(view):
    """A transformer threshold carried onto an LLM score would measure a
    different thing entirely."""
    view.engine.setCurrentIndex(view.engine.findData("transformer"))
    assert view.strict_top1.value() == pytest.approx(0.55)
    view.engine.setCurrentIndex(view.engine.findData("llm"))
    assert view.strict_top1.value() == pytest.approx(0.70)
    assert not view.llm_row.isHidden()


def test_settings_reflect_the_widgets(view, tmp_path):
    _prepare(view, tmp_path)
    view.use_sentiment.setChecked(False)
    view.descriptors.item(_row_of(view.descriptors, "program")).setCheckState(
        Qt.CheckState.Checked)

    settings = view.settings()
    assert settings.text_column == "answer"
    assert settings.labels_text.splitlines() == ["Cost", "Belonging"]
    assert settings.use_sentiment is False
    assert settings.descriptor_columns == ["program"]


def _row_of(widget, text: str) -> int:
    for i in range(widget.count()):
        if widget.item(i).text() == text:
            return i
    raise AssertionError(f"{text!r} not in the list")


def _prepare(view, tmp_path) -> None:
    """Load data, map it, write themes, and pass the gate."""
    _load(view, tmp_path)
    view.text_column.setCurrentIndex(view.text_column.findData("answer"))
    view.question_column.setCurrentIndex(view.question_column.findData("question"))
    view.labels_edit.setPlainText("Cost\nBelonging")
    view.pii_confirm.setChecked(True)


def _drain(app, rounds: int = 80) -> None:
    for _ in range(rounds):
        app.processEvents()
        if QThreadPool.globalInstance().waitForDone(30):
            break
    for _ in range(15):
        app.processEvents()


def test_the_text_column_is_never_guessed(view, tmp_path):
    """The first text-like column of a long-form survey is often the *question*.

    An auto-pick would quietly analyse the prompts instead of the answers, and
    the run would succeed — a wrong default that runs is worse than one more
    click, so the mapping starts blank.
    """
    _load(view, tmp_path)
    assert view.text_column.currentData() == "", "no column should be pre-selected"
    assert not mapping_is_ready(view._frame, view.settings())
    assert any("text column" in b for b in view.blockers())
