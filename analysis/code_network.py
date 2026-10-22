#!/usr/bin/env python
"""
The code network: which codes travel together, drawn as a map.

Every rival ships one of these. ATLAS.ti calls them networks, MAXQDA calls them
MAXMaps, NVivo calls them concept maps, and they are the picture qualitative
researchers put in papers to show how a coding frame hangs together. QualSafe
has had the underlying numbers since v3 — `analysis/cooccurrence.py` — and has
only ever drawn them as a heatmap, which answers "how often do these two
co-occur" but not "what is the shape of this codebook".

Three decisions separate this from the rivals' version, and the first is the one
that matters.

**The layout is deterministic.** Open the same project twice and the map is
identical, pixel for pixel; so is the map on the desktop build, because the
geometry is computed here and both front ends only draw it. Every rival's
network view is force-directed from a random seed, so it rearranges itself each
time it opens — which means a researcher cannot cite one, cannot put "Figure 3"
in a paper and have a reviewer reproduce it, and cannot put two side by side and
say the frame changed. That is not a small usability nicety. It is the
difference between a picture and a figure.

**Edges are Jaccard, not raw counts.** A code applied to half the corpus
co-occurs often with everything, so a raw-count network is a picture of code
frequency wearing the costume of a picture of code relationships. Jaccard is
size-independent: it asks what share of the units carrying either code carry
both.

**It says what it hid.** Every network view is a thresholded view — draw every
edge and you get a black disc — so the threshold is stated, and the number of
relationships it removed is reported alongside the picture rather than left for
the reader to assume was zero.

What this is not
----------------
It is a map of co-occurrence, not of meaning. Two codes sit close because they
were applied to the same units, which can mean they are conceptually related, or
that they are redundant and should be merged, or that one is a sub-case of the
other, or that a single long response happened to attract both. Reading the
excerpts behind an edge is the only way to tell, which is why `edge_units`
carries the drill-down ids.

And note the unit. In survey mode an excerpt is the whole response, so an edge
means "the same person's answer carried both codes" — co-mention, not
same-span. That is a looser claim than Dedoose's same-span co-occurrence, and it
travels with the graph in `caveats()` rather than being left in a docstring
nobody reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from analysis.cooccurrence import cooccurrence_jaccard, cooccurrence_matrix

#: Below this Jaccard, an edge is noise: two codes that share one unit out of
#: forty tell you nothing, and drawing it buries the edges that do.
DEFAULT_MIN_STRENGTH = 0.10

#: Above roughly this many codes a network stops being readable at any layout
#: quality, and the honest answer is a different view rather than a worse map.
READABLE_NODE_LIMIT = 40

#: Fixed. Not a tuning knob: it is what makes the picture reproducible.
LAYOUT_ITERATIONS = 300


@dataclass(frozen=True)
class Node:
    """One code, placed."""

    name: str
    #: Units carrying this code — the diagonal of the co-occurrence matrix.
    count: int
    x: float
    y: float


@dataclass(frozen=True)
class Edge:
    """One relationship between two codes, with the evidence behind it."""

    source: str
    target: str
    #: Jaccard similarity, 0..1. Size-independent by construction.
    strength: float
    #: Units carrying both codes.
    count: int

    @property
    def key(self) -> Tuple[str, str]:
        return (self.source, self.target)


@dataclass(frozen=True)
class CodeNetwork:
    """A drawable map of a codebook, and everything needed to qualify it."""

    nodes: List[Node]
    edges: List[Edge]
    unit: str
    min_strength: float
    #: Relationships that existed but fell below the threshold. Reported, never
    #: silently dropped: a network that hides its own filtering is a graph of
    #: whatever the author wanted to show.
    edges_hidden: int = 0
    #: Codes with no surviving edge. Drawn, not discarded — "this code connects
    #: to nothing" is a finding, and removing it would hide it.
    isolated: List[str] = field(default_factory=list)
    #: Set when no map was produced, saying why in a sentence.
    refusal: str = ""
    #: Drill-down: the unit ids behind each edge, keyed (a, b) with a < b.
    edge_units: Dict[Tuple[str, str], List[str]] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return not self.refusal and bool(self.nodes)

    def caveats(self) -> List[str]:
        """What has to be said alongside a picture like this."""
        notes = [
            "Codes sit close because they were applied to the same units, not "
            "because they mean similar things. An edge can mean the two are "
            "related, that they are redundant and should be merged, that one is "
            "a sub-case of the other, or that one long response drew both. "
            "Reading the excerpts behind the edge is the only way to tell.",
        ]
        if self.unit == "excerpt_id":
            notes.append(
                "The unit is the excerpt. In survey mode that is the whole "
                "response, so an edge means both codes were applied to the same "
                "person's answer — co-mention, not the same span of text.")
        if self.edges_hidden:
            notes.append(
                f"{self.edges_hidden} relationship(s) fell below the "
                f"{self.min_strength:g} strength threshold and are not drawn. "
                "Lower the threshold to see them.")
        if self.isolated:
            listed = ", ".join(self.isolated[:5])
            more = f" and {len(self.isolated) - 5} more" if len(self.isolated) > 5 else ""
            notes.append(
                f"No relationship above the threshold for: {listed}{more}. "
                "They are drawn unconnected rather than removed.")
        if len(self.nodes) > READABLE_NODE_LIMIT:
            notes.append(
                f"{len(self.nodes)} codes is more than a network diagram can "
                "show legibly. Treat this as an overview and use the "
                "co-occurrence matrix for specific pairs.")
        return notes

    def to_frames(self) -> Dict[str, pd.DataFrame]:
        """Node and edge tables ready for a chart layer or an export.

        The edge table carries both endpoints' coordinates so a renderer can
        draw a segment without joining anything — Vega-Lite and QPainter both
        want it that way, and doing the join once here is what keeps the two
        front ends drawing the same picture.
        """
        positions = {node.name: (node.x, node.y) for node in self.nodes}
        nodes = pd.DataFrame([
            {"code": n.name, "count": n.count, "x": n.x, "y": n.y,
             "isolated": n.name in set(self.isolated)}
            for n in self.nodes
        ])
        edges = pd.DataFrame([
            {"source": e.source, "target": e.target,
             "strength": round(e.strength, 4), "count": e.count,
             "x": positions[e.source][0], "y": positions[e.source][1],
             "x2": positions[e.target][0], "y2": positions[e.target][1]}
            for e in self.edges
        ])
        return {"nodes": nodes, "edges": edges}


def build_code_network(
    coding_df: pd.DataFrame,
    *,
    unit: str = "excerpt_id",
    min_strength: float = DEFAULT_MIN_STRENGTH,
    label_col: str = "code_name",
    max_nodes: Optional[int] = None,
) -> CodeNetwork:
    """Build a placed, drawable code network from a coding table.

    `unit` chooses what counts as co-occurring: ``excerpt_id`` (default),
    ``source_id``, or ``respondent_id`` — the same choice
    `cooccurrence_matrix` offers, kept identical so the network and the heatmap
    can never disagree about the same project.

    `max_nodes` keeps the most-applied codes and says so; without it every code
    is drawn.
    """
    if coding_df is None or coding_df.empty or label_col not in coding_df.columns:
        return CodeNetwork(
            nodes=[], edges=[], unit=unit, min_strength=min_strength,
            refusal="Nothing is coded yet, so there are no relationships to map.")

    matrix, drill = cooccurrence_matrix(coding_df, label_col=label_col,
                                        group_col=unit)
    if matrix.empty or len(matrix.index) < 2:
        return CodeNetwork(
            nodes=[], edges=[], unit=unit, min_strength=min_strength,
            refusal=("A network needs at least two codes. With one code there "
                     "is nothing for it to relate to."))

    counts = {code: int(matrix.at[code, code]) for code in matrix.index}
    kept = sorted(matrix.index, key=lambda c: (-counts[c], c))
    if max_nodes is not None and max_nodes > 0:
        kept = kept[:max_nodes]
    kept_set = set(kept)

    jaccard = cooccurrence_jaccard(matrix)

    edges: List[Edge] = []
    hidden = 0
    units: Dict[Tuple[str, str], List[str]] = {}
    ordered = sorted(kept)
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            pair_count = int(matrix.at[a, b])
            if pair_count <= 0:
                continue
            strength = float(jaccard.at[a, b])
            if strength < min_strength:
                hidden += 1
                continue
            edges.append(Edge(source=a, target=b, strength=strength,
                              count=pair_count))
            key = (a, b) if a < b else (b, a)
            if key in drill:
                units[key] = list(drill[key])

    connected = {name for edge in edges for name in edge.key}
    isolated = [code for code in ordered if code not in connected]

    positions = _layout(ordered, edges)
    nodes = [Node(name=code, count=counts[code], x=positions[code][0],
                  y=positions[code][1])
             for code in ordered]

    refusal = ""
    if not edges:
        refusal = (
            f"No two codes co-occur at strength {min_strength:g} or above, so "
            "there is nothing to draw as a network. Either the codes genuinely "
            "sit apart, or the threshold is too high — try lowering it, or read "
            "the co-occurrence matrix instead.")

    return CodeNetwork(
        nodes=nodes if not refusal else [], edges=edges, unit=unit,
        min_strength=min_strength, edges_hidden=hidden, isolated=isolated,
        refusal=refusal, edge_units=units)


#: Where the unconnected codes are parked, as a fraction of the canvas width.
#: They get their own column instead of a place in the simulation — see below.
ISOLATE_COLUMN_X = 0.96

#: How much of the width the connected graph gets when isolates are present.
CONNECTED_WIDTH = 0.82


def _layout(codes: Sequence[str], edges: Sequence[Edge]) -> Dict[str, Tuple[float, float]]:
    """Place nodes deterministically: force-directed for the graph, a column
    for the codes that are not in it.

    Fruchterman-Reingold, started from an evenly spaced circle rather than from
    random positions, run for a fixed number of iterations with a fixed cooling
    schedule. There is no seed anywhere in it, because there is no randomness in
    it: the same graph produces the same coordinates on every machine and in
    every process, which is what lets the picture be a figure in a paper rather
    than a screenshot of a thing that will look different tomorrow.

    **Unconnected codes are placed, not simulated.** Nothing attracts them, so
    in the simulation repulsion alone pushes them as far as the cooling schedule
    allows; they then set the bounding box, and the actual structure gets
    normalised into a corner of the canvas. The first version of this did
    exactly that — one orphan code compressed a four-code cluster into six
    percent of the width, with every unit test passing. So they get a column of
    their own at the edge, which is both readable and a fairer picture: they are
    outside the network, and they look it.

    Written against numpy rather than networkx so this adds no dependency to a
    project whose selling point is that it installs and runs offline.
    """
    if len(codes) == 1:
        return {codes[0]: (0.5, 0.5)}

    connected_names = sorted({name for edge in edges for name in edge.key})
    isolated_names = [code for code in codes if code not in set(connected_names)]

    if not connected_names:
        # No structure to show; an even circle is the honest arrangement.
        return _to_unit_box(codes, _circle(len(codes)))

    positions = _force_directed(connected_names, edges)
    placed = _to_unit_box(connected_names, positions)

    if not isolated_names:
        return placed

    # Squeeze the graph left to make room for the column, keeping its aspect.
    placed = {code: (x * CONNECTED_WIDTH, y) for code, (x, y) in placed.items()}

    count = len(isolated_names)
    if count == 1:
        spacing = [0.5]
    else:
        spacing = [0.08 + 0.84 * i / (count - 1) for i in range(count)]
    for code, y in zip(isolated_names, spacing):
        placed[code] = (ISOLATE_COLUMN_X, y)

    return placed


def _circle(count: int) -> np.ndarray:
    """Evenly spaced points on a unit circle. The deterministic start, and the
    whole answer when there are no edges."""
    angles = np.linspace(0.0, 2.0 * np.pi, count, endpoint=False)
    return np.column_stack([np.cos(angles), np.sin(angles)]).astype(float)


def _force_directed(names: Sequence[str], edges: Sequence[Edge]) -> np.ndarray:
    """Fruchterman-Reingold over the connected codes only."""
    count = len(names)
    index = {code: i for i, code in enumerate(names)}
    positions = _circle(count)

    weights = np.zeros((count, count), dtype=float)
    for edge in edges:
        i, j = index[edge.source], index[edge.target]
        weights[i, j] = weights[j, i] = edge.strength

    # The distance at which attraction and repulsion balance.
    k = np.sqrt(1.0 / count)
    temperature = 0.1
    cooling = temperature / (LAYOUT_ITERATIONS + 1)

    for _ in range(LAYOUT_ITERATIONS):
        delta = positions[:, None, :] - positions[None, :, :]
        distance = np.linalg.norm(delta, axis=-1)
        np.fill_diagonal(distance, 1.0)          # self term is discarded
        distance = np.maximum(distance, 1e-6)    # never divide by ~0

        repulsion = (k * k) / distance
        attraction = (distance / k) * weights
        magnitude = repulsion - attraction
        np.fill_diagonal(magnitude, 0.0)

        direction = delta / distance[..., None]
        force = (direction * magnitude[..., None]).sum(axis=1)

        step = np.linalg.norm(force, axis=1)
        step = np.maximum(step, 1e-6)
        positions += force / step[:, None] * np.minimum(step, temperature)[:, None]
        temperature -= cooling

    return positions


def _to_unit_box(codes: Sequence[str],
                 positions: np.ndarray) -> Dict[str, Tuple[float, float]]:
    """Scale coordinates into [0, 1] on both axes, preserving aspect.

    Both axes are divided by the *same* span so the picture is not stretched:
    scaling each axis to its own range would distort a genuinely elongated
    graph into a square one and make two codes look closer than they are.
    """
    low = positions.min(axis=0)
    high = positions.max(axis=0)
    span = float(np.max(high - low))
    if span <= 0:
        return {code: (0.5, 0.5) for code in codes}

    centred = positions - (low + high) / 2.0
    scaled = centred / span + 0.5
    return {code: (float(scaled[i, 0]), float(scaled[i, 1]))
            for i, code in enumerate(codes)}


def network_from_project(project, *, unit: str = "excerpt_id",
                         min_strength: float = DEFAULT_MIN_STRENGTH,
                         rater_id: Optional[str] = None,
                         **kwargs: Any) -> CodeNetwork:
    """Build the network for a project's coding.

    `rater_id` restricts to one coder. Left unset, every coder's applications
    are pooled, which inflates co-occurrence whenever two raters coded the same
    excerpt differently — the same trap `PORTED_BACK.md` §5 recorded against the
    co-occurrence matrix, so the filter is offered here from the start rather
    than added after someone publishes a number.
    """
    coding = project.coding_table()
    if rater_id and not coding.empty and "rater_id" in coding.columns:
        coding = coding[coding["rater_id"] == rater_id]
    return build_code_network(coding, unit=unit, min_strength=min_strength,
                              **kwargs)
