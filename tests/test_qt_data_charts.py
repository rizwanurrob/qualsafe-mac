"""
The desktop Data Charts screen, driven end to end (Qt fork).

Two claims are pinned. **The desktop and the web page build the same chart**: both
call `core/chartbuilder`, so these assert on the `ChartData` the screen holds and
on the exported picture, not on pixels. **A chart can leave the program**: PNG at
the right size, SVG, PDF, the table as CSV/Excel, and the clipboard.

Offline and deterministic (the built-in sample survey and small tmp files). File
choosers go through `_ask_save_path`, replaced here, because a real dialog blocks
forever under the offscreen platform.
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("PySide6", reason="Qt front end not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QToolButton  # noqa: E402

from core.chartbuilder import export  # noqa: E402
from qualsafe_qt.views.data_charts_view import DataChartsView  # noqa: E402

R1 = "Relationships with friends, family, partners, or roommates"
CHOICES = [R1, "Getting involved or finding community",
           "Managing anxiety, stress, or feeling overwhelmed", "Paying for college",
           "Balancing work and classes"]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def view(app, tmp_path):
    v = DataChartsView(storage_root=tmp_path / "cb")     # never the real user folder
    v.load_sample()
    yield v
    v.deleteLater()


def pick(combo, key):
    index = combo.findData(key)
    assert index >= 0, f"{key!r} not offered; have {[combo.itemData(i) for i in range(combo.count())]}"
    combo.setCurrentIndex(index)


def select(lst, names):
    for i in range(lst.count()):
        lst.item(i).setSelected(lst.item(i).text() in names)


def data(v):
    assert isinstance(v._built, tuple), v._built
    return v._built[0]


def png_size(raw: bytes):
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", raw[16:24])


def choose(v, field):
    pick(v.field_combo, field)
    v.flush()


# ── loading and inspection ───────────────────────────────────────────────────

def test_the_screen_starts_empty_and_is_the_charts_activity_in_the_shell(app, tmp_path):
    v = DataChartsView(storage_root=tmp_path / "cb")
    assert "Open a file" in v.problem_label.text()
    from qualsafe_qt.windows.main_window import MainWindow
    window = MainWindow()
    # Spreadsheet charts are the Charts activity; charts of coded themes are
    # inside Surveys (UX-2: two chart tools no longer share a name or a place).
    window.open_activity("charts")
    assert window.activity.content.indexOf(window.data_charts) >= 0
    window.open_activity("surveys", "explore")
    assert window.activity.content.indexOf(window.charts) >= 0
    assert window.activity.content.indexOf(window.data_charts) < 0
    assert window.data_charts.parent() is not None


def test_sample_shows_rows_columns_types_and_missing_counts(view):
    assert view.summary_label.text() == "240 rows × 12 columns"
    rows = {view.fields_table.item(r, 0).text(): [view.fields_table.item(r, c).data(Qt.DisplayRole)
                                                 for c in range(1, 5)]
            for r in range(view.fields_table.rowCount())}
    assert rows["Age"][0] == "numeric" and rows["Age"][2] > 0          # blanks counted
    assert rows["Class year"][2] == 0 and rows["Class year"][3] == 4
    assert view.fields_table.item(0, 0).text() == "Respondent"


def test_open_a_csv_reads_it_and_leaves_the_file_alone(view, tmp_path):
    path = tmp_path / "survey.csv"
    path.write_bytes("Q,G\nYes,a\nNo,b\nYes,a\n".encode("utf-8"))
    before = path.read_bytes()
    assert view.open_path(str(path))
    assert "survey.csv" in view.file_label.text() and view.summary_label.text().startswith("3 rows")
    choose(view, "Q")
    assert set(data(view).categories) == {"Yes", "No"}
    assert path.read_bytes() == before


def test_open_an_excel_workbook_and_switch_sheets(view, tmp_path):
    path = tmp_path / "w.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as book:
        pd.DataFrame({"A": ["x", "y", "x"]}).to_excel(book, sheet_name="First", index=False)
        pd.DataFrame({"B": ["p", "q"], "C": [1, 2]}).to_excel(book, sheet_name="Second", index=False)
    assert view.open_path(str(path))
    assert not view.sheet_combo.isHidden() and view.sheet_combo.count() == 2
    assert view.summary_label.text().startswith("3 rows")
    pick(view.sheet_combo, "Second")
    assert view.summary_label.text() == "2 rows × 2 columns"
    assert [view.field_combo.itemData(i) for i in range(view.field_combo.count())] == ["", "B", "C"]


def test_an_unreadable_file_is_reported_without_a_dialog(view, tmp_path):
    bad = tmp_path / "x.pdf"
    bad.write_bytes(b"%PDF")
    signals = []
    view.status.connect(signals.append)
    assert not view.open_path(str(bad))
    assert "could not be read" in view.file_label.text() and signals


# ── single question ──────────────────────────────────────────────────────────

def test_choosing_a_field_draws_a_chart_and_fills_the_table(view):
    choose(view, "Class year")
    d = data(view)
    assert set(d.categories) == {"First-year", "Sophomore", "Junior", "Senior"}
    assert view._png[:4] == b"\x89PNG" and view.preview.pixmap() is not None
    assert not view.preview.pixmap().isNull()
    headers = [view.table_widget.horizontalHeaderItem(c).text() for c in range(view.table_widget.columnCount())]
    assert headers == ["Response", "Count", "Percent", "Valid N"]
    assert view.table_widget.rowCount() == 4


def test_count_and_percent_change_the_plotted_value(view):
    choose(view, "Class year")
    assert data(view).table["value"].sum() == pytest.approx(100.0)
    pick(view.agg_combo, "count")
    view.flush()
    assert data(view).table["value"].sum() == pytest.approx(240.0)


def test_split_by_makes_a_grouped_chart_with_per_group_bases(view):
    pick(view.field_combo, "First generation")
    select(view.group_list, ["Class year"])
    view.flush()
    d = data(view)
    assert len(d.groups) == 4 and d.table["valid_n"].nunique() > 1
    assert view.config().chart_type == "grouped_bar"
    headers = [view.table_widget.horizontalHeaderItem(c).text() for c in range(view.table_widget.columnCount())]
    assert "Class year" in headers


def test_a_measure_summary_needs_and_uses_a_numeric_field(view):
    pick(view.field_combo, "Class year")
    pick(view.agg_combo, "mean")
    view.flush()
    assert "value field" in view.problem_label.text()
    pick(view.measure_combo, "Age")
    view.flush()
    assert data(view).value_title == "Mean of Age"
    assert view.problem_label.text() == ""


def test_warnings_are_shown_in_words(view):
    pick(view.field_combo, "Age")
    pick(view.chart_combo, "bar_horizontal")            # ask for categories from a number
    view.flush()
    assert not view.warning_label.isHidden()
    assert "numeric field being charted as categories" in view.warning_label.text()


# ── survey structures ────────────────────────────────────────────────────────

def test_a_matrix_question_reads_in_scale_order_with_top_and_bottom_boxes(view):
    pick(view.kind_combo, "matrix")
    select(view.columns_list, ["I feel like I belong here", "I feel safe on campus"])
    view.flush()
    d = view._built[0]
    assert d.kind == "matrix" and len(d.groups) == 2
    assert d.categories[:5] == ["Strongly disagree", "Somewhat disagree", "Neutral",
                                "Somewhat agree", "Strongly agree"]
    assert view.config().sort == "scale" and view.config().chart_type == "normalized_bar"
    assert view.boxes_table.rowCount() == 8                      # 2 items x 4 boxes
    assert view.tabs.isTabVisible(1)
    labels = {view.boxes_table.item(r, 6).data(Qt.DisplayRole) for r in range(view.boxes_table.rowCount())}
    assert all("/" in str(x) for x in labels)                    # numerator/valid N, never a bare N


def test_leaving_matrix_restores_the_frequency_sort(view):
    pick(view.kind_combo, "matrix")
    assert view.config().sort == "scale"
    pick(view.kind_combo, "single")
    assert view.config().sort == "desc"


def test_select_all_keeps_comma_containing_choices_whole(view):
    pick(view.kind_combo, "multi")
    pick(view.field_combo, "Concerns")
    view.choices_edit.setPlainText("\n".join(CHOICES))
    view.flush()
    d = data(view)
    assert len(d.categories) == 5 and R1 in d.categories
    assert d.value_title.endswith("multiple selections allowed")
    assert d.table["percent"].sum() > 100.0                       # need not sum to 100


def test_suggesting_choices_fills_the_list_from_the_data(view):
    pick(view.kind_combo, "multi")
    pick(view.field_combo, "Concerns")
    view.suggest_choices()
    lines = view.choices_edit.toPlainText().splitlines()
    assert R1 in lines and len(lines) == 5
    assert view.config().multi.mode == "known"


def test_simple_mode_warns_that_a_comma_may_cut_a_choice(view):
    pick(view.kind_combo, "multi")
    pick(view.field_combo, "Concerns")
    pick(view.multi_mode_combo, "simple")
    view.flush()
    assert "cut them into pieces" in view.warning_label.text()


def test_free_text_gives_keywords_the_count_and_a_response_export(view, tmp_path, monkeypatch):
    pick(view.kind_combo, "text")
    pick(view.field_combo, "Comment")
    view.flush()
    d = data(view)
    assert d.kind == "text" and "helpful" in d.categories and d.valid_n < 240
    assert not view.save_responses_button.isHidden()
    out = tmp_path / "responses.csv"
    monkeypatch.setattr(view, "_ask_save_path", lambda default, flt: str(out))
    assert view.save_responses() == str(out)
    saved = pd.read_csv(out, encoding="utf-8-sig")
    assert len(saved) == d.valid_n and list(saved.columns) == ["Row", "Response"]


# ── refine: filters, grid, undo ───────────────────────────────────────────────

def test_a_filter_narrows_the_base_and_undo_redo_step_over_it(view):
    choose(view, "First generation")
    before = data(view).valid_n
    pick(view.filter_col, "Class year")
    pick(view.filter_op, "in")
    view.filter_values.setText("Senior")
    view.add_filter_button.click()
    view.flush()
    narrowed = data(view).valid_n
    assert 0 < narrowed < before and view.filters_list.count() == 1
    view.undo_button.click()
    assert data(view).valid_n == before and view.filters_list.count() == 0
    view.redo_button.click()
    assert data(view).valid_n == narrowed
    view.filters_list.setCurrentRow(0)
    view.remove_filter_button.click()
    view.flush()
    assert data(view).valid_n == before


def test_a_filter_with_no_value_is_refused_in_words(view):
    choose(view, "First generation")
    signals = []
    view.status.connect(signals.append)
    pick(view.filter_col, "Class year")
    view.add_filter_button.click()
    assert signals == ["That filter needs a value."] and view.config().filters == []


def test_undo_steps_back_over_a_sort_but_not_over_the_title(view):
    choose(view, "Class year")
    pick(view.sort_combo, "alpha")
    view.title_edit.setText("My chart")
    view.flush()
    view.undo()
    assert view.config().sort == "desc" and view.config().labels.title == "My chart"
    assert view.title_edit.text() == "My chart"


def test_reset_chart_clears_choices_and_is_undoable(view):
    choose(view, "Class year")
    view.reset_button.click()
    assert view.config().column == "" and "Choose a field" in view.problem_label.text()
    view.undo()
    assert view.config().column == "Class year" and isinstance(view._built, tuple)


def _grid_row(view, category):
    return next(r for r in range(view.grid.rowCount()) if view.grid.item(r, 0).text() == category)


def test_the_category_grid_relabels_combines_excludes_and_orders(view):
    choose(view, "Class year")
    assert view.grid.rowCount() == 4
    view.grid.item(_grid_row(view, "Senior"), 3).setText("Fourth year")           # rename
    view.grid.item(_grid_row(view, "Junior"), 4).setText("Upper")                 # combine
    view.grid.item(_grid_row(view, "Senior"), 4).setText("Upper")
    view.grid.item(_grid_row(view, "Sophomore"), 2).setCheckState(Qt.Unchecked)   # exclude
    view.flush()
    d = data(view)
    assert set(d.categories) == {"First-year", "Upper"}
    rc = view.config().recode
    assert rc.exclude == ["Sophomore"] and rc.merges[0].label == "Upper"
    assert sorted(rc.merges[0].members) == ["Junior", "Senior"]
    view.grid.item(_grid_row(view, "First-year"), 5).setText("2")
    view.grid.item(_grid_row(view, "Junior"), 5).setText("1")
    view.flush()
    assert view.config().sort == "custom" and data(view).categories[0] == "Upper"


def test_a_recode_that_would_merge_labels_silently_is_refused(view):
    choose(view, "Class year")
    view.grid.item(_grid_row(view, "Junior"), 3).setText("Senior")
    view.flush()
    assert "would be the display name of" in view.problem_label.text()


def test_the_grid_is_not_rebuilt_while_you_type_in_it(view):
    choose(view, "Class year")
    view.grid.item(0, 3).setText("Renamed")
    view.flush()
    assert view.grid.item(0, 3).text() == "Renamed"


def test_blank_answers_can_be_shown_as_their_own_category(view):
    choose(view, "Residence")                       # contains the token "NULL"
    hidden = data(view)
    assert "No response" not in hidden.categories and hidden.missing_n > 0
    pick(view.blank_combo, "show")
    view.flush()
    assert "No response" in data(view).categories


def test_a_custom_denominator_changes_the_percentages(view):
    choose(view, "Class year")
    pick(view.denom_combo, "custom")
    view.denom_spin.setValue(1000)
    view.flush()
    row = data(view).table.iloc[0]
    assert row["denominator"] == 1000 and row["percent"] == pytest.approx(100 * row["count"] / 1000)


# ── chart, theme, labels ─────────────────────────────────────────────────────

def test_titles_size_and_theme_reach_the_spec(view):
    choose(view, "Class year")
    view.title_edit.setText("Class year mix")
    pick(view.size_combo, "large")
    pick(view.theme_combo, "Grayscale")
    view.flush()
    spec = view._built[2]
    assert spec["title"]["text"] == "Class year mix" and spec["title"]["color"] == "#111111"
    assert view.config().display.size == "large"
    view.default_button.click()
    assert view.config().theme.name == "QualSafe default"
    assert view._built[2]["title"]["color"] == "#15284B"


def test_a_colour_typed_in_the_grid_beats_the_theme_and_a_bad_one_is_ignored(view):
    choose(view, "Class year")
    view.grid.item(_grid_row(view, "Senior"), 6).setText("#112233")
    view.flush()
    assert view.config().theme.color_overrides == {"Senior": "#112233"}
    signals = []
    view.status.connect(signals.append)
    view.grid.item(_grid_row(view, "Junior"), 6).setText("gold")
    assert view.config().theme.color_overrides == {"Senior": "#112233"}
    assert any("Not a colour" in s for s in signals)


def test_the_suggested_chart_is_starred_and_pie_is_never_forced(view):
    choose(view, "Class year")
    labels = [view.chart_combo.itemText(i) for i in range(view.chart_combo.count())]
    assert labels[0].startswith("Horizontal bar") and "suggested" in labels[0]
    assert view.config().chart_type == "bar_horizontal"


def test_figure_shape_presets_and_custom_size(view):
    choose(view, "Class year")
    assert not view.width_spin.isEnabled()
    pick(view.preset_combo, "Custom")
    assert view.width_spin.isEnabled()
    view.width_spin.setValue(800)
    view.height_spin.setValue(500)
    view.flush()
    assert export.export_pixels(view.config(), 150) == (1250, 781)


# ── export ───────────────────────────────────────────────────────────────────

def _save_to(view, monkeypatch, path):
    monkeypatch.setattr(view, "_ask_save_path", lambda default, flt: str(path))


@pytest.mark.parametrize("dpi,size", [(150, (2000, 1125)), (300, (4000, 2250))])
def test_png_is_saved_at_the_chosen_dpi(view, tmp_path, monkeypatch, dpi, size):
    choose(view, "Class year")
    pick(view.dpi_combo, dpi)
    out = tmp_path / "chart.png"
    _save_to(view, monkeypatch, out)
    assert view.save_picture() == str(out)
    assert png_size(out.read_bytes()) == size


def test_svg_and_pdf_export(view, tmp_path, monkeypatch):
    choose(view, "Class year")
    pick(view.format_combo, "svg")
    out = tmp_path / "chart.svg"
    _save_to(view, monkeypatch, out)
    view.save_picture()
    assert out.read_bytes().lstrip().startswith(b"<svg")
    pick(view.format_combo, "pdf")
    out2 = tmp_path / "chart.pdf"
    _save_to(view, monkeypatch, out2)
    view.save_picture()
    assert out2.read_bytes()[:4] == b"%PDF"


def test_transparent_png_has_an_alpha_channel(view):
    choose(view, "Class year")
    view.transparent_check.setChecked(True)
    view.flush()
    assert view.picture_bytes("png", 96)[25] == 6


def test_copy_picture_puts_an_image_on_the_clipboard(view):
    choose(view, "Class year")
    QGuiApplication.clipboard().clear()
    assert view.copy_picture()
    image = QGuiApplication.clipboard().image()
    assert not image.isNull() and image.width() > 1000


def test_table_saves_as_csv_and_excel_and_copies_as_text(view, tmp_path, monkeypatch):
    choose(view, "Class year")
    view.totals_check.setChecked(True)
    csv_path = tmp_path / "t.csv"
    _save_to(view, monkeypatch, csv_path)
    view.save_table()
    back = pd.read_csv(csv_path, encoding="utf-8-sig")
    assert back["Response"].tolist()[-1] == "Total" and back["Count"].iloc[-1] == 240
    xlsx_path = tmp_path / "t.xlsx"
    _save_to(view, monkeypatch, xlsx_path)
    view.save_table()
    assert set(pd.read_excel(xlsx_path, sheet_name=None)) == {"Summary", "Notes"}
    assert view.copy_table()
    assert QGuiApplication.clipboard().text().splitlines()[0] == "Response\tCount\tPercent\tValid N"


def test_a_very_long_title_still_gives_a_safe_default_file_name(view):
    choose(view, "Class year")
    view.title_edit.setText("How much do you agree that " + "the university supports students " * 20)
    view.flush()
    name = view._default_name("png")
    assert name.endswith(".png") and len(name) <= 130
    assert not any(ch in name for ch in '<>:"/\\|?*')


def test_nothing_to_export_says_so_instead_of_raising(view, monkeypatch):
    signals = []
    view.status.connect(signals.append)
    assert view.save_picture() is None and not view.copy_picture()
    assert signals == ["There is no chart to save yet."]


# ── numeric and time charts ──────────────────────────────────────────────────

def test_a_number_starts_as_a_histogram_and_a_date_as_a_line(view):
    pick(view.field_combo, "Hours per week")
    view.flush()
    assert view.config().chart_type == "histogram" and view.config().aggregation == "percent"
    assert "suggested" in view.chart_combo.itemText(view.chart_combo.currentIndex())
    types = [view.chart_combo.itemData(i) for i in range(view.chart_combo.count())]
    assert types[:3] == ["histogram", "box", "scatter"]
    assert data(view).kind == "numeric" and data(view).notes["chart"] == "histogram"
    pick(view.field_combo, "Survey date")
    view.flush()
    assert view.config().chart_type == "line" and view.config().aggregation == "count"
    assert data(view).notes["x_kind"] == "temporal"


def test_bins_and_time_grain_change_the_chart(view):
    pick(view.field_combo, "Hours per week")
    view.bins_spin.setValue(5)
    view.flush()
    assert len(data(view).categories) == 5
    pick(view.field_combo, "Survey date")
    pick(view.grain_combo, "month")
    view.flush()
    assert data(view).categories == ["2025-09", "2025-10", "2025-11", "2025-12"]
    pick(view.grain_combo, "year")
    view.flush()
    assert data(view).categories == ["2025"]


def test_numeric_charts_hide_the_category_grid_and_show_their_own_controls(view):
    pick(view.field_combo, "Hours per week")
    view.flush()
    view.show()
    view.set_step("adjust")
    for toggle in view.findChildren(QToolButton):          # the options are folded away
        if toggle.isCheckable() and toggle.text().startswith("More options"):
            toggle.setChecked(True)
    assert not view.grid.isVisible() and view.bins_spin.isVisible()
    assert not view.grain_combo.isVisible() and not view.trend_check.isVisible()
    pick(view.chart_combo, "box")
    view.flush()
    assert view.sort_combo.isVisible() and not view.bins_spin.isVisible()
    pick(view.field_combo, "Class year")
    view.flush()
    assert view.grid.isVisible() and not view.bins_spin.isVisible()
    view.hide()


def test_box_plot_by_group_and_scatter_with_a_line_of_best_fit(view):
    pick(view.field_combo, "Hours per week")
    pick(view.chart_combo, "box")
    select(view.group_list, ["Class year"])
    view.flush()
    d = data(view)
    assert len(d.table) == 4 and set(d.table["category"]) == {"First-year", "Sophomore", "Junior", "Senior"}
    pick(view.chart_combo, "scatter")
    view.flush()
    assert "value field" not in view.problem_label.text() and "second numeric field" in view.problem_label.text()
    pick(view.measure_combo, "Age")
    view.trend_check.setChecked(True)
    view.flush()
    d = data(view)
    assert d.notes["chart"] == "scatter" and "fit" in d.notes and d.base_note.startswith("Line of best fit")
    assert [layer["mark"]["type"] for layer in view._built[2]["layer"]][:2] == ["point", "line"]
    assert view.config().value_field == "Age" and view.config().display.trend_line


def test_a_chart_switched_to_a_line_counts_instead_of_taking_a_share(view):
    pick(view.field_combo, "Survey date")
    pick(view.chart_combo, "area")
    select(view.group_list, ["First generation"])
    view.flush()
    assert view.config().aggregation == "count" and data(view).groups
    assert view._built[2]["layer"][0]["encoding"]["y"]["stack"] == "zero"


def test_the_numeric_table_and_picture_export(view, tmp_path, monkeypatch):
    pick(view.field_combo, "Hours per week")
    view.flush()
    headers = [view.table_widget.horizontalHeaderItem(c).text() for c in range(view.table_widget.columnCount())]
    assert headers[:3] == ["Range", "Count", "Percent"]
    out = tmp_path / "hist.png"
    monkeypatch.setattr(view, "_ask_save_path", lambda default, flt: str(out))
    assert view.save_picture() == str(out) and png_size(out.read_bytes()) == (4000, 2250)


def test_undo_after_switching_to_a_numeric_chart_restores_the_summary(view):
    pick(view.field_combo, "Class year")
    pick(view.agg_combo, "percent")
    view.flush()
    pick(view.field_combo, "Hours per week")
    view.flush()
    view.undo()
    assert view.config().column == "Class year" and view.config().aggregation == "percent"
    assert view.config().chart_type == "bar_horizontal"          # a histogram of categories is not offered
    assert set(data(view).categories) == {"First-year", "Sophomore", "Junior", "Senior"}


def test_the_analysed_field_cannot_also_be_the_split(view):
    pick(view.field_combo, "Hours per week")
    pick(view.chart_combo, "box")
    select(view.group_list, ["Class year"])
    view.flush()
    assert view.config().group_by == ["Class year"]
    pick(view.field_combo, "Class year")
    view.flush()
    assert view.config().group_by == [] and isinstance(view._built, tuple)


# ── saved charts and custom themes ───────────────────────────────────────────

from core.chartbuilder import store, themes  # noqa: E402
from PySide6.QtWidgets import QDialogButtonBox  # noqa: E402
from qualsafe_qt.widgets.theme_dialog import ThemeDialog  # noqa: E402


def test_a_chart_is_saved_reopened_after_a_reset_and_replaced_by_name(view):
    choose(view, "Class year")
    view.title_edit.setText("Class mix")
    pick(view.sort_combo, "alpha")
    view.flush()
    before = view.config().to_dict()
    view.chart_name_edit.setText("Fall class mix")
    assert view.save_current_chart()
    assert view.saved_combo.count() == 1 and view.saved_combo.currentData() == "Fall class mix"
    view.reset_button.click()
    assert view.config().column == ""
    view.open_saved_button.click()
    assert view.config().to_dict() == before and isinstance(view._built, tuple)
    assert view.notes_label_out.isHidden()
    pick(view.sort_combo, "asc")
    view.flush()
    view.chart_name_edit.setText("FALL CLASS MIX")
    view.save_current_chart()
    assert view.saved_combo.count() == 1
    assert store.load_chart("fall class mix", root=view._root).config.sort == "asc"
    view.delete_saved_button.click()
    assert view.saved_combo.count() == 0 and not view.open_saved_button.isEnabled()


def test_a_saved_chart_uses_the_title_when_no_name_is_given_and_needs_a_file_first(app, tmp_path):
    empty = DataChartsView(storage_root=tmp_path / "cb")
    signals = []
    empty.status.connect(signals.append)
    assert not empty.save_current_chart() and signals == ["Open a file first."]
    empty.load_sample()
    empty.field_combo.setCurrentIndex(empty.field_combo.findData("Class year"))
    empty.title_edit.setText("From the title")
    empty.flush()
    assert empty.save_current_chart() and empty.saved_combo.currentData() == "From the title"
    assert not empty.save_current_chart(name="   ")


def test_opening_a_chart_keeps_its_own_chart_type_and_reports_what_did_not_fit(view):
    cfg = store.ChartConfig(column="Class year", chart_type="donut", group_by=["Not in this file"])
    store.save_chart("Elsewhere", cfg, {"name": "other.csv", "columns": ["Class year"]}, root=view._root)
    view.refresh_saved_list()
    assert view.open_saved_chart("Elsewhere")
    c = view.config()
    assert c.column == "Class year" and c.chart_type == "donut" and c.group_by == []
    assert not view.notes_label_out.isHidden() and "'Not in this file'" in view.notes_label_out.text()
    assert isinstance(view._built, tuple)
    pick(view.field_combo, "Residence")                 # a new question: back to the suggestion
    view.flush()
    assert view.config().chart_type == "bar_horizontal"


def test_a_chart_file_can_be_shared_and_opened_elsewhere(view, tmp_path, monkeypatch):
    choose(view, "Class year")
    view.title_edit.setText("Shared")
    view.flush()
    out = tmp_path / "shared.qchart.json"
    monkeypatch.setattr(view, "_ask_save_path", lambda default, flt: str(out))
    assert view.export_chart_file() == str(out)
    view.reset_button.click()
    assert view.import_chart_file(str(out))
    assert view.config().labels.title == "Shared" and view.config().column == "Class year"
    bad = tmp_path / "bad.json"
    bad.write_text("not a chart", encoding="utf-8")
    signals = []
    view.status.connect(signals.append)
    assert not view.import_chart_file(str(bad)) and "not a chart file" in signals[-1]


def test_the_theme_dialog_validates_with_the_shared_words(app):
    dialog = ThemeDialog()
    ok = dialog.buttons.button(QDialogButtonBox.Ok)
    assert not ok.isEnabled() and "name" in dialog.error_label.text()
    dialog.name_edit.setText("Campus")
    assert ok.isEnabled() and dialog.error_label.text() == ""
    dialog.colour_edits["primary"].setText("gold")
    assert not ok.isEnabled() and "'gold' is not a hex colour" in dialog.error_label.text()
    dialog.colour_edits["primary"].setText("112233")
    dialog.palette_edit.setText("#010101, #020202")
    theme = dialog.theme()
    assert theme.name == "Campus" and theme.primary == "#112233"
    assert theme.categorical == ["#010101", "#020202"] and theme.tertiary == ["#B7B4D8"]
    assert theme.title == themes.BUILT_IN_DEFAULT.title                     # starts from the default


def test_a_custom_theme_is_kept_on_disk_and_seen_by_the_next_window(view, tmp_path):
    dialog = ThemeDialog()
    dialog.name_edit.setText("Campus")
    dialog.colour_edits["primary"].setText("#112233")
    choose(view, "Class year")
    assert view.save_theme(dialog.theme())
    assert view.config().theme.name == "Campus" and set(view._built[0].table["color"]) == {"#112233"}
    assert list(store.load_themes(view._root)) == ["Campus"]
    other = DataChartsView(storage_root=view._root)                # a new window, same folder
    assert other.theme_combo.findData("Campus") >= 0
    assert view.delete_theme_button.isEnabled()
    assert view.delete_current_theme()
    assert store.load_themes(view._root) == {} and view.config().theme.name == "QualSafe default"
    assert not view.delete_theme_button.isEnabled()


def test_a_built_in_theme_name_is_refused_and_built_ins_cannot_be_deleted(view):
    signals = []
    view.status.connect(signals.append)
    clash = themes.build_theme("Grayscale", primary="#111111", secondary="#222222", neutral="#333333")
    assert not view.save_theme(clash) and "built-in theme" in signals[-1]
    assert not view.delete_current_theme() and "Only your own themes" in signals[-1]


def test_a_theme_can_be_shared_as_a_file_and_added_from_one(view, tmp_path, monkeypatch):
    view.save_theme(themes.build_theme("Campus", primary="#112233", secondary="#445566",
                                        neutral="#778899"))
    out = tmp_path / "campus.json"
    monkeypatch.setattr(view, "_ask_save_path", lambda default, flt: str(out))
    assert view.share_current_theme() == str(out)
    view.delete_current_theme()
    assert view.import_theme_file(str(out))
    assert view.config().theme.name == "Campus"
    assert not view.import_theme_file(str(tmp_path / "missing.json"))


def test_a_chart_that_names_a_theme_this_computer_lacks_says_so(view):
    cfg = store.ChartConfig(column="Class year")
    cfg.theme.name = "Someone else's theme"
    store.save_chart("Themed", cfg, root=view._root)
    view.refresh_saved_list()
    view.open_saved_chart("Themed")
    assert "'Someone else's theme' is not on this computer" in view.notes_label_out.text()
    assert isinstance(view._built, tuple)
