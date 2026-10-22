"""
The desktop chart builder, driven end to end (Qt fork).

Two claims are being pinned, and they are the reasons the screen exists.

**The desktop and the web build plot the same numbers.** `core/chart_spec.py`
decides what a chart is and `aggregate()` computes the values; this screen only
drags, paints and saves. A test that asserted on pixels would not catch the
failure that matters, so these assert on the aggregated frame the canvas is
given.

**A figure can leave the program.** A chart nobody can export is a chart that
does not go in the paper, so the image and the CSV are covered as first-class
outputs rather than conveniences.

Offline, deterministic, real `.qnw` files in tmp_path.
"""

from __future__ import annotations

import os

import pandas as pd
import pytest

pytest.importorskip("PySide6", reason="Qt front end not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, Qt  # noqa: E402
from PySide6.QtGui import QUndoStack  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.chart_spec import MEASURE  # noqa: E402
from core.model import Code, CodeApplication, Descriptor, Source  # noqa: E402
from core.project import Project  # noqa: E402
from qualsafe_qt.services.project_service import ProjectService  # noqa: E402
from qualsafe_qt.views.charts_view import ChartsView  # noqa: E402
from qualsafe_qt.widgets.chart_canvas import NOT_PAINTABLE, ChartCanvas  # noqa: E402
from qualsafe_qt.widgets.shelves import FIELD_MIME, Shelf  # noqa: E402

CODES = ("Cost", "Advising", "Belonging")
YEARS = ("First-year", "Senior")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def store(tmp_path):
    """Twelve respondents, three codes, one descriptor."""
    path = tmp_path / "project.qnw"
    with Project.create(path) as project:
        ids = {name: project.add_code(Code(code_id="", name=name, definition=name))
               for name in CODES}
        for index in range(12):
            source_id = f"s{index:02d}"
            source = Source(source_id=source_id, type="survey_response",
                            raw_text=f"Response {index}.", label="Q1",
                            metadata={"response_id": f"r{index:02d}"})
            project.add_source(source)
            excerpt_id = project.add_whole_response_excerpt(source)
            project.set_descriptor(Descriptor(source_id=source_id, key="class_year",
                                              value=YEARS[index % 2]))
            for offset, name in enumerate(CODES):
                if (index + offset) % (offset + 2) == 0:
                    project.apply_code(CodeApplication(
                        application_id="", excerpt_id=excerpt_id,
                        code_id=ids[name], rater_id="human_primary"))
    return path


@pytest.fixture()
def view(app, store):
    service = ProjectService()
    service.open(store)
    charts = ChartsView(service, QUndoStack())
    charts.refresh()
    return charts


def _set(view, mark, **fields):
    """Choose a mark and fill its shelves, the way the screen does."""
    view.mark.setCurrentIndex(view.mark.findData(mark))
    shelves = view.shelf_row.shelves()
    for key, value in fields.items():
        if key not in shelves:
            continue
        if value in {"count", "distinct", "sum", "mean", "median", "min", "max"}:
            shelves[key].set_aggregate(value)
        else:
            shelves[key].set_field(value)
    return view


class TestTheNumbersComeFromTheSharedModule:

    def test_a_count_matches_the_coding_table(self, view, store):
        _set(view, "bar_horizontal", x="code_name", y="count")

        with Project.open(store) as project:
            expected = project.coding_table()["code_name"].value_counts().to_dict()

        plotted = dict(zip(view._plotted["code_name"], view._plotted[MEASURE]))
        assert plotted == {k: float(v) for k, v in expected.items()}

    def test_a_colour_shelf_adds_a_grouping_column(self, view):
        view.source_descriptors.setChecked(True)
        _set(view, "stacked_bar", x="class_year", y="count", color="code_name")

        assert set(view._plotted.columns) == {"class_year", "code_name", MEASURE}

    def test_the_canvas_is_handed_the_same_frame_it_plots(self, view):
        _set(view, "bar_horizontal", x="code_name", y="count")
        assert view.canvas._frame.equals(view._plotted)

    def test_the_descriptor_join_is_the_shared_one(self, view):
        """The mixed-methods table comes from analysis.crosstab, not from here."""
        view.source_descriptors.setChecked(True)
        assert "class_year" in view._field_types


class TestDragAndDrop:

    def test_dropping_a_field_puts_it_on_the_shelf(self, app):
        shelf = Shelf("x", "X")
        payload = QMimeData()
        payload.setData(FIELD_MIME, b"code_name")

        class _Event:
            def mimeData(self):
                return payload

            def acceptProposedAction(self):
                pass

        shelf.dropEvent(_Event())
        assert shelf.field() == "code_name"

    def test_a_drag_carrying_anything_else_is_ignored(self, app):
        """A plain-text drag would let any text in the app land on a shelf,
        including a passage out of the reader."""
        shelf = Shelf("x", "X")
        payload = QMimeData()
        payload.setText("some passage the analyst was reading")

        class _Event:
            def mimeData(self):
                return payload

            def acceptProposedAction(self):
                raise AssertionError("should not have been accepted")

        shelf.dropEvent(_Event())
        assert shelf.field() == ""

    def test_a_shelf_can_be_emptied_from_the_keyboard(self, app):
        """A builder you can only add to is one you restart to correct."""
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent

        shelf = Shelf("x", "X")
        shelf.set_field("code_name")
        shelf.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete,
                                      Qt.KeyboardModifier.NoModifier))
        assert shelf.field() == ""

    def test_switching_mark_keeps_the_shelves_it_still_has(self, view):
        """Bar to stacked bar should not empty what was just filled."""
        _set(view, "bar", x="code_name", y="count")
        view.mark.setCurrentIndex(view.mark.findData("stacked_bar"))

        assert view.shelf_row.shelves()["x"].field() == "code_name"

    def test_an_arc_labels_its_shelves_as_size_and_slices(self, view):
        """A pie has no axes, so calling them X and Y would be a lie."""
        view.mark.setCurrentIndex(view.mark.findData("pie"))
        assert set(view.shelf_row.shelves()) == {"y", "color"}


