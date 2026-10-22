"""
Mapping between source-string offsets and Qt document positions.

**Why this module exists.** The evidentiary link in QualSafe is
``excerpt.text == source.raw_text[char_start:char_end]`` (`core.model.Excerpt.
verify_offsets`, non-negotiable invariant #4). The Qt front end gets its offsets
from a `QTextCursor`, which counts positions in a `QTextDocument` — and a
`QTextDocument` is **not** a verbatim copy of the string you put into it.

Measured on PySide6 6.11 (`QPlainTextEdit` and `QTextEdit` behave identically):

=====================  ========  ==========================================
source                 becomes   effect on offsets
=====================  ========  ==========================================
CR LF (U+000D U+000A)  LF        **length changes** -- later offsets shift
CR (U+000D)            LF        none (1:1 substitution)
U+2028 LINE SEP        LF        none (1:1 substitution)
U+2029 PARAGRAPH SEP   LF        none (1:1 substitution)
U+00A0 NO-BREAK SPACE  SPACE     none (1:1 substitution)
TAB, VT, FF, NUL       kept      none
=====================  ========  ==========================================

Both kinds are real in this corpus: CRLF is what a Windows ``.txt`` transcript
contains, and U+00A0 is what Word puts in a ``.docx``. So a naive "assume 1:1"
would silently attach codes to the wrong passage in a CRLF document -- exactly
the failure invariant #4 exists to prevent -- while a naive "assert the two
strings are equal" would refuse to code a perfectly ordinary ``.docx``.

The approach: build the map from the one length-changing rule, then **verify**
it by reconstructing what Qt should have produced and comparing against the real
document text. If the reconstruction does not match (a future Qt normalizes
something new), `OffsetMap.is_exact` is False and the caller must refuse to code
that document rather than guess. Coding the wrong passage is worse than not
coding at all.

Pure Python, no Qt import -- so the mapping is testable without a display.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

# Spelled as code points rather than literals: every one of these is invisible
# in an editor, and a literal NBSP is precisely the character a tool silently
# "fixes" into a plain space -- which would break the table without visibly
# breaking the file.
_CR = chr(0x0D)
_LF = chr(0x0A)
_LINE_SEP = chr(0x2028)
_PARA_SEP = chr(0x2029)
_NBSP = chr(0x00A0)
_SPACE = chr(0x20)

#: The CRLF pair, whose collapse to a single LF is the one transformation that
#: moves offsets. Handled separately from the 1:1 table below.
CRLF = _CR + _LF

#: Characters Qt replaces one-for-one on entry to a QTextDocument. These never
#: move an offset -- they only mean the Qt text and the source text are unequal,
#: which is why equality is the wrong check.
QT_SUBSTITUTIONS = {
    _CR: _LF,
    _LINE_SEP: _LF,
    _PARA_SEP: _LF,
    _NBSP: _SPACE,
}


def expected_qt_text(source: str) -> str:
    """Reconstruct what Qt turns `source` into: CRLF collapse, then substitution.

    If this equals ``document.toPlainText()``, the map built from the same rules
    is exactly right -- which is how `OffsetMap` earns `is_exact`.
    """
    collapsed = (source or "").replace(CRLF, _LF)
    return "".join(QT_SUBSTITUTIONS.get(ch, ch) for ch in collapsed)


class OffsetMap:
    """Translates between source-string indices and Qt document positions.

    The common case -- a document with no CRLF -- is the identity, and is stored
    as such (no per-character tables), so a 40-page transcript costs nothing.

    Indices are *positions between characters*: valid inputs run ``0..len``
    inclusive, matching how `QTextCursor.selectionStart` / `selectionEnd` and
    Python slicing both work. Out-of-range inputs are clamped rather than
    raising, because they arrive from a live cursor.
    """

    __slots__ = ("_src_len", "_qt_len", "_src_to_qt", "_qt_to_src", "is_exact")

    def __init__(self, source: str, qt_text: Optional[str] = None) -> None:
        source = source or ""
        rebuilt = expected_qt_text(source)
        # With the real document text in hand we verify; with none passed we
        # trust the reconstruction (tests, and callers building a map before the
        # widget exists).
        self.is_exact: bool = True if qt_text is None else (qt_text == rebuilt)

        self._src_len = len(source)
        self._qt_len = len(rebuilt)

        if CRLF not in source:
            # Nothing changes length, so positions coincide. Skip the tables.
            self._src_to_qt: Optional[List[int]] = None
            self._qt_to_src: Optional[List[int]] = None
            return

        src_to_qt: List[int] = []
        qt_to_src: List[int] = [0] * (self._qt_len + 1)
        qt_pos = 0
        i = 0
        while i < self._src_len:
            if source.startswith(CRLF, i):
                # The pair became one paragraph separator: both source indices
                # sit at that single Qt position, and the Qt position resolves
                # back to the *first* of them, so a selection touching the break
                # covers the whole pair instead of orphaning the CR.
                qt_to_src[qt_pos] = i
                src_to_qt.append(qt_pos)      # the CR
                src_to_qt.append(qt_pos)      # the LF
                i += 2
            else:
                qt_to_src[qt_pos] = i
                src_to_qt.append(qt_pos)
                i += 1
            qt_pos += 1
        src_to_qt.append(qt_pos)              # end sentinel
        qt_to_src[qt_pos] = self._src_len     # end sentinel

        self._src_to_qt = src_to_qt
        self._qt_to_src = qt_to_src
        # A sentinel disagreeing with the reconstructed length would be a bug in
        # the walk above rather than a Qt surprise -- either way, not exact.
        if qt_pos != self._qt_len:
            self.is_exact = False

    # -- translation ---------------------------------------------------------
    def to_qt(self, source_index: int) -> int:
        """Source-string index -> Qt document position."""
        idx = max(0, min(self._src_len, int(source_index)))
        if self._src_to_qt is None:
            return idx
        return self._src_to_qt[idx]

    def to_source(self, qt_position: int) -> int:
        """Qt document position -> source-string index."""
        pos = max(0, min(self._qt_len, int(qt_position)))
        if self._qt_to_src is None:
            return pos
        return self._qt_to_src[pos]

    def span_to_qt(self, start: int, end: int) -> Tuple[int, int]:
        return self.to_qt(start), self.to_qt(end)

    def span_to_source(self, start: int, end: int) -> Tuple[int, int]:
        return self.to_source(start), self.to_source(end)

    # -- introspection -------------------------------------------------------
    @property
    def source_length(self) -> int:
        return self._src_len

    @property
    def qt_length(self) -> int:
        return self._qt_len

    @property
    def is_identity(self) -> bool:
        """True when Qt positions and source indices coincide (no CRLF present)."""
        return self._src_to_qt is None
