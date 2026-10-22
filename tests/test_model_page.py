"""
The model builder page (`V6_PLAN.md` Phase C, Streamlit half).

The page decides nothing — the grammar is in `core/model_spec.py`, the table in
`analysis/design_matrix.py`, the fitting in `analysis/models.py`. So these tests
are about the wiring and about the three interface decisions that carry the
methodology, not about statistics.

Streamlit is driven through a recording stub rather than a live server: it is
what `tests/test_app_smoke.py` already does, and what makes it possible to
assert on the words an analyst actually sees.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.model_page as page
from analysis.design_matrix import DesignMatrix
from core.model_spec import METHODS, ModelRequest, Shelf


class FakeStreamlit:
    """Records what the page rendered, and answers widgets from `answers`."""

    def __init__(self, answers: Dict[str, Any] | None = None):
        self.answers = answers or {}
        # What a person chose on the previous run is already in session state when the page draws.
        self.session_state: Dict[str, Any] = dict(self.answers)
        self.downloads: List[Dict[str, Any]] = []
        self.captions: List[str] = []
        self.warnings: List[str] = []
        self.errors: List[str] = []
        self.infos: List[str] = []
        self.buttons: List[Dict[str, Any]] = []
        self.tables: List[pd.DataFrame] = []
        self.markdowns: List[str] = []

    # -- output --
    def header(self, text, *a, **k): self.markdowns.append(text)
    def subheader(self, text, *a, **k): self.markdowns.append(text)
    def markdown(self, text, *a, **k): self.markdowns.append(text)
    def caption(self, text, *a, **k): self.captions.append(text)
    def warning(self, text, *a, **k): self.warnings.append(text)
    def error(self, text, *a, **k): self.errors.append(text)
    def info(self, text, *a, **k): self.infos.append(text)
    def dataframe(self, frame, *a, **k): self.tables.append(frame)
    def metric(self, *a, **k): pass
    def download_button(self, label, data=None, *a, file_name="", **k):
        self.downloads.append({"label": label, "file_name": file_name,
                               "bytes": len(data) if data is not None else 0})
        return False

    # -- input --
    def _answer(self, key, default):
        return self.answers.get(key, default)

    def selectbox(self, label, options, *a, key=None, **k):
        return self._answer(key, options[0] if len(options) else None)

    def radio(self, label, options, *a, key=None, **k):
        return self._answer(key, options[0])

    def multiselect(self, label, options, *a, key=None, default=None, **k):
        return self._answer(key, default or [])

    def number_input(self, label, *a, key=None, value=0, **k):
        return self._answer(key, value)

    def button(self, label, *a, key=None, disabled=False, **k):
        self.buttons.append({"label": label, "disabled": disabled, "key": key})
        return self._answer(key, False)

    # -- layout --
    def columns(self, spec, *a, **k):
        count = spec if isinstance(spec, int) else len(spec)
        return [_Ctx(self) for _ in range(count)]

    def expander(self, *a, **k): return _Ctx(self)
    def spinner(self, *a, **k): return _Ctx(self)


class _Ctx:
    def __init__(self, parent): self._parent = parent
    def __enter__(self): return self._parent
    def __exit__(self, *exc): return False
    def __getattr__(self, name): return getattr(self._parent, name)


def matrix(n=200, seed=2, codes=("Cost", "Access", "Belonging")):
    import numpy as np

    rng = np.random.default_rng(seed)
    columns: Dict[str, Any] = {"case_id": [str(i) for i in range(n)]}
    for name in codes:
        columns[f"code::{name}"] = rng.integers(0, 2, n)
    columns["desc::gpa"] = rng.normal(3.0, 0.4, n)
    columns["retention"] = rng.integers(0, 2, n)
    columns["n_codes"] = rng.integers(1, 4, n)
    return DesignMatrix(frame=pd.DataFrame(columns), unit="source_id",
                        encoding="binary", raters_pooled=["human_primary"])


@pytest.fixture()
def st_stub(monkeypatch):
    def install(answers=None):
        stub = FakeStreamlit(answers)
        monkeypatch.setattr(page, "st", stub)
        return stub
    return install


class TestTheShelves:

    def test_the_four_shelves_are_rendered(self, st_stub):
        stub = st_stub()

        request = page._render_shelves(matrix())

        assert isinstance(request, ModelRequest)
        assert request.method in METHODS

    def test_the_codes_are_offered_as_predictors_by_default(self, st_stub):
        """An empty page is a worse starting point than a sensible one, and the
        codes are what this program has that a statistics package does not."""
        columns = list(matrix().frame.columns)

        defaults = page._default_predictors(columns)

        assert all(c.startswith("code::") for c in defaults)
        assert defaults

    def test_the_seed_and_folds_reach_the_request(self, st_stub):
        st_stub({"model_seed": 4242, "model_folds": 3})

        request = page._render_shelves(matrix())

        assert request.seed == 4242
        assert request.folds == 3


class TestTreatmentIsOnlyForInference:
    """The interface decision that carries the methodology."""

    def test_the_treatment_shelf_is_disabled_for_predictive_methods(self, st_stub):
        stub = st_stub({"model_method": "lasso",
                        "model_treatment": "code::Cost"})

        request = page._render_shelves(matrix())

        assert request.treatment.is_empty, (
            "a predictive method must not silently accept a treatment")

    def test_double_lasso_accepts_one(self, st_stub):
        st_stub({"model_method": "double_lasso",
                 "model_treatment": "code::Cost",
                 "model_outcome": "retention"})

        request = page._render_shelves(matrix())

        assert request.treatment.first == "code::Cost"


class TestProblemsAreShownBeforeTheButton:

    def test_a_blocking_problem_disables_the_run_button(self, st_stub):
        stub = st_stub({"model_method": "double_lasso",
                        "model_outcome": "retention"})
        request = ModelRequest(method="double_lasso",
                               outcome=Shelf(("retention",)),
                               predictors=Shelf(("code::Cost",)))

        page._render_problems(matrix(), request)

        assert stub.buttons and stub.buttons[0]["disabled"]

    def test_a_valid_spec_leaves_the_button_enabled(self, st_stub):
        stub = st_stub()
        request = ModelRequest(method="lasso", outcome=Shelf(("retention",)),
                               predictors=Shelf(("code::Cost", "desc::gpa")))

        page._render_problems(matrix(), request)

        assert stub.buttons and not stub.buttons[0]["disabled"]

    def test_the_problem_is_shown_as_a_sentence(self, st_stub):
        stub = st_stub()
        request = ModelRequest(method="double_lasso",
                               outcome=Shelf(("retention",)),
                               predictors=Shelf(("code::Cost",)))

        page._render_problems(matrix(), request)

        assert any("Treatment" in message for message in stub.errors)

    def test_advice_warns_rather_than_blocks(self, st_stub):
        stub = st_stub()
        request = ModelRequest(method="ols", outcome=Shelf(("retention",)),
                               predictors=Shelf(("code::Cost", "code::Access",
                                                 "code::Belonging", "desc::gpa",
                                                 "n_codes")),
                               folds=15)

        page._render_problems(matrix(n=60), request)

        assert not stub.buttons[0]["disabled"]
        assert stub.warnings


class TestTheResult:

    @staticmethod
    def _fitted(stub_answers=None):
        from analysis.models import fit

        request = ModelRequest(method="lasso", outcome=Shelf(("retention",)),
                               predictors=Shelf(("code::Cost", "desc::gpa")))
        return fit(matrix(), request)

    def test_the_caveats_are_rendered_and_not_behind_a_toggle(self, st_stub):
        stub = st_stub()

        page._render_result(self._fitted())

        blob = " ".join(stub.captions)
        assert "Seed" in blob
        assert len(stub.captions) > 1

    def test_the_estimate_table_is_shown(self, st_stub):
        stub = st_stub()

        page._render_result(self._fitted())

        assert stub.tables and "term" in stub.tables[0].columns

    def test_an_importance_result_says_it_has_no_direction(self, st_stub):
        from analysis.models import fit

        stub = st_stub()
        request = ModelRequest(method="random_forest",
                               outcome=Shelf(("retention",)),
                               predictors=Shelf(("code::Cost", "desc::gpa")))

        page._render_result(fit(matrix(), request))

        assert any("no direction" in c for c in stub.captions)

    def test_an_effect_shows_its_interval(self, st_stub):
        from analysis.double_lasso import EffectEstimate

        stub = st_stub()
        effect = EffectEstimate(
            treatment="code::Cost", coefficient=0.5, std_error=0.1,
            interval=(0.3, 0.7), selected_by_treatment=["desc::gpa"])

        page._render_effect(effect)

        assert any("Effect of" in m for m in stub.markdowns)

    def test_controls_found_only_by_the_treatment_step_are_named(self, st_stub):
        from analysis.double_lasso import EffectEstimate

        stub = st_stub()
        effect = EffectEstimate(
            treatment="code::Cost", coefficient=0.5, std_error=0.1,
            interval=(0.3, 0.7), selected_by_treatment=["desc::gpa"])

        page._render_effect(effect)

        assert any("only because they predict the treatment" in c
                   for c in stub.captions)


class TestTheDownloads:
    """Three buttons for three moments: a spreadsheet now, a chapter later, and
    somebody who wants to redo this in R."""

    @staticmethod
    def _fit_and_render(stub):
        from analysis.models import fit

        request = ModelRequest(method="lasso", outcome=Shelf(("retention",)),
                               predictors=Shelf(("code::Cost", "desc::gpa")))
        built = matrix()
        result = fit(built, request)
        stub.session_state["model_last_request"] = request
        stub.session_state["model_last_matrix"] = built
        page._render_result(result)
        return result

    def test_the_table_the_report_and_the_matrix_are_all_offered(self, st_stub):
        stub = st_stub()

        self._fit_and_render(stub)

        labels = [d["label"] for d in stub.downloads]
        assert any("CSV" in label for label in labels)
        assert any("Word" in label for label in labels)
        assert any("Design matrix" in label for label in labels)

    def test_the_word_report_is_a_real_document(self, st_stub):
        """Not an empty buffer: the button builds the file, so a failure here
        is a failure the analyst would have met on click."""
        stub = st_stub()

        self._fit_and_render(stub)

        report = next(d for d in stub.downloads if "Word" in d["label"])
        assert report["bytes"] > 5000
        assert report["file_name"].endswith(".docx")

    def test_without_a_stored_spec_only_the_csv_is_offered(self, st_stub):
        """The report needs the spec and the matrix, not just the result."""
        from analysis.models import fit

        stub = st_stub()
        page._render_result(fit(matrix(), ModelRequest(
            method="lasso", outcome=Shelf(("retention",)),
            predictors=Shelf(("code::Cost", "desc::gpa")))))

        assert [d["label"] for d in stub.downloads] == ["Table (CSV)"]

    def test_fitting_stores_what_the_export_needs(self, st_stub):
        stub = st_stub({"model_fit": True})
        request = ModelRequest(method="lasso", outcome=Shelf(("retention",)),
                               predictors=Shelf(("code::Cost", "desc::gpa")))

        page._render_problems(matrix(), request)

        assert stub.session_state.get("model_last_request") == request
        assert stub.session_state.get("model_last_matrix") is not None


class TestWhenThereIsNothingToModel:

    def test_no_project_says_so_rather_than_rendering_empty_shelves(self, st_stub):
        stub = st_stub()

        page.render_model_page(None)

        assert stub.infos and "Open or create a project" in stub.infos[0]

    def test_a_refused_matrix_shows_its_own_sentence(self, st_stub, monkeypatch,
                                                    tmp_path):
        store = tmp_path / "p.qnw"
        store.write_bytes(b"")
        stub = st_stub()
        refused = DesignMatrix(frame=pd.DataFrame(), unit="source_id",
                               encoding="binary",
                               refusal="Nothing is coded yet.")
        monkeypatch.setattr(page, "_build_matrix", lambda project: refused)

        class FakeProject:
            def __enter__(self): return self
            def __exit__(self, *exc): return False

        monkeypatch.setattr(page.Project, "open",
                            staticmethod(lambda *a, **k: FakeProject()))

        page.render_model_page(store)

        assert "Nothing is coded yet." in stub.infos


class StubProject:
    """Just enough project for the rater picker."""

    def coding_table(self):
        return pd.DataFrame([{"rater_id": "human_primary"}])


class TestTheEncodingChoiceIsWired:
    """Found by reading the code back: the encoding radio was computed from the
    *unit* label, so "how many times" silently did nothing."""

    def test_choosing_counts_actually_asks_for_counts(self, st_stub, monkeypatch):
        st_stub({"model_encoding": "How many times"})
        seen = {}

        def record(project, **kwargs):
            seen.update(kwargs)
            return matrix()

        monkeypatch.setattr(page, "matrix_from_project", record)
        page._build_matrix(StubProject())

        assert seen["encoding"] == "count"

    def test_the_default_is_binary(self, st_stub, monkeypatch):
        st_stub()
        seen = {}
        monkeypatch.setattr(page, "matrix_from_project",
                            lambda project, **kw: (seen.update(kw), matrix())[1])

        page._build_matrix(StubProject())

        assert seen["encoding"] == "binary"

    def test_the_unit_choice_is_wired_too(self, st_stub, monkeypatch):
        st_stub({"model_unit": "A respondent (across documents)"})
        seen = {}
        monkeypatch.setattr(page, "matrix_from_project",
                            lambda project, **kw: (seen.update(kw), matrix())[1])

        page._build_matrix(StubProject())

        assert seen["unit"] == "respondent_id"


def test_the_page_is_reachable_from_the_navigation():
    """A page nobody can open is not shipped."""
    source = (Path(__file__).resolve().parents[1] / "streamlit_app.py").read_text(
        encoding="utf-8")

    assert "render_model_page" in source
    assert '"Modelling"' in source