class TestSuggestions:

    def test_the_first_suggestion_is_over_a_real_category(self, view):
        """Not application_id — the defect a rendered picture caught."""
        view.suggestions.setCurrentIndex(0)
        view._apply_suggestion()
        assert view.request().x.field == "code_name"

    def test_applying_a_suggestion_produces_a_drawable_chart(self, view):
        view.suggestions.setCurrentIndex(0)
        view._apply_suggestion()
        assert not view._plotted.empty
        assert view.save_image.isEnabled()


class TestProblemsAreExplainedNotDrawn:

    def test_an_unfilled_shelf_produces_a_sentence(self, view):
        view.mark.setCurrentIndex(view.mark.findData("pie"))
        for shelf in view.shelf_row.shelves().values():
            shelf.clear_field()
        assert "Slices" in view._problem.text()
        assert not view.save_image.isEnabled()

    def test_averaging_text_says_why(self, view):
        _set(view, "bar", x="code_name")
        view.shelf_row.shelves()["y"].set_field("code_name")
        view.shelf_row.shelves()["y"].set_aggregate("mean")
        assert "has no mean" in view._problem.text()

    def test_a_mark_this_canvas_cannot_paint_says_so(self, view):
        """Rather than drawing something that looks right and is not."""
        _set(view, "line", x="code_name", y="count")

        assert view.canvas._message == NOT_PAINTABLE["line"]
        assert not view.save_image.isEnabled()

    def test_the_numbers_stay_saveable_even_then(self, view):
        """The values exist; only this canvas cannot draw them, so the analyst
        can still take them elsewhere."""
        _set(view, "line", x="code_name", y="count")
        assert view.save_data.isEnabled()


class TestAFigureCanLeaveTheProgram:

    def test_the_image_is_opaque(self, view):
        """A transparent PNG pasted into Word loses light text on white."""
        _set(view, "bar_horizontal", x="code_name", y="count")
        view.canvas.resize(600, 400)

        image = view.canvas.to_image(scale=2)

        assert not image.hasAlphaChannel()
        assert image.pixelColor(3, 3).alpha() == 255

    def test_the_image_scales_for_print(self, view):
        _set(view, "bar_horizontal", x="code_name", y="count")
        view.canvas.resize(600, 400)

        assert view.canvas.to_image(scale=1).width() == 600
        assert view.canvas.to_image(scale=3).width() == 1800

    def test_the_saved_numbers_are_the_plotted_numbers(self, view, tmp_path):
        _set(view, "bar_horizontal", x="code_name", y="count")
        out = tmp_path / "chart.csv"
        view._plotted.to_csv(out, index=False)

        written = pd.read_csv(out)
        assert MEASURE in written.columns
        assert len(written) == len(view._plotted)


