"""Explainer clips: the rules they are written to, and the list of them (item 4.8).

A clip is one small SVG file in `core/ux/help/media/`, read by both apps. SVG animation is
only partly supported by Qt's renderer, which is what the desktop uses, so a clip may use
exactly what Qt was measured to play (2026-10-07, PySide6 6.11):

* Only `<animateTransform>` of type `translate`, `rotate` or `scale`. No `<animate>`, `<set>`,
  opacity or colour changes, motion paths, CSS animation, script, `foreignObject`, images or
  links to anything outside the file.
* One `<animateTransform>` for each element, `begin="0s"`, `fill="freeze"`, and the same `dur`
  as the whole clip. Qt draws an element in its un-animated state until its own `begin`, and
  does not run a second animation on the same element, so a clip is choreographed by a list of
  `values` instead: Qt spaces them evenly over `dur` (it ignores `keyTimes`), and an element
  waits by repeating a value.
* `scale` takes two numbers ("1 1"; one number draws nothing in Qt). To make something appear,
  scale it from 0.001; to make it go away, scale it back to 0.001.
* Qt does not hold the last picture past the end of a clip (it starts again, and not at a fixed
  frame), so a player stops on the last frame it shows.
* No longer than 60 seconds, 16:9 (`viewBox="0 0 640 360"`), a `<title>` and a `<desc>` that tell
  the whole clip in words (screen readers, and anyone who does not press play), and the
  captions as `<text>` inside the file, so they cannot be separated from the picture.

No video files (item 4.11). Nothing taught so far needs a real recording of the screen, and a
video costs megabytes where these clips cost kilobytes, in an installer that is already about
176 MB. If a clip ever does need one (for example, dragging across a passage to code it), add it
only with a decision recorded in `V8_PROGRESS.md` and a budget set in `tests/test_ux_media.py`.

`check()` reads a clip and says what breaks these rules. `tools/make_explainers.py` writes the
clips from a timeline, which keeps them inside the rules by construction; the check is the
independent test that it did. Nothing here imports Qt or Streamlit.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

MEDIA_DIR = Path(__file__).resolve().parent / "media"
MAX_SECONDS = 60
VIEWBOX = "0 0 640 360"
SVG_NS = "http://www.w3.org/2000/svg"

_FORBIDDEN_TAGS = {"animate", "set", "animateMotion", "animateColor", "script", "foreignObject",
                   "image", "a", "use", "style", "iframe", "video", "audio"}
_ALLOWED_TYPES = {"translate", "rotate", "scale"}
_NUMBER = r"-?\d+(?:\.\d+)?"


@dataclass(frozen=True)
class Clip:
    clip_id: str
    title: str
    seconds: int
    articles: Tuple[str, ...]   # the help articles it belongs with (`<activity>-<step>`)
    summary: str                # one sentence, for the list and the player's caption


#: The Explore step of Surveys and of Interviews, where Model an outcome lives.
EXPLORE = ("surveys-explore", "interviews-explore")

#: In the order they are offered. Each has `media/<clip_id>.svg`.
CLIPS: List[Clip] = [
    Clip("suggest-and-check", "How a suggested code becomes your coding", 30, ("surveys-code",),
         "QualSafe suggests a code for each answer; you read each one and fix any that are wrong."),
    Clip("what-agreement-means", "What agreement tells you", 34, ("surveys-code",),
         "Agreement shows how often two coders chose the same, allowing for luck, one code at a time."),
    Clip("who-is-speaking", "Why you confirm who is speaking", 26, ("interviews-add",),
         "QualSafe proposes who is the interviewer; once you confirm it, their words are set apart."),
    Clip("readable-tree", "Why a decision tree is easy to read", 32, EXPLORE,
         "A tree asks one yes-or-no question at a time, so you can read the path down to any group."),
    Clip("random-forest", "What a random forest does", 34, EXPLORE,
         "A forest builds many trees from random samples and takes the most common vote."),
    Clip("double-lasso", "How double lasso picks what to allow for", 42, EXPLORE,
         "Two passes pick the details to allow for, then the effect is estimated with a trustworthy range."),
    Clip("lasso-no-p-values", "Why lasso shows no p-values", 34, EXPLORE,
         "The data chose which details to keep, so a p-value would look surer than it is."),
]


def path_of(clip_id: str) -> Path:
    return MEDIA_DIR / f"{clip_id}.svg"


def read(clip_id: str) -> Optional[str]:
    path = path_of(clip_id)
    return path.read_text(encoding="utf-8") if path.is_file() else None


def get(clip_id: str) -> Optional[Clip]:
    return next((c for c in CLIPS if c.clip_id == clip_id), None)


def for_article(article: str) -> List[Clip]:
    return [c for c in CLIPS if article in c.articles]


def missing() -> List[str]:
    return [c.clip_id for c in CLIPS if not path_of(c.clip_id).is_file()]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _seconds(value: str) -> Optional[float]:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)s", (value or "").strip())
    return float(match.group(1)) if match else None


def moments_of(text: str) -> List[float]:
    """When the captions begin, in seconds: the places Next and Back jump to. May be empty."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    return [float(v) for v in re.findall(_NUMBER, root.get("data-moments", ""))]


