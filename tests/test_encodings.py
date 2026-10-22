"""
Reading a CSV that Excel wrote (`RELEASE_READINESS.md` §1.1, "messy encodings").

`RELEASE_READINESS.md` lists *"no real research project has been carried
through"* as a blocker and gives three examples of what a real project has that
sample data does not: **messy encodings**, a participant who withdraws, and a
codebook reorganised halfway. The second and third were already tested. The
first was not, and it turned out not to need a real project at all — it needed
one file.

`pd.read_csv(path)` assumes UTF-8. Excel on Windows writes **cp1252** unless the
user picks the *"CSV UTF-8"* menu item rather than the plain *"CSV"* one, and
almost nobody does. The moment a response contains a curly apostrophe — which
free-text answers are full of, because Word and Excel insert them automatically
— reading raises `UnicodeDecodeError` on the first screen.

That was the most likely single reason a first real user would bounce off this
program, and it was filed behind a blocker that reads as though it needs a
research project to reach.

**The fallback must report itself.** `latin-1` cannot raise: every byte decodes
to something. So a wrong guess does not crash, it produces a corpus where every
apostrophe is `â€™` — which nobody notices until it is quoted in a paper.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.encodings import ENCODINGS, LAST_RESORT, TextRead, read_csv, read_json

#: A curly apostrophe, an em-dash and an accent — the three characters that make
#: an Excel CSV unreadable, and all three routine in survey prose.
AWKWARD = "The advisor said it’s fine — I disagreed. Café hours were short."

ROWS = f'response_id,response_text\n1,"{AWKWARD}"\n2,"Nothing to report"\n'


def written(tmp_path, encoding, name="survey.csv", text=ROWS):
    path = tmp_path / name
    path.write_text(text, encoding=encoding)
    return path


class TestTheFileExcelActuallyWrites:

    def test_plain_utf8_reads_cleanly(self, tmp_path):
        found = read_csv(written(tmp_path, "utf-8"))

        assert found.encoding == "utf-8"
        assert not found.is_fallback
        assert found.note() == ""

    def test_csv_utf8_from_excel_reads_cleanly(self, tmp_path):
        """Excel's "CSV UTF-8" adds a BOM. pandas strips it, so the first column
        is not `\\ufeffresponse_id` — verified rather than assumed, because the
        symptom of getting this wrong is a KeyError on the id column."""
        found = read_csv(written(tmp_path, "utf-8-sig"))

        assert list(found.frame.columns)[0] == "response_id"
        assert found.encoding == "utf-8"

    def test_plain_csv_from_excel_no_longer_raises(self, tmp_path):
        """The defect. Before the fallback this was UnicodeDecodeError on
        byte 0x92 — a curly apostrophe."""
        found = read_csv(written(tmp_path, "cp1252"))

        assert found.encoding == "cp1252"
        assert len(found.frame) == 2

    def test_the_text_survives_the_fallback_intact(self, tmp_path):
        """Loading is not enough: the characters have to be right."""
        found = read_csv(written(tmp_path, "cp1252"))

        text = found.frame.loc[0, "response_text"]
        assert "’" in text, "the curly apostrophe was mangled"
        assert "—" in text, "the em-dash was mangled"
        assert "Café" in text, "the accent was mangled"

    def test_a_raw_pandas_read_still_fails_on_that_file(self, tmp_path):
        """Pins the premise. If pandas ever starts handling this itself, this
        test failing is how we find out, rather than the fallback quietly
        becoming dead code."""
        path = written(tmp_path, "cp1252")

        with pytest.raises(UnicodeDecodeError):
            pd.read_csv(path)


class TestTheFallbackReportsItself:
    """A wrong guess does not crash. That is what makes silence dangerous."""

    def test_a_clean_utf8_read_says_nothing(self, tmp_path):
        assert read_csv(written(tmp_path, "utf-8")).note() == ""

    def test_a_cp1252_read_explains_itself_and_names_the_fix(self, tmp_path):
        note = read_csv(written(tmp_path, "cp1252")).note()

        assert "cp1252" in note
        assert "CSV UTF-8" in note

    def test_the_last_resort_is_reported_as_a_guess_not_a_success(self):
        """`latin-1` decodes every byte, so reaching it proves nothing."""
        guessed = TextRead(frame=pd.DataFrame(), encoding=LAST_RESORT,
                           rejected=["utf-8", "cp1252"])

        assert guessed.is_guess
        note = guessed.note()
        assert "never fails and therefore proves nothing" in note
        assert "â€™" in note, "the note should show what mojibake looks like"

    def test_what_was_rejected_is_recorded(self, tmp_path):
        found = read_csv(written(tmp_path, "cp1252"))

        assert found.rejected == ["utf-8"]

    def test_the_order_is_utf8_first(self):
        """UTF-8 must be tried first or a valid UTF-8 file could be read as
        cp1252, which never raises and silently mangles it."""
        assert ENCODINGS[0] == "utf-8"
        assert ENCODINGS[-1] == LAST_RESORT


class TestJson:

    def test_json_gets_the_same_fallback(self, tmp_path):
        path = tmp_path / "data.json"
        path.write_text(f'[{{"response_text": "{AWKWARD}"}}]', encoding="cp1252")

        found = read_json(path)

        assert "’" in found.frame.loc[0, "response_text"]


class TestItReachesTheLoadersThatMatter:

    def test_the_engine_loader_uses_it(self, tmp_path):
        """`core.run_config.load_table` — used by the desktop pipeline screen.

        The first version of this docstring said this was "what the pipeline
        reads through". That was **false**, and the test passed anyway: the CLI
        pipeline has its own loader in `analyze_survey.py`, and it still raised
        `UnicodeDecodeError` while this test was green. Running the pipeline
        against an Excel-written file is what found it.
        """
        from core.run_config import load_table

        frame = load_table(written(tmp_path, "cp1252"))

        assert len(frame) == 2
        assert "’" in frame.loc[0, "response_text"]

    def test_the_cli_pipeline_loader_uses_it_too(self, tmp_path):
        """`analyze_survey.read_input_table` — what `--config` runs through.

        The loader that actually failed. A fix applied to two other readers
        looked complete, and running the pipeline against an Excel-written file
        is what showed it was not.
        """
        from analyze_survey import read_input_table

        path = written(tmp_path, "cp1252")
        frame = read_input_table(
            {"input": {"file_path": str(path), "encoding": "utf-8"}})

        assert len(frame) == 2
        assert "’" in frame.loc[0, "response_text"]

    def test_an_uploaded_csv_gets_the_fallback(self, tmp_path):
        """The primary web import path, and a buffer rather than a path — which
        is why a path-based helper could not serve it."""
        import io

        from app.shared.io import load_uploaded_file_with_note

        class Upload(io.BytesIO):
            name = "from_excel.csv"

        upload = Upload(written(tmp_path, "cp1252").read_bytes())
        frame, note = load_uploaded_file_with_note(upload)

        assert len(frame) == 2
        assert "’" in frame.loc[0, "response_text"]
        assert "cp1252" in note

    def test_the_labelling_sample_gets_it(self, tmp_path):
        """The one file the analyst is *asked* to open in Excel and save back.

        They type labels into it; Excel re-encodes it as cp1252; reading it as
        UTF-8 then fails on a response they were labelling.
        """
        source = (Path(__file__).resolve().parents[1]
                  / "iterative_supervised_thematic.py").read_text(encoding="utf-8")

        assert "read_csv_with_fallback(" in source

    def test_an_explicitly_configured_encoding_is_tried_first(self, tmp_path):
        from core.encodings import candidate_encodings

        assert candidate_encodings("cp1252")[0] == "cp1252"
        assert candidate_encodings(None)[0] == "utf-8"

    def test_a_configured_encoding_is_not_duplicated_in_the_candidates(self):
        from core.encodings import candidate_encodings

        assert candidate_encodings("utf-8").count("utf-8") == 1

    #: Files that may call `pd.read_csv` directly, and why. Every one of these
    #: reads an artifact **this program wrote**, always as UTF-8, so a fallback
    #: would add a code path that can never run. Anything not listed here reads
    #: a file a person supplied and must go through `core.encodings`.
    #:
    #: Being wrong about that is a real defect, not a style point: this list
    #: once said `core/populate.py` read "the coding sample this program wrote".
    #: It read the *second coder's* sample, which the UI tells a colleague to
    #: edit in Excel -- and it also let pandas type the ids, so "000123" became
    #: 123 (review finding F3). Such files now use `read_csv_as_text`.
    #:
    #: The allow-list exists because the first version of this test asserted
    #: "nobody calls pd.read_csv" and found nineteen callers — which is not a
    #: defect, it is a distinction the test had not made.
    MAY_READ_DIRECTLY = {
        "core/sample_project.py": "the shipped sample, which is UTF-8",
        "app/analysis_page.py": "responses_scored.csv, written by the pipeline",
        "app/results.py": "pipeline outputs",
        "app/run_analysis.py": "pipeline outputs",
        "app/home_page.py": "the shipped synthetic sample, which is UTF-8",
        "app/labeling_lab.py": "pipeline outputs and the embedded subset",
        "app/data_setup.py": "the shipped synthetic sample, which is UTF-8",
        "iterative_supervised_thematic.py": "prior-round artifacts it wrote",
    }

    def test_every_reader_of_a_user_file_goes_through_the_fallback(self):
        """The check that would have caught this in one step.

        A fix reached two readers and looked complete; the pipeline used a
        third. Rather than trusting the list is now finished, this asserts that
        any *new* `pd.read_csv` is either in a file that reads our own output or
        is a deliberate decision someone had to record here.
        """
        import ast

        root = Path(__file__).resolve().parents[1]
        unexpected = []
        for source in (list(root.glob("*.py")) + list(root.glob("core/**/*.py"))
                       + list(root.glob("app/**/*.py"))
                       + list(root.glob("analysis/*.py"))
                       + list(root.glob("exports/*.py"))
                       + list(root.glob("interview/*.py"))
                       + list(root.glob("qualsafe_qt/**/*.py"))):
            relative = source.relative_to(root).as_posix()
            if source.name == "encodings.py" or relative in self.MAY_READ_DIRECTLY:
                continue
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "read_csv"
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "pd"):
                    unexpected.append(f"{relative}:{node.lineno}")

        assert not unexpected, (
            "these call pd.read_csv directly and will raise on a CSV written by "
            "Excel. Either route them through core.encodings, or add the file "
            f"to MAY_READ_DIRECTLY with the reason: {unexpected}")

    def test_the_allow_list_has_a_reason_for_every_entry(self):
        """An allow-list without reasons becomes a list of things nobody
        remembers deciding."""
        assert all(reason.strip() for reason in self.MAY_READ_DIRECTLY.values())

    def test_the_allow_list_has_no_stale_entries(self):
        """A file listed here that no longer calls pd.read_csv is a permission
        outliving its reason."""
        import ast

        root = Path(__file__).resolve().parents[1]
        stale = []
        for relative in self.MAY_READ_DIRECTLY:
            source = root / relative
            if not source.exists():
                stale.append(relative)
                continue
            tree = ast.parse(source.read_text(encoding="utf-8"))
            calls = [n for n in ast.walk(tree)
                     if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Attribute)
                     and n.func.attr == "read_csv"]
            if not calls:
                stale.append(relative)

        assert not stale, f"listed but no longer reading directly: {stale}"

    def test_the_app_loader_uses_it(self, tmp_path):
        from app.shared.io import load_file_from_path

        frame = load_file_from_path(written(tmp_path, "cp1252"))

        assert len(frame) == 2

    def test_the_app_loader_can_return_the_note(self, tmp_path):
        from app.shared.io import read_with_encoding_note

        _frame, note = read_with_encoding_note(written(tmp_path, "cp1252"))

        assert "cp1252" in note

    def test_a_utf8_file_produces_no_note_through_the_app(self, tmp_path):
        from app.shared.io import read_with_encoding_note

        _frame, note = read_with_encoding_note(written(tmp_path, "utf-8"))

        assert note == ""

    def test_load_table_still_returns_a_plain_frame(self):
        """Most callers only want the frame, and their signature must not
        change just because one caller wants the note."""
        import inspect

        from core.run_config import load_table

        assert "DataFrame" in str(inspect.signature(load_table).return_annotation)

    def test_the_note_is_available_to_callers_that_show_files_to_people(self, tmp_path):
        from core.run_config import load_table_with_note

        _frame, note = load_table_with_note(written(tmp_path, "cp1252"))

        assert "cp1252" in note

    def test_a_utf8_file_produces_no_note_from_the_engine_loader(self, tmp_path):
        from core.run_config import load_table_with_note

        _frame, note = load_table_with_note(written(tmp_path, "utf-8"))

        assert note == ""

    def test_the_desktop_shows_the_note_too(self):
        """Both builds qualify a file the same way. The web app warned and the
        desktop app did not, which is the same silent-mojibake risk the note
        exists to prevent — just on the build most likely to be installed."""
        source = (Path(__file__).resolve().parents[1] / "qualsafe_qt" / "views"
                  / "pipeline_view.py").read_text(encoding="utf-8")

        assert "load_table_with_note" in source
        assert "encoding_note" in source

    def test_the_import_screen_shows_the_note(self):
        """A note nobody sees is the same as no note."""
        source = (Path(__file__).resolve().parents[1] / "app"
                  / "data_setup.py").read_text(encoding="utf-8")

        assert "read_with_encoding_note" in source
        assert "st.warning(encoding_note)" in source


class TestItDoesNotSwallowRealErrors:

    def test_a_missing_file_still_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_csv(tmp_path / "absent.csv")

    def test_a_binary_file_is_refused_rather_than_loaded_as_garbage(self, tmp_path):
        """A consequence of the fallback, not an accident of it.

        `latin-1` decodes every byte, so without a guard a `.csv` that is really
        a PNG or a truncated download parses as a one-cell table of control
        characters, and the analyst sees an empty-looking dataset with no error.
        Measured before the guard existed: a four-byte binary file loaded
        happily as a single row.

        `pytest.raises(Exception)` was the first version of this and passed the
        moment anything at all went wrong, which is barely an assertion.
        """
        from core.encodings import NUL, NotATextFileError

        path = tmp_path / "broken.csv"
        path.write_bytes(NUL + bytes([1, 2, 3]))

        with pytest.raises(NotATextFileError, match="NUL bytes"):
            read_csv(path)

    def test_the_refusal_guesses_what_the_file_probably_is(self, tmp_path):
        """A `.csv` that is really a workbook is the common case, and saying so
        is more use than reporting a decoding failure."""
        from core.encodings import NUL, NotATextFileError

        path = tmp_path / "actually_excel.csv"
        path.write_bytes(b"PK" + NUL + b"rubbish" * 40)

        with pytest.raises(NotATextFileError, match="Excel workbook"):
            read_csv(path)

    def test_a_real_csv_is_not_mistaken_for_binary(self, tmp_path):
        """The guard must not reject the files it exists to protect."""
        for encoding in ("utf-8", "utf-8-sig", "cp1252"):
            found = read_csv(written(tmp_path, encoding, name=encoding + ".csv"))
            assert len(found.frame) == 2

    def test_no_source_file_here_contains_a_literal_nul(self):
        """Python refuses to import a module containing one.

        Writing this guard through a shell heredoc turned an escaped byte into a
        literal NUL inside `core/encodings.py`, which stopped the entire test
        session collecting — not just this file. `NUL = bytes([0])` exists so
        the byte is never written as a literal again.
        """
        root = Path(__file__).resolve().parents[1]
        for source in list(root.glob("core/*.py")) + list(root.glob("tests/*.py")):
            assert bytes([0]) not in source.read_bytes(), source
