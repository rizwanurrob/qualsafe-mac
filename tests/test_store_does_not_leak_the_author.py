"""
What a shared `.qnw` says about the machine that wrote it.

The Streamlit checkbox calls it "a portable project file you can reopen or
share". The desktop offers it the same way. So the question is what a recipient
gets that the sender did not mean to send.

Every imported document recorded the **absolute path** it came from. A real one
is not neutral:

    C:/Users/jsmith/OneDrive - State University/IRB-2026-0142/
    Participant Interviews/P07_Maria_Gonzalez_transcript.docx

Measured by searching the bytes of a store built that way: the author's
username, their institution's OneDrive tenant, the IRB protocol number and a
participant's name were all present in the file. In the artifact a
FERPA/IRB-safe tool holds out for sharing.

**The privacy gate could not have caught it.** `privacy.scan.scan_frame` takes a
DataFrame — it scans what goes *in*. Nothing scanned what goes out, and the
store's metadata is not data any user typed.

Nothing ever read the value back either. It was written by `add_document`,
asserted by one test, and consumed by no code anywhere, so the leak bought
nothing at all.

What is kept, and why
---------------------
The file's **name** stays; the directories go. Provenance is a fair question and
the name is already visible — `import_documents` makes the document's title out
of it. So a filename containing a participant's name is still in the store,
**as the title the analyst chose**, and these tests say so rather than implying
a leak was closed that was not. Silently renaming somebody's documents would
break their ability to match a document to their own records, which is a worse
failure than the one being fixed.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.documents import add_document, source_filename  # noqa: E402
from core.project import SCHEMA_VERSION, Project  # noqa: E402

LEAK = (r"C:\Users\jsmith\OneDrive - State University\IRB-2026-0142"
        r"\Participant Interviews\P07_Maria_Gonzalez_transcript.docx")
PRIVATE = ("jsmith", "OneDrive - State University", "IRB-2026-0142",
           "Participant Interviews")


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "shared.qnw"
    Project.create(path).close()
    return path


class TestTheNameSurvivesAndTheDirectoriesDoNot:

    @pytest.mark.parametrize("given, expected", [
        (LEAK, "P07_Maria_Gonzalez_transcript.docx"),
        ("/home/jsmith/irb-2026/P07.txt", "P07.txt"),
        ("P07.docx", "P07.docx"),
        ("", ""),
        (None, ""),
    ])
    def test_it_keeps_only_the_filename(self, given, expected):
        assert source_filename(given) == expected

    def test_a_windows_path_is_split_even_off_windows(self):
        """The scenario is a store moving between machines, so the separator in
        the stored string need not be the running platform's. `PurePosixPath`
        does not treat a backslash as a separator and would hand back the whole
        leaking path."""
        assert source_filename(r"C:\a\b\c.txt") == "c.txt"

    def test_mixed_separators_still_reduce(self):
        assert source_filename("C:/a\\b/c.txt") == "c.txt"


class TestANewStoreDoesNotCarryTheAuthorsFilesystem:

    def test_the_private_parts_are_not_in_the_bytes(self, store):
        with Project.open(store) as project:
            add_document(project, "P07", "I felt lost.", source_path=LEAK)

        raw = store.read_bytes()

        assert [p for p in PRIVATE if p.encode() in raw] == []

    def test_the_filename_is_still_recorded(self, store):
        with Project.open(store) as project:
            add_document(project, "P07", "I felt lost.", source_path=LEAK)
            found = project.list_sources()[0]

        assert found.metadata["source_path"] == "P07_Maria_Gonzalez_transcript.docx"

    def test_the_document_text_is_untouched(self, store):
        """The fix must shorten a path, not touch anybody's data."""
        with Project.open(store) as project:
            add_document(project, "P07", "I felt lost.", source_path=LEAK)

            assert project.list_sources()[0].raw_text == "I felt lost."


class TestAnExistingStoreIsCleanedWhenOpened:
    """Stores written before this are the ones most likely to be shared, since
    they are the ones that exist."""

    @staticmethod
    def _legacy(store: Path) -> str:
        """A v5 store holding an absolute path, as one written before v4.11."""
        with Project.open(store) as project:
            source_id = add_document(project, "P07", "I felt lost.",
                                     source_path="placeholder.docx")
        with sqlite3.connect(str(store)) as conn:
            row = conn.execute(
                "SELECT metadata_json FROM sources WHERE source_id=?",
                (source_id,)).fetchone()
            metadata = json.loads(row[0])
            metadata["source_path"] = LEAK
            conn.execute("UPDATE sources SET metadata_json=? WHERE source_id=?",
                         (json.dumps(metadata), source_id))
            conn.execute("UPDATE meta SET value='5' WHERE key='schema_version'")
            conn.commit()
        return source_id

    def test_opening_it_shortens_the_path(self, store):
        source_id = self._legacy(store)

        with Project.open(store) as project:
            found = [s for s in project.list_sources() if s.source_id == source_id][0]

        assert found.metadata["source_path"] == "P07_Maria_Gonzalez_transcript.docx"

    def test_opening_it_removes_the_private_parts_from_the_file(self, store):
        """Not merely from the value read back. SQLite marks a rewritten row's
        old page free and leaves it legible, so the migration is followed by a
        VACUUM -- the same lesson `core/erasure.py` measured for deletion."""
        self._legacy(store)

        with Project.open(store):
            pass

        raw = store.read_bytes()
        assert [p for p in PRIVATE if p.encode() in raw] == []

    def test_the_store_records_that_it_has_been_through_it(self, store):
        """The store ends up at the CURRENT schema version, not literally 6.

        Same relative form as `test_schema_v4.py`'s own
        `assert version == SCHEMA_VERSION >= 4`, for the same reason: the
        invariant is "opening ran every migration up to the version this code
        understands", not "the number is 6 forever" -- a later, correct schema
        bump (v7 arrived the same day this was found, via schema
        v7/coding_decisions) would otherwise fail a test that agrees with it.
        """
        self._legacy(store)

        with Project.open(store):
            pass

        with sqlite3.connect(str(store)) as conn:
            version = conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]

        assert int(version) == SCHEMA_VERSION >= 6

    def test_a_store_with_no_documents_migrates_without_complaint(self, store):
        with sqlite3.connect(str(store)) as conn:
            conn.execute("UPDATE meta SET value='5' WHERE key='schema_version'")
            conn.commit()

        with Project.open(store) as project:
            assert project.list_sources() == []

    def test_a_relative_path_is_left_alone(self, store):
        """Nothing to strip, and rewriting it would be churn."""
        with Project.open(store) as project:
            source_id = add_document(project, "P07", "text",
                                     source_path="notes.docx")
        with sqlite3.connect(str(store)) as conn:
            conn.execute("UPDATE meta SET value='5' WHERE key='schema_version'")
            conn.commit()

        with Project.open(store) as project:
            found = [s for s in project.list_sources() if s.source_id == source_id][0]

        assert found.metadata["source_path"] == "notes.docx"


