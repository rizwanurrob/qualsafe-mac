"""
The code network (v4.7, `V5_PLAN.md` §B8).

The picture every rival ships and this project did not. What is under test is
mostly not "does it draw" — it is the three properties that make it worth
shipping rather than a fourth copy of what NVivo already does.

**It is reproducible.** The same project produces the same coordinates, in this
process and the next one. Every rival's network view is force-directed from a
random seed and rearranges itself on every open, which is why nobody cites one.
A figure a reviewer cannot reproduce is a screenshot, not a figure.

**It is a picture of relationships, not of frequency.** Edges are Jaccard, so a
code applied to half the corpus does not appear joined to everything.

**It says what it hid.** Thresholding is unavoidable; hiding the thresholding
is not.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.code_network import (
    DEFAULT_MIN_STRENGTH, LAYOUT_ITERATIONS, READABLE_NODE_LIMIT,
    build_code_network, network_from_project)
from core.model import Code, CodeApplication, Excerpt, Source
from core.project import Project


def coding(pairs, rater="human_primary"):
    """Build a coding table from ``[(unit_id, code_name), ...]``."""
    return pd.DataFrame([
        {"excerpt_id": f"e{unit}", "source_id": f"s{unit}",
         "code_name": name, "rater_id": rater}
        for unit, name in pairs
    ])


def linked(code_a, code_b, times, start=0):
    """`times` units carrying both codes."""
    return [(start + i, name) for i in range(times) for name in (code_a, code_b)]


class TestItIsReproducible:
    """The property that distinguishes this from every rival's version."""

    def test_the_same_input_gives_the_same_coordinates(self):
        table = coding(linked("Cost", "Access", 6) + linked("Cost", "Staff", 5, start=6))

        first = build_code_network(table)
        second = build_code_network(table)

        assert [(n.name, n.x, n.y) for n in first.nodes] == \
               [(n.name, n.x, n.y) for n in second.nodes]

    def test_row_order_does_not_move_the_picture(self):
        """A coding table is not ordered, so an implementation that depended on
        row order would produce a different figure after any re-import."""
        table = coding(linked("Cost", "Access", 6) + linked("Cost", "Staff", 5, start=6))
        shuffled = table.iloc[::-1].reset_index(drop=True)

        assert [(n.name, n.x, n.y) for n in build_code_network(table).nodes] == \
               [(n.name, n.x, n.y) for n in build_code_network(shuffled).nodes]

    def test_the_layout_has_no_random_seed_because_it_has_no_randomness(self):
        """Checked on the source: a seeded RNG is reproducible only until
        somebody reorders the calls, and this must be reproducible across
        machines and processes."""
        import analysis.code_network as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        for banned in ("np.random", "random.random", "random.seed", "default_rng"):
            assert banned not in source, f"{banned} in a layout that must be stable"

    def test_the_iteration_count_is_fixed(self):
        assert isinstance(LAYOUT_ITERATIONS, int) and LAYOUT_ITERATIONS > 0

    def test_every_node_lands_inside_the_unit_box(self):
        table = coding(linked("Cost", "Access", 6) + linked("Staff", "Wait", 6, start=6))

        network = build_code_network(table)

        assert all(0.0 <= n.x <= 1.0 and 0.0 <= n.y <= 1.0 for n in network.nodes)

    def test_identical_positions_do_not_divide_by_zero(self):
        """Two codes on the same units can converge to the same point."""
        network = build_code_network(coding(linked("Cost", "Access", 8)))

        assert network.usable
        assert all(n.x == n.x for n in network.nodes)      # not NaN


