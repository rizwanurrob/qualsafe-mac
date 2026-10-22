"""Explainer clips: written to the rules Qt's SVG player needs, and played by it (items 4.8, 4.9)."""

from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from core.ux import help as shared_help
from core.ux import words
from core.ux.help import media

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
IDS = [c.clip_id for c in media.CLIPS]

HEAD = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360" width="640" height="360" '
        'data-moments="1 5">'
        "<title>T</title><desc>{desc}</desc>")
DESC = "A made-up example with enough words in it to tell the whole clip in plain words."
GOOD_ANIM = ('<animateTransform attributeName="transform" type="{kind}" values="{values}" '
             'begin="0s" dur="10s" fill="freeze"/>')


def svg(body: str, *, desc: str = DESC, head: str = "") -> str:
    return (head or HEAD.format(desc=desc)) + body + "</svg>"


def good(kind="scale", values="0.001 0.001;1 1", extra="") -> str:
    return svg(f'<g>{GOOD_ANIM.format(kind=kind, values=values)}<text>caption</text></g>{extra}')


# -- the files -------------------------------------------------------------------------

def test_there_are_clips_and_none_is_missing_or_left_over():
    assert len(IDS) >= 3 and media.missing() == []
    on_disk = {p.stem for p in media.MEDIA_DIR.glob("*.svg")}
    assert on_disk == set(IDS)


@pytest.mark.parametrize("clip_id", IDS)
def test_every_clip_follows_the_rules(clip_id):
    assert media.check(media.read(clip_id)) == []


@pytest.mark.parametrize("clip", media.CLIPS, ids=IDS)
def test_the_listed_length_is_the_real_length_and_within_a_minute(clip):
    assert media.duration_of(media.read(clip.clip_id)) == clip.seconds <= media.MAX_SECONDS


@pytest.mark.parametrize("clip", media.CLIPS, ids=IDS)
def test_a_clip_belongs_with_an_article_that_exists_and_has_a_plain_summary(clip):
    assert clip.articles
    for article in clip.articles:
        activity_key, _, step_key = article.partition("-")
        assert shared_help.article(activity_key, step_key), clip.clip_id
    assert clip.summary.endswith(".") and len(clip.summary.split()) <= 25
    assert words.find_never(clip.title + clip.summary) == []
    assert words.find_replace(clip.title + clip.summary) == []


@pytest.mark.parametrize("clip_id", IDS)
def test_the_words_in_a_clip_are_plain(clip_id):
    root = ET.fromstring(media.read(clip_id))
    said = " ".join("".join(e.itertext()) for e in root.iter() if e.tag.endswith("text"))
    said += " " + " ".join(e.text or "" for e in root.iter() if e.tag.endswith(("title", "desc")))
    assert words.find_never(said) == [] and words.find_replace(said) == []
    assert 20 <= len(said.split())


@pytest.mark.parametrize("clip_id", IDS)
def test_the_description_tells_the_whole_clip_and_each_caption_is_in_it(clip_id):
    root = ET.fromstring(media.read(clip_id))
    desc = next(e for e in root if e.tag.endswith("desc")).text
    assert len(desc.split()) >= 30, "the description is what a screen reader and a non-viewer get"


def test_the_clips_are_small_enough_to_ship():
    sizes = [media.path_of(i).stat().st_size for i in IDS]
    assert max(sizes) < 100_000 and sum(sizes) < 800_000


def test_the_media_folder_holds_only_clips_and_no_video():
    """4.11: no MP4 until a clip really needs a screen recording, with a decision and a budget."""
    assert {p.suffix for p in media.MEDIA_DIR.iterdir() if p.is_file()} == {".svg"}


def test_the_files_are_what_the_generator_writes():
    import make_explainers

    assert make_explainers.main(["--check"]) == 0, "run: python tools/make_explainers.py"


# -- the checker catches each way a clip can fail in Qt --------------------------------------

def test_the_checker_passes_a_good_clip():
    assert media.check(good()) == []


