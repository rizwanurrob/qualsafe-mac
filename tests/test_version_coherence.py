"""
The version stamp has to be true, because reproducibility rests on it.

`PACKAGE_VERSION` is written into every run manifest, every methods appendix,
every codebook report, every framework export and every `.qdpx`. It is the
number a reviewer uses to obtain the software that produced a result.

It had stopped being true. The engine sat at 4.4.0 while the store moved to
schema v5, so those documents named a release that **cannot open the file it
claims to have written** — a v5 store raises `SchemaTooNewError` on 4.4.0 rather
than degrading. Nothing caught it, because nothing was checking.

These are cheap and they are the check that was missing.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.manifest import PACKAGE_VERSION  # noqa: E402
from core.project import SCHEMA_VERSION  # noqa: E402


def _released_versions() -> list:
    """Version headings in the changelog, newest first."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    return re.findall(r"^## v(\d+\.\d+\.\d+)", text, re.M)


class TestTheStampMatchesTheCode:

    def test_the_newest_release_in_the_changelog_is_the_package_version(self):
        """The check that was missing. Without it the stamp fell two releases
        behind the code and every exported document inherited the lie."""
        released = _released_versions()
        assert released, "no released version headings found in CHANGELOG.md"
        assert released[0] == PACKAGE_VERSION, (
            f"CHANGELOG's newest release is v{released[0]} but PACKAGE_VERSION "
            f"is {PACKAGE_VERSION}. Every manifest, methods appendix and .qdpx "
            "carries that number, so they disagree with the changelog about "
            "what produced them.")

    def test_the_version_only_goes_forwards(self):
        versions = [tuple(int(p) for p in v.split(".")) for v in _released_versions()]
        assert versions == sorted(versions, reverse=True), (
            "changelog versions are not in descending order")

    def test_there_is_no_stale_unreleased_section_above_the_newest_release(self):
        """An Unreleased section is fine while work is in flight. One sitting
        above a released heading that does not match the code is how this drifted.
        """
        text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        headings = re.findall(r"^## (.+)$", text, re.M)
        if not headings:
            return
        if headings[0].lower().startswith("unreleased"):
            assert _released_versions()[0] == PACKAGE_VERSION, (
                "there is unreleased work above a release heading that does not "
                "match PACKAGE_VERSION; cut the release or bump the version")


class TestThereIsOnlyOneVersionNumber:
    """A second copy is how a version goes stale without anyone editing it.

    `core/populate.py` declared its own `PACKAGE_VERSION = "3.0.0-dev"` and wrote
    it into the Run row of every survey run, so projects recorded a version four
    releases dead — inside the store, not merely in an export — while
    `interview/populate.py` imported the real one and recorded it correctly.
    """

    def test_only_core_manifest_defines_the_package_version(self):
        import ast

        definers = []
        for path in ROOT.rglob("*.py"):
            parts = set(path.parts)
            if parts & {".venv", "venv", "build", "dist", "site-packages", "tests"}:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in tree.body:                    # module scope only
                targets = (node.targets if isinstance(node, ast.Assign)
                           else [node.target] if isinstance(node, ast.AnnAssign)
                           else [])
                if any(isinstance(t, ast.Name) and t.id == "PACKAGE_VERSION"
                       for t in targets):
                    definers.append(path.relative_to(ROOT).as_posix())

        assert definers == ["core/manifest.py"], (
            f"PACKAGE_VERSION is defined in {definers}. Every copy but "
            "core/manifest.py is a version waiting to go stale; import it "
            "instead.")

    def test_pyproject_declares_the_same_version(self):
        """`tools/build_release.py` names the download from `pyproject.toml`.

        It said 4.4.0 while the code said 4.6.0, so the release zip a user
        downloads would have been called `QualSafe_v4.4.0.zip` and contained
        4.6.0 — the same defect as the manifest stamp, on the one filename the
        user actually sees.
        """
        import re as _re

        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        match = _re.search(r'^version\s*=\s*"([^"]+)"', text, _re.M)

        assert match, "no version in pyproject.toml"
        assert match.group(1) == PACKAGE_VERSION, (
            f"pyproject says {match.group(1)}, the code says {PACKAGE_VERSION}; "
            "the release archive would be named after the wrong one")

    def test_a_survey_run_records_the_real_version(self):
        """The Run row is the store's own provenance. It is what a reviewer reads
        to learn which software produced the coding in the file."""
        from core import populate

        assert populate.PACKAGE_VERSION == PACKAGE_VERSION


class TestTheInterfaceSaysItToo:
    """Recoverable from an export is not the same as visible.

    Both numbers reached every exported document and neither reached the screen,
    so the one moment they are wanted — sitting in front of a project, wondering
    whether this install opens it — was the one moment they were absent.
    """

    def test_the_sidebar_footer_names_both_numbers(self, monkeypatch):
        from app.shared import widgets

        printed = []

        class FakeSidebar:
            def caption(self, text, *a, **k):
                printed.append(text)

            def divider(self, *a, **k):
                pass

        monkeypatch.setattr(widgets.st, "sidebar", FakeSidebar())
        widgets.render_version_footer()

        blob = " ".join(printed)
        assert PACKAGE_VERSION in blob
        assert f"v{SCHEMA_VERSION}" in blob

    def test_the_status_panel_ends_with_it(self):
        """Wired in, not merely defined."""
        import ast
        import inspect

        from app.shared import widgets

        tree = ast.parse(inspect.getsource(widgets.render_sidebar_status))
        called = {node.func.id for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}

        assert "render_version_footer" in called


class TestAReviewerCanTellWhatOpensTheFile:
    """Knowing which release made a project does not say whether an install can
    open it. The store format does, and a newer one raises rather than
    degrading."""

    def test_the_run_manifest_records_the_schema_version(self, tmp_path):
        import json

        from core.manifest import write_run_manifest

        path = write_run_manifest(
            tmp_path, config={}, run_summary={},
            engine_type="transformer", engine_model="all-MiniLM-L6-v2")
        recorded = json.loads(Path(path).read_text(encoding="utf-8"))

        assert recorded["schema_version"] == SCHEMA_VERSION
        assert recorded["package_version"] == PACKAGE_VERSION

    def test_the_methods_appendix_records_the_schema_version(self, tmp_path):
        from core.project import Project
        from exports.methods_appendix import methods_facts

        store = tmp_path / "p.qnw"
        Project.create(store).close()
        with Project.open(store) as project:
            facts = methods_facts(project)

        assert facts["schema_version"] == SCHEMA_VERSION
        assert facts["package_version"] == PACKAGE_VERSION

    def test_the_appendix_prints_both_numbers(self, tmp_path):
        """The stamp a reviewer actually reads. Both numbers have to reach the
        page, not just the facts dict."""
        from docx import Document

        from core.project import Project
        from exports.methods_appendix import build_methods_appendix

        store = tmp_path / "p.qnw"
        Project.create(store).close()
        out = build_methods_appendix(store, tmp_path / "methods.docx")

        text = " ".join(p.text for p in Document(str(out)).paragraphs)
        assert PACKAGE_VERSION in text
        assert f"v{SCHEMA_VERSION}" in text