def moments(clip_id: str) -> List[float]:
    text = read(clip_id)
    return moments_of(text) if text else []


def duration_of(text: str) -> Optional[float]:
    """The clip's length in seconds (the `dur` every animation shares), or None."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    durs = {_seconds(el.get("dur", "")) for el in root.iter() if _local(el.tag) == "animateTransform"}
    durs.discard(None)
    return max(durs) if durs else None


def check(text: str) -> List[str]:
    """What in this SVG breaks the rules above. Empty means it is a valid clip."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return [f"not valid SVG: {exc}"]
    problems: List[str] = []
    if _local(root.tag) != "svg":
        return ["the root element is not <svg>"]
    if root.get("viewBox") != VIEWBOX:
        problems.append(f'viewBox must be "{VIEWBOX}" (16:9)')
    if not (root.get("width") and root.get("height")):
        problems.append("width and height must be set")

    title = next((e for e in root if _local(e.tag) == "title"), None)
    desc = next((e for e in root if _local(e.tag) == "desc"), None)
    if title is None or not (title.text or "").strip():
        problems.append("missing <title>")
    if desc is None or len((desc.text or "").split()) < 12:
        problems.append("missing <desc> telling the whole clip in words (at least 12 words)")
    if not any(_local(e.tag) == "text" and "".join(e.itertext()).strip() for e in root.iter()):
        problems.append("the captions must be <text> inside the file")

    animated = 0
    durs = set()
    for element in root.iter():
        tag = _local(element.tag)
        if tag in _FORBIDDEN_TAGS:
            problems.append(f"<{tag}> is not allowed")
        for attribute, value in element.attrib.items():
            name = _local(attribute)
            if name.startswith("on") or name == "href" or (name == "style" and "animation" in value):
                problems.append(f"{name}= is not allowed")
            if "http" in value and name not in ("xmlns",) and not value.startswith(SVG_NS):
                problems.append(f"{name}= points outside the file")
        if tag != "animateTransform":
            continue
        animated += 1
        kind = element.get("type")
        if kind not in _ALLOWED_TYPES:
            problems.append(f"animateTransform type must be translate, rotate or scale, not {kind!r}")
        if element.get("attributeName") != "transform":
            problems.append("animateTransform must animate transform")
        if element.get("begin", "0s") not in ("0s", "0"):
            problems.append('begin must be "0s": Qt does not hold an element back until a later begin')
        if element.get("fill") != "freeze":
            problems.append('fill must be "freeze"')
        seconds = _seconds(element.get("dur", ""))
        if seconds is None:
            problems.append('dur must be in seconds, like "30s"')
        else:
            durs.add(seconds)
        if element.get("keyTimes") is not None:
            problems.append("keyTimes is ignored by Qt: space the values evenly instead")
        if element.get("repeatCount") is not None:
            problems.append("repeatCount is not used: the player stops on the last frame")
        if any(c in element.attrib for c in ("from", "to", "by")):
            problems.append("use values=, not from/to: it is the one form Qt plays for every type")
        values = [v.strip() for v in (element.get("values") or "").split(";") if v.strip()]
        if len(values) < 2:
            problems.append("values needs at least two stops")
        for value in values:
            numbers = re.findall(_NUMBER, value)
            if not numbers or re.sub(_NUMBER, "", value).strip():
                problems.append(f"values has something that is not a number: {value!r}")
            elif kind == "scale" and len(numbers) != 2:
                problems.append("scale needs two numbers (sx sy); one draws nothing in Qt")
            elif kind == "translate" and len(numbers) != 2:
                problems.append("translate needs two numbers (x y)")
            elif kind == "rotate" and len(numbers) != 1:
                problems.append("rotate takes one angle; turn about a point with a nested group")
        # Only one animateTransform per element: Qt does not run a second.
    for element in root.iter():
        kids = [k for k in element if _local(k.tag) == "animateTransform"]
        if len(kids) > 1:
            problems.append("an element has more than one animateTransform; nest groups instead")
    if animated == 0:
        problems.append("nothing moves: no animateTransform")
    stops = moments_of(text)
    if not stops:
        problems.append("data-moments is missing: Next and Back need the times captions begin")
    elif stops != sorted(stops) or len(set(stops)) != len(stops) or (durs and max(stops) >= max(durs)):
        problems.append("data-moments must be increasing times inside the clip")
    if len(durs) > 1:
        problems.append(f"every animation must share one dur, found {sorted(durs)}")
    if durs and max(durs) > MAX_SECONDS:
        problems.append(f"longer than {MAX_SECONDS} seconds")
    return sorted(set(problems))