class TestWhatIsDeliberatelyStillThere:
    """Stated, not glossed. A fix that is described as removing more than it
    removes is worse than one honestly bounded."""

    def test_a_participant_name_inside_a_filename_survives(self, store):
        """Because the analyst chose that filename and the program shows it to
        them as the document's title. Silently renaming their documents would
        break matching a document to their own records."""
        with Project.open(store) as project:
            add_document(project, "P07_Maria_Gonzalez_transcript",
                         "I felt lost.", source_path=LEAK)

        assert b"Maria_Gonzalez" in store.read_bytes()

    def test_the_title_is_where_it_comes_from(self, store):
        """So this is a research-practice matter to surface, not a string to
        rewrite behind somebody's back."""
        with Project.open(store) as project:
            add_document(project, "P07_Maria_Gonzalez_transcript", "text")
            found = project.list_sources()[0]

        assert found.metadata["title"] == "P07_Maria_Gonzalez_transcript"


class TestTheRunManifestDoesNotCarryItEither:
    """The same question, one artifact over, asked because the first answer made
    it obvious: what else leaves this program?

    A run manifest is written into every output folder and travels with it -- to
    a supervisor, a co-author, a submission. It recorded `input.file` as the
    absolute path of the analysed file, so it carried the same username, tenant
    and folder structure the `.qnw` did. Nothing reads the field back; the only
    reference to it anywhere is a comment.
    """

    def test_the_manifest_records_a_name_not_a_path(self, tmp_path):
        from core.manifest import write_run_manifest

        path = write_run_manifest(
            tmp_path,
            config={"input": {"file_path": LEAK},
                    "output": {"output_dir": str(tmp_path)}},
            run_summary={}, engine_type="transformer", engine_model="x")

        recorded = json.loads(Path(path).read_text(encoding="utf-8"))

        assert recorded["input"]["file"] == "P07_Maria_Gonzalez_transcript.docx"

    def test_the_private_parts_are_not_in_the_manifest(self, tmp_path):
        from core.manifest import write_run_manifest

        path = write_run_manifest(
            tmp_path,
            config={"input": {"file_path": LEAK},
                    "output": {"output_dir": str(tmp_path)}},
            run_summary={}, engine_type="transformer", engine_model="x")

        raw = Path(path).read_bytes()

        assert [p for p in PRIVATE if p.encode() in raw] == []

    def test_a_missing_input_path_is_left_as_it_was(self, tmp_path):
        """None must stay None rather than becoming the string 'None'."""
        from core.manifest import write_run_manifest

        path = write_run_manifest(
            tmp_path, config={"output": {"output_dir": str(tmp_path)}},
            run_summary={}, engine_type="transformer", engine_model="x")

        assert json.loads(Path(path).read_text(encoding="utf-8"))["input"]["file"] is None

    def test_provenance_still_answers_which_file(self, tmp_path):
        """The point of the field. The name identifies the file; the directory
        identified the person."""
        from core.manifest import write_run_manifest

        path = write_run_manifest(
            tmp_path,
            config={"input": {"file_path": "/srv/data/wave2_responses.csv"},
                    "output": {"output_dir": str(tmp_path)}},
            run_summary={}, engine_type="transformer", engine_model="x")

        assert json.loads(Path(path).read_text(encoding="utf-8")
                          )["input"]["file"] == "wave2_responses.csv"


class TestTheGapThatLetThisThrough:

    def test_the_privacy_scanner_only_sees_input_data(self):
        """`scan_frame` takes a DataFrame. It cannot see store metadata, which
        is why nothing caught this -- the gate is on the way in, and a `.qnw` is
        the way out."""
        import inspect

        from privacy.scan import scan_frame

        first = list(inspect.signature(scan_frame).parameters)[0]

        assert first == "df"

    def test_nothing_reads_the_stored_path_back(self):
        """The leak bought nothing. If a consumer ever appears, this test should
        fail and the trade re-argued rather than silently changed."""
        import ast

        readers = []
        for path in sorted(ROOT.rglob("*.py")):
            parts = set(path.parts)
            if parts & {".venv", "venv", "build", "dist", "site-packages", "tests"}:
                continue
            if path.name in ("documents.py", "migrations.py"):
                continue          # where it is written and where it is shortened
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and node.value == "source_path":
                    readers.append(path.relative_to(ROOT).as_posix())

        assert readers == [], f"source_path is now read by {sorted(set(readers))}"
