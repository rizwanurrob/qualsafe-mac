"""The clip player, the Watch link on a step, and the clips in Help (item 4.10)."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6", reason="Qt front end not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.ux import words  # noqa: E402
from core.ux.help import media  # noqa: E402
from qualsafe_qt.views import help_view  # noqa: E402
from qualsafe_qt.widgets.clip_player import FPS, ClipDialog, ClipPlayer  # noqa: E402

CLIP = "suggest-and-check"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def player(qapp):
    widget = ClipPlayer()
    widget.resize(700, 460)
    widget.show()
    assert widget.load(CLIP)
    qapp.processEvents()
    yield widget
    widget.close()


# -- the player ------------------------------------------------------------------------------

def test_it_starts_paused_on_the_finished_picture_so_nothing_moves_until_asked(player):
    last = media.get(CLIP).seconds * FPS - 1
    assert not player.is_playing and player.frame == last
    assert player.play_button.text() == "Replay"
    assert player.time_label.text() == "0:30 / 0:30"
    assert player.slider.maximum() == last and player.slider.value() == last


def test_play_starts_again_from_the_beginning_and_pause_holds_the_frame(player, qapp):
    player.play()
    assert player.is_playing and player.frame == 0 and player.play_button.text() == "Pause"
    QTest.qWait(250)
    qapp.processEvents()
    moved = player.frame
    assert moved > 0
    player.pause()
    assert not player.is_playing and player.frame >= moved and player.play_button.text() == "Play"
    held = player.frame
    QTest.qWait(150)
    assert player.frame == held


def test_it_stops_on_the_last_frame_instead_of_starting_again(player):
    last = media.get(CLIP).seconds * FPS - 1
    player.play()
    player._clock_from = last - 1                      # a moment from the end
    player._tick()
    player._clock_from = last
    player._tick()
    assert player.frame == last and not player.is_playing
    assert player.play_button.text() == "Replay"


def test_the_slider_seeks_and_the_clock_follows(player):
    player.slider.setValue(15 * FPS)
    assert player.frame == 15 * FPS and player.time_label.text() == "0:15 / 0:30"
    assert not player.is_playing


def test_next_and_back_go_one_caption_at_a_time_with_no_motion(player):
    player.seek(0)
    assert not player.back_button.isEnabled() and player.next_button.isEnabled()
    seen = []
    for _ in range(10):
        before = player.frame
        player.next_button.click()
        if player.frame == before:
            break
        seen.append(player.frame / FPS)
    assert len(seen) == len(media.moments(CLIP)) and seen == sorted(seen)
    assert all(a > b for a, b in zip(seen, [m + 1.0 for m in media.moments(CLIP)]))
    assert not player.is_playing and not player.next_button.isEnabled()
    player.back_button.click()
    assert abs(player.frame / FPS - seen[-2]) < 0.05


def test_next_pauses_a_clip_that_is_playing(player):
    player.play()
    player.next_button.click()
    assert not player.is_playing


def test_the_keys_play_and_step(player, qapp):
    player.seek(0)
    QTest.keyClick(player, Qt.Key.Key_Right)
    assert player.frame > 0
    QTest.keyClick(player, Qt.Key.Key_Left)
    assert player.frame == 0
    QTest.keyClick(player, Qt.Key.Key_Space)
    assert player.is_playing
    QTest.keyClick(player, Qt.Key.Key_Space)
    assert not player.is_playing


def test_clicking_the_picture_plays_and_pauses(player):
    player.canvas.clicked.emit()
    assert player.is_playing
    player.canvas.clicked.emit()
    assert not player.is_playing


def test_the_whole_clip_can_be_read_as_text_and_a_screen_reader_gets_it(player):
    assert not player.text_label.isVisibleTo(player)
    player.text_button.click()
    assert player.text_label.isVisibleTo(player)
    desc = media.get(CLIP) and player.canvas.accessibleDescription()
    assert len(desc.split()) >= 30 and desc in player.text_label.text()
    assert player.canvas.accessibleName() == media.get(CLIP).title
    assert player.slider.accessibleName() == "Position in the clip"


def test_it_pauses_when_hidden_and_an_unknown_clip_is_refused(player):
    player.play()
    player.hide()
    assert not player.is_playing
    assert player.load("no-such-clip") is False


def test_the_words_on_the_controls_are_plain(player):
    shown = " ".join([player.play_button.text(), player.back_button.text(), player.next_button.text(),
                      player.text_button.text(), player.back_button.toolTip(), player.next_button.toolTip(),
                      player.text_button.toolTip()])
    assert words.find_never(shown) == [] and words.find_replace(shown) == []


def test_every_clip_loads_and_its_slides_stay_inside_the_clip(qapp):
    for clip in media.CLIPS:
        widget = ClipPlayer()
        assert widget.load(clip.clip_id)
        widget.seek(0)
        frames = []
        while widget.next_button.isEnabled():
            widget.next_button.click()
            frames.append(widget.frame)
        assert frames and frames == sorted(frames) and frames[-1] <= clip.seconds * FPS - 1


# -- the dialog the Watch link opens ---------------------------------------------------------

def test_the_dialog_offers_a_choice_only_when_there_are_several_clips(qapp):
    one = ClipDialog(["who-is-speaking"])
    several = ClipDialog([c.clip_id for c in media.for_article("surveys-explore")])
    one.show()
    several.show()
    assert not one.picker.isVisibleTo(one) and several.picker.isVisibleTo(several)
    assert several.picker.count() == 4
    assert one.summary.text() == media.get("who-is-speaking").summary
    several.picker.setCurrentIndex(2)
    assert several.player.clip_id == several.picker.itemData(2) and not several.player.is_playing
    one.close()
    several.close()


# -- the Watch link on a step, and the clips in Help ------------------------------------------

@pytest.fixture
def window(qapp):
    from qualsafe_qt.windows.main_window import MainWindow

    win = MainWindow()
    win.resize(1300, 850)
    win.show()
    qapp.processEvents()
    yield win
    win.close()


def test_a_step_with_clips_shows_how_long_they_are_and_one_without_hides_the_link(window, qapp):
    window.open_activity("surveys", "code")
    assert window.activity.watch_button.isVisibleTo(window)
    assert window.activity.watch_button.text() == "Watch (2 short clips)"
    window.activity.show_step("interviews", "add")
    assert window.activity.watch_button.text() == "Watch (26 s)"
    window.activity.show_step("charts", "open")
    assert not window.activity.watch_button.isVisibleTo(window)


def test_watch_opens_the_clips_for_that_step_paused(window, qapp):
    window.open_activity("surveys", "explore")
    window.activity.watch_button.click()
    qapp.processEvents()
    dialog = window._clip_dialog
    assert dialog.isVisible() and dialog.picker.count() == 4
    assert not dialog.player.is_playing
    dialog.close()


def test_help_lists_every_clip_with_the_player_above_its_text(window, qapp):
    titles = [t for t, _b in help_view.HELP_SECTIONS]
    for clip in media.CLIPS:
        assert f"Watch: {clip.title}" in titles
        assert help_view.CLIP_TITLES[f"Watch: {clip.title}"] == clip.clip_id
    window.open_help()
    view = window.help
    assert not view.player.isVisibleTo(view)
    row = next(i for i in range(view.contents.count()) if view.contents.item(i).text().startswith("Watch: What a random"))
    view.contents.setCurrentRow(row)
    assert view.player.isVisibleTo(view) and view.player.clip_id == "random-forest"
    assert "In words." in view.body.toPlainText()
    view.player.play()
    view.contents.setCurrentRow(0)                              # another section: the clip stops
    assert not view.player.isVisibleTo(view) and not view.player.is_playing


def test_the_exported_guide_has_the_clips_as_text(qapp):
    guide = help_view.full_guide()
    for clip in media.CLIPS:
        assert clip.title in guide and clip.summary in guide
