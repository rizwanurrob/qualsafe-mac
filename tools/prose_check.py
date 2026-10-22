#!/usr/bin/env python
"""
Check prose for the habits that read as machine-written.

    python tools/prose_check.py app README.md
    python tools/prose_check.py --strings app          # UI text only

The list comes from Wikipedia's *Signs of AI writing*, which is the most
carefully assembled catalogue of the tells — assembled by editors who spend
their days reverting the stuff, and updated as the models change.

Two kinds of check, and the second is the one that matters here.

**Vocabulary** is the famous half: *delve*, *crucial*, *tapestry*, *showcasing*,
*leverage*, *robust*, *seamless*. It is also the half this project already
passes, because someone wrote the text carefully.

**Rhythm** is the half that gets missed, and it is measured rather than matched:

- *Em dashes.* Careful technical prose uses a handful per thousand words. Machine
  prose uses them as a general-purpose joint, several times a paragraph.
- *Bold.* Emphasis works by being rare. One bolded phrase every twenty-five
  words is texture rather than emphasis. Bolded **UI controls do not count**:
  naming a menu item or a keyboard shortcut in bold is what good documentation
  does, and the first version of this tool did not tell the two apart. It
  reported the Help guide at 35 per thousand and would have had someone strip
  the markup that makes a walkthrough followable.
- *Negative parallelism.* "Not X, but Y." "Not a nicety, a necessity." "Rather
  than." One is a good sentence. Six on a page is a tic.

A count is not a verdict. The point is to make a habit visible so a person can
decide, which is why this prints numbers and a threshold rather than a pass or a
fail on any single sentence.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

#: Vocabulary the Wikipedia page names, plus the promotional register it flags.
#: A single instance means nothing; the page says so and so does this tool.
VOCABULARY = {
    "delve", "crucial", "pivotal", "underscore", "underscores", "underscoring",
    "tapestry", "testament", "vibrant", "showcase", "showcases", "showcasing",
    "leverage", "leverages", "leveraging", "seamless", "seamlessly",
    "meticulous", "meticulously", "intricate", "realm", "foster", "fosters",
    "fostering", "garner", "boast", "boasts", "harnesses", "elevate",
    "empower", "empowers", "empowering", "unlock", "unlocks", "myriad",
    "plethora", "bolster", "bolsters", "cutting-edge", "state-of-the-art",
    "game-changer", "revolutionize", "transformative", "holistic", "synergy",
    "utilize", "utilizes", "utilizing", "invaluable", "unparalleled",
    "indelible", "multifaceted", "nuanced",
}

#: Sentence shapes the page calls out by name.
PHRASES: List[Tuple[str, str]] = [
    ("not only ... but", r"\bnot only\b[^.?!]{0,80}\bbut\b"),
    ("not just ... but", r"\bnot just\b[^.?!]{0,60}\bbut\b"),
    ("it's not X, it's Y", r"\bit'?s not\b[^.?!]{0,50},\s*it'?s\b"),
    ("serves as", r"\b(serves as|stands as|functions as)\b"),
    ("participle tail", r",\s+(ensuring|highlighting|emphasizing|showcasing|"
                        r"underscoring|reflecting|symbolizing|fostering)\b"),
    ("in today's ...", r"\bin today'?s\b[^.?!]{0,30}\b(world|landscape)\b"),
    ("whether you're", r"\bwhether you'?re\b"),
    ("dive into", r"\b(dive into|deep dive|let'?s explore)\b"),
    ("plays a key role", r"\bplays? an? (crucial|vital|key|pivotal) role\b"),
]

#: Negative parallelism, counted rather than forbidden.
NEGATIVES: List[Tuple[str, str]] = [
    ("not X but Y", r"\bnot \w+,? but\b"),
    ("rather than", r"\brather than\b"),
    ("is not a/an/the", r"\bis not (a|an|the)\b"),
]

#: Per thousand words. Chosen from this project's own best-written prose rather
#: than from an outside style guide: the project's best prose sits at 6.8 em dashes
#: and 10.2 bolds per thousand and reads well, so these leave room above that.
EM_DASH_PER_1K = 8.0
BOLD_PER_1K = 18.0
NEGATIVE_PER_1K = 3.0


#: A menu path, a button, a keyboard shortcut. Bolding these is what good
#: documentation does: a walkthrough that says "click File > New project"
#: without marking it is harder to follow, not cleaner. Counting them as
#: emphasis is what made the first run of this tool report the Help guide at 35
#: bolds per thousand words and recommend stripping the very markup that makes a
#: walkthrough followable.
_CONTROL = re.compile(
    r"(→|->|`)"                                  # a menu path or code span
    r"|^(Ctrl|Alt|Shift|Cmd|Esc|Tab|Enter|F\d+)\b"    # a keyboard shortcut
    r"|^[A-Z][\w .&'/…-]{0,28}…?$"          # "Add code", "Models"
)


def names_a_control(span: str) -> bool:
    """Is this bolded run a UI control rather than emphasis?"""
    span = span.strip()
    if not span or len(span.split()) > 5:
        return False
    return bool(_CONTROL.search(span))


@dataclass
class Report:
    path: str
    words: int
    em_dashes: int
    bolds: int
    negatives: int
    vocabulary: Dict[str, int]
    phrases: Dict[str, int]

    def rate(self, count: int) -> float:
        return (count / self.words * 1000) if self.words else 0.0

    def failures(self) -> List[str]:
        out = []
        if self.rate(self.em_dashes) > EM_DASH_PER_1K:
            out.append(f"em dashes {self.rate(self.em_dashes):.1f}/1k "
                       f"(limit {EM_DASH_PER_1K})")
        if self.rate(self.bolds) > BOLD_PER_1K:
            out.append(f"bold {self.rate(self.bolds):.1f}/1k (limit {BOLD_PER_1K})")
        if self.rate(self.negatives) > NEGATIVE_PER_1K:
            out.append(f"negative parallelism {self.rate(self.negatives):.1f}/1k "
                       f"(limit {NEGATIVE_PER_1K})")
        if self.vocabulary:
            named = ", ".join(sorted(self.vocabulary))
            out.append(f"flagged vocabulary: {named}")
        if self.phrases:
            named = ", ".join(sorted(self.phrases))
            out.append(f"flagged constructions: {named}")
        return out


def check_text(text: str, path: str) -> Report:
    words = len(re.findall(r"\b\w+\b", text))
    lowered = text.lower()

    vocabulary: Dict[str, int] = {}
    for word in VOCABULARY:
        found = len(re.findall(r"\b" + re.escape(word) + r"\b", lowered))
        if found:
            vocabulary[word] = found

    phrases: Dict[str, int] = {}
    for name, pattern in PHRASES:
        found = len(re.findall(pattern, text, re.I))
        if found:
            phrases[name] = found

    negatives = sum(len(re.findall(p, text, re.I)) for _n, p in NEGATIVES)
    bolds = sum(1 for span in re.findall(r"\*\*([^*\n]+)\*\*", text)
                if not names_a_control(span)) + text.count("<b>")

    return Report(path=path, words=words, em_dashes=text.count("—"),
                  bolds=bolds, negatives=negatives,
                  vocabulary=vocabulary, phrases=phrases)


def ui_strings(path: Path) -> str:
    """Every string literal long enough to be prose, docstrings excluded.

    Docstrings are for the next developer and follow the codebase's own voice;
    what a user reads is the target here.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return ""
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)
    return "\n".join(
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and len(node.value) >= 40 and node.value not in docstrings)


