#!/usr/bin/env python
"""
Reading a CSV that Excel wrote (`RELEASE_READINESS.md` §1.1, "messy encodings").

`pd.read_csv(path)` assumes UTF-8. Excel on Windows does not write UTF-8 unless
the user picks the *"CSV UTF-8"* item rather than the plain *"CSV"* one, and
almost nobody does — the plain one is higher in the menu and is what "Save as
CSV" has meant for twenty years. That file is **cp1252**, and the moment a
response contains a curly apostrophe, an em-dash or a café, reading it raises:

    UnicodeDecodeError: 'utf-8' codec can't decode byte 0x92 in position 49

Measured, not assumed. That is a raw traceback, on the first screen, for a file
the researcher believes is fine — and free-text survey answers are *made* of
curly apostrophes, because Word and Excel insert them automatically.

This is the most likely single reason a first real user bounces off the program,
and it was listed under "no real research project has been carried through" as
though it needed a real project to find. It needed one file.

What this does
--------------
Tries encodings in order and **reports which one worked**. It does not guess
silently, because the failure mode of guessing is not a crash — it is a corpus
where every apostrophe has become `â€™` and nobody notices until it is quoted in
a paper.

- **utf-8** first, which also covers `utf-8-sig`: pandas strips the BOM itself,
  so a "CSV UTF-8" file needs nothing special (verified rather than assumed).
- **cp1252** next, the Windows Western default.
- **latin-1** last, which *never raises* — every byte is a valid character. That
  makes it a guarantee of loading and no guarantee at all of being right, so
  reaching it is reported as a warning rather than a success.

No dependency is added for character detection. An ordered fallback that says
what it did is more honest than a probabilistic guess that does not, at the
sizes and origins of file this program sees.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence

import pandas as pd

#: Tried in this order. `utf-8` covers `utf-8-sig` because pandas strips the BOM.
ENCODINGS: Sequence[str] = ("utf-8", "cp1252", "latin-1")

#: The last resort. It cannot fail and therefore cannot reassure: every byte
#: decodes to *something*, so a wrong guess produces mojibake rather than an
#: error. Reaching it is always reported.
LAST_RESORT = "latin-1"

#: How much of the file to inspect before trying to parse it. Enough to
#: catch a binary header, small enough to be free.
_SNIFF_BYTES = 8192

#: Built rather than written as a literal, so no source file in this project
#: ever contains a NUL byte -- Python refuses to import a module that does.
NUL = bytes([0])


@dataclass(frozen=True)
class TextRead:
    """A frame, and the truth about how it was decoded."""

    frame: pd.DataFrame
    encoding: str
    #: Encodings that raised before this one worked. Empty on a clean UTF-8 read.
    rejected: List[str]

    @property
    def is_fallback(self) -> bool:
        """True when an earlier candidate was tried and rejected."""
        return bool(self.rejected)

    @property
    def is_guess(self) -> bool:
        """True when the file loaded only because `latin-1` cannot fail."""
        return self.encoding == LAST_RESORT

    def note(self) -> str:
        """What to tell the analyst. Empty when there is nothing to say."""
        if not self.is_fallback:
            return ""
        if self.is_guess:
            return (
                f"This file is not UTF-8 and is not {ENCODINGS[1]} either, so it "
                f"was read as {LAST_RESORT}, which never fails and therefore "
                "proves nothing. Check a few responses for mangled characters "
                "before coding: an apostrophe showing as â€™ means the guess was "
                "wrong. Re-exporting from Excel as “CSV UTF-8” avoids this.")
        return (
            f"This file is not UTF-8; it was read as {self.encoding}, which is "
            "what Excel on Windows writes when you choose plain “CSV”. That is "
            "usually right. If curly quotes or accents look wrong in the "
            "responses, re-export as “CSV UTF-8”.")



class NotATextFileError(ValueError):
    """Raised when a file is binary and cannot be a delimited text file.

    This exists *because* of the fallback rather than in spite of it. `latin-1`
    decodes every byte, so without a guard a `.csv` that is really a PNG, a
    `.sav`, or a truncated download loads as a one-cell table of control
    characters and the analyst sees an empty-looking dataset with no error.

    Measured: a four-byte binary file parsed happily as a single row. Refusing
    is better than a silent garbage frame — a NUL byte cannot appear in a valid
    CSV.
    """


def _refuse_binary(path: Path | str) -> None:
    """Refuse a file that is obviously not text, before any decoding."""
    try:
        head = Path(path).open("rb").read(_SNIFF_BYTES)
    except OSError:
        return          # let the reader raise the real filesystem error
    if NUL in head:
        raise NotATextFileError(
            f"{Path(path).name} contains NUL bytes, so it is a binary file "
            "rather than a delimited text file. It may be an Excel workbook or "
            "an SPSS file saved with a .csv extension, or a truncated download.")


def read_csv(path: Path | str, *, preferred: Optional[str] = None,
             **kwargs: Any) -> TextRead:
    """`pd.read_csv` with an ordered encoding fallback and a report.

    `preferred` is tried first. It exists for the CLI, whose config carries an
    `encoding:` key: an analyst who has said what their file is should be
    believed before the guesses, and a fallback should still catch them when
    they are wrong -- which they usually are, because the shipped example config
    says `utf-8` and nobody edits it.
    """
    _refuse_binary(path)
    return _attempt(lambda enc: pd.read_csv(path, encoding=enc, **kwargs),
                    preferred=preferred)


def read_csv_as_text(path: Path | str, *, preferred: Optional[str] = None,
                     **kwargs: Any) -> TextRead:
    """`read_csv` for a file a person may have edited: every cell as text.

    `response_id` is the join key for coding, agreement, erasure and the store,
    and pandas' type inference changes it: "000123" becomes the integer 123 and
    "101" can come back as 101.0. A literal "N/A" answer becomes a missing value.
    Reading everything as text, with blanks as "", keeps the file saying what
    it says. Review finding F3: a colleague's codes landed on respondent 123
    with nothing reported unmatched, and erasing respondent 000123 left their
    row in the run's CSVs.
    """
    kwargs.setdefault("dtype", str)
    kwargs.setdefault("keep_default_na", False)
    return read_csv(path, preferred=preferred, **kwargs)


def read_csv_bytes(data: bytes, *, preferred: Optional[str] = None,
                   **kwargs: Any) -> TextRead:
    """The same fallback for an in-memory upload, which has no path.

    A web upload arrives as a file object, and an uploaded CSV is exactly the
    case most likely to have come straight out of Excel -- so this is the path
    that needs the fallback most, and it was the one a path-only helper could
    not serve.
    """
    import io

    if NUL in data[:_SNIFF_BYTES]:
        raise NotATextFileError(
            "That file contains NUL bytes, so it is a binary file rather than "
            "a delimited text file. It may be an Excel workbook or an SPSS "
            "file saved with a .csv extension.")
    return _attempt(lambda enc: pd.read_csv(io.BytesIO(data), encoding=enc,
                                            **kwargs),
                    preferred=preferred)


def read_json(path: Path | str, **kwargs: Any) -> TextRead:
    """`pd.read_json` with the same fallback.

    JSON is *specified* as UTF-8, so a non-UTF-8 JSON file is malformed rather
    than merely inconvenient — but it is malformed in a way that is not the
    researcher's fault and that refusing to read helps nobody.
    """
    _refuse_binary(path)
    return _attempt(lambda enc: pd.read_json(path, encoding=enc, **kwargs))


def candidate_encodings(preferred: Optional[str] = None) -> List[str]:
    """`ENCODINGS`, with `preferred` moved to the front if it is not already."""
    if not preferred:
        return list(ENCODINGS)
    rest = [e for e in ENCODINGS if e.lower() != preferred.lower()]
    return [preferred] + rest


def _attempt(load: Callable[[str], pd.DataFrame],
             preferred: Optional[str] = None) -> TextRead:
    rejected: List[str] = []
    last: Optional[Exception] = None
    for encoding in candidate_encodings(preferred):
        try:
            return TextRead(frame=load(encoding), encoding=encoding,
                            rejected=list(rejected))
        except (UnicodeDecodeError, LookupError) as error:
            rejected.append(encoding)
            last = error
    # `latin-1` cannot raise UnicodeDecodeError, so arriving here means the file
    # is broken in some other way and the caller should see that error, not a
    # story about encodings.
    raise last if last is not None else ValueError("the file could not be read")
