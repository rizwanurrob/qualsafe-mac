"""Consistent pseudonyms in the PII gate (V7 Update 2, U5), and the settings
link that carries masking into the run manifest."""

from __future__ import annotations

import pandas as pd

from privacy.scan import pseudonymise_frame, pseudonymise_series


def test_one_person_gets_one_pseudonym_everywhere():
    series = pd.Series([
        "My advisor Jenna Morales has been great.",
        "Shout out to Jenna  Morales at the tutoring center.",   # spacing differs
        "My roommate Diego helped a lot.",
    ])
    masked, mapping = pseudonymise_series(series)
    assert masked.tolist() == [
        "My advisor [PERSON_1] has been great.",
        "Shout out to [PERSON_1] at the tutoring center.",
        "My roommate [PERSON_2] helped a lot.",
    ]
    assert mapping == {"[PERSON_1]": "Jenna Morales", "[PERSON_2]": "Diego"}


def test_a_surname_alone_is_not_assumed_to_be_the_same_person():
    masked, mapping = pseudonymise_series(pd.Series([
        "Professor Okafor really cares.", "My advisor Chinedu Okafor replied."]))
    assert masked.tolist() == ["Professor [PERSON_1] really cares.",
                               "My advisor [PERSON_2] replied."]


def test_other_identifiers_are_still_masked():
    masked, _ = pseudonymise_series(pd.Series(
        ["Email jenna@example.edu or text (617) 555-0142; I live at 14 Beacon St."]))
    assert masked.iloc[0] == "Email [EMAIL] or text [PHONE]; I live at [ADDRESS]."


def test_one_mapping_across_columns():
    frame = pd.DataFrame({"q1": ["My advisor Jenna Morales helped."],
                          "q2": ["Thanks to Jenna Morales again."], "id": ["x"]})
    masked, mapping = pseudonymise_frame(frame, ["q1", "q2"])
    assert masked.loc[0, "q2"] == "Thanks to [PERSON_1] again."
    assert mapping == {"[PERSON_1]": "Jenna Morales"}
    assert frame.loc[0, "q1"] == "My advisor Jenna Morales helped.", "source frame untouched"


def test_the_gate_flags_travel_through_run_settings_into_the_config():
    from core.run_config import RunSettings, build_config

    frame = pd.DataFrame({"response_id": ["1"], "question_text": ["Q"], "response_text": ["a"]})
    settings = RunSettings(text_column="response_text", id_column="response_id",
                           question_column="question_text", labels_text="Cost",
                           pii_masking_applied=True, pii_pseudonymised=True)
    import tempfile
    config = build_config(frame, settings, tempfile.mkdtemp())
    assert config["privacy"] == {"masking_applied": True, "pseudonymised": True}