SKIP = ("__pycache__", ".venv", "build", "dist", "project_progress")


def gather(targets: Iterable[str], strings_only: bool) -> List[Report]:
    reports: List[Report] = []
    for target in targets:
        path = Path(target)
        candidates = [path] if path.is_file() else [
            p for p in sorted(path.rglob("*"))
            if p.suffix in {".py", ".md"} and not any(s in str(p) for s in SKIP)
        ]
        for candidate in candidates:
            if candidate.suffix == ".py":
                text = ui_strings(candidate)
            elif strings_only:
                continue
            else:
                text = candidate.read_text(encoding="utf-8", errors="replace")
            if len(re.findall(r"\b\w+\b", text)) < 150:
                continue    # too short for a rate to mean anything
            reports.append(check_text(text, str(candidate)))
    return reports


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("targets", nargs="+")
    parser.add_argument("--strings", action="store_true",
                        help="only UI strings inside .py files")
    parser.add_argument("--quiet", action="store_true",
                        help="print only what exceeds a threshold")
    arguments = parser.parse_args(argv)

    reports = gather(arguments.targets, arguments.strings)
    failing = 0
    for report in sorted(reports, key=lambda r: -r.rate(r.em_dashes)):
        problems = report.failures()
        if problems:
            failing += 1
        elif arguments.quiet:
            continue
        print(f"{report.path}  ({report.words} words)")
        print(f"    em {report.rate(report.em_dashes):5.1f}/1k   "
              f"bold {report.rate(report.bolds):5.1f}/1k   "
              f"neg {report.rate(report.negatives):5.1f}/1k")
        for problem in problems:
            print(f"    ! {problem}")

    print(f"\n{len(reports)} file(s) checked, {failing} over a threshold")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