class TestTheLayoutIsReadable:
    """The tests that were missing.

    The first version placed everything with one force simulation and produced a
    valid Vega-Lite spec, correct edges, correct strengths, and an unusable
    picture: nothing attracts an unconnected code, so repulsion alone threw it
    to the far corner, where it set the bounding box and normalised the actual
    structure into six percent of the canvas. Twenty-seven tests passed. Only
    rendering it showed the problem, so these assert on the geometry that
    rendering revealed.
    """

    @staticmethod
    def _spans(network):
        connected = [n for n in network.nodes if n.name not in set(network.isolated)]
        xs = [n.x for n in connected]
        ys = [n.y for n in connected]
        return max(xs) - min(xs), max(ys) - min(ys)

    def test_one_unconnected_code_does_not_squash_the_graph(self):
        rows = linked("Cost", "Access", 12) + linked("Staff", "Wait", 8, start=12)
        rows += linked("Cost", "Staff", 4, start=20) + [(99, "Orphan")]

        with_orphan = build_code_network(coding(rows))
        x_span, y_span = self._spans(with_orphan)

        assert x_span > 0.5, f"connected graph squashed to {x_span:.3f} of the width"
        assert y_span > 0.5, f"connected graph squashed to {y_span:.3f} of the height"

    def test_adding_an_unconnected_code_barely_moves_the_connected_ones(self):
        """The structure is a property of the graph. A code that is in no
        relationship is not part of the graph and must not redraw it."""
        rows = linked("Cost", "Access", 12) + linked("Staff", "Wait", 8, start=12)
        rows += linked("Cost", "Staff", 4, start=20)

        without = {n.name: (n.x, n.y) for n in build_code_network(coding(rows)).nodes}
        with_orphan = {n.name: (n.x, n.y)
                       for n in build_code_network(coding(rows + [(99, "Orphan")])).nodes}

        for name, (x, y) in without.items():
            moved_x = abs(with_orphan[name][0] - x)
            assert moved_x < 0.25, f"{name} moved {moved_x:.3f} in x"
            assert with_orphan[name][1] == pytest.approx(y), f"{name} moved in y"

    def test_unconnected_codes_are_parked_together_not_scattered(self):
        rows = linked("Cost", "Access", 12) + [(97, "OrphanA"), (98, "OrphanB")]

        network = build_code_network(coding(rows))
        parked = [n for n in network.nodes if n.name.startswith("Orphan")]

        assert len({round(n.x, 6) for n in parked}) == 1, "not in one column"
        assert len({round(n.y, 6) for n in parked}) == 2, "stacked on one point"

    def test_two_codes_that_co_occur_are_not_drawn_on_top_of_each_other(self):
        network = build_code_network(coding(linked("Cost", "Access", 8)))
        a, b = network.nodes

        assert abs(a.x - b.x) + abs(a.y - b.y) > 0.1

    def test_a_graph_with_no_edges_at_all_still_places_every_node(self):
        """Refused as a network, but the layout must not crash on the way."""
        from analysis.code_network import _layout

        placed = _layout(["A", "B", "C"], [])

        assert len(placed) == 3
        assert len({(round(x, 6), round(y, 6)) for x, y in placed.values()}) == 3


class TestItMapsRelationshipsNotFrequency:

    def test_edges_are_jaccard_not_counts(self):
        """A code on almost everything must not come out joined to everything.

        "Everywhere" appears on all 20 units; "Rare" appears on 2, both shared
        with Everywhere. Raw counts would make Everywhere–Common the strongest
        edge by far. Jaccard says Rare is entirely contained in Everywhere.
        """
        rows = [(i, "Everywhere") for i in range(20)]
        rows += [(i, "Common") for i in range(10)]
        rows += [(i, "Rare") for i in range(2)]

        network = build_code_network(coding(rows), min_strength=0.0)
        strengths = {frozenset(e.key): e.strength for e in network.edges}

        assert strengths[frozenset(("Everywhere", "Rare"))] == pytest.approx(0.1)
        assert strengths[frozenset(("Everywhere", "Common"))] == pytest.approx(0.5)

    def test_a_pair_that_never_co_occurs_has_no_edge(self):
        rows = [(0, "Cost"), (1, "Access")]

        network = build_code_network(coding(rows), min_strength=0.0)

        assert network.edges == []

    def test_node_size_is_the_number_of_units_carrying_the_code(self):
        rows = [(i, "Cost") for i in range(7)] + [(0, "Access")]

        network = build_code_network(coding(rows), min_strength=0.0)
        counts = {n.name: n.count for n in network.nodes}

        assert counts == {"Cost": 7, "Access": 1}

    def test_the_edge_carries_its_own_evidence(self):
        network = build_code_network(coding(linked("Cost", "Access", 6)))

        edge = network.edges[0]
        assert edge.count == 6
        assert len(network.edge_units[("Access", "Cost")]) == 6


class TestItSaysWhatItHid:

    def test_weak_edges_are_counted_not_silently_dropped(self):
        rows = [(i, "Everywhere") for i in range(20)]
        rows += [(i, "Rare") for i in range(1)]          # jaccard 0.05

        network = build_code_network(coding(rows), min_strength=0.5)

        assert network.edges_hidden == 1

    def test_the_caveats_report_the_hidden_count_and_the_threshold(self):
        rows = [(i, "Everywhere") for i in range(20)]
        rows += [(i, "Rare") for i in range(1)]
        rows += [(i, "Other") for i in range(10)]

        network = build_code_network(coding(rows), min_strength=0.4)
        blob = " ".join(network.caveats())

        assert "0.4" in blob
        assert "not drawn" in blob

    def test_an_unconnected_code_is_drawn_rather_than_removed(self):
        """"This code relates to nothing" is a finding about the codebook."""
        rows = linked("Cost", "Access", 6) + [(99, "Orphan")]

        network = build_code_network(coding(rows))

        assert "Orphan" in network.isolated
        assert "Orphan" in {n.name for n in network.nodes}

    def test_the_caveats_name_the_unconnected_codes(self):
        rows = linked("Cost", "Access", 6) + [(99, "Orphan")]

        blob = " ".join(build_code_network(coding(rows)).caveats())

        assert "Orphan" in blob

    def test_the_caveats_say_closeness_is_not_meaning(self):
        network = build_code_network(coding(linked("Cost", "Access", 6)))
        blob = " ".join(network.caveats()).lower()

        assert "not because they mean" in blob
        assert "merged" in blob

    def test_survey_mode_gets_the_co_mention_caveat(self):
        """An excerpt is the whole response in survey mode, so an edge is a
        looser claim than Dedoose's same-span co-occurrence."""
        network = build_code_network(coding(linked("Cost", "Access", 6)),
                                     unit="excerpt_id")

        assert any("co-mention" in note for note in network.caveats())

    def test_a_crowded_network_says_it_is_crowded(self):
        rows = []
        for i in range(READABLE_NODE_LIMIT + 5):
            rows += linked(f"Code{i:02d}", f"Code{(i + 1) % (READABLE_NODE_LIMIT + 5):02d}",
                           6, start=i * 10)

        network = build_code_network(coding(rows))

        assert any("legibly" in note for note in network.caveats())


