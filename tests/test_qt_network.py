"""
The desktop half of the code network (`V5_PLAN.md` §B8b).

The claim being defended is narrow and is the whole reason the feature is worth
shipping against ATLAS.ti, MAXQDA and NVivo: **the two builds draw the same
figure.** So the tests that matter here are not "does it paint" — they are that
this canvas computes no geometry of its own, and that what it does compute from
the shared layout stays inside the widget.

Everything is checked offscreen. The lesson from `test_qt_charts.py` applies:
rendering it is what finds the problems that structure tests miss.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("PySide6", reason="Qt front end not installed")

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402

from analysis.code_network import build_code_network  # noqa: E402
from qualsafe_qt.widgets.network_canvas import (  # noqa: E402
    _MARGIN, _MAX_RADIUS, NetworkCanvas)


def coding(pairs):
    return pd.DataFrame([
        {"excerpt_id": f"e{u}", "source_id": f"s{u}", "code_name": n,
         "rater_id": "h"}
        for u, n in pairs
    ])


def linked(a, b, times, start=0):
    return [(start + i, name) for i in range(times) for name in (a, b)]


@pytest.fixture()
def network():
    rows = linked("Cost", "Access", 12) + linked("Staff", "Wait", 8, start=12)
    rows += linked("Cost", "Staff", 4, start=20) + [(99, "Orphan")]
    return build_code_network(coding(rows))


@pytest.fixture()
def canvas(qapp, network):
    widget = NetworkCanvas()
    widget.resize(900, 600)
    widget.set_network(network)
    return widget


class TestItComputesNoGeometryOfItsOwn:
    """The point of the feature. If this canvas decided positions, the desktop
    figure and the web figure would be two similar pictures rather than one."""

    def test_the_canvas_does_not_lay_anything_out(self):
        """Checked on the parsed source rather than by comparing pictures: a
        second layout here would be a slow, quiet divergence."""
        import ast

        import qualsafe_qt.widgets.network_canvas as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        defined = {node.name for node in ast.walk(tree)
                   if isinstance(node, ast.FunctionDef)}

        assert "_layout" not in defined and "_force_directed" not in defined
        for banned in ("np.random", "networkx", "_circle("):
            assert banned not in source, f"{banned} in the painting layer"

    def test_it_reads_the_positions_the_shared_module_produced(self, canvas, network):
        """Node order and identity come from the network, not from the widget."""
        canvas.to_image(scale=1)

        painted = [name for _rect, name, _count in canvas._node_hits]
        assert painted == [node.name for node in network.nodes]


class TestEverythingStaysInsideTheWidget:
    """The bug this class exists for: a node at x = 1.0 is a *centre* on the
    boundary, so insetting by the margin alone draws the biggest circles half
    outside the widget."""

    def test_every_node_is_fully_inside(self, canvas):
        canvas.to_image(scale=1)
        frame = QRect(0, 0, canvas.width(), canvas.height())

        for rect, name, _count in canvas._node_hits:
            assert frame.contains(rect), f"{name} is drawn outside the widget"

    def test_the_largest_node_clears_the_edge(self, canvas):
        """The biggest circle is the one that overflows first."""
        canvas.to_image(scale=1)
        widest = max(canvas._node_hits, key=lambda hit: hit[0].width())

        assert widest[0].left() >= 0
        assert widest[0].right() <= canvas.width()

    def test_the_inset_leaves_room_for_a_radius_not_just_a_margin(self):
        assert _MAX_RADIUS > _MARGIN / 2, (
            "if this stops being true, revisit the inset arithmetic")

    def test_a_tiny_widget_does_not_crash(self, qapp, network):
        widget = NetworkCanvas()
        widget.resize(20, 20)
        widget.set_network(network)

        widget.to_image(scale=1)          # must not raise


class TestItPaints:

    def test_the_image_is_opaque(self, canvas):
        """A transparent PNG pasted into Word loses the figure against white."""
        image = canvas.to_image(scale=1)

        assert not image.isNull()
        assert image.pixelColor(2, 2).alpha() == 255

    def test_something_is_actually_drawn(self, canvas):
        """A canvas that painted nothing would pass every structural test."""
        image = canvas.to_image(scale=1)
        background = image.pixelColor(1, 1).rgb()

        different = sum(
            1
            for x in range(0, image.width(), 7)
            for y in range(0, image.height(), 7)
            if image.pixelColor(x, y).rgb() != background)

        assert different > 40, "the canvas is blank"

    def test_scaling_up_scales_the_image(self, canvas):
        assert canvas.to_image(scale=3).width() == canvas.width() * 3

    def test_both_themes_paint(self, canvas):
        for mode in ("dark", "light"):
            canvas.set_theme_mode(mode)
            assert not canvas.to_image(scale=1).isNull()

    def test_the_background_follows_the_theme(self, canvas):
        """The heatmap shipped a dark ramp in light mode once. Same trap."""
        canvas.set_theme_mode("dark")
        dark = canvas.to_image(scale=1).pixelColor(1, 1).rgb()
        canvas.set_theme_mode("light")
        light = canvas.to_image(scale=1).pixelColor(1, 1).rgb()

        assert dark != light


class TestItSaysWhyWhenThereIsNothingToShow:

    def test_a_refusal_is_shown_as_its_sentence(self, qapp):
        refused = build_code_network(pd.DataFrame())
        widget = NetworkCanvas()
        widget.resize(600, 400)

        widget.set_network(refused)

        assert not widget.has_network()
        assert "Nothing is coded yet" in widget._message

    def test_a_refused_network_still_paints_without_raising(self, qapp):
        widget = NetworkCanvas()
        widget.resize(600, 400)
        widget.set_network(build_code_network(pd.DataFrame()))

        assert not widget.to_image(scale=1).isNull()

    def test_no_network_at_all_is_a_message_not_a_crash(self, qapp):
        widget = NetworkCanvas()
        widget.resize(600, 400)

        widget.set_network(None)

        assert not widget.has_network()
        assert not widget.to_image(scale=1).isNull()


class TestWhatAClickReports:

    def test_clicking_a_node_names_the_code(self, canvas, network):
        canvas.to_image(scale=1)
        rect, name, _count = canvas._node_hits[0]

        assert name in {n.name for n in network.nodes}
        assert rect.width() > 0

    def test_every_edge_is_hittable(self, canvas, network):
        canvas.to_image(scale=1)

        assert len(canvas._edge_hits) == len(network.edges)

    def test_the_tooltip_data_carries_strength_and_count(self, canvas):
        canvas.to_image(scale=1)
        _rect, _a, _b, strength, count = canvas._edge_hits[0]

        assert 0.0 <= strength <= 1.0
        assert count > 0
