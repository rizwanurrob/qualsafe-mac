"""
The runtime estimate, against measurements (`core/run_config.py`).

Nobody had ever run this program on more than 45 responses. The largest file in
`data/` is 45 lines; the largest fixture anywhere is 500 synthetic rows in a unit
test. A first-year experience survey — this tool's actual audience — is routinely
500 to 5,000 open-text responses.

So the number a researcher plans their afternoon around had never been checked
against a real run, and it was wrong by more than an order of magnitude.

**What was measured**, on a 12-core CPU with the shipped models:

    embeddings              0.011 s/row      (estimate said 0.02 — fine)
    sentiment               0.075 s/row      (estimate said 0.03 — 2.5x low)
    zero-shot, 3 labels     0.259 s/row/label
    zero-shot, 6 labels     0.245 s/row/label
    zero-shot, 12 labels    0.236 s/row/label

Zero-shot is **per response per label** — the NLI model runs once for every
pairing — and the old estimate charged a flat 0.12 s per row regardless of label
count. With six labels that is 1.44 s/row against a predicted 0.12.

At 5,000 responses the old estimate read *"about 9–26 minutes"* for a run that
takes over two hours. That is not a rounding error: it is a researcher starting
a job before a meeting and coming back to find it nowhere near done — the
interrupted long run that crash-safe checkpointing exists to survive.

These tests pin the shape of the model rather than the constants, because the
constants are machine-dependent and the shape is not.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.run_config import (
    MODEL_LOAD_SECONDS, SECONDS_PER_ROW_PER_LABEL_ZERO_SHOT,
    estimate_runtime_minutes, estimate_runtime_seconds)


def _range_minutes(text: str):
    """The (low, high) bounds of a displayed range, always in minutes.

    The string switches to hours for long runs, so a scraper that ignored the
    unit would compare 1.3 hours against 47 minutes and conclude the bigger
    corpus was faster.
    """
    found = [float(v) for v in re.findall(r"[\d.]+", text)]
    scale = 60.0 if "hour" in text else 1.0
    return found[0] * scale, found[-1] * scale


def estimate(rows, labels=6, sentiment=True, zero_shot=True):
    return estimate_runtime_minutes(
        rows, use_sentiment=sentiment, use_zero_shot=zero_shot,
        use_question_theme=False, use_question_zero_shot=False,
        n_labels=labels)


def seconds(rows, labels=6, sentiment=True, zero_shot=True):
    """The point estimate, in seconds.

    The numeric properties are asserted against this rather than against the
    displayed string, because the string changes units at two hours and a regex
    that scrapes numbers out of it would silently compare hours to minutes.
    """
    return estimate_runtime_seconds(
        rows, use_sentiment=sentiment, use_zero_shot=zero_shot,
        use_question_theme=False, use_question_zero_shot=False,
        n_labels=labels)


class TestItScalesWithTheLabelCount:
    """The term the old model omitted entirely, and the dominant one."""

    def test_doubling_the_labels_roughly_doubles_the_estimate(self):
        assert seconds(1000, labels=12) > seconds(1000, labels=6) * 1.7, (
            "the label count barely moved the estimate")

    def test_three_labels_is_cheaper_than_twelve(self):
        assert seconds(1000, labels=3) < seconds(1000, labels=12)

    def test_labels_do_not_matter_when_zero_shot_is_off(self):
        """Only the zero-shot stage is per-label. Embeddings are not."""
        few = estimate(1000, labels=3, zero_shot=False)["cpu"]
        many = estimate(1000, labels=30, zero_shot=False)["cpu"]

        assert few == many

    def test_the_per_label_constant_is_the_measured_one(self):
        assert 0.15 < SECONDS_PER_ROW_PER_LABEL_ZERO_SHOT < 0.40, (
            "if this moved, re-measure rather than adjusting to taste")


class TestItBracketsWhatWasActuallyMeasured:
    """Measured runs, and the estimate has to contain them."""

    def test_forty_rows_matches_the_observed_run(self):
        """Pass 14 ran 40 responses with six labels end to end in about 100
        seconds, model loading included."""
        low, high = _range_minutes(estimate(40)["cpu"])

        assert low <= 100 / 60.0 <= high

    def test_two_hundred_rows_matches_the_measured_zero_shot_rate(self):
        """Measured: 200 rows of six-label zero-shot took 379 s, plus about
        45 s of model loading and a couple of seconds of embedding."""
        observed_minutes = (379 + 45 + 2.3) / 60.0

        low, high = _range_minutes(estimate(200)["cpu"])

        assert low <= observed_minutes <= high

    def test_five_thousand_rows_is_reported_in_hours_not_minutes(self):
        """The case the old estimate got most wrong: it said 9-26 minutes.

        Both halves matter. The arithmetic has to say over two hours, and the
        sentence has to say it in hours -- "about 77-230 minute(s)" is a unit
        conversion the reader should not be doing while deciding whether to
        start a run before a meeting.
        """
        assert seconds(5000) > 2 * 3600

        shown = estimate(5000)["cpu"]
        assert "hour" in shown, shown
        assert "minute" not in shown, shown


class TestItErrsHigh:
    """A run that finishes early is a pleasant surprise. One that overruns by an
    afternoon is a lost afternoon."""

    def test_the_range_brackets_the_point_estimate_asymmetrically(self):
        low, high = _range_minutes(estimate(1000)["cpu"])

        assert high - low > 0, "an estimate with no range is a false promise"
        assert high > low * 2, "the upper bound should allow for a slower machine"

    def test_model_loading_is_not_ignored(self):
        """It dominates a small run and is invisible in any per-row figure,
        which is why a tiny corpus feels slower than the arithmetic suggests."""
        assert MODEL_LOAD_SECONDS > 10

        assert seconds(1) > MODEL_LOAD_SECONDS
        assert seconds(0) == pytest.approx(MODEL_LOAD_SECONDS)

    def test_a_bigger_corpus_never_estimates_lower(self):
        previous = 0.0
        for rows in (10, 100, 1000, 10000):
            found = seconds(rows)
            assert found >= previous
            previous = found


class TestBothFrontEndsPassTheLabelCount:
    """An estimate that assumes six labels is wrong for every other codebook."""

    def test_the_streamlit_page_passes_it(self):
        source = (Path(__file__).resolve().parents[1] / "app"
                  / "run_analysis.py").read_text(encoding="utf-8")

        assert "n_labels=" in source

    def test_the_desktop_screen_passes_it(self):
        source = (Path(__file__).resolve().parents[1] / "qualsafe_qt" / "views"
                  / "pipeline_view.py").read_text(encoding="utf-8")

        assert "n_labels=" in source

    def test_the_shared_wrapper_forwards_it(self):
        from app.shared.data import estimate_runtime_minutes as wrapper

        import inspect

        assert "n_labels" in inspect.signature(wrapper).parameters


class TestTheGpuFigureIsHonestAboutBeingUnmeasured:

    def test_the_gpu_estimate_is_lower_than_the_cpu_one(self):
        found = estimate(1000)

        assert _range_minutes(found["gpu"])[0] < _range_minutes(found["cpu"])[0]

    def test_the_speedup_is_documented_as_an_assumption(self):
        """No GPU was available to measure, and the constant says so rather
        than presenting itself as a finding."""
        source = (Path(__file__).resolve().parents[1] / "core"
                  / "run_config.py").read_text(encoding="utf-8")

        assert "Not measured" in source or "not measured" in source