class TestItRefusesWhenThereIsNothingToDraw:

    def test_an_empty_table_gets_a_sentence(self):
        network = build_code_network(pd.DataFrame())

        assert not network.usable
        assert "Nothing is coded yet" in network.refusal

    def test_one_code_cannot_form_a_network(self):
        network = build_code_network(coding([(0, "Cost"), (1, "Cost")]))

        assert not network.usable
        assert "at least two codes" in network.refusal

    def test_no_surviving_edge_is_a_refusal_that_suggests_the_threshold(self):
        rows = [(i, "Everywhere") for i in range(20)] + [(0, "Rare")]

        network = build_code_network(coding(rows), min_strength=0.9)

        assert not network.usable
        assert "threshold is too high" in network.refusal

    def test_the_default_threshold_is_stated_not_hidden(self):
        assert 0.0 < DEFAULT_MIN_STRENGTH < 1.0
        network = build_code_network(coding(linked("Cost", "Access", 6)))
        assert network.min_strength == DEFAULT_MIN_STRENGTH


class TestTheFramesARendererGets:

    def test_edges_carry_both_endpoints_so_no_join_is_needed(self):
        """Vega-Lite and QPainter both want segments, and doing the join once
        here is what keeps the two front ends drawing the same picture."""
        network = build_code_network(coding(linked("Cost", "Access", 6)))

        edges = network.to_frames()["edges"]

        assert set(["x", "y", "x2", "y2"]).issubset(edges.columns)
        positions = {n.name: (n.x, n.y) for n in network.nodes}
        row = edges.iloc[0]
        assert (row["x"], row["y"]) == positions[row["source"]]
        assert (row["x2"], row["y2"]) == positions[row["target"]]

    def test_the_node_frame_flags_the_unconnected_ones(self):
        rows = linked("Cost", "Access", 6) + [(99, "Orphan")]

        nodes = build_code_network(coding(rows)).to_frames()["nodes"]

        assert bool(nodes.set_index("code").at["Orphan", "isolated"])


class TestReadingFromAProject:

    @pytest.fixture()
    def project(self, tmp_path):
        path = tmp_path / "p.qnw"
        with Project.create(path) as project:
            codes = {name: project.add_code(Code(code_id="", name=name))
                     for name in ("Cost", "Access", "Staff")}
            for index in range(8):
                text = f"response {index}"
                source_id = project.add_source(Source(
                    source_id="", type="survey_response", raw_text=text,
                    label="Q1", metadata={"response_id": f"r{index}"}))
                excerpt = project.add_excerpt(Excerpt(
                    excerpt_id="", source_id=source_id, text=text,
                    char_start=0, char_end=len(text)))
                # Cost and Access always together; Staff only by a second rater.
                for name in ("Cost", "Access"):
                    project.apply_code(CodeApplication(
                        application_id="", excerpt_id=excerpt,
                        code_id=codes[name], rater_id="human_primary"))
                project.apply_code(CodeApplication(
                    application_id="", excerpt_id=excerpt,
                    code_id=codes["Staff"], rater_id="transformer"))
        return path

    def test_it_builds_from_a_store(self, project):
        with Project.open(project) as proj:
            network = network_from_project(proj)

        assert network.usable
        assert {n.name for n in network.nodes} == {"Cost", "Access", "Staff"}

    def test_restricting_to_one_rater_changes_the_picture(self, project):
        """Pooling raters inflates co-occurrence whenever two coders coded the
        same excerpt differently — the trap PORTED_BACK §5 recorded against the
        co-occurrence matrix."""
        with Project.open(project) as proj:
            pooled = network_from_project(proj)
            human = network_from_project(proj, rater_id="human_primary")

        assert {n.name for n in human.nodes} == {"Cost", "Access"}
        assert len(pooled.nodes) > len(human.nodes)

    def test_an_empty_project_refuses_rather_than_raising(self, tmp_path):
        path = tmp_path / "empty.qnw"
        Project.create(path).close()

        with Project.open(path) as proj:
            network = network_from_project(proj)

        assert not network.usable
        assert network.refusal


def test_the_module_adds_no_dependency():
    """numpy and pandas only. A project whose selling point is that it installs
    and runs offline should not gain networkx for one view."""
    import ast

    import analysis.code_network as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported = {(node.module or "").split(".")[0]
                for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imported |= {alias.name.split(".")[0]
                 for node in ast.walk(tree) if isinstance(node, ast.Import)
                 for alias in node.names}

    assert "networkx" not in imported
    assert "scipy" not in imported
