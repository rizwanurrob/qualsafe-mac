"""
The text a user reads, checked for the habits that read as machine-written.

The catalogue is Wikipedia's *Signs of AI writing*, which is the most carefully
assembled list of the tells: written by editors who spend their days reverting
the stuff, and revised as the models change.

Running it over this project produced one finding worth acting on and one worth
recording as a mistake.

**The vocabulary is clean.** No *delve*, no *tapestry*, no *showcasing*, no
*leverage*. That is the half everyone checks and the half this project already
passed, because the text was written with care.

**The em dash is the real habit.** Twelve to twenty per thousand words across
every file, used as a general-purpose joint where a comma, a colon or a full
stop would do. That is the strongest formatting tell on the list and it was
everywhere.

**The bold finding was wrong, and the tool was wrong.** The first run reported
the Help guide at 35 bolds per thousand words. Nearly all of them were UI
controls: `**File > New project…**`, `**Ctrl+Z**`. Bolding those is what good
documentation does, and acting on the number would have stripped the markup that
makes a walkthrough followable. The tool now tells a control from emphasis, and
the same guide measures 12.8. **A metric that has not been checked against the
thing it measures is not evidence.**

This test is a ratchet rather than a standard. Files already corrected are held
at the threshold; the rest carry a recorded allowance so the habit cannot spread
while the backlog is worked through. Lower an allowance when you fix a file;
never raise one.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.prose_check import (  # noqa: E402
    EM_DASH_PER_1K, NEGATIVE_PER_1K, check_text, names_a_control, ui_strings)

#: Files whose user-facing text is corrected and must stay corrected.
CORRECTED = [
    "app/charts_page.py",
]

#: Everything else, with the rate it is at now. These are allowances, not
#: targets: a file may improve, and lowering the number here is how a fix is
#: recorded. Raising one is how the habit spreads, so the test says no.
ALLOWANCE = {
    # Measured 2026-08-29, rounded up. Every one of these is above the 8.0 the
    # tool asks for; the habit is house-wide and predates this pass.
    "app/analysis_page.py": 12.0,
    "app/codebook.py": 21.0,
    "app/data_management.py": 20.0,
    "app/data_setup.py": 15.0,
    "app/documents_page.py": 22.0,
    "app/labeling_lab.py": 6.0,
    "app/query_page.py": 26.0,
    "app/run_analysis.py": 25.0,
    "app/search_page.py": 28.0,
    "app/shared/widgets.py": 8.0,
    "app/theme_setup.py": 12.0,
    "app/wizard.py": 19.0,
}


def _report(relative: str):
    path = ROOT / relative
    if not path.exists():
        pytest.skip(f"{relative} is not in this build")
    return check_text(ui_strings(path), relative)


class TestTheVocabularyStaysClean:
    """The half this project already passes. A regression here is somebody
    pasting in prose that was not written for this program."""

    @pytest.mark.parametrize("relative", CORRECTED + sorted(ALLOWANCE))
    def test_no_flagged_vocabulary(self, relative):
        report = _report(relative)
        assert not report.vocabulary, (
            f"{relative} uses {sorted(report.vocabulary)} — the words the "
            "catalogue names. Say the ordinary thing instead.")

    @pytest.mark.parametrize("relative", CORRECTED + sorted(ALLOWANCE))
    def test_no_flagged_constructions(self, relative):
        report = _report(relative)
        assert not report.phrases, (
            f"{relative} uses {sorted(report.phrases)}")


class TestCorrectedFilesStayCorrected:

    @pytest.mark.parametrize("relative", CORRECTED)
    def test_em_dashes_are_within_the_limit(self, relative):
        report = _report(relative)
        rate = report.rate(report.em_dashes)
        assert rate <= EM_DASH_PER_1K, (
            f"{relative} is back to {rate:.1f} em dashes per 1,000 words. "
            "A comma, a colon or a full stop does the same work without the "
            "tell.")

    @pytest.mark.parametrize("relative", CORRECTED)
    def test_negative_parallelism_is_within_the_limit(self, relative):
        report = _report(relative)
        assert report.rate(report.negatives) <= NEGATIVE_PER_1K


class TestTheRestDoesNotGetWorse:
    """A ratchet. The backlog is real and this stops it growing."""

    @pytest.mark.parametrize("relative,allowance", sorted(ALLOWANCE.items()))
    def test_within_its_recorded_allowance(self, relative, allowance):
        report = _report(relative)
        rate = report.rate(report.em_dashes)
        assert rate <= allowance, (
            f"{relative} has risen to {rate:.1f} em dashes per 1,000 words, "
            f"above its recorded {allowance}. Either bring the new text into "
            "line or, if the file genuinely improved elsewhere, lower the "
            "allowance to match.")

    def test_no_allowance_is_far_above_what_the_file_needs(self):
        """An allowance that drifts far above the real rate stops ratcheting.

        Warns rather than fails: a file can legitimately shrink and leave its
        allowance loose, and failing for being *too good* would be absurd.
        """
        slack = []
        for relative, allowance in ALLOWANCE.items():
            path = ROOT / relative
            if not path.exists():
                continue
            report = check_text(ui_strings(path), relative)
            if report.words >= 150 and report.rate(report.em_dashes) < allowance - 6:
                slack.append(
                    f"{relative}: {report.rate(report.em_dashes):.1f} vs {allowance}")
        if slack:
            pytest.skip("allowances that could be tightened: " + "; ".join(slack))


class TestTheToolItself:
    """The bold miscount is the reason these exist."""

    def test_a_menu_path_is_a_control_not_emphasis(self):
        assert names_a_control("File → New project…")
        assert names_a_control("Ctrl+Z")
        assert names_a_control("Add code")
        assert names_a_control("`--check`")

    def test_a_sentence_is_emphasis_not_a_control(self):
        assert not names_a_control("this is the part that matters most of all")
        assert not names_a_control("never overwritten")

    def test_bold_controls_do_not_count_towards_the_bold_rate(self):
        controls = check_text("**File → Open** then **Ctrl+S** " * 20, "x")
        prose = check_text("**this matters** and **so does this** " * 20, "x")

        assert controls.bolds == 0
        assert prose.bolds > 0

    def test_an_em_dash_is_counted(self):
        assert check_text("a — b", "x").em_dashes == 1

    def test_a_hyphen_is_not_an_em_dash(self):
        assert check_text("a mixed-methods table", "x").em_dashes == 0
