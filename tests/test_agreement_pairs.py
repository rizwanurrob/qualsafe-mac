"""Which two raters a kappa table compares, decided in one place (finding F5).

The Word report, Excel workbook and bundle each picked "the first rater id
starting with `human`" and "the first engine", alphabetically. So after one
adjudication they compared `human_adjudicated` (a handful of disputed items)
with the engine; the bundle could compare against the text-search auto-coder;
and on a real project -- where each pipeline run registers a fresh `rater_…`
id -- the Word/Excel/appendix lookups for a rater *named* `transformer` never
matched anything. They also printed kappa on codes seen twice.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis.agreement import DEFAULT_MIN_SUPPORT, labels_from_delimited, per_code_kappa
from core.agreement_pairs import comparisons, engine_raters, human_vs_engine, primary_human
from core.model import CodeApplication, Rater
from core.populate import populate_project_store, record_human_codings
from core.project import Project

LABELS = ["Belonging", "Cost"]


def _config():
    return {"input": {}, "output": {},
            "models": {"zero_shot_model": "facebook/bart-large-mnli"},
            "zero_shot": {"labels": LABELS,
                          "strict_coding": {"enabled": True, "uncertain_label": "UNCERTAIN_REVIEW"}}}


def _scored(n=12, seed_shift=0):
    rows = []
    for i in range(n):
        label = LABELS[(i + seed_shift) % 2] if i % 4 else "UNCERTAIN_REVIEW"
        rows.append({"response_id": f"r{i}", "question_text": "Q1", "response_text": f"text {i}",
                     "zshot_top_label": LABELS[i % 2], "zshot_top_score": 0.8,
                     "zshot_strict_label": label, "zshot_strict_confident": label != "UNCERTAIN_REVIEW",
                     "zshot_strict_margin": 0.3})
    return pd.DataFrame(rows)


def _human_sample(n=12):
    """A Lab sample: the analyst coded every other response and left the rest."""
    return {f"r{i}": ([LABELS[i % 2]] if i % 2 == 0 else []) for i in range(n)}


@pytest.fixture()
def project(tmp_path):
    store = populate_project_store(_scored(), _config(), tmp_path / "p.qnw")
    record_human_codings(store, _human_sample(), question_text="Q1")
    return store


def test_a_real_pipeline_run_is_found_as_the_engine(project):
    with Project.open(project) as proj:
        engines = engine_raters(proj)
        assert len(engines) == 1 and engines[0].startswith("rater_")
        assert primary_human(proj) == "human_primary"


def test_the_latest_run_is_compared_not_a_pool_of_runs(project, tmp_path):
    populate_project_store(_scored(seed_shift=1), _config(), project)
    with Project.open(project) as proj:
        engines = engine_raters(proj)
        comp = human_vs_engine(proj)
    assert len(engines) == 2
    assert comp.rater_b == engines[0], "newest run first"
    assert any("most recent" in c for c in comp.caveats)


def test_adjudication_and_auto_coders_never_stand_in(project):
    from core.adjudication import record_adjudications

    with Project.open(project) as proj:
        proj.add_rater(Rater(rater_id="auto_textsearch", kind="transformer"))
        excerpt = proj.list_excerpts()[0].excerpt_id
        code = proj.get_codebook()[0].code_id
        proj.apply_code(CodeApplication(application_id="", excerpt_id=excerpt, code_id=code,
                                        coder="transformer", rater_id="auto_textsearch"))
    record_adjudications(project, {excerpt: []})
    with Project.open(project) as proj:
        comp = human_vs_engine(proj)
    assert comp.rater_a == "human_primary"
    assert comp.rater_b.startswith("rater_")


def test_the_store_and_the_screen_give_the_same_kappa(project):
    """The Agreement tab computes from the coding-sample CSV and the scored CSV;
    every export computes from the store. Same project, same numbers."""
    human_csv = pd.DataFrame([{"response_id": k, "human_labels": "|".join(v)}
                              for k, v in _human_sample().items()])
    screen = per_code_kappa(labels_from_delimited(human_csv),
                            labels_from_delimited(_scored(), label_col="zshot_strict_label"),
                            min_support=1)
    with Project.open(project) as proj:
        comp = human_vs_engine(proj)
    store = per_code_kappa(comp.labels_a, comp.labels_b, min_support=1)
    cols = ["code", "n_items", "n_human", "n_model", "kappa"]
    pd.testing.assert_frame_equal(screen[cols].reset_index(drop=True),
                                  store[cols].reset_index(drop=True))


def test_an_old_project_carries_the_overstatement_caveat(tmp_path):
    path = tmp_path / "old.qnw"
    store = populate_project_store(_scored(), _config(), path)
    with Project.open(store) as proj:   # a human who coded before v8: no review record
        proj.add_rater(Rater(rater_id="human_primary", kind="human"))
        ex = proj.list_excerpts()[0].excerpt_id
        proj.apply_code(CodeApplication(application_id="", excerpt_id=ex,
                                        code_id=proj.get_codebook()[0].code_id,
                                        coder="human", rater_id="human_primary"))
        comp = human_vs_engine(proj)
    assert any("overstated" in c for c in comp.caveats)


def test_human_pairs_exclude_the_adjudicator(project):
    record_human_codings(project, _human_sample(), question_text="Q1", rater_id="human_B")
    from core.adjudication import record_adjudications
    with Project.open(project) as proj:
        record_adjudications(project, {proj.list_excerpts()[0].excerpt_id: []})
        labels = [c.label for c in comparisons(proj) if c.kind == "human_vs_human"]
    assert labels == ["human_B vs human_primary"]



# ── how the responses the person coded were chosen ─────────────────────────────
def _store_with_human(tmp_path, coded):
    """_scored(): every 4th response UNCERTAIN (25%). The person codes `coded`."""
    store = populate_project_store(_scored(n=40), _config(), tmp_path / "s.qnw")
    record_human_codings(store, {f"r{i}": [LABELS[i % 2]] for i in coded},
                         question_text="Q1")
    return store


def _caveat(store):
    with Project.open(store) as proj:
        comp = human_vs_engine(proj)
    return " ".join(comp.caveats)


def test_every_sampled_comparison_says_what_kappa_describes(tmp_path):
    assert "does not record how the responses human_primary coded were chosen" \
        in _caveat(_store_with_human(tmp_path, range(0, 40, 3)))


def test_a_review_queue_sample_is_flagged_as_harder(tmp_path):
    """Only the UNCERTAIN responses coded: 100% vs 0% without a code."""
    text = _caveat(_store_with_human(tmp_path, range(0, 40, 4)))
    assert "harder than the rest" in text and "understates" in text


def test_an_easy_sample_is_flagged_as_easier(tmp_path):
    """Only responses the engine was confident about."""
    text = _caveat(_store_with_human(tmp_path, [i for i in range(40) if i % 4][:20]))
    assert "easier than the rest" in text and "overstates" in text


def test_a_mixed_sample_is_not_accused(tmp_path):
    """Every third response: 4 of 14 uncertain (29%) against 6 of 26 (23%)."""
    text = _caveat(_store_with_human(tmp_path, range(0, 40, 3)))
    assert "no sign they were chosen for difficulty" in text
    assert "cannot show they were random" in text


def test_coding_everything_involves_no_selection(tmp_path):
    text = _caveat(_store_with_human(tmp_path, range(40)))
    assert "no selection is involved" in text


def test_a_chosen_earlier_run_is_labelled(project):
    from core.agreement_pairs import compare_with_engine

    populate_project_store(_scored(seed_shift=1), _config(), project)
    with Project.open(project) as proj:
        older = engine_raters(proj)[1]
        comp = compare_with_engine(proj, "human_primary", older)
    assert comp.rater_b == older
    assert any("earlier run" in c for c in comp.caveats)


# ── the exports use it ──────────────────────────────────────────────────────
@pytest.mark.parametrize("module,func", [("exports.docx_report", "_agreement_table"),
                                         ("exports.excel_workbook", "_agreement"),
                                         ("exports.bundle", "_agreement_frame")])
def test_every_export_reports_the_real_engine_on_every_reviewed_item(project, module, func):
    import importlib
    fn = getattr(importlib.import_module(module), func)
    with Project.open(project) as proj:
        table = fn(proj)
    assert table is not None, "a real pipeline run's engine must be found"
    assert int(table["n_items"].iloc[0]) == 12


@pytest.mark.parametrize("module,func", [("exports.docx_report", "_agreement_table"),
                                         ("exports.excel_workbook", "_agreement"),
                                         ("exports.bundle", "_agreement_frame")])
def test_exports_keep_the_insufficient_n_rule(tmp_path, module, func):
    import importlib
    store = populate_project_store(_scored(n=4), _config(), tmp_path / "small.qnw")
    record_human_codings(store, _human_sample(n=4), question_text="Q1")
    fn = getattr(importlib.import_module(module), func)
    with Project.open(store) as proj:
        table = fn(proj)
    assert table is None or table["kappa"].isna().all()


def test_the_methods_appendix_finds_the_real_engine(project):
    from exports.methods_appendix import reliability_tables
    with Project.open(project) as proj:
        tables = reliability_tables(proj, min_support=1)
    assert any("human_primary vs" in label for label in tables)


def test_the_adjudicated_set_can_be_picked_and_says_what_it_is(project):
    from core.adjudication import ADJUDICATED_RATER, record_adjudications
    from core.agreement_pairs import compare_raters, selectable_raters

    with Project.open(project) as proj:
        excerpt = proj.list_excerpts()[0].excerpt_id
    record_adjudications(project, {excerpt: []})
    with Project.open(project) as proj:
        assert selectable_raters(proj)[-1] == ADJUDICATED_RATER
        comp = compare_raters(proj, "human_primary", ADJUDICATED_RATER)
    assert any("not an inter-rater reliability figure" in c for c in comp.caveats)
