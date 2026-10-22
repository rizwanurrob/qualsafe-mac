#!/usr/bin/env python
"""Write the explainer clips (core/ux/help/media/*.svg) from a timeline.

    python tools/make_explainers.py            # writes every clip
    python tools/make_explainers.py --check    # writes nothing; exits 1 if a file differs

A clip is a list of *actors*. Each actor has a position and a size over time, written as a few
keyframes. This script samples them on a fixed grid and writes, for each actor, two nested
groups with one `<animateTransform>` each (a `translate` and a `scale`), the only thing Qt's
SVG renderer plays reliably. `core/ux/help/media.py` says why, and checks the result.

Captions are `<text>` in the file. Nothing in a clip is real data: the answers are invented.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.ux.help import media  # noqa: E402

GRID = 0.5                # seconds between stops
HIDDEN = 0.001            # Qt draws nothing at this size
FONT = "Segoe UI"

INK, PAPER, MUTED, LINE = "#1b1b1f", "#ffffff", "#5b5b66", "#9a9aa6"
PLUM, TEAL, AMBER, RED, GREEN = "#7a2d8a", "#0f6f7a", "#b45309", "#b3261e", "#1b7a43"


def _num(x: float) -> str:
    text = f"{x:.3f}".rstrip("0").rstrip(".")
    return text if text and text != "-0" else "0"


def _sample(keys: Sequence[Tuple[float, Tuple[float, ...]]], t: float) -> Tuple[float, ...]:
    """Linear between keyframes; the first value before the first key, the last after the last."""
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t <= t1:
            f = (t - t0) / (t1 - t0) if t1 > t0 else 1.0
            return tuple(a + (b - a) * f for a, b in zip(v0, v1))
    return keys[-1][1]


class Actor:
    """Something drawn around its own centre (0, 0), placed and sized over time."""

    def __init__(self, inner: str, x: float, y: float, *, visible: bool = False) -> None:
        self.inner = inner
        self._pos: List[Tuple[float, Tuple[float, ...]]] = [(0.0, (x, y))]
        self._size: List[Tuple[float, Tuple[float, ...]]] = [(0.0, (1.0 if visible else HIDDEN,))]

    def move(self, t: float, x: float, y: float, over: float = 1.0) -> "Actor":
        """Be at (x, y) by time t, having started `over` seconds earlier from where it was."""
        _, here = self._pos[-1]
        self._pos += [(max(t - over, self._pos[-1][0]), here), (t, (x, y))]
        return self

    def show(self, t: float, over: float = 0.5) -> "Actor":
        self._size += [(max(t - over, self._size[-1][0]), (HIDDEN,)), (t, (1.0,))]
        return self

    def hide(self, t: float, over: float = 0.5) -> "Actor":
        self._size += [(max(t - over, self._size[-1][0]), (1.0,)), (t, (HIDDEN,))]
        return self

    def svg(self, duration: float) -> str:
        stops = int(round(duration / GRID)) + 1
        times = [i * GRID for i in range(stops)]
        pos = [_sample(self._pos, t) for t in times]
        size = [_sample(self._size, t) for t in times]
        dur = f"{_num(duration)}s"
        move = ";".join(f"{_num(x)} {_num(y)}" for x, y in pos)
        grow = ";".join(f"{_num(s[0])} {_num(s[0])}" for s in size)
        x0, y0 = pos[0]
        return (
            f'<g transform="translate({_num(x0)} {_num(y0)})">'
            f'<animateTransform attributeName="transform" type="translate" values="{move}" '
            f'begin="0s" dur="{dur}" fill="freeze"/>'
            f'<g transform="scale({_num(size[0][0])} {_num(size[0][0])})">'
            f'<animateTransform attributeName="transform" type="scale" values="{grow}" '
            f'begin="0s" dur="{dur}" fill="freeze"/>'
            f"{self.inner}</g></g>"
        )


# -- shapes, all centred on (0, 0) -------------------------------------------------------

def text(lines: Sequence[str], size: int = 15, fill: str = INK, weight: str = "normal",
         anchor: str = "middle") -> str:
    step = size * 1.3
    top = -step * (len(lines) - 1) / 2
    spans = "".join(
        f'<tspan x="0" y="{_num(top + i * step + size * 0.35)}">{escape(line)}</tspan>'
        for i, line in enumerate(lines))
    return (f'<text font-family="{FONT}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}">{spans}</text>')


def card(w: float, h: float, lines: Sequence[str], *, size: int = 14, fill: str = PAPER,
         stroke: str = LINE, dashed: bool = False, ink: str = INK, weight: str = "normal",
         radius: float = 8) -> str:
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    return (f'<rect x="{_num(-w / 2)}" y="{_num(-h / 2)}" width="{_num(w)}" height="{_num(h)}" '
            f'rx="{_num(radius)}" fill="{fill}" stroke="{stroke}" stroke-width="2"{dash}/>'
            + text(lines, size, ink, weight))


def tick(color: str = GREEN, size: float = 12) -> str:
    return (f'<polyline points="{_num(-size)},0 {_num(-size / 3)},{_num(size * 0.7)} '
            f'{_num(size)},{_num(-size * 0.7)}" fill="none" stroke="{color}" stroke-width="4" '
            'stroke-linecap="round" stroke-linejoin="round"/>')


def cross(color: str = RED, size: float = 10) -> str:
    return (f'<path d="M{_num(-size)} {_num(-size)} L{_num(size)} {_num(size)} '
            f'M{_num(size)} {_num(-size)} L{_num(-size)} {_num(size)}" stroke="{color}" '
            'stroke-width="4" stroke-linecap="round"/>')


def caption(lines: Sequence[str]) -> str:
    width = min(620, 24 + max(len(line) for line in lines) * 9.4)
    height = 16 + 22 * len(lines)
    return card(width, height, lines, size=17, fill=INK, stroke=INK, ink=PAPER, radius=10)


# -- a clip ------------------------------------------------------------------------------

class Clip:
    def __init__(self, clip_id: str, title: str, description: str, seconds: int) -> None:
        self.id, self.title, self.description, self.seconds = clip_id, title, description, seconds
        self.actors: List[Actor] = []
        self.moments: List[float] = []      # when each caption begins: the "slides" of the clip

    def add(self, actor: Actor) -> Actor:
        self.actors.append(actor)
        return actor

    def say(self, lines: Sequence[str], start: float, end: Optional[float] = None) -> Actor:
        """A caption at the bottom from `start`; until `end`, or to the last frame if none."""
        self.moments.append(start)
        actor = self.add(Actor(caption(lines), 320, 322).show(start, 0.4))
        return actor if end is None else actor.hide(end, 0.4)

    def render(self) -> str:
        body = "\n".join(actor.svg(self.seconds) for actor in self.actors)
        moments = " ".join(_num(m) for m in sorted(set(self.moments)))
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{media.VIEWBOX}" '
            f'width="640" height="360" data-moments="{moments}">\n'
            f"<title>{escape(self.title)}</title>\n"
            f"<desc>{escape(self.description)}</desc>\n"
            f'<rect x="0" y="0" width="640" height="360" fill="{PAPER}"/>\n'
            f"{body}\n</svg>\n")


# -- the clips ---------------------------------------------------------------------------

def suggest_and_check() -> Clip:
    clip = Clip(
        "suggest-and-check", "How a suggested code becomes your coding",
        "Three made-up survey answers are listed. QualSafe puts a suggested code beside each one, "
        "shown with a dashed outline and a question mark. A tick moves down the list as you read "
        "each answer. The second suggestion is wrong, so it is replaced with the code you choose. "
        "The suggestions you agree with become solid, and what you decide is what is counted.",
        30)
    answers = [
        (["The textbooks cost more than I planned for."], "Money", "Money"),
        (["My roommate and I study together every week."], "Money", "Belonging"),
        (["My advisor answered every email within a day."], "Support", "Support"),
    ]
    ys = [95, 165, 235]
    for i, (lines, _guess, _final) in enumerate(answers):
        clip.add(Actor(card(330, 44, lines, size=14), 220, ys[i]).show(0.5 + i))
    for i, (_lines, guess, final) in enumerate(answers):
        x = 480
        guessed = clip.add(Actor(card(120, 32, [guess + " ?"], size=15, dashed=True, stroke=MUTED,
                                       ink=MUTED), x, ys[i]).show(5.0 + 0.5 * i))
        if guess == final:
            guessed.hide(20.0)
            clip.add(Actor(card(120, 32, [final], size=15, stroke=TEAL, fill="#e6f4f5",
                                ink=TEAL, weight="bold"), x, ys[i]).show(21.0))
        else:
            guessed.hide(16.0)
            clip.add(Actor(card(120, 32, [final], size=15, stroke=TEAL, fill="#e6f4f5",
                                ink=TEAL, weight="bold"), x, ys[i]).show(18.0))
    # a marker for "you are reading this one" moves down the list ...
    clip.add(Actor(tick(PLUM, 14), 395, ys[0]).show(7.5).move(12.0, 395, ys[1], 1.0)
             .move(14.5, 395, ys[2], 1.0).hide(16.0))
    # ... and a green tick stays beside each answer once you have accepted or fixed its code
    for row, when in ((0, 10.5), (2, 15.0), (1, 19.5)):
        clip.add(Actor(tick(GREEN, 12), 395, ys[row]).show(when))
    clip.say(["QualSafe suggests a code for each answer."], 1.5, 6.5)
    clip.say(["You read each answer and its suggestion."], 7.5, 13.0)
    clip.say(["Where a suggestion is wrong, you change it."], 14.0, 20.0)
    clip.say(["What you decide is what gets counted."], 22.0)
    return clip


def what_agreement_means() -> Clip:
    clip = Clip(
        "what-agreement-means", "What agreement tells you",
        "Two coders each mark ten answers for one code, Money. Coder A and Coder B choose the same "
        "on eight of the ten. Because most answers are no for this code, luck alone would match "
        "often, so agreement takes luck off the score and shows 0.52. It is worked out for each "
        "code separately. A second code that was used on very few answers shows no figure.",
        34)
    a = [1, 0, 0, 1, 0, 0, 0, 1, 0, 0]
    b = [1, 0, 0, 0, 0, 0, 0, 1, 1, 0]
    x0, dx = 190, 40
    clip.add(Actor(text(["Code: Money"], 18, INK, "bold"), 320, 40).show(0.5))
    clip.add(Actor(text(["Coder A"], 15, MUTED), 100, 90).show(1.0))
    clip.add(Actor(text(["Coder B"], 15, MUTED), 100, 150).show(1.0))
    for i in range(10):
        x = x0 + dx * i
        for row, marks, y in ((0, a, 90), (1, b, 150)):
            filled = marks[i]
            shape = card(28, 28, [""], fill=PLUM if filled else PAPER, stroke=PLUM if filled else LINE,
                         radius=5)
            clip.add(Actor(shape, x, y).show(2.0 + 0.25 * i + 0.1 * row, 0.3))
    clip.add(Actor(text(["Filled means: this code applies"], 13, MUTED), 320, 192).show(5.5))
    for i in range(10):
        x = x0 + dx * i
        same = a[i] == b[i]
        clip.add(Actor(tick(GREEN, 9) if same else cross(RED, 8), x, 125).show(8.0 + 0.25 * i, 0.2))
    clip.add(Actor(text(["Same on 8 of 10 answers"], 17, INK, "bold"), 320, 225).show(11.5)
             .hide(18.0))
    clip.add(Actor(card(350, 40, ["Most answers are \"no\", so luck matches often"], size=14,
                        fill="#fff4e0", stroke=AMBER, ink=AMBER), 320, 225).show(19.0).hide(24.0))
    clip.add(Actor(card(220, 48, ["Agreement  0.52"], size=20, fill="#e6f4f5", stroke=TEAL,
                        ink=TEAL, weight="bold"), 320, 225).show(25.0))
    clip.add(Actor(card(300, 40, ["Support: used on too few answers, no figure"], size=13,
                        fill="#f1f1f4", stroke=LINE, ink=MUTED), 320, 270).show(30.0))
    clip.say(["Agreement counts how often two coders chose the same."], 3.0, 10.5)
    clip.say(["It takes luck off the score."], 12.0, 18.5)
    clip.say(["It is worked out for each code on its own."], 20.0, 26.5)
    clip.say(["Too few answers: no figure."], 30.0)
    return clip


def who_is_speaking() -> Clip:
    clip = Clip(
        "who-is-speaking", "Why you confirm who is speaking",
        "A short made-up interview with two speakers, A and B. QualSafe notices that A asks "
        "the questions and proposes that A is the interviewer and B the participant. You confirm "
        "or correct that. Once you do, the interviewer's lines are set apart with a grey veil and "
        "the participant's lines get a purple bar, because the participant's words are what you code.",
        26)
    lines = [("A:", "How has your first term gone?"), ("B:", "Busy, but I like my classes."),
             ("A:", "What has been hardest?"), ("B:", "Paying for books. It adds up.")]
    ys = [75, 125, 175, 225]
    for i, (who, said) in enumerate(lines):
        row = text([f"{who}  {said}"], 16, INK, anchor="start")
        clip.add(Actor(row, 120, ys[i]).show(0.5 + 0.5 * i))
    clip.add(Actor(card(240, 34, ["A asks the questions"], size=14, fill="#fff4e0", stroke=AMBER,
                        ink=AMBER), 480, 100).show(5.0).hide(11.0))
    clip.add(Actor(card(250, 34, ["A = Interviewer ?   B = Participant ?"], size=13, dashed=True,
                        stroke=MUTED, ink=MUTED), 450, 150).show(8.0).hide(14.0))
    clip.add(Actor(tick(PLUM, 14), 600, 150).show(13.0).hide(17.0))
    for i, (who, _said) in enumerate(lines):
        if who == "A:":
            veil = (f'<rect x="-8" y="-18" width="400" height="34" rx="5" fill="#ffffff" '
                    f'fill-opacity="0.55"/>')
            clip.add(Actor(veil, 120, ys[i]).show(15.0))
        else:
            clip.add(Actor(f'<rect x="-4" y="-16" width="6" height="30" rx="3" fill="{PLUM}"/>',
                           108, ys[i]).show(16.0))
    clip.say(["QualSafe looks at who asks the questions."], 4.5, 10.0)
    clip.say(["It proposes who is the interviewer."], 10.5, 14.5)
    clip.say(["You confirm it, or correct it."], 14.7, 19.0)
    clip.say(["The participant's words are the ones you code."], 19.5)
    return clip




# -- shapes for the modelling clips -----------------------------------------------------------

def dot(filled: bool, color: str = TEAL, r: float = 9) -> str:
    """A person: filled means finished the term, hollow means did not."""
    if filled:
        return f'<circle cx="0" cy="0" r="{_num(r)}" fill="{color}" stroke="{color}" stroke-width="2"/>'
    return f'<circle cx="0" cy="0" r="{_num(r)}" fill="{PAPER}" stroke="{MUTED}" stroke-width="2.5"/>'


def line(dx: float, dy: float, color: str = LINE, width: float = 3) -> str:
    """A line from (0, 0) to (dx, dy): placed at its start, so it grows out of it."""
    return (f'<line x1="0" y1="0" x2="{_num(dx)}" y2="{_num(dy)}" stroke="{color}" '
            f'stroke-width="{_num(width)}" stroke-linecap="round"/>')


def chip(label: str, w: float = 96, *, fill: str = "#f1f1f4", stroke: str = LINE, ink: str = INK,
         weight: str = "normal", size: int = 13) -> str:
    return card(w, 26, [label], size=size, fill=fill, stroke=stroke, ink=ink, weight=weight, radius=13)


def ring(w: float, h: float, color: str) -> str:
    return (f'<rect x="{_num(-w / 2)}" y="{_num(-h / 2)}" width="{_num(w)}" height="{_num(h)}" '
            f'rx="{_num(h / 2)}" fill="none" stroke="{color}" stroke-width="4"/>')


def tree_icon(color: str = TEAL) -> str:
    """A tiny tree: a trunk and two branches, each ending in a leaf."""
    return (f'<path d="M0 22 L0 0 M0 0 L-18 -16 M0 0 L18 -16 M-18 -16 L-28 -28 M-18 -16 L-8 -28 '
            f'M18 -16 L8 -28 M18 -16 L28 -28" stroke="{color}" stroke-width="3.5" fill="none" '
            f'stroke-linecap="round"/>'
            + "".join(f'<circle cx="{x}" cy="{y}" r="5" fill="{color}"/>'
                      for x, y in ((-28, -28), (-8, -28), (8, -28), (28, -28))))


def readable_tree() -> Clip:
    clip = Clip(
        "readable-tree", "Why a decision tree is easy to read",
        "Twelve made-up students are shown, filled if they finished the term and hollow if not. "
        "A decision tree asks one yes-or-no question at a time. The first question, how many hours "
        "a week the student works, sends them down one of two branches. Those who work twenty hours "
        "or more are asked a second question, whether they have a study group. Each student ends "
        "up in one group, and you can read the path down to any group in plain words.",
        32)
    # twelve people: (works 20+ hours, has study group, finished)
    people = [(1, 1, 1), (1, 1, 1), (1, 1, 0), (1, 0, 0), (1, 0, 0), (1, 0, 0),
              (0, 0, 1), (0, 0, 1), (0, 1, 1), (0, 1, 1), (0, 0, 1), (0, 0, 0)]
    start = [(290 + 28 * (i % 6) + (14 if (i // 6) else 0), 118 + 32 * (i // 6)) for i in range(12)]
    # the groups they end up in: a box each, with the people inside and the count below them
    leaves = {"a1": (90, 235), "a2": (250, 235), "b": (480, 235)}
    clip.add(Actor(text(["Filled: finished the term.   Hollow: did not."], 13, MUTED), 320, 28).show(0.5))
    # boxes first, so the people are drawn in front of them
    for key, (lx, ly) in leaves.items():
        width = 150 if key != "b" else 170
        clip.add(Actor(card(width, 88, [""], fill="#fafafc", stroke=LINE, radius=10), lx, ly).show(19.0))
    for key, said in (("a1", "2 of 3 finish"), ("a2", "0 of 3 finish"), ("b", "5 of 6 finish")):
        lx, ly = leaves[key]
        clip.add(Actor(text([said], 14, INK, "bold"), lx, ly + 31).show(24.0))
    taken = {"a1": 0, "a2": 0, "b": 0}
    for n, (where, (works, group, finished)) in enumerate(zip(start, people)):
        leaf = "b" if not works else ("a1" if group else "a2")
        slot = taken[leaf]
        taken[leaf] += 1
        cols = 4 if leaf == "b" else 3
        lx, ly = leaves[leaf]
        end = (lx - 28 * (cols - 1) / 2 + 28 * (slot % cols), ly - 20 + 26 * (slot // cols))
        person = clip.add(Actor(dot(bool(finished)), where[0], where[1]).show(1.0 + 0.15 * n, 0.3))
        person.move(21.0, end[0], end[1], 2.0)
    clip.add(Actor(card(210, 36, ["Hours worked each week"], size=15, fill="#f3e9f6", stroke=PLUM,
                        ink=PLUM, weight="bold"), 320, 62).show(8.0))
    clip.add(Actor(line(-130, 52), 290, 80).show(11.0))
    clip.add(Actor(line(130, 52), 350, 80).show(11.5))
    clip.add(Actor(line(0, 61), 480, 132).show(19.0))
    clip.add(Actor(text(["20 or more"], 13, MUTED), 150, 104).show(12.0))
    clip.add(Actor(text(["under 20"], 13, MUTED), 490, 104).show(12.0))
    clip.add(Actor(card(170, 32, ["Has a study group?"], size=14, fill="#f3e9f6", stroke=PLUM,
                        ink=PLUM, weight="bold"), 160, 152).show(14.0))
    clip.add(Actor(line(-70, 27), 130, 168).show(16.0))
    clip.add(Actor(line(70, 27), 190, 168).show(16.5))
    clip.add(Actor(text(["yes"], 13, MUTED), 84, 180).show(17.0))
    clip.add(Actor(text(["no"], 13, MUTED), 266, 180).show(17.0))
    clip.say(["Twelve students. Some finished the term, some did not."], 1.5, 7.0)
    clip.say(["A decision tree asks one yes-or-no question at a time."], 8.5, 14.0)
    clip.say(["Each answer sends people down a branch."], 14.5, 20.0)
    clip.say(["Read down any branch to see who ended up there."], 22.0, 28.0)
    clip.say(["Every group can be explained in plain words."], 28.5)
    return clip


def random_forest() -> Clip:
    clip = Clip(
        "random-forest", "What a random forest does",
        "A random forest builds many decision trees. Five small trees appear, each learning from "
        "a different random sample of the students. A new made-up student is shown to each tree "
        "and each tree votes on whether the student will finish the term. Four trees say yes and "
        "one says no, and the most common vote is the forest's answer. A forest is usually more "
        "accurate than one tree, but it cannot be read as a single set of rules.",
        34)
    xs = [90, 205, 320, 435, 550]
    for i, x in enumerate(xs):
        clip.add(Actor(tree_icon(), x, 108).show(1.5 + 0.8 * i))
    for i, x in enumerate(xs):
        sample = card(84, 30, [f"sample {i + 1}"], size=12, fill="#f1f1f4", stroke=LINE, ink=MUTED)
        clip.add(Actor(sample, x, 40).show(8.0 + 0.5 * i))
        clip.add(Actor(line(0, 24, LINE, 2), x, 56).show(8.5 + 0.5 * i))
    votes = [True, True, False, True, True]
    for i, (x, yes) in enumerate(zip(xs, votes)):
        when = 16.0 + 0.5 * i
        clip.add(Actor(line(0, 28, LINE, 2), x, 134).show(when))
        vote = (card(88, 56, [""], fill="#fafafc", stroke=LINE)
                + f'<g transform="translate(0 -10)">{tick(GREEN, 11) if yes else cross(RED, 9)}</g>'
                + f'<g transform="translate(0 16)">{text(["finishes" if yes else "does not"], 13)}</g>')
        clip.add(Actor(vote, x, 192).show(when + 0.3))
    clip.add(Actor(text(["Each tree votes on a new student"], 13, MUTED), 320, 236).show(18.5))
    clip.add(Actor(card(260, 36, ["4 say finishes, 1 says does not"], size=14, fill="#fff4e0",
                        stroke=AMBER, ink=AMBER), 320, 268).show(21.0).hide(25.5))
    clip.add(Actor(card(260, 40, ["The forest says: finishes"], size=16, fill="#e6f4f5", stroke=TEAL,
                        ink=TEAL, weight="bold"), 320, 268).show(26.0))
    clip.say(["A forest builds many trees."], 1.5, 7.0)
    clip.say(["Each tree learns from a different random sample."], 8.0, 14.5)
    clip.say(["Each tree votes on a new student."], 15.5, 21.5)
    clip.say(["The most common vote is the forest's answer."], 22.0, 29.0)
    clip.say(["Usually more accurate than one tree, but harder to read."], 29.5)
    return clip


def double_lasso() -> Clip:
    clip = Clip(
        "double-lasso", "How double lasso picks what to allow for",
        "You want the effect of one thing, having a study group, on an outcome, finishing the "
        "term. Many other details, such as hours worked and credits, could get in the way. Pass one "
        "keeps the details that help predict the outcome. Pass two keeps the details that help "
        "predict the one thing. Every detail picked in either pass is allowed for, and the rest "
        "are set aside. The effect is then estimated with a range that stays trustworthy.",
        42)
    clip.add(Actor(card(230, 40, ["Outcome: finishing the term"], size=14, fill="#f3e9f6", stroke=PLUM,
                        ink=PLUM, weight="bold"), 150, 50).show(1.0))
    clip.add(Actor(card(240, 40, ["The one thing: a study group"], size=14, fill="#e6f4f5", stroke=TEAL,
                        ink=TEAL, weight="bold"), 490, 50).show(2.0))
    names = ["Age", "Hours worked", "Housing", "First generation", "Commute", "Major", "Credits", "Aid"]
    pos = [(110 + 140 * (i % 4), 140 + 52 * (i // 4)) for i in range(8)]
    pass1 = {1, 6, 7}           # Hours worked, Credits, Aid
    pass2 = {1, 3, 4}           # Hours worked, First generation, Commute
    union = pass1 | pass2
    chips = []
    for i, (name, (x, y)) in enumerate(zip(names, pos)):
        c = Actor(chip(name, 124), x, y).show(6.0 + 0.3 * i, 0.3)
        chips.append(c)
        clip.add(c)
    for i, (x, y) in enumerate(pos):
        if i in pass1:
            clip.add(Actor(ring(138, 38, TEAL), x, y).show(14.0 + 0.5 * sorted(pass1).index(i), 0.3))
        if i in pass2:
            clip.add(Actor(ring(150, 46, PLUM), x, y).show(21.0 + 0.5 * sorted(pass2).index(i), 0.3))
    for i, c in enumerate(chips):
        if i not in union:
            # set aside: shrink to half size and stay put
            c._size += [(28.0, (1.0,)), (29.0, (0.55,))]
    clip.add(Actor(card(210, 28, ["Pass 1: predicts the outcome"], size=13, fill="#e6f4f5", stroke=TEAL,
                        ink=TEAL), 150, 248).show(13.5).hide(20.0))
    clip.add(Actor(card(230, 28, ["Pass 2: predicts the one thing"], size=13, fill="#f3e9f6", stroke=PLUM,
                        ink=PLUM), 490, 248).show(20.5).hide(27.0))
    clip.add(Actor(card(300, 28, ["Allowed for: every detail from either pass"], size=13, fill="#e8f5ec",
                        stroke=GREEN, ink=GREEN), 320, 248).show(28.0).hide(34.0))
    clip.add(Actor(card(380, 40, ["8 more in every 100 finish (range 3 to 13)"], size=15, fill="#e6f4f5",
                        stroke=TEAL, ink=TEAL, weight="bold"), 320, 252).show(35.0))
    clip.say(["You want the effect of one thing on an outcome."], 1.5, 5.5)
    clip.say(["Many other details could get in the way."], 6.0, 12.5)
    clip.say(["Pass 1 keeps the details that help predict the outcome."], 13.5, 20.0)
    clip.say(["Pass 2 keeps the details that help predict the one thing."], 20.5, 27.0)
    clip.say(["Every detail from either pass is allowed for."], 28.0, 34.0)
    clip.say(["Then the effect is estimated, with a trustworthy range."], 35.0)
    return clip


def lasso_no_p_values() -> Clip:
    clip = Clip(
        "lasso-no-p-values", "Why lasso shows no p-values",
        "A lasso looks at your data and keeps only the details that help predict the outcome. Here "
        "it keeps three of eight. A p-value assumes you chose what to test before you looked at the "
        "data, but the data chose these details, so a p-value would look surer than it is and is not "
        "shown. Instead you see which details were kept and how well they predict new students.",
        34)
    names = ["Age", "Hours worked", "Housing", "First generation", "Commute", "Major", "Credits", "Aid"]
    pos = [(120 + 134 * (i % 4), 130 + 46 * (i // 4)) for i in range(8)]
    kept = {1, 6, 7}
    for i, (name, (x, y)) in enumerate(zip(names, pos)):
        clip.add(Actor(chip(name, 118), x, y).show(1.0 + 0.3 * i, 0.3))
    clip.add(Actor(card(150, 34, ["Your data"], size=14, fill="#f1f1f4", stroke=LINE, ink=MUTED), 320, 50)
             .show(4.5))
    clip.add(Actor(line(0, 34, LINE, 3), 320, 68).show(6.0))
    for i, (x, y) in enumerate(pos):
        if i in kept:
            clip.add(Actor(ring(132, 36, TEAL), x, y).show(7.5 + 0.5 * sorted(kept).index(i), 0.3))
    clip.add(Actor(card(130, 36, ["p = 0.01"], size=18, fill="#fff4e0", stroke=AMBER, ink=AMBER,
                        weight="bold"), 320, 258).show(14.0).hide(25.0))
    clip.add(Actor(cross(RED, 22), 320, 258).show(19.0).hide(25.0))
    clip.add(Actor(card(430, 40, ["Shown instead: what was kept, and how well it predicts"], size=14,
                        fill="#e6f4f5", stroke=TEAL, ink=TEAL), 320, 258).show(27.0))
    clip.say(["A lasso looks at the data and keeps the details that help."], 1.5, 8.0)
    clip.say(["The data chose which details to keep."], 8.5, 14.0)
    clip.say(["A p-value assumes you chose before looking."], 14.5, 21.0)
    clip.say(["So a p-value here would look surer than it is."], 21.5, 27.0)
    clip.say(["You see what was kept and how well it predicts."], 28.0)
    return clip


BUILDERS = {"suggest-and-check": suggest_and_check, "what-agreement-means": what_agreement_means,
            "who-is-speaking": who_is_speaking, "readable-tree": readable_tree,
            "random-forest": random_forest, "double-lasso": double_lasso,
            "lasso-no-p-values": lasso_no_p_values}


def build_all() -> Dict[str, str]:
    out = {}
    for clip_id, build in BUILDERS.items():
        clip = build()
        listed = media.get(clip_id)
        if listed is None or listed.seconds != clip.seconds:
            raise SystemExit(f"{clip_id}: its length in media.CLIPS must be {clip.seconds} seconds")
        out[clip_id] = clip.render()
    return out


def main(argv: Sequence[str] = ()) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="write nothing; exit 1 if a file is out of date")
    args = parser.parse_args(list(argv) or sys.argv[1:])
    media.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    stale = []
    for clip_id, svg in build_all().items():
        path = media.path_of(clip_id)
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != svg:
                stale.append(clip_id)
        else:
            path.write_text(svg, encoding="utf-8", newline="\n")
            print(f"wrote {path.relative_to(ROOT)} ({len(svg) // 1024} KB)")
    if stale:
        print("out of date:", ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
