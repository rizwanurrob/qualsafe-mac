"""XGBoost as a method beside random forest and gradient boosting (Update 3, item 3.12).

The spec and refusal tests need no XGBoost. The fitting tests skip when it is not installed.
"""

from __future__ import annotations

from pathlib import Path

import importlib.util

import numpy as np
import pandas as pd
import pytest

from analysis.design_matrix import DesignMatrix
from analysis.models import fit
from core import model_spec
from core.model_spec import METHODS, ModelRequest, Shelf, can_run, problems

ROOT = Path(__file__).resolve().parents[1]


def matrix(n=240, seed=3, kind="binary"):
    """A project where 'retention' follows code::Cost strongly and code::Access a little."""
    rng = np.random.default_rng(seed)
    cost = rng.integers(0, 2, n)
    access = rng.integers(0, 2, n)
    noise = rng.integers(0, 2, n)
    if kind == "binary":
        outcome = ((0.9 * cost + 0.25 * access + rng.normal(0, 0.25, n)) > 0.55).astype(int)
    else:
        outcome = 2.0 * cost + 0.5 * access + rng.normal(0, 0.4, n)
    frame = pd.DataFrame({"case_id": [str(i) for i in range(n)], "code::Cost": cost,
                          "code::Access": access, "code::Noise": noise, "retention": outcome})
    return DesignMatrix(frame=frame, unit="source_id", encoding="binary", raters_pooled=["human_primary"])


def request(method="xgboost", seed=11, **kw):
    return ModelRequest(method=method, outcome=Shelf(("retention",)),
                        predictors=Shelf(("code::Cost", "code::Access", "code::Noise")), seed=seed, **kw)


@pytest.fixture()
def package_missing(monkeypatch):
    monkeypatch.setitem(model_spec._PACKAGE_STATE, "xgboost", False)


# ── the method and its conditions (no package needed) ───────────────────────

def test_the_method_is_listed_beside_the_other_tree_methods_with_a_higher_floor():
    keys = list(METHODS)
    assert keys.index("xgboost") == keys.index("gradient_boosting") + 1
    spec = METHODS["xgboost"]
    assert spec.label == "XGBoost (boosted trees)" and spec.requires == "xgboost"
    assert not spec.coefficients and not spec.inferential
    assert spec.floor == 100 > METHODS["random_forest"].floor


def test_below_its_floor_it_is_refused_in_a_sentence_with_the_number():
    found = problems(request(), ["code::Cost", "code::Access", "code::Noise", "retention"], n_cases=60)
    assert any("needs about 100 cases" in p and "60" in p for p in found) or not METHODS["xgboost"].available()


def test_without_the_package_it_says_so_blocks_the_run_and_the_list_says_not_installed(package_missing):
    columns = ["code::Cost", "code::Access", "code::Noise", "retention"]
    found = problems(request(), columns, n_cases=240)
    assert any("needs an extra component (xgboost)" in p for p in found)
    assert not can_run(request(), columns, n_cases=240)
    assert METHODS["xgboost"].display_label == "XGBoost (boosted trees) (not installed)"
    assert METHODS["random_forest"].display_label == "Random forest"


def test_fitting_without_the_package_is_a_refusal_not_a_crash(package_missing):
    result = fit(matrix(), request())
    assert not result.usable and "needs an extra component (xgboost)" in result.refusal


def test_a_package_that_is_installed_but_cannot_load_counts_as_not_available(monkeypatch):
    import importlib
    monkeypatch.delitem(model_spec._PACKAGE_STATE, "xgboost", raising=False)

    def broken(name, *a, **k):
        raise OSError("libomp.dylib could not be loaded")
    monkeypatch.setattr(importlib, "import_module", broken)
    assert model_spec.package_works("xgboost") is False
    assert model_spec._PACKAGE_STATE["xgboost"] is False            # remembered, not retried


def test_the_package_is_a_listed_dependency_everywhere_the_others_are():
    for name in ("requirements.txt", "requirements-light.txt", "requirements-compat.txt", "pyproject.toml"):
        assert "xgboost" in (ROOT / name).read_text(encoding="utf-8"), name


def test_importing_the_spec_does_not_import_the_package():
    import subprocess
    import sys
    code = "import sys, core.model_spec; print('xgboost' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT))
    assert out.stdout.strip() == "False"


def test_the_desktop_method_list_says_when_it_is_not_installed(package_missing, monkeypatch):
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QUndoStack
    from PySide6.QtWidgets import QApplication
    import qualsafe_qt.views.model_view as module
    from tests.test_qt_model_view import FakeService, matrix as small_matrix

    monkeypatch.setattr(module, "matrix_from_project", lambda project, **kwargs: small_matrix())
    app = QApplication.instance() or QApplication([])
    view = module.ModelView(FakeService(), QUndoStack())
    labels = [view.method.itemText(i) for i in range(view.method.count())]
    assert "XGBoost (boosted trees) (not installed)" in labels and "Random forest" in labels
    assert view.method.findData("xgboost") >= 0                      # still offered, never hidden
    view.close()


# ── the fit (needs the package) ─────────────────────────────────────────────

# The app's own check, which really imports it. A package that is installed but cannot load is the same as
# not installed: on macOS the XGBoost wheel needs OpenMP (Homebrew's libomp), and without it the import fails
# while `find_spec` still finds the package (the Mac CI run, 2026-10-15).
needs_xgboost = pytest.mark.skipif(not model_spec.package_works("xgboost"),
                                   reason="XGBoost is not installed here, or cannot load (on macOS it needs libomp)")


@needs_xgboost
@pytest.mark.parametrize("kind", ["binary", "continuous"])
def test_it_ranks_the_strongest_predictor_first(kind):
    result = fit(matrix(kind=kind), request())
    assert result.usable and result.kind == "importance"
    ranked = result.frame()
    assert ranked.iloc[0]["term"] == "code::Cost"


@needs_xgboost
def test_it_agrees_with_the_random_forest_on_what_matters_most():
    forest = fit(matrix(), request("random_forest")).frame().iloc[0]["term"]
    boosted = fit(matrix(), request("xgboost")).frame().iloc[0]["term"]
    assert forest == boosted == "code::Cost"


@needs_xgboost
def test_the_same_seed_gives_identical_numbers():
    a = fit(matrix(), request(seed=5)).frame()
    b = fit(matrix(), request(seed=5)).frame()
    pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))


@needs_xgboost
def test_it_reports_importances_with_the_caveats_and_the_provenance():
    result = fit(matrix(), request(seed=9))
    text = " ".join(result.notes)
    assert "permutation importances, not coefficients" in text and "no direction" in text
    import xgboost
    assert f"XGBoost {xgboost.__version__}" in text and "one thread" in text and "seed 9" in text
    assert result.seed == 9 and result.score_name == "accuracy (CV)" and result.score is not None


@needs_xgboost
def test_a_continuous_outcome_is_scored_by_r_squared():
    assert fit(matrix(kind="continuous"), request()).score_name == "R² (CV)"


@needs_xgboost
def test_it_is_refused_below_its_floor_not_fitted():
    small = matrix(n=90)
    result = fit(small, request())
    assert not result.usable and "100" in result.refusal