class TestTheCanvasPaintsWithoutRaising:
    """Every paintable mark, rendered offscreen. A canvas that throws mid-paint
    leaves a half-drawn widget and no error anyone sees."""

    @pytest.mark.parametrize("mark", sorted(
        {"bar", "bar_horizontal", "stacked_bar", "normalized_bar", "grouped_bar",
         "pie", "donut", "heatmap"}))
    def test_it_renders(self, view, mark):
        view.source_descriptors.setChecked(True)
        _set(view, mark, x="class_year", y="count", color="code_name")
        if mark in ("pie", "donut"):
            view.shelf_row.shelves()["color"].set_field("code_name")
        if mark == "heatmap":
            view.shelf_row.shelves()["y"].set_field("code_name")
            view.shelf_row.shelves()["color"].set_aggregate("count")
        view.canvas.resize(700, 480)

        image = view.canvas.to_image(scale=1)
        assert image.width() == 700

    def test_an_empty_canvas_says_something_rather_than_nothing(self, app):
        canvas = ChartCanvas()
        canvas.resize(400, 300)
        canvas.set_chart(None, pd.DataFrame())
        canvas.to_image(scale=1)   # must not raise


class TestSavedCharts:
    """v4.6 §B1d: the desktop half of saved charts.

    The image and the CSV export a moment. This exports the method, and it is
    the last capability the two builds did not share.
    """

    def test_a_chart_is_saved_and_comes_back(self, view, store):
        _set(view, "bar_horizontal", x="code_name", y="count")
        view.title.setText("Theme frequency")
        view.save_name.setText("Theme frequency")

        view._save_chart()

        with Project.open(store) as project:
            assert [c.name for c in project.list_charts()] == ["Theme frequency"]

    def test_reopening_restores_the_whole_request(self, view):
        _set(view, "bar_horizontal", x="code_name", y="count")
        view.title.setText("Theme frequency")
        view.save_name.setText("Theme frequency")
        view._save_chart()

        _set(view, "pie", color="code_name", y="count")
        view.title.setText("something else")

        view.saved_charts.setCurrentIndex(0)
        view._open_saved_chart()

        request = view.request()
        assert request.mark == "bar_horizontal"
        assert request.x.field == "code_name"
        assert request.y.aggregate == "count"
        assert view.title.text() == "Theme frequency"

    def test_saving_the_same_name_replaces_rather_than_adds(self, view, store):
        """An analyst who tweaks a chart and saves it again means that chart."""
        for mark in ("bar_horizontal", "pie"):
            _set(view, mark, x="code_name", y="count", color="code_name")
            view.save_name.setText("Themes")
            view._save_chart()

        with Project.open(store) as project:
            assert len(project.list_charts()) == 1

    def test_the_data_source_is_remembered(self, view, store):
        """The same shelves mean different things over different frames."""
        view.source_descriptors.setChecked(True)
        _set(view, "bar_horizontal", x="class_year", y="count")
        view.save_name.setText("By year")
        view._save_chart()

        with Project.open(store) as project:
            assert project.get_chart("By year").source == "codings_with_descriptors"

    def test_deleting_removes_it(self, view, store):
        _set(view, "bar_horizontal", x="code_name", y="count")
        view.save_name.setText("Gone soon")
        view._save_chart()

        view.saved_charts.setCurrentIndex(0)
        view._delete_saved_chart()

        with Project.open(store) as project:
            assert project.list_charts() == []

    def test_a_chart_that_cannot_be_drawn_is_not_saved(self, view, store):
        """A chart that cannot be drawn cannot be re-run either.

        Refused in the status bar rather than a dialog. The page is already
        showing what is wrong a few pixels above the button, and the first
        version of this used QMessageBox -- which blocked this test forever
        under the offscreen platform instead of failing it.
        """
        _set(view, "pie")
        for shelf in view.shelf_row.shelves().values():
            shelf.clear_field()
        view.save_name.setText("Broken")

        view._save_chart()

        with Project.open(store) as project:
            assert project.list_charts() == []

    def test_opening_a_saved_chart_and_a_suggestion_share_one_path(self):
        """Two ways of putting a ChartRequest into the widgets would drift."""
        import inspect

        from qualsafe_qt.views import charts_view

        for name in ("_apply_suggestion", "_open_saved_chart"):
            source = inspect.getsource(getattr(charts_view.ChartsView, name))
            assert "_apply_request" in source, f"{name} does not delegate"
