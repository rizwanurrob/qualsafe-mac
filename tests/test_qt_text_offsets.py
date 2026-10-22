"""
The source-offset <-> Qt-position mapping (Qt fork).

This guards the evidentiary link. A `QTextCursor` counts positions in a
`QTextDocument`, which normalizes the text on the way in; character offsets are
what tie a code to its evidence (`core.model.Excerpt.verify_offsets`). If the
mapping is wrong, QualSafe attaches codes to the wrong passage and says nothing
-- so these tests assert the round trip on the exact characters Qt is known to
transform, and the property "the text at the mapped Qt span is what the analyst
saw" on a document containing all of them at once.

Deliberately Qt-free (pure `OffsetMap`) except for the two tests marked
`needs_qt`, which pin the *actual* Qt behaviour this module is modelled on --
if a future PySide6 normalizes something new, those fail rather than the app
silently miscoding.
"""

from __future__ import annotations

import pytest

from qualsafe_qt.text_offsets import CRLF, OffsetMap, expected_qt_text

CR = chr(0x0D)
LF = chr(0x0A)
LINE_SEP = chr(0x2028)
PARA_SEP = chr(0x2029)
NBSP = chr(0x00A0)


# -- the reconstruction ------------------------------------------------------
def test_lf_document_is_unchanged():
    text = "alpha" + LF + "bravo"
    assert expected_qt_text(text) == text


def test_crlf_collapses_to_lf():
    assert expected_qt_text("a" + CRLF + "b") == "a" + LF + "b"


@pytest.mark.parametrize("char,replacement", [
    (CR, LF), (LINE_SEP, LF), (PARA_SEP, LF), (NBSP, " "),
])
def test_one_to_one_substitutions_keep_length(char, replacement):
    text = "alpha" + char + "bravo"
    got = expected_qt_text(text)
    assert got == "alpha" + replacement + "bravo"
    assert len(got) == len(text), "a 1:1 substitution must not move offsets"


def test_tab_and_control_chars_survive():
    text = "a\tb\x0bc\x0cd\x00e"
    assert expected_qt_text(text) == text


# -- the identity fast path --------------------------------------------------
def test_document_without_crlf_uses_the_identity_map():
    text = "alpha" + LF + "bravo" + NBSP + "charlie"
    omap = OffsetMap(text)
    assert omap.is_identity
    for i in range(len(text) + 1):
        assert omap.to_qt(i) == i
        assert omap.to_source(i) == i


def test_identity_map_is_still_exact_when_qt_substituted_characters():
    # An NBSP makes the Qt text differ from the source while offsets still line
    # up. Checking equality instead of the reconstruction would wrongly refuse
    # to code every .docx Word ever produced.
    text = "alpha" + NBSP + "bravo"
    omap = OffsetMap(text, qt_text=expected_qt_text(text))
    assert omap.is_exact
    assert omap.is_identity


# -- the CRLF map ------------------------------------------------------------
def test_crlf_map_shifts_later_offsets():
    text = "a" + CRLF + "b"          # indices: a=0 CR=1 LF=2 b=3
    omap = OffsetMap(text)
    assert not omap.is_identity
    assert omap.qt_length == 3       # "a\nb"
    assert [omap.to_qt(i) for i in range(len(text) + 1)] == [0, 1, 1, 2, 3]


def test_crlf_map_round_trips_the_word_after_the_break():
    text = "alpha" + CRLF + "bravo"
    omap = OffsetMap(text)
    start = text.index("bravo")
    end = start + len("bravo")
    qt_start, qt_end = omap.span_to_qt(start, end)
    assert expected_qt_text(text)[qt_start:qt_end] == "bravo"
    assert omap.span_to_source(qt_start, qt_end) == (start, end)


def test_qt_position_of_a_break_resolves_to_the_whole_pair():
    # Selecting the line break in the widget must give back a source span that
    # covers CR *and* LF -- an excerpt ending between them would slice a pair.
    text = "a" + CRLF + "b"
    omap = OffsetMap(text)
    assert omap.span_to_source(1, 2) == (1, 3)


