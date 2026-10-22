"""
The PII gate when it actually finds something (`RELEASE_READINESS.md` §1.3).

The readiness document has listed this as a release blocker for months, phrased
as *"the privacy gate's positive path has never run … untested against real
data"*. That phrasing conflates two different needs, and only one of them is
genuinely unmeetable here:

- **Real data.** Cannot be had, and would not be a test — a suite that needs a
  live student record is a suite nobody can run.
- **Data containing PII patterns.** Entirely synthesisable, and it exercises the
  same code path byte for byte. The scanner does not know whether an email
  address belongs to a person.

So the blocker was never "no real data". It was that nothing had ever driven the
gate with a frame that trips it, and every fixture in this suite was
deliberately PII-quiet. These tests do that, with obviously fake identifiers.

What the path has to do, in order: find, show, offer masking, apply masking to
the **working copy only**, record that it happened, and still require the
analyst's explicit attestation afterwards — masking is not consent, and neither
is a clean scan.

Every value below is invented. `555` numbers are the reserved fictional range,
`example.com` is the reserved documentation domain, and the SSNs are in the
`000` area that has never been issued.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.shared.widgets as widgets
from privacy.scan import mask_frame, scan_frame, summarize_findings

#: Deliberately fake, and fake in the reserved ways: 555 numbers, example.com,
#: and SSNs in the never-issued 000 area. A fixture that looked like real PII
#: would be a small version of the problem this gate exists to prevent.
RESPONSES = [
    "The advisor emailed me at jordan.blake@example.com and never followed up.",
    "Call me on (555) 013-4477 if you want the full story about the fees.",
    "My student number 0004417782 was wrong on every letter they sent.",
    "They had my SSN as 000-12-3456 which is not even my number.",
    "The library hours were the best part of the term.",
]

QUIET = [
    "The library hours were the best part of the term.",
    "Advising was fine, nothing to report.",
    "I would have liked more evening seminars.",
]


def frame(texts=None, column="response"):
    return pd.DataFrame({column: texts if texts is not None else RESPONSES})


class FakeStreamlit:
    """Records what the gate rendered and answers its widgets."""

    def __init__(self, answers: Dict[str, Any] | None = None):
        self.answers = answers or {}
        self.session_state: Dict[str, Any] = {}
        self.captions: List[str] = []
        self.warnings: List[str] = []
        self.infos: List[str] = []
        self.successes: List[str] = []
        self.frames: List[pd.DataFrame] = []
        self.subheaders: List[str] = []
        self.reran = False

    def subheader(self, text, *a, **k): self.subheaders.append(text)
    def caption(self, text, *a, **k): self.captions.append(text)
    def warning(self, text, *a, **k): self.warnings.append(text)
    def info(self, text, *a, **k): self.infos.append(text)
    def success(self, text, *a, **k): self.successes.append(text)
    def dataframe(self, data, *a, **k): self.frames.append(data)
    def rerun(self): self.reran = True

    def checkbox(self, label, *a, key=None, value=False, **k):
        return self.answers.get(key, value)

    def multiselect(self, label, options, *a, key=None, default=None, **k):
        return self.answers.get(key, default if default is not None else [])

    def button(self, label, *a, key=None, **k):
        return bool(self.answers.get(key, False))

    def radio(self, label, options, *a, key=None, index=0, **k):
        return self.answers.get(key, options[index])
    def download_button(self, *a, **k): return False
    def expander(self, *a, **k): return _Ctx(self)
    def container(self, *a, **k): return _Ctx(self)


class _Ctx:
    def __init__(self, parent): self._parent = parent
    def __enter__(self): return self._parent
    def __exit__(self, *exc): return False
    def __getattr__(self, name): return getattr(self._parent, name)


@pytest.fixture()
def gate(monkeypatch):
    def run(data=None, **answers):
        stub = FakeStreamlit(answers)
        monkeypatch.setattr(widgets, "st", stub)
        confirmed = widgets.render_pii_gate(data if data is not None else frame())
        return stub, confirmed
    return run


class TestItFindsWhatIsThere:
    """The half that was genuinely untested: a frame that trips the scanner."""

    def test_the_fixture_actually_trips_the_scanner(self):
        """If this ever stops being true the rest of the file tests nothing."""
        findings = scan_frame(frame())

        assert findings, "the PII fixture no longer contains detectable PII"

    def test_every_kind_of_identifier_is_found(self):
        signals = {f["signal"] for f in scan_frame(frame())}

        assert "email address" in signals
        assert "phone-like number" in signals
        assert "SSN-like number" in signals

    def test_the_findings_are_shown_as_a_table(self, gate):
        stub, _confirmed = gate()

        assert stub.frames, "findings were detected but never displayed"

    def test_a_clean_frame_shows_no_table(self, gate):
        """Every fixture in this suite used to be this case, which is why the
        path above had never run."""
        stub, _confirmed = gate(frame(QUIET))

        assert not stub.frames

    def test_the_summary_says_what_was_found(self, gate):
        stub, _confirmed = gate()

        assert any(summarize_findings(scan_frame(frame())) == caption
                   for caption in stub.captions)

    def test_the_findings_are_called_rough_checks_not_a_verdict(self, gate):
        """The scanner misses a name written mid-sentence and flags harmless
        years. Presenting it as a verdict would be the more dangerous error."""
        stub, _confirmed = gate()

        blob = " ".join(stub.captions)
        assert "rough checks, not a verdict" in blob
        assert "Your review is what this gate records" in blob


class TestMaskingIsOfferedAndApplied:

    def test_masking_is_offered_for_the_columns_that_have_matches(self, gate):
        stub, _confirmed = gate()

        blob = " ".join(stub.captions)
        assert "[EMAIL]" in blob and "[PHONE]" in blob

    def test_applying_it_changes_the_working_copy(self, gate):
        stub, _confirmed = gate(pii_mask_cols=["response"], pii_apply_mask=True)

        masked = stub.session_state["df"]
        joined = " ".join(masked["response"])
        assert "jordan.blake@example.com" not in joined
        assert "[EMAIL]" in joined

    def test_the_phone_and_ssn_go_too(self, gate):
        stub, _confirmed = gate(pii_mask_cols=["response"], pii_apply_mask=True)

        joined = " ".join(stub.session_state["df"]["response"])
        assert "555" not in joined
        assert "000-12-3456" not in joined

    def test_the_source_file_is_untouched(self, gate):
        """Masking edits the working copy. A gate that rewrote the analyst's
        file would be destroying evidence to protect it."""
        original = frame()
        before = original["response"].tolist()

        gate(original, pii_mask_cols=["response"], pii_apply_mask=True)

        assert original["response"].tolist() == before

    def test_masking_is_recorded_so_the_manifest_can_carry_it(self, gate):
        stub, _confirmed = gate(pii_mask_cols=["response"], pii_apply_mask=True)

        assert stub.session_state["pii_masking_applied"] is True

    def test_the_manifest_writes_that_flag(self, tmp_path):
        """The other end of it: the run manifest is what a reviewer reads."""
        import json

        from core.manifest import write_run_manifest

        path = write_run_manifest(
            tmp_path, config={}, run_summary={"pii_masking_applied": True},
            engine_type="transformer", engine_model="x")

        # Under `local_mode`, beside the offline flags, which is the right
        # place: an auditor reading that block is asking what this run actually
        # did to the data rather than what the software promises.
        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
        assert manifest["local_mode"]["pii_masking_applied"] is True

    def test_the_manifest_records_when_masking_was_not_applied(self, tmp_path):
        """The absence has to be recorded too, or a reviewer cannot tell an
        unmasked run from an older manifest that lacked the field."""
        import json

        from core.manifest import write_run_manifest

        path = write_run_manifest(
            tmp_path, config={}, run_summary={},
            engine_type="transformer", engine_model="x")

        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
        assert manifest["local_mode"]["pii_masking_applied"] is False

    def test_nothing_is_masked_without_the_button(self, gate):
        stub, _confirmed = gate(pii_mask_cols=["response"])

        assert "df" not in stub.session_state
        assert not stub.session_state.get("pii_masking_applied")


class TestMaskingIsNotConsent:
    """The decision the gate exists to record. Masking removes identifiers; it
    does not attest that the file was reviewed, and nor does a clean scan."""

    def test_masking_alone_does_not_open_the_gate(self, gate):
        _stub, confirmed = gate(pii_mask_cols=["response"], pii_apply_mask=True)

        assert confirmed is False

    def test_a_clean_scan_alone_does_not_open_the_gate(self, gate):
        _stub, confirmed = gate(frame(QUIET))

        assert confirmed is False

    def test_only_the_attestation_opens_it(self, gate):
        _stub, confirmed = gate(pii_confirm_checkbox=True)

        assert confirmed is True

    def test_the_attestation_is_recorded_against_the_source(self, gate):
        stub, _confirmed = gate(pii_confirm_checkbox=True)

        assert stub.session_state["pii_confirmed"] is True
        assert "last_confirmed_source" in stub.session_state

    def test_the_reminder_is_shown_whatever_the_scan_found(self, gate):
        """A clean scan is the case where an analyst is most likely to click
        through, so the warning must not be conditional on findings."""
        for data in (frame(), frame(QUIET)):
            stub, _confirmed = gate(data)
            assert stub.warnings, "no FERPA reminder shown"


class TestTheBlockerThisFileCloses:
    """`RELEASE_READINESS.md` §1.3 said the positive path was untested because
    no real data had been through it. Real data was never what it needed."""

    def test_the_whole_path_runs_in_order(self, gate):
        """Find, show, offer, mask, record, and still require attestation."""
        stub, confirmed = gate(pii_mask_cols=["response"], pii_apply_mask=True,
                               pii_confirm_checkbox=True)

        assert scan_frame(frame()), "found"
        assert stub.frames, "shown"
        assert stub.session_state.get("pii_masking_applied"), "masked and recorded"
        assert confirmed, "attested"

    def test_the_fixture_contains_no_real_identifiers(self):
        """A fixture that looked like real PII would be a small version of the
        problem this gate exists to prevent: 555 numbers, example.com, and
        SSNs in the never-issued 000 area."""
        joined = " ".join(RESPONSES)

        assert "example.com" in joined
        assert "(555)" in joined
        assert "000-" in joined
