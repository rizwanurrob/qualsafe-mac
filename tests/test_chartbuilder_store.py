"""
Saved charts and custom themes (`core/chartbuilder/store.py`).

Each test uses a tmp folder as the storage root; nothing touches the real user
folder. The property that matters most is reproducibility: a chart saved, read
back and drawn from the same data is the same chart.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.chartbuilder import store, themes
from core.chartbuilder.build import build_data
from core.chartbuilder.config import ChartConfig, FilterRule, Merge
from core.chartbuilder.sample import sample_frame


@pytest.fixture()
def root(tmp_path):
    return tmp_path / "cb"


def _cfg(**kw):
    cfg = ChartConfig(column="Class year", **kw)
    cfg.labels.title = "Class mix"
    cfg.recode.rename = {"Senior": "Fourth year"}
    cfg.recode.merges = [Merge("Lower", ["First-year", "Sophomore"])]
    cfg.filters = [FilterRule("First generation", "in", ["Yes", "No"])]
    cfg.theme.color_overrides = {"Junior": "#112233"}
    return cfg


# ── where it lives ────────────────────────────────────────────────────────────

def test_the_folder_follows_the_settings_override_then_the_platform(monkeypatch, tmp_path):
    monkeypatch.setenv("QNW_SETTINGS_DIR", str(tmp_path))
    assert store.data_dir() == tmp_path / "chartbuilder"
    assert store.charts_dir() == tmp_path / "chartbuilder" / "charts"
    assert store.themes_path() == tmp_path / "chartbuilder" / "themes.json"
    monkeypatch.delenv("QNW_SETTINGS_DIR")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert store.data_dir() == tmp_path / "Roaming" / "QualSafe" / "chartbuilder"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert "Application Support" in store.data_dir().parts
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert store.data_dir() == tmp_path / "xdg" / "QualSafe" / "chartbuilder"


# ── saved charts ──────────────────────────────────────────────────────────────

def test_a_saved_chart_reads_back_identical(root):
    cfg = _cfg()
    path = store.save_chart("Class mix, Fall 2026", cfg, {"name": "s.csv", "sheet": None,
                                                          "columns": ["Class year"]}, root=root)
    assert path.suffix == ".json" and path.name.endswith(store.CHART_SUFFIX)
    saved = store.load_chart("class mix, fall 2026", root=root)         # any case
    assert saved.config.to_dict() == cfg.to_dict()
    assert saved.dataset == {"name": "s.csv", "sheet": None, "columns": ["Class year"]}
    assert saved.chart_type == "bar_horizontal" and saved.saved_at


def test_the_same_chart_is_drawn_from_the_same_data_after_saving(root):
    frame = sample_frame(120)
    cfg = _cfg()
    before, _ = build_data(frame, cfg)
    store.save_chart("q", cfg, root=root)
    loaded = store.load_chart("q", root=root).config
    after, _ = build_data(frame, loaded)
    pd.testing.assert_frame_equal(before.table, after.table)
    assert before.categories == after.categories and before.warnings == after.warnings


def test_saving_under_an_existing_name_replaces_it_whatever_the_case(root):
    store.save_chart("Belonging", ChartConfig(column="a"), root=root)
    store.save_chart("  belonging ", ChartConfig(column="b"), root=root)
    charts = store.list_charts(root)
    assert len(charts) == 1 and charts[0].name == "belonging"
    assert store.load_chart("BELONGING", root=root).config.column == "b"
    assert len(list(store.charts_dir(root).glob("*.json"))) == 1


def test_names_that_slug_alike_are_still_two_charts(root):
    store.save_chart("Q1: how?", ChartConfig(column="a"), root=root)
    store.save_chart("Q1/ how?", ChartConfig(column="b"), root=root)
    assert {c.name for c in store.list_charts(root)} == {"Q1: how?", "Q1/ how?"}
    assert store.load_chart("Q1: how?", root=root).config.column == "a"


def test_a_blank_name_and_an_unknown_chart_say_so(root):
    with pytest.raises(store.StoreError, match="name"):
        store.save_chart("  ", ChartConfig(), root=root)
    with pytest.raises(store.StoreError, match="no saved chart called 'nope'"):
        store.load_chart("nope", root=root)
    assert store.list_charts(root) == [] and not store.delete_chart("nope", root=root)


def test_the_list_is_newest_first_and_skips_files_that_are_not_charts(root):
    import time
    store.save_chart("old", ChartConfig(column="a"), root=root)
    time.sleep(1.05)
    store.save_chart("new", ChartConfig(column="b"), root=root)
    (store.charts_dir(root) / "junk.qchart.json").write_text("{not json", encoding="utf-8")
    (store.charts_dir(root) / "other.qchart.json").write_text('{"format": "something else"}',
                                                              encoding="utf-8")
    assert [c.name for c in store.list_charts(root)] == ["new", "old"]


def test_delete_removes_only_that_chart(root):
    store.save_chart("a", ChartConfig(column="x"), root=root)
    store.save_chart("b", ChartConfig(column="y"), root=root)
    assert store.delete_chart("A", root=root)
    assert [c.name for c in store.list_charts(root)] == ["b"]


def test_a_very_long_name_saves_under_a_windows_safe_file_name(root):
    name = "How much do you agree that " + "the university supports students " * 20
    path = store.save_chart(name, ChartConfig(column="a"), root=root)
    assert len(path.name) < 100 and len(str(path)) < 240
    assert store.load_chart(name, root=root).name == name.strip()


def test_a_chart_file_holds_no_row_data(root):
    frame = sample_frame(50)
    cfg = _cfg()
    build_data(frame, cfg)
    path = store.save_chart("q", cfg, {"name": "s.csv", "columns": list(frame.columns)}, root=root)
    text = path.read_text(encoding="utf-8")
    assert "R0001" not in text and frame["Comment"].dropna().iloc[0] not in text
    assert set(json.loads(text)) == {"format", "version", "config_version", "name", "saved_at",
                                     "note", "dataset", "config"}


def test_chart_files_export_and_import_as_bytes():
    saved = store.SavedChart("Shared", _cfg(), {"name": "s.csv", "columns": ["a"]}, note="for Dana")
    again = store.chart_from_bytes(store.chart_to_bytes(saved))
    assert again.config.to_dict() == saved.config.to_dict() and again.note == "for Dana"
    with_bom = b"\xef\xbb\xbf" + store.chart_to_bytes(saved)
    assert store.chart_from_bytes(with_bom).name == "Shared"


@pytest.mark.parametrize("text,match", [
    ("not json at all", "not valid JSON"),
    ('["a list"]', "not a QualSafe chart"),
    ('{"format": "qualsafe-chart", "version": 99, "config": {}}', "newer version"),
    ('{"format": "other"}', "not a QualSafe chart")])
def test_a_file_that_is_not_a_chart_is_refused_in_words(text, match):
    with pytest.raises(store.StoreError, match=match):
        store.chart_from_text(text)
    with pytest.raises(store.StoreError, match="not text"):
        store.chart_from_bytes(b"\xff\xfe\x00\x01")


def test_loading_is_forgiving_of_unknown_and_missing_keys():
    text = json.dumps({"format": "qualsafe-chart", "version": 1, "name": "old",
                       "config": {"column": "Q", "from_the_future": 1,
                                  "labels": {"title": "T", "new_option": True}}})
    saved = store.chart_from_text(text)
    assert saved.config.column == "Q" and saved.config.labels.title == "T"
    assert saved.config.theme.name == "QualSafe default"          # defaults fill the gaps


def test_an_unwritable_folder_is_reported_not_raised_as_an_oserror(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file", encoding="utf-8")
    with pytest.raises(store.StoreError, match="Could not save"):
        store.save_chart("x", ChartConfig(column="a"), root=blocker / "sub")
    assert not list(tmp_path.rglob("*.tmp"))


# ── opening a saved chart on a file ───────────────────────────────────────────

def test_the_same_structure_reopens_with_nothing_to_report():
    frame = sample_frame(60)
    cfg = _cfg()
    cfg.dataset = {"name": "s.csv", "sheet": None, "columns": [str(c) for c in frame.columns]}
    fitted, notes = store.fit_to_frame(cfg, frame)
    assert notes == [] and fitted.to_dict() == cfg.to_dict()


def test_a_different_file_clears_missing_fields_and_says_which():
    frame = pd.DataFrame({"Class year": ["a", "b"], "Other": ["x", "y"]})
    cfg = ChartConfig(column="Missing question", group_by=["Class year", "Gone"], value_field="Score",
                      filters=[FilterRule("Gone", "in", ["1"]), FilterRule("Other", "in", ["x"])])
    fitted, notes = store.fit_to_frame(cfg, frame)
    assert fitted.column == "" and fitted.group_by == ["Class year"] and fitted.value_field == ""
    assert [f.column for f in fitted.filters] == ["Other"]
    text = " ".join(notes)
    assert "'Missing question'" in text and "'Gone'" in text and "'Score'" in text
    assert "Filters on missing fields were removed" in text


def test_matrix_columns_are_fitted_too():
    frame = pd.DataFrame({"A": ["x"], "B": ["y"]})
    cfg = ChartConfig(kind="matrix", columns=["A", "B", "C"])
    fitted, notes = store.fit_to_frame(cfg, frame)
    assert fitted.columns == ["A", "B"] and "'C'" in notes[0]


def test_recode_entries_for_categories_that_are_gone_are_reported_and_kept():
    frame = pd.DataFrame({"Q": ["Yes", "No", "Yes"]})
    cfg = ChartConfig(column="Q")
    cfg.recode.rename = {"Yes": "Agreed", "Maybe": "Unsure"}
    cfg.recode.exclude = ["Perhaps"]
    fitted, notes = store.fit_to_frame(cfg, frame)
    assert any("2 relabel/combine/exclude choice(s)" in n and "'Maybe'" in n for n in notes)
    assert fitted.recode.rename == {"Yes": "Agreed", "Maybe": "Unsure"}      # kept: it may come back


def test_a_file_with_extra_fields_still_reproduces_the_chart():
    frame = pd.DataFrame({"Q": ["a", "b"], "New": ["x", "y"]})
    cfg = ChartConfig(column="Q")
    cfg.dataset = {"name": "old.csv", "columns": ["Q"]}
    fitted, notes = store.fit_to_frame(cfg, frame)
    assert fitted.column == "Q" and any("1 field(s) the chart was not made with" in n for n in notes)


# ── custom themes ─────────────────────────────────────────────────────────────

def _theme(name="Campus", **kw):
    fields = dict(primary="#112233", secondary="#445566", neutral="#778899", tertiary="#AABBCC")
    fields.update(kw)
    return themes.build_theme(name, **fields)


def test_a_custom_theme_persists_and_reads_back(root):
    store.save_theme(_theme(), root)
    loaded = store.load_themes(root)
    assert list(loaded) == ["Campus"] and loaded["Campus"].primary == "#112233"
    assert loaded["Campus"].builtin is False and loaded["Campus"].tertiary == ["#AABBCC"]


def test_a_saved_theme_draws_the_chart_in_its_colours(root):
    store.save_theme(_theme(), root)
    frame = pd.DataFrame({"Q": ["a", "b", "a", "c"] * 10})
    cfg = ChartConfig(column="Q")
    cfg.theme.name = "Campus"
    data, theme = build_data(frame, cfg, store.load_themes(root))
    assert theme.name == "Campus" and set(data.table["color"]) == {"#112233"}
    cfg.theme.name = "Deleted theme"                                    # falls back, never fails
    assert build_data(frame, cfg, store.load_themes(root))[1].name == "QualSafe default"


def test_saving_a_theme_again_replaces_it_and_refuses_built_in_names(root):
    store.save_theme(_theme(primary="#111111"), root)
    store.save_theme(_theme(name="campus", primary="#222222"), root)
    loaded = store.load_themes(root)
    assert list(loaded) == ["campus"] and loaded["campus"].primary == "#222222"
    for name in ("QualSafe default", "qualsafe default", "Grayscale"):
        with pytest.raises(store.StoreError, match="built-in theme"):
            store.save_theme(_theme(name=name), root)
    with pytest.raises(store.StoreError, match="cannot be deleted"):
        store.delete_theme("QualSafe default", root)


def test_deleting_a_theme_and_a_damaged_file(root):
    store.save_theme(_theme("A"), root)
    store.save_theme(_theme("B"), root)
    assert list(store.delete_theme("A", root)) == ["B"]
    store.themes_path(root).write_text("{broken", encoding="utf-8")
    assert store.load_themes(root) == {}
    assert store.themes_path(root).with_suffix(".json.bad").exists()      # set aside, not lost
    assert store.save_theme(_theme("C"), root).keys() == {"C"}


def test_one_bad_theme_entry_does_not_hide_the_others(root):
    good = _theme("Good").to_dict()
    bad = dict(good, name="Bad", primary="not a colour")
    store.themes_path(root).parent.mkdir(parents=True)
    store.themes_path(root).write_text(json.dumps(
        {"format": store.THEME_FORMAT, "version": 1, "themes": [bad, good]}), encoding="utf-8")
    assert list(store.load_themes(root)) == ["Good"]


def test_a_theme_file_can_be_shared_as_bytes():
    theme = _theme("Shared")
    again = store.theme_from_bytes(store.theme_to_bytes(theme))
    assert again == theme
    for junk in (b"nope", b'{"format": "x"}', b'{"format": "qualsafe-themes", "themes": []}'):
        with pytest.raises(store.StoreError, match="not a QualSafe theme file"):
            store.theme_from_bytes(junk)


def test_the_theme_form_helper_refuses_bad_hex_in_words_and_derives_the_rest():
    with pytest.raises(ValueError, match="'gold' is not a hex colour"):
        _theme(primary="gold")
    with pytest.raises(ValueError, match="Give the theme a name"):
        _theme(name="  ")
    t = _theme(text="#333333", tertiary="#111111, #222222 #333333", palette="")
    assert t.title == "#333333" and t.tertiary == ["#111111", "#222222", "#333333"]
    assert t.categorical[:2] == ["#112233", "#445566"]                 # derived from the roles
    custom = _theme(palette="#010101,#020202")
    assert custom.categorical == ["#010101", "#020202"]
