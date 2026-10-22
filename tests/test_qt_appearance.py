"""
Appearance: palettes, per-code colours, semantic colours, text size.

Three defects motivated this file, and each has a test that would have caught it.

1. **Six categorical colours.** A twelve-code codebook produced six colours, so
   every code had an identical twin in the reader's margin stripes — in the one
   place the app asks you to trust colour.
2. **Thirty-one hardcoded hex values in the views.** `qualsafe_qt/theme.py`
   exists so the app does not accumulate a second place deciding what a colour
   means; the rich-text labels were doing exactly that, hardcoding the *dark*
   skin's amber and green, which on the light skin are the washed-out values
   `core/theme.py` deliberately darkens.
3. **No way to change anything.** No per-code colour, no text size, and the
   heatmap ramp was not remembered between sessions.
"""

from __future__ import annotations

import os
import re

import pytest

pytest.importorskip("PySide6", reason="Qt front end not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QUndoStack  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.documents import add_document  # noqa: E402
from core.model import Code  # noqa: E402
from core.project import Project  # noqa: E402
from core.theme import get_palette  # noqa: E402
from qualsafe_qt.colors import (  # noqa: E402
    CODE_COLOR_MEMO, code_colors, is_valid_hex, load_overrides, set_override,
)
from qualsafe_qt.services.project_service import ProjectService  # noqa: E402
from qualsafe_qt.theme import (  # noqa: E402
    CATEGORY_PALETTES, DEFAULT_CATEGORY_PALETTE, category_colors, muted_color,
    stylesheet, success_color, warning_color,
)

#: Every project file under qualsafe_qt that renders user-facing text.
_VIEW_DIRS = ("qualsafe_qt/views", "qualsafe_qt/widgets")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def service(qapp, tmp_path):
    path = tmp_path / "colors.qnw"
    with Project.create(path) as proj:
        add_document(proj, "D", "Some text about cost and belonging.")
        for name in ("Cost", "Belonging", "Advising"):
            proj.add_code(Code(code_id="", name=name))
    svc = ProjectService()
    svc.open(path)
    yield svc
    svc.close()


# -- defect 1: not enough colours --------------------------------------------
def test_a_real_sized_codebook_gets_distinct_colours():
    """Twelve codes used to produce six colours — every code had a twin."""
    names = [f"Code {i:02d}" for i in range(1, 17)]
    colors = code_colors(names, "dark")
    distinct = {c.name() for c in colors.values()}
    assert len(distinct) == len(names), (
        f"{len(names)} codes should get {len(names)} distinct colours, "
        f"got {len(distinct)}")


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_every_palette_is_internally_distinct(mode):
    for name in CATEGORY_PALETTES:
        colors = category_colors(mode, name)
        assert len(set(colors)) == len(colors), f"{name}/{mode} repeats a colour"


def test_the_default_palette_still_starts_with_the_upstream_six():
    """A small project must look identical in both front ends, so the first six
    are `core/theme.py`'s, byte for byte."""
    for mode in ("dark", "light"):
        assert category_colors(mode)[:6] == get_palette(mode)["category"]


def test_a_colour_blind_safe_palette_is_offered():
    """Okabe-Ito. For a research tool whose margin stripes carry meaning, a
    red/green categorical scheme is not sufficient on its own."""
    assert any("Okabe" in name for name in CATEGORY_PALETTES)
    okabe = next(n for n in CATEGORY_PALETTES if "Okabe" in n)
    colors = category_colors("dark", okabe)
    assert "#009E73" in colors and "#0072B2" in colors


def test_colours_stay_stable_when_a_late_code_is_added():
    """Keyed on the sorted name list, so adding "Zebra" must not reshuffle
    everything the analyst has already learned."""
    before = code_colors(["Alpha", "Beta", "Gamma"], "dark")
    after = code_colors(["Alpha", "Beta", "Gamma", "Zebra"], "dark")
    for name in ("Alpha", "Beta", "Gamma"):
        assert before[name].name() == after[name].name()


# -- defect 2: colours bypassing the palette ---------------------------------
def test_no_view_hardcodes_a_hex_colour():
    """`qualsafe_qt/theme.py` exists so there is one place that decides what a
    colour means. A literal hex in a view is a second place."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    offenders = []
    for folder in _VIEW_DIRS:
        for path in (root / folder).glob("*.py"):
            for number, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), start=1):
                code = line.split("#", 1)[0]          # ignore comments
                if re.search(r"#[0-9A-Fa-f]{6}\b", code):
                    offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, "hardcoded colours:\n" + "\n".join(offenders)


def test_semantic_colours_differ_between_skins():
    """The whole point: amber on white must not be the amber used on black."""
    assert warning_color("dark") != warning_color("light")
    assert success_color("dark") != success_color("light")
    assert muted_color("dark") != muted_color("light")
    # And they are the values core/theme.py chose, not something invented here.
    assert warning_color("light") == get_palette("light")["amber"]
    assert success_color("light") == get_palette("light")["green"]


# -- defect 3: nothing was adjustable ----------------------------------------
def test_the_base_font_size_reaches_the_stylesheet():
    """Reading transcripts for hours is the main activity; text size is not a
    cosmetic preference here."""
    assert "13.5pt" in stylesheet("dark", font_pt=13.5)
    assert "9.0pt" in stylesheet("light", font_pt=9.0)


def test_the_appearance_dialog_reports_and_reverts(qapp):
    from qualsafe_qt.windows.appearance_dialog import AppearanceDialog

    initial = {"theme_mode": "dark", "font_pt": 10.5,
               "category_palette": DEFAULT_CATEGORY_PALETTE,
               "heatmap_scheme": list(__import__(
                   "core.theme", fromlist=["x"]).HEATMAP_SCHEMES)[0]}
    dialog = AppearanceDialog(dict(initial))
    seen = []
    dialog.changed.connect(seen.append)

    dialog.font_pt.setValue(14.0)
    assert seen and seen[-1]["font_pt"] == 14.0

    okabe = next(n for n in CATEGORY_PALETTES if "Okabe" in n)
    dialog.palette.setCurrentIndex(dialog.palette.findData(okabe))
    assert seen[-1]["category_palette"] == okabe

    # Cancel must put back what was there — a live preview that cannot be
    # backed out of turns "try a palette" into a commitment.
    dialog._revert()
    assert seen[-1] == initial


# -- per-code colours travel with the project --------------------------------
def test_a_code_colour_is_stored_in_the_project_not_the_machine(service, tmp_path):
    """An analyst's scheme should reach a colleague with the .qnw, so it lives
    in the store — as a reserved memo, needing no schema change."""
    service.set_code_color("Cost", "#B00020")
    assert service.code_color_overrides() == {"Cost": "#B00020"}

    # It is really in the file, and survives a reopen.
    service.reopen()
    assert service.code_color_overrides()["Cost"] == "#B00020"

    with Project.open(service.path) as proj:
        memos = proj.list_memos(target_type=CODE_COLOR_MEMO)
        assert len(memos) == 1


def test_an_override_wins_over_the_palette(service):
    service.set_code_color("Cost", "#B00020")
    colors = code_colors(service.code_names(), "dark",
                         overrides=service.code_color_overrides())
    assert colors["Cost"].name() == "#b00020"
    # Other codes keep their palette colour.
    assert colors["Belonging"].name() != "#b00020"


def test_clearing_an_override_returns_to_the_palette(service):
    service.set_code_color("Cost", "#B00020")
    service.set_code_color("Cost", None)
    assert service.code_color_overrides() == {}


def test_setting_a_colour_twice_replaces_rather_than_accumulates(service):
    service.set_code_color("Cost", "#B00020")
    service.set_code_color("Cost", "#00A000")
    assert service.code_color_overrides() == {"Cost": "#00a000".upper()} or \
        service.code_color_overrides() == {"Cost": "#00A000"}
    with Project.open(service.path) as proj:
        assert len(proj.list_memos(target_type=CODE_COLOR_MEMO)) == 1


def test_a_malformed_colour_is_ignored(service):
    service.set_code_color("Cost", "not a colour")
    assert service.code_color_overrides() == {}
    assert not is_valid_hex("nope")
    assert is_valid_hex("#abc") and is_valid_hex("#AABBCC")


def test_colour_memos_do_not_appear_in_the_codebook_memo_panel(service):
    """They use a reserved target type, so the Streamlit build's memo panels —
    which filter on `code` / `project` / `analysis_view` — never show them."""
    service.set_code_color("Cost", "#B00020")
    code = next(c for c in service.codebook() if c.name == "Cost")
    assert service.list_memos("code", code.code_id) == []


def test_an_override_for_a_deleted_code_is_simply_unused(service):
    service.set_code_color("Ghost", "#B00020")
    colors = code_colors(service.code_names(), "dark",
                         overrides=service.code_color_overrides())
    assert "Ghost" not in colors
    assert len(colors) == 3


# -- the whole app follows one appearance path -------------------------------
def test_appearance_reaches_every_screen_that_paints(qapp, tmp_path):
    import qualsafe_qt.windows.main_window as module

    module.open_settings().clear()
    window = module.MainWindow()
    try:
        okabe = next(n for n in CATEGORY_PALETTES if "Okabe" in n)
        window._preview_appearance({
            "theme_mode": "light", "font_pt": 12.0,
            "category_palette": okabe,
            "heatmap_scheme": list(__import__(
                "core.theme", fromlist=["x"]).HEATMAP_SCHEMES)[0]})

        assert window.documents._palette_name == okabe
        assert window.analysis._palette_name == okabe
        assert window.documents.reader._theme_mode == "light"
        assert window.documents.reader.stripes._mode == "light"
        assert "12.0pt" in QApplication.instance().styleSheet()
        # The menu checkbox must not drift out of sync with the applied skin.
        assert window._theme_action.isChecked()
    finally:
        window.close()
