"""Identifiers inside prose (review finding F6).

The pattern scanner found every email, phone, SSN and long id in the
privacy-trap file, and none of the names, street addresses or room numbers,
which is where identifying detail lives in open-ended answers ("my advisor
Dr. Chen"). The module's own rule still holds: a signal that fires on ordinary
text teaches analysts to click past it. So names are detected only where the
sentence anchors them -- a title, or "my advisor/roommate/..." -- and every
positive case below has a negative one that must stay silent.
"""

from __future__ import annotations

import pandas as pd
import pytest

from privacy.scan import mask_text_series, scan_frame

FOUND = [
    ("My advisor Jenna Morales has been great.", "name", "Jenna Morales"),
    ("my roommate Diego helped me a lot.", "name", "Diego"),
    ("Professor Okafor really cares.", "name", "Okafor"),
    ("Dr. Chen said I should drop the class.", "name", "Chen"),
    ("I live at 14 Beacon St and the walk is fine.", "address", "14 Beacon St"),
    ("I live at 212 Commonwealth Avenue.", "address", "212 Commonwealth Avenue"),
    ("Anyone on my floor knows me, I am in room 814.", "room", "room 814"),
    ("Apt 3B has no heat.", "room", "Apt 3B"),
]

SILENT = [
    "When the Green Line is down my whole day falls apart.",
    "I know every delay announcement on the Orange Line by heart now.",
    "My English professor wrote 'see me' on my paper.",
    "My advisor was hard to reach during registration.",
    "The professor does not know who I am.",
    "Financial Aid never answered my email.",
    "I spent 300 dollars on books and 40 on parking.",
    "There were 200 people in the room for my lecture.",
    "I have 3 classes on Tuesday and work until 9.",
    "Boston is expensive and I miss New York.",
]


@pytest.mark.parametrize("text,kind,value", FOUND)
def test_an_anchored_identifier_is_found(text, kind, value):
    findings = scan_frame(pd.DataFrame({"response_text": [text]}), text_cols=["response_text"])
    signals = " | ".join(f["signal"] for f in findings)
    assert kind in signals, f"{kind!r} not reported for {text!r}: {signals!r}"


@pytest.mark.parametrize("text,kind,value", FOUND)
def test_masking_removes_it_and_says_what_it_was(text, kind, value):
    masked = mask_text_series(pd.Series([text])).iloc[0]
    assert value not in masked
    assert f"[{kind.upper()}]" in masked


@pytest.mark.parametrize("text", SILENT)
def test_ordinary_prose_stays_silent(text):
    findings = scan_frame(pd.DataFrame({"response_text": [text]}), text_cols=["response_text"])
    assert findings == [], f"false alarm on {text!r}: {findings}"
    assert mask_text_series(pd.Series([text])).iloc[0] == text


def test_the_title_or_relation_is_kept_so_the_sentence_still_reads():
    masked = mask_text_series(pd.Series(["My advisor Jenna Morales has been great."])).iloc[0]
    assert masked == "My advisor [NAME] has been great."


def test_examples_shown_to_the_analyst_are_masked():
    findings = scan_frame(pd.DataFrame({"t": ["Professor Okafor really cares."]}), text_cols=["t"])
    assert all("Okafor" not in f["example_masked"] for f in findings)


def test_the_summary_says_what_the_scanner_cannot_see():
    from privacy.scan import SCANNER_LIMITS, summarize_findings

    assert "name" in SCANNER_LIMITS.lower()
    assert SCANNER_LIMITS in summarize_findings([])
