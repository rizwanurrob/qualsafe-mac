"""
The desktop Model screen (`V6_PLAN.md` Phase C, desktop half).

The claim being defended is the same one the code network defends: **both builds
answer the same question the same way.** So these tests are about the wiring and
the three decisions that carry the methodology — all of which live in the shared
grammar — rather than about statistics, which `tests/test_models.py` and
`tests/test_double_lasso.py` already cover.

The one thing genuinely new here is `MultiShelf`: the chart builder's `Shelf`
holds one field and Predictors and Controls hold many.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("PySide6", reason="Qt front end not installed")

from PySide6.QtCore import QMimeData, Qt  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402

from analysis.design_matrix import DesignMatrix  # noqa: E402
from core.model_spec import METHODS  # noqa: E402
from qualsafe_qt.widgets.model_shelves import MultiShelf  # noqa: E402
from qualsafe_qt.widgets.shelves import FIELD_MIME  # noqa: E402


def matrix(n=200, seed=4):
    import numpy as np

    rng = np.random.default_rng(seed)
    columns = {"case_id": [str(i) for i in range(n)],
               "code::Cost": rng.integers(0, 2, n),
               "code::Access": rng.integers(0, 2, n),
               "desc::gpa": rng.normal(3.0, 0.4, n),
               "retention": rng.integers(0, 2, n),
               "n_codes": rng.integers(1, 4, n)}
    return DesignMatrix(frame=pd.DataFrame(columns), unit="source_id",
                        encoding="binary", raters_pooled=["human_primary"])


class FakeService:
    """Enough project service for the view to build and refresh."""

    def __init__(self, open_=True):
        from PySide6.QtCore import QObject, Signal

        class Signals(QObject):
            project_changed = Signal(object)
            store_changed = Signal()

        self._signals = Signals()
        self.project_changed = self._signals.project_changed
        self.store_changed = self._signals.store_changed
        self.is_open = open_
        self.project = object()

    def coding_table(self):
        return pd.DataFrame([{"rater_id": "human_primary"},
                             {"rater_id": "transformer"}])


@pytest.fixture()
def view(qapp, monkeypatch):
    import qualsafe_qt.views.model_view as module
    from PySide6.QtGui import QUndoStack

    monkeypatch.setattr(module, "matrix_from_project",
                        lambda project, **kwargs: matrix())
    widget = module.ModelView(FakeService(), QUndoStack())
    widget.resize(1200, 800)
    return widget


class TestMultiShelf:
    """The one new widget: Predictors and Controls hold many fields."""

    def test_it_holds_fields_in_drop_order(self, qapp):
        shelf = MultiShelf("predictors", "Predictors")

        shelf.add_field("code::Cost")
        shelf.add_field("desc::gpa")

        assert shelf.fields() == ["code::Cost", "desc::gpa"]

    def test_a_repeat_is_ignored_rather_than_duplicated(self, qapp):
        """The same field twice would make its coefficient uninterpretable, not
        merely make the list untidy."""
        shelf = MultiShelf("predictors", "Predictors")

        shelf.add_field("code::Cost")
        shelf.add_field("code::Cost")

        assert shelf.fields() == ["code::Cost"]

    def test_an_empty_name_is_ignored(self, qapp):
        shelf = MultiShelf("predictors", "Predictors")

        shelf.add_field("")

        assert shelf.fields() == []

    def test_clearing_empties_it(self, qapp):
        shelf = MultiShelf("predictors", "Predictors")
        shelf.set_fields(["code::Cost", "desc::gpa"])

        shelf.clear_fields()

        assert shelf.fields() == []

    def test_it_accepts_the_same_drag_the_chart_shelves_take(self, qapp):
        """Same MIME type, so the palette a researcher already knows works."""
        shelf = MultiShelf("predictors", "Predictors")
        payload = QMimeData()
        payload.setData(FIELD_MIME, b"code::Cost")

        shelf.dropEvent(_drop(payload))

        assert shelf.fields() == ["code::Cost"]

    def test_it_refuses_a_plain_text_drag(self, qapp):
        """A passage dragged out of the reader must not land on a shelf."""
        shelf = MultiShelf("predictors", "Predictors")
        payload = QMimeData()
        payload.setText("a sentence from a transcript")

        shelf.dropEvent(_drop(payload))

        assert shelf.fields() == []

    def test_it_reports_how_many_it_holds(self, qapp):
        shelf = MultiShelf("predictors", "Predictors")
        shelf.set_fields(["code::Cost", "desc::gpa"])

        assert "2" in shelf.count_label.text()


def _drop(payload):
    """A drop event carrying `payload`."""
    from PySide6.QtCore import QPointF

    return QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, payload,
                      Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


class TestTreatmentIsOnlyForInference:
    """The same decision the web page makes, because it is in the grammar."""

    def test_the_treatment_shelf_is_disabled_for_a_predictive_method(self, view):
        view.method.setCurrentIndex(view.method.findData("lasso"))

        assert not view.treatment.isEnabled()

    def test_it_is_enabled_for_double_lasso(self, view):
        view.method.setCurrentIndex(view.method.findData("double_lasso"))

        assert view.treatment.isEnabled()

    def test_a_predictive_method_ignores_a_treatment_already_dropped(self, view):
        view.method.setCurrentIndex(view.method.findData("double_lasso"))
        view.treatment.set_field("code::Cost")
        view.method.setCurrentIndex(view.method.findData("lasso"))

        assert view.request().treatment.is_empty

    def test_exactly_one_method_enables_it(self, view):
        enabled = []
        for key in METHODS:
            view.method.setCurrentIndex(view.method.findData(key))
            if view.treatment.isEnabled():
                enabled.append(key)

        assert enabled == ["double_lasso"]


class TestProblemsGateTheButton:

    def test_a_spec_with_no_outcome_cannot_be_run(self, view):
        view.outcome.clear_field()

        view._validate()

        assert not view.run_button.isEnabled()
        # isHidden, not isVisible: a child of a window that was never shown
        # reports isVisible() == False whatever its own flag says, so the
        # first version of this assertion could not have failed.
        assert not view.problems.isHidden()

    def test_a_valid_spec_enables_the_button(self, view):
        view.outcome.set_field("retention")
        view.predictors.set_fields(["code::Cost", "desc::gpa"])
        view.method.setCurrentIndex(view.method.findData("lasso"))

        assert view.run_button.isEnabled()

    def test_double_lasso_without_a_treatment_is_blocked(self, view):
        view.outcome.set_field("retention")
        view.predictors.set_fields(["code::Cost", "desc::gpa"])
        view.method.setCurrentIndex(view.method.findData("double_lasso"))

        assert not view.run_button.isEnabled()
        assert "Treatment" in view.problems.text()

    def test_the_problem_is_a_sentence_not_a_code(self, view):
        view.outcome.clear_field()
        view._validate()

        assert "Choose what you want to explain" in view.problems.text()


class TestTheResult:

    @staticmethod
    def _fit(view, method="lasso"):
        from analysis.models import fit

        view.outcome.set_field("retention")
        view.predictors.set_fields(["code::Cost", "desc::gpa"])
        view.method.setCurrentIndex(view.method.findData(method))
        view._on_fitted(fit(view._matrix, view.request()))

    def test_the_estimates_reach_the_table(self, view):
        self._fit(view)

        assert view.table_model.rowCount() >= 2

    def test_the_caveats_are_rendered(self, view):
        self._fit(view)

        assert "How to read this" in view.caveats.toHtml()

    def test_the_seed_is_shown_with_the_result(self, view):
        self._fit(view)

        assert "Seed" in view.caveats.toHtml()

    def test_a_predictive_fit_shows_no_effect_banner(self, view):
        """isHidden, for the reason given in TestProblemsGateTheButton:
        `not isVisible()` on an unshown widget is vacuously true."""
        self._fit(view)

        assert view.effect.isHidden()

    def test_an_importance_result_says_it_has_no_direction(self, view):
        self._fit(view, "random_forest")

        assert "no direction" in view.caveats.toHtml()

    def test_a_refusal_is_shown_rather_than_an_empty_table(self, view):
        from analysis.models import ModelResult

        view._on_fitted(ModelResult(method="lasso", outcome="retention",
                                    refusal="Not enough complete cases."))

        assert "Not enough complete cases." in view.problems.text()

    def test_a_thrown_error_is_surfaced_not_swallowed(self, view):
        view._on_failed("something went wrong inside sklearn")

        assert "something went wrong" in view.problems.text()


class TestBothBuildsAgree:

    def test_the_desktop_view_computes_no_statistics_of_its_own(self):
        """The claim: the numbers are the same numbers. A fit here would be a
        second implementation and a slow, quiet divergence."""
        import ast

        import qualsafe_qt.views.model_view as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        defined = {node.name for node in ast.walk(tree)
                   if isinstance(node, ast.FunctionDef)}

        assert not ({"_fit_linear", "_fit_forest", "_ols_hc1", "_select"} & defined)
        for banned in ("sklearn", "LassoCV", "RandomForest"):
            assert banned not in source, f"{banned} in the view layer"

    def test_the_methods_offered_are_the_shared_ones(self, view):
        offered = [view.method.itemData(i) for i in range(view.method.count())]

        assert offered == list(METHODS)

    def test_the_screen_is_registered_with_the_shell(self):
        source = (Path(__file__).resolve().parents[1] / "qualsafe_qt" /
                  "windows" / "main_window.py").read_text(encoding="utf-8")

        assert "ModelView" in source
        assert '"Modelling": self.modelling' in source       # mounted by a step

        from core.ux import activities
        assert activities.locations(activities.DESKTOP, "Modelling")

    def test_it_is_not_called_models_like_the_model_manager(self):
        """Two tabs called the same thing meaning different things is a support
        ticket waiting to happen: Models downloads language models."""
        source = (Path(__file__).resolve().parents[1] / "qualsafe_qt" /
                  "windows" / "main_window.py").read_text(encoding="utf-8")

        from qualsafe_qt.widgets.activity import SCREEN_TITLES

        # The regression screen is "Model an outcome" inside an activity; the
        # name "Models" belongs to the model manager, in Settings, once.
        assert SCREEN_TITLES["Modelling"] == "Model an outcome"
        assert source.count('addTab(self.models, "Models")') == 1

    def test_the_payload_verification_imports_the_new_view(self):
        """`build_payload.py` asserts the tab count matches VIEWS, so a screen
        missing from that list fails the build rather than shipping untested."""
        source = (Path(__file__).resolve().parents[1] / "packaging" /
                  "build_payload.py").read_text(encoding="utf-8")

        assert '"model_view"' in source
        assert "analysis.double_lasso" in source


class TestWhenThereIsNothingToModel:

    def test_no_project_says_so(self, qapp, monkeypatch):
        import qualsafe_qt.views.model_view as module
        from PySide6.QtGui import QUndoStack

        widget = module.ModelView(FakeService(open_=False), QUndoStack())

        assert "No project open" in widget.empty_label.text()

    def test_a_refused_matrix_shows_its_own_sentence(self, qapp, monkeypatch):
        import qualsafe_qt.views.model_view as module
        from PySide6.QtGui import QUndoStack

        refused = DesignMatrix(frame=pd.DataFrame(), unit="source_id",
                               encoding="binary",
                               refusal="Nothing is coded yet.")
        monkeypatch.setattr(module, "matrix_from_project",
                            lambda project, **kwargs: refused)

        widget = module.ModelView(FakeService(), QUndoStack())

        assert "Nothing is coded yet." in widget.empty_label.text()
