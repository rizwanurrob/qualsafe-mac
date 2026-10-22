"""
Constructs Python accepts silently and that mean the opposite of what they say.

A duplicate key in a dict literal is not an error. It is a *discard*: Python
keeps the last one and says nothing, no linter runs in this project's test
gate, and no test can fail because there is nothing to fail on.

This one is here because it happened. Merging the v4.9.0 inference cache into
`portable-llm` conflicted in the theme-engine config block — that branch's LLM
checkpoint keys against master's `inference_cache` key — and both sides defined
`resume_callback`. Keeping both sides produced a dict with the same key twice.
The behaviour was correct by luck (the surviving one was the better of the two)
and the whole suite passed on both branches.

That is the exact profile of a defect worth a cheap structural check: silent,
survivable, produced by an ordinary mechanical action, invisible to every test
that exists. Merge conflicts in argument dicts are going to keep happening while
two branches diverge, so the check earns its keep.

**Verified against the real thing**, not only against a synthetic dict: run over
`portable-llm` at the merge commit that introduced it, the check reports

    line 1879 repeats 'resume_callback' (first at 1869)

and reports nothing at the commit before or the commit after. A structural check
that has never been shown to fire is a check nobody should trust.

The set is deliberately small. These are not style rules — each one is a place
where the code says one thing and does another.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SKIP_DIRS = {".venv", "venv", "build", "dist", "site-packages", ".git",
             "__pycache__", "node_modules"}


def source_files():
    for path in sorted(ROOT.rglob("*.py")):
        if SKIP_DIRS & set(path.parts):
            continue
        yield path


def parsed_sources():
    for path in source_files():
        try:
            yield path, ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue


def _constant_keys(node: ast.Dict):
    """The literal keys of a dict display, in source order.

    Computed keys and `**spread` entries (a None key) are skipped: they are not
    statically knowable, and a spread genuinely intends later entries to win.
    """
    for key in node.keys:
        if isinstance(key, ast.Constant) and isinstance(
                key.value, (str, int, float, bool, type(None))):
            yield key


class TestNoDictLiteralSaysTheSameKeyTwice:

    def test_every_dict_display_has_distinct_literal_keys(self):
        offenders = []
        for path, tree in parsed_sources():
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict):
                    continue
                seen = {}
                for key in _constant_keys(node):
                    if key.value in seen:
                        offenders.append(
                            f"{path.relative_to(ROOT).as_posix()}:{key.lineno} "
                            f"repeats {key.value!r} "
                            f"(first at line {seen[key.value]})")
                    else:
                        seen[key.value] = key.lineno

        assert offenders == [], (
            "a duplicate key in a dict literal is silently discarded, not "
            "reported:\n  " + "\n  ".join(offenders))

    def test_the_check_finds_one_when_there_is_one(self):
        """A structural test that cannot fail is worse than no test."""
        tree = ast.parse('x = {"a": 1, "b": 2, "a": 3}')
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.Dict))

        keys = [key.value for key in _constant_keys(node)]

        assert keys == ["a", "b", "a"]
        assert len(keys) != len(set(keys))

    def test_a_spread_does_not_count_as_a_duplicate(self):
        """`{**defaults, "a": 1}` means later entries to win. That is the
        construct working, not failing."""
        tree = ast.parse('x = {**defaults, "a": 1}')
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.Dict))

        assert [key.value for key in _constant_keys(node)] == ["a"]

    def test_a_computed_key_is_left_alone(self):
        tree = ast.parse('x = {name: 1, "name": 2}')
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.Dict))

        assert [key.value for key in _constant_keys(node)] == ["name"]


class TestNoFunctionRepeatsAParameterName:
    """The same discard, one construct over. Python raises for a duplicate
    parameter at compile time, so this catches only what a parser accepts —
    which is why it is cheap enough to keep alongside the dict check."""

    def test_no_call_passes_the_same_keyword_twice(self):
        offenders = []
        for path, tree in parsed_sources():
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                names = [kw.arg for kw in node.keywords if kw.arg is not None]
                if len(names) != len(set(names)):
                    repeated = sorted({n for n in names if names.count(n) > 1})
                    offenders.append(
                        f"{path.relative_to(ROOT).as_posix()}:{node.lineno} "
                        f"passes {', '.join(repeated)} more than once")

        assert offenders == [], "\n  ".join(["duplicate keyword arguments:"] + offenders)
