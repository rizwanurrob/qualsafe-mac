"""Interface wording rules (V8_PLAN.md section 2.1), and a scan that checks them.

Two lists:

* `NEVER` are hype words that must not appear in interface text at all.
* `REPLACE` are model or internal terms with a plain word to use instead.
  They may still appear in Settings, the glossary and the methods appendix
  (`ALLOWED_PATHS`). Hype words (`NEVER`) are banned there too.

`scan()` reads the string literals of the front-end source files and counts the
terms. It never imports Qt or Streamlit. On the desktop the count must be zero
outside `ALLOWED_PATHS` (`tests/test_ux_words.py`); on the web it is zero too
(Update 3, phase 4b, item 4b.5h).

Single-word strings are read only when they are written as a label (capitalised, letters only), because other single
words are mostly identifiers and keys. A one-word heading written in lower case has to be checked by eye.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

ROOT = Path(__file__).resolve().parents[2]

# Never in interface text.
NEVER: Dict[str, str] = {
    "AI-powered": r"\bAI[- ]powered\b",
    "smart": r"\bsmart\b",
    "intelligent": r"\bintelligen(?:t|ce)\b",
    "magic": r"\bmagic(?:al)?\b",
    "insights": r"\binsights?\b",
    "leverage": r"\bleverag(?:e|es|ed|ing)\b",
    "seamless": r"\bseamless(?:ly)?\b",
    "unlock": r"\bunlock(?:s|ed|ing)?\b",
    "effortless": r"\beffortless(?:ly)?\b",
    "revolutionary": r"\brevolutionary\b",
}

# term -> (pattern, plain replacement)
REPLACE: Dict[str, Tuple[str, str]] = {
    "zero-shot": (r"zero[- ]shot", "suggested code"),
    "UNCERTAIN_REVIEW": (r"UNCERTAIN_REVIEW", "Needs your review"),
    "excerpt": (r"\bexcerpts?\b", "passage"),
    "rater": (r"\braters?\b", "coder"),
    "descriptor": (r"descriptors?", "respondent details (surveys), attributes (interviews)"),
    "pipeline": (r"pipelines?", "analysis"),
    "embedding": (r"embeddings?", "(Settings only)"),
    "NLI/MNLI/SST-2": (r"\b(?:NLI|MNLI|SST-2)\b", "(Settings only)"),
    "transformer": (r"transformers?", "(Settings only)"),
    "Hugging Face": (r"Hugging ?Face", "(Settings only)"),
    "LLM": (r"\bLLMs?\b", "local language model (optional)"),
    "heuristic": (r"heuristics?", "rough check"),
    "cluster": (r"clusters?", "group of similar answers"),
    "corpus": (r"\bcorpus\b", "your documents"),
    "hallucination": (r"hallucinat\w+", "quotes not found in the transcript"),
    "id field": (r"\b\w+_id\b", "a plain name such as Respondent or Coder"),
    "code:: prefix": (r"\bcode::", "the code's name"),
}

# Where technical terms are allowed to appear.
ALLOWED_PATHS: Tuple[str, ...] = (
    "qualsafe_qt/views/models_view.py",
    "app/model_manager.py",
    "app/shared/models.py",            # the web's model panel: Settings > Models, More options
    # The Help pages. They are rewritten in Update 3 phase 4 (items 4.1 to 4.4); after that only
    # the glossary and the troubleshooting article belong here, and this line goes.
    "qualsafe_qt/views/help_view.py",
)

FRONT_END_GLOBS: Dict[str, Tuple[str, ...]] = {
    "desktop": ("qualsafe_qt/views/*.py", "qualsafe_qt/widgets/*.py",
                "qualsafe_qt/windows/*.py"),
    "web": ("app/*.py", "app/shared/*.py", "interview_ui.py"),
}


def _looks_like_a_label(text: str) -> bool:
    """A one-word string written as a label ("Descriptor", "Excerpts"): capitalised letters only. Lower-case
    one-word strings are keys and identifiers, which this scan has always left alone."""
    return text.isalpha() and text[:1].isupper()


def ui_strings(source: str) -> List[str]:
    """String literals that look like interface text (not docstrings)."""
    tree = ast.parse(source)
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            d = ast.get_docstring(node, clean=False)
            if d:
                docs.add(d)
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value not in docs and len(n.value) > 3
            and (" " in n.value or _looks_like_a_label(n.value))]


def find_never(text: str) -> List[str]:
    return [k for k, p in NEVER.items() if re.search(p, text, re.I)]


def find_replace(text: str) -> List[str]:
    flags = {"UNCERTAIN_REVIEW": 0, "id field": 0, "code:: prefix": 0}
    return [k for k, (p, _) in REPLACE.items()
            if re.search(p, text, flags.get(k, re.I))]


def _files(surface: str, root: Path) -> Iterable[Path]:
    for pattern in FRONT_END_GLOBS[surface]:
        yield from sorted(root.glob(pattern))


def scan(root: Path = ROOT) -> Dict[str, Dict[str, Counter]]:
    """Count banned and replaceable terms per surface.

    Returns {surface: {"never": Counter, "replace": Counter}}. Files in
    `ALLOWED_PATHS` are only checked for `NEVER` words.
    """
    allowed = {(root / p).resolve() for p in ALLOWED_PATHS}
    out: Dict[str, Dict[str, Counter]] = {}
    for surface in FRONT_END_GLOBS:
        never, repl = Counter(), Counter()
        for f in _files(surface, root):
            skip_replace = f.resolve() in allowed       # technical terms are fine there; hype never is
            for s in ui_strings(f.read_text(encoding="utf-8")):
                never.update(find_never(s))
                if not skip_replace:
                    repl.update(find_replace(s))
        out[surface] = {"never": never, "replace": repl}
    return out


def report(root: Path = ROOT) -> str:
    lines = []
    for surface, res in scan(root).items():
        lines.append(f"{surface}")
        lines.append("  never:   " + (", ".join(f"{k} {n}" for k, n in sorted(res["never"].items())) or "none"))
        lines.append("  replace: " + (", ".join(f"{k} {n}" for k, n in res["replace"].most_common()) or "none"))
    return "\n".join(lines)


if __name__ == "__main__":
    print(report())