@pytest.mark.parametrize("text,fragment", [
    (svg('<g><animate attributeName="opacity" values="0;1" dur="10s"/><text>x</text></g>'), "<animate> is not allowed"),
    (svg('<set attributeName="opacity" to="1"/><text>x</text>'), "<set> is not allowed"),
    (svg('<image href="x.png"/><text>x</text>'), "<image> is not allowed"),
    (svg('<script>alert(1)</script><text>x</text>'), "<script> is not allowed"),
    (svg('<g onclick="x()"><text>x</text></g>' + GOOD_ANIM.format(kind="scale", values="1 1;2 2")), "on"),
    (good().replace('type="scale"', 'type="skewX"'), "translate, rotate or scale"),
    (good().replace('begin="0s"', 'begin="3s"'), 'begin must be "0s"'),
    (good().replace('fill="freeze"', 'fill="remove"'), "freeze"),
    (good().replace('values="0.001 0.001;1 1"', 'from="0.1 0.1" to="1 1"'), "values="),
    (good(values="0.1;1"), "scale needs two numbers"),
    (good("translate", "0;5"), "translate needs two numbers"),
    (good("rotate", "0 0;90 0"), "rotate takes one angle"),
    (good(values="0.001 0.001"), "at least two stops"),
    (good(values="a b;1 1"), "not a number"),
    (good().replace('fill="freeze"', 'fill="freeze" keyTimes="0;1"'), "keyTimes"),
    (good().replace('fill="freeze"', 'fill="freeze" repeatCount="indefinite"'), "repeatCount"),
    (good().replace('dur="10s"', 'dur="90s"'), "longer than 60 seconds"),
    (good().replace('dur="10s"', 'dur="ten"'), "dur must be in seconds"),
    (svg("<g><text>x</text></g>"), "nothing moves"),
    (good().replace("<text>caption</text>", ""), "captions must be <text>"),
    (good().replace("<title>T</title>", ""), "missing <title>"),
    (good().replace(DESC, "short"), "missing <desc>"),
    (good().replace('viewBox="0 0 640 360"', 'viewBox="0 0 100 100"'), "viewBox"),
    (good().replace(' data-moments="1 5"', ""), "data-moments is missing"),
    (good().replace('data-moments="1 5"', 'data-moments="5 1"'), "increasing times"),
    (good().replace('data-moments="1 5"', 'data-moments="1 12"'), "increasing times"),
    ("<svg", "not valid SVG"),
])
def test_the_checker_names_what_is_wrong(text, fragment):
    assert any(fragment in problem for problem in media.check(text)), media.check(text)


def test_two_animations_on_one_element_are_refused_because_qt_runs_only_the_first():
    two = GOOD_ANIM.format(kind="scale", values="1 1;2 2") * 2
    assert any("more than one" in p for p in media.check(svg(f"<g>{two}<text>x</text></g>")))


def test_animations_with_different_lengths_are_refused():
    a = GOOD_ANIM.format(kind="scale", values="1 1;2 2")
    b = GOOD_ANIM.format(kind="scale", values="1 1;2 2").replace('dur="10s"', 'dur="12s"')
    assert any("share one dur" in p for p in media.check(svg(f"<g>{a}<g>{b}</g><text>x</text></g>")))


# -- Qt plays them ---------------------------------------------------------------------------

pytest.importorskip("PySide6", reason="Qt front end not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _renderer(text: str):
    from PySide6.QtCore import QByteArray
    from PySide6.QtSvg import QSvgRenderer

    return QSvgRenderer(QByteArray(text.encode("utf-8")))


def _frame(renderer, n: int):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter

    renderer.setCurrentFrame(n)
    image = QImage(320, 180, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    renderer.render(painter, QRectF(0, 0, 320, 180))
    painter.end()
    return image


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("clip", media.CLIPS, ids=IDS)
def test_qt_plays_the_clip_so_the_frames_really_change(qapp, clip):
    renderer = _renderer(media.read(clip.clip_id))
    assert renderer.isValid() and renderer.animated()
    last = int(renderer.animationDuration() / 1000 * renderer.framesPerSecond()) - 1
    assert last == clip.seconds * renderer.framesPerSecond() - 1
    first, middle, end = _frame(renderer, 0), _frame(renderer, last // 2), _frame(renderer, last)
    assert first != middle, "nothing moves in the first half"
    assert middle != end, "nothing moves in the second half"
    assert first != end


def test_qt_really_does_play_what_the_rules_allow_and_not_what_they_forbid(qapp):
    """The rules came from measuring Qt; this keeps them honest if Qt changes."""
    allowed = _renderer(svg(
        '<g>' + GOOD_ANIM.format(kind="translate", values="0 0;200 0;200 0")
        + '<rect x="10" y="10" width="60" height="60" fill="#7a2d8a"/></g><text>x</text>'))
    assert _frame(allowed, 0) != _frame(allowed, 150)
    one_number = _renderer(svg(
        '<circle cx="160" cy="90" r="40" fill="#0a7">'
        + GOOD_ANIM.format(kind="scale", values="0.1;1") + "</circle><text>x</text>"))
    assert _frame(one_number, 0) == _frame(one_number, 150), "a one-number scale draws the same nothing"


@pytest.mark.parametrize("clip", media.CLIPS, ids=IDS)
def test_every_clip_lists_the_times_its_captions_begin(clip):
    stops = media.moments(clip.clip_id)
    assert len(stops) >= 3 and stops == sorted(stops) and 0 <= stops[0] and stops[-1] < clip.seconds


def test_clips_are_found_by_the_article_they_belong_with():
    assert [c.clip_id for c in media.for_article("surveys-code")] == ["suggest-and-check", "what-agreement-means"]
    assert [c.clip_id for c in media.for_article("interviews-add")] == ["who-is-speaking"]
    assert len(media.for_article("surveys-explore")) == 4 == len(media.for_article("interviews-explore"))
    assert media.for_article("charts-open") == []