def test_many_crlf_breaks_accumulate_the_shift():
    text = CRLF.join(["one", "two", "three", "four"])
    omap = OffsetMap(text)
    qt_text = expected_qt_text(text)
    start = text.index("four")
    qt_start, qt_end = omap.span_to_qt(start, start + 4)
    assert qt_text[qt_start:qt_end] == "four"
    assert qt_start == start - 3, "three CRLF pairs collapsed before 'four'"


def test_out_of_range_offsets_clamp_rather_than_raise():
    omap = OffsetMap("a" + CRLF + "b")
    assert omap.to_qt(-5) == 0
    assert omap.to_qt(10_000) == omap.qt_length
    assert omap.to_source(-5) == 0
    assert omap.to_source(10_000) == omap.source_length


def test_empty_document():
    omap = OffsetMap("")
    assert omap.is_identity and omap.is_exact
    assert omap.span_to_qt(0, 0) == (0, 0)


# -- the property that actually matters --------------------------------------
def test_every_word_maps_to_itself_in_a_document_with_all_the_traps():
    """The guarantee, stated directly: for every word in a nasty document, the
    Qt span the map produces shows that same word."""
    text = (
        "Interviewer: how did you find the cost?" + CRLF
        + "Respondent: the tuition" + NBSP + "bill was the hard part." + CR
        + "I worked" + LINE_SEP + "twenty hours." + CRLF + CRLF
        + "Interviewer: and belonging?" + PARA_SEP
        + "Respondent: I made friends late." + LF
    )
    qt_text = expected_qt_text(text)
    omap = OffsetMap(text, qt_text=qt_text)
    assert omap.is_exact

    for word in ("cost", "tuition", "bill", "worked", "twenty", "belonging",
                 "friends", "late"):
        start = text.index(word)
        end = start + len(word)
        qt_start, qt_end = omap.span_to_qt(start, end)
        assert qt_text[qt_start:qt_end] == word, f"{word!r} mapped to the wrong span"
        # ...and back again, so a selection in the widget recovers the source
        # span the excerpt will be stored with.
        assert omap.span_to_source(qt_start, qt_end) == (start, end)


def test_mismatched_qt_text_is_reported_not_guessed():
    # If a future Qt normalizes something this module does not model, the map
    # must declare itself unreliable so the caller refuses to code.
    omap = OffsetMap("alpha" + CRLF + "bravo", qt_text="something else entirely")
    assert not omap.is_exact


# -- pinning the real Qt behaviour -------------------------------------------
def test_real_qt_matches_the_model():
    """The whole module is a model of Qt's normalization -- check it is true.

    Skipped when PySide6 is absent, so the engine suite still runs torch-free
    and Qt-free.
    """
    pytest.importorskip("PySide6", reason="Qt front end not installed")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QTextDocument

    samples = [
        "plain" + LF + "text",
        "a" + CRLF + "b" + CRLF + "c",
        "a" + CR + "b",
        "a" + LINE_SEP + "b",
        "a" + PARA_SEP + "b",
        "a" + NBSP + "b",
        "a\tb\x0bc\x0cd",
        "",
    ]
    for src in samples:
        doc = QTextDocument()
        doc.setPlainText(src)
        assert doc.toPlainText() == expected_qt_text(src), (
            f"Qt normalized {src!r} differently than this module models")


def test_real_qt_cursor_positions_agree_with_the_map():
    """End to end: put a CRLF document in a real widget, select a word with a
    real cursor, and check the map turns those positions back into the source
    offsets whose slice is that word."""
    pytest.importorskip("PySide6", reason="Qt front end not installed")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QTextCursor, QTextDocument

    text = "The cost" + CRLF + "of tuition" + CRLF + "was hard."
    doc = QTextDocument()
    doc.setPlainText(text)
    omap = OffsetMap(text, qt_text=doc.toPlainText())
    assert omap.is_exact

    word = "tuition"
    qt_index = doc.toPlainText().index(word)
    cursor = QTextCursor(doc)
    cursor.setPosition(qt_index)
    cursor.setPosition(qt_index + len(word), QTextCursor.MoveMode.KeepAnchor)
    assert cursor.selectedText() == word

    start, end = omap.span_to_source(cursor.selectionStart(), cursor.selectionEnd())
    assert text[start:end] == word, "the stored excerpt would not be what was selected"
