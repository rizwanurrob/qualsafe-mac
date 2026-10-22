"""
The document reader: real text selection, inline highlights, margin stripes.

**This widget is the reason the fork exists.** Streamlit has no way to return the
character offsets of a mouse selection, so QualSafe's Streamlit build offers two
honest workarounds -- tick pre-split sentences, or paste a passage and locate it
with a fuzzy matcher. Qt hands the offsets over directly:
`QTextCursor.selectionStart()` / `selectionEnd()`. Drag across text, get exact
offsets, code the passage. That is the whole thesis.

Three things this widget is careful about:

1. **Offsets are translated, never assumed.** A `QTextDocument` normalizes CRLF
   to LF on the way in, which shifts every later position. Every offset crossing
   this boundary goes through `text_offsets.OffsetMap`, and when the map cannot
   verify itself the widget reports `is_codeable == False` so the view refuses
   to code rather than code the wrong passage.
2. **Overlapping codings both stay visible.** Inline highlight colours come from
   `core.documents.segment_by_spans` -- the same tested function the Streamlit
   reader uses -- which splits at every span boundary so a passage coded both
   *Cost* and *Belonging* renders as one segment carrying both. The margin
   stripes then show each coding as its own bar in its own lane, which is the
   part Streamlit could not do at all.
3. **It never touches the store.** It is handed text and spans and emits
   selections; `ProjectService` owns everything persistent.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QTextEdit, QWidget

from core.documents import segment_by_spans
from qualsafe_qt.colors import with_alpha
from qualsafe_qt.text_offsets import OffsetMap
from qualsafe_qt.theme import muted_color

#: Width of one stripe lane, and the gap between lanes, in device-independent px.
_LANE_WIDTH = 7
_LANE_GAP = 2
#: How many overlapping codings get their own lane before the margin gives up
#: and stacks the rest in the last one. Four is past the point of readability.
_MAX_LANES = 4
#: Alpha for the inline highlight fill, per skin. A tint that reads clearly on
#: white is nearly invisible over the dark panel (#1C1E22), so dark needs more
#: of it -- the same reason `core/theme.py` gives the two skins different heat
#: ramps rather than one ramp and a hope. Passages carrying more than one code
#: are filled harder so overlap is visible without opening a tooltip.
_FILL_ALPHA = {
    "dark": {"single": 90, "multi": 140},
    "light": {"single": 60, "multi": 105},
}


def _unknown_color(mode: str = "dark") -> QColor:
    """The stripe colour for a code with no assigned colour.

    From the palette rather than a literal grey: on the light skin a mid grey
    that reads as "unspecified" on dark reads as "faint text" instead.
    """
    return QColor(muted_color(mode))


class CodingStripes(QWidget):
    """The margin: one coloured bar per coded passage, alongside the text.

    Modelled on the line-number-area pattern from the Qt docs, but positioned by
    character offsets instead of line numbers, so a bar starts and ends exactly
    where the coding does rather than snapping to whole lines.

    Overlapping codings are assigned separate lanes, so two codes on the same
    paragraph read as two bars rather than one bar of an ambiguous colour.
    """

    #: A stripe was clicked: the excerpt_id of the coding it represents.
    span_clicked = Signal(str)

    def __init__(self, editor: "_ReaderEdit", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._editor = editor
        self._spans: List[Dict[str, Any]] = []
        self._lanes: Dict[str, int] = {}
        self._colors: Dict[str, QColor] = {}
        self._hit_boxes: List[Tuple[QRect, str]] = []
        self._mode = "dark"
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Coded passages. Click a stripe to select its passage.")

    def sizeHint(self):  # noqa: D102 - Qt override
        from PySide6.QtCore import QSize

        return QSize(_MAX_LANES * (_LANE_WIDTH + _LANE_GAP) + _LANE_GAP, 0)

    def set_theme_mode(self, mode: str) -> None:
        self._mode = mode if mode in ("dark", "light") else "dark"
        self.update()

    def set_spans(self, spans: Sequence[Dict[str, Any]], colors: Dict[str, QColor]) -> None:
        """Replace the coded spans (source offsets) and their code colours."""
        self._spans = [dict(s) for s in spans]
        self._colors = dict(colors)
        self._lanes = _assign_lanes(self._spans)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: D102 - Qt override
        point = event.position().toPoint()
        for rect, excerpt_id in self._hit_boxes:
            if rect.contains(point):
                self.span_clicked.emit(excerpt_id)
                return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: D102 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        self._hit_boxes = []

        visible = self._editor.visible_source_range()
        if visible is None:
            return
        first_pos, last_pos = visible
        height = self.height()

        for span in self._spans:
            start, end = int(span["char_start"]), int(span["char_end"])
            if end < first_pos or start > last_pos:
                continue
            top = 0 if start < first_pos else self._editor.y_top_for_source(start)
            bottom = height if end > last_pos else self._editor.y_bottom_for_source(end)
            if top is None or bottom is None:
                continue
            top = max(0, int(top))
            bottom = min(height, int(bottom))
            if bottom <= top:
                bottom = top + 2      # a one-line coding must still be visible

            lane = self._lanes.get(span["excerpt_id"], 0)
            x = _LANE_GAP + lane * (_LANE_WIDTH + _LANE_GAP)
            codes = span.get("codes") or []
            color = self._colors.get(codes[0] if codes else "", _unknown_color(self._mode))
            rect = QRect(x, top, _LANE_WIDTH, bottom - top)
            painter.fillRect(rect, color)
            # A second code on the same passage gets a contrasting cap, so an
            # overlapping coding is visible even when it shares a lane.
            if len(codes) > 1:
                second = self._colors.get(codes[1], _unknown_color(self._mode))
                painter.fillRect(QRect(x, top, _LANE_WIDTH, max(3, (bottom - top) // 4)),
                                 second)
            # Widen the click target: a 7px bar is honest visually and hostile
            # to a mouse.
            self._hit_boxes.append(
                (QRect(x - 2, top, _LANE_WIDTH + 4, max(6, bottom - top)),
                 span["excerpt_id"]))


class _ReaderEdit(QPlainTextEdit):
    """The text surface. `QPlainTextEdit` rather than `QTextEdit` because it lays
    out lazily, which is what keeps a 40-page transcript scrolling smoothly."""

    #: Emitted whenever the viewport moves, so the margin repaints with it.
    viewport_changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        # Reading prose, not code: a serif-ish proportional face at comfortable
        # size and leading. The default monospace makes transcripts unreadable.
        font = QFont()
        font.setPointSize(max(10, font.pointSize() + 1))
        self.setFont(font)
        self.verticalScrollBar().valueChanged.connect(self.viewport_changed)
        # Replaced per document by DocumentView.set_document. Per-instance, not
        # a class attribute, so two open readers cannot share one translator.
        self.offset_map = OffsetMap("")

    def resizeEvent(self, event) -> None:  # noqa: D102 - Qt override
        super().resizeEvent(event)
        self.viewport_changed.emit()

    # -- geometry helpers used by the margin ---------------------------------
    def visible_source_range(self) -> Optional[Tuple[int, int]]:
        """``(first, last)`` **source** offsets currently laid out in the viewport.

        Translated out of Qt positions before returning, because the margin
        compares this against span offsets that are in source coordinates. In a
        CRLF document the two drift apart, and comparing them raw would cull
        stripes that should be on screen.

        Only these positions are safe to ask `cursorRect` about: `QPlainTextEdit`
        lays out lazily, so an off-screen position has no reliable geometry.
        """
        block = self.firstVisibleBlock()
        if not block.isValid():
            return None
        first = block.position()
        bottom = self.viewport().height()
        last = first
        while block.isValid():
            geometry = self.blockBoundingGeometry(block).translated(self.contentOffset())
            if geometry.top() > bottom:
                break
            last = block.position() + max(0, block.length() - 1)
            block = block.next()
        return self.offset_map.to_source(first), self.offset_map.to_source(last)

    def _cursor_rect_at(self, qt_position: int):
        cursor = self.textCursor()
        cursor.setPosition(max(0, min(self.document().characterCount() - 1,
                                      int(qt_position))))
        return self.cursorRect(cursor)

    def y_top_for_qt(self, qt_position: int) -> Optional[float]:
        rect = self._cursor_rect_at(qt_position)
        return None if rect.isNull() else rect.top()

    def y_bottom_for_qt(self, qt_position: int) -> Optional[float]:
        rect = self._cursor_rect_at(qt_position)
        return None if rect.isNull() else rect.bottom()

    # The margin works in source offsets; `offset_map` (set in __init__ and
    # replaced per document) is the translator.
    def y_top_for_source(self, source_index: int) -> Optional[float]:
        return self.y_top_for_qt(self.offset_map.to_qt(source_index))

    def y_bottom_for_source(self, source_index: int) -> Optional[float]:
        return self.y_bottom_for_qt(self.offset_map.to_qt(source_index))


class DocumentView(QWidget):
    """Reader + margin. Hands out *source* offsets; knows nothing about the store.

    Typical use::

        view.set_document(source_id, raw_text)
        view.set_spans(spans, colors)          # from core.documents.coding_spans
        start, end = view.selected_span()      # source offsets, ready to code
    """

    #: The selection changed: (char_start, char_end, selected_text). An empty
    #: selection emits (-1, -1, "").
    selection_changed = Signal(int, int, str)
    #: A coded passage was activated (stripe clicked, or cursor moved into it).
    span_activated = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._source_id = ""
        self._text = ""
        self._offsets = OffsetMap("")
        self._spans: List[Dict[str, Any]] = []
        self._colors: Dict[str, QColor] = {}
        #: Source spans spoken by the interviewer (or anyone who is not the participant):
        #: shown in italics, so the participant's words stand out. No colour: colour means a code.
        self._speaker_spans: List[Tuple[int, int]] = []
        self._theme_mode = "dark"

        self.editor = _ReaderEdit(self)
        self.stripes = CodingStripes(self.editor, self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.stripes)
        layout.addWidget(self.editor, 1)
        self.stripes.setFixedWidth(self.stripes.sizeHint().width())

        self.editor.viewport_changed.connect(self.stripes.update)
        self.editor.selectionChanged.connect(self._on_selection_changed)
        self.editor.cursorPositionChanged.connect(self._on_cursor_moved)
        self.stripes.span_clicked.connect(self._on_stripe_clicked)

    def set_theme_mode(self, mode: str) -> None:
        """Switch skin. Repaints highlights at the alpha that skin needs."""
        self._theme_mode = mode if mode in _FILL_ALPHA else "dark"
        self.stripes.set_theme_mode(self._theme_mode)
        self._apply_highlights()

    # -- content -------------------------------------------------------------
    def set_document(self, source_id: str, text: str) -> None:
        """Load a document. `text` must be the source's `raw_text`, verbatim."""
        self._source_id = source_id
        self._text = text or ""
        self.editor.setPlainText(self._text)
        # Build the translator against what Qt *actually* stored, so a document
        # Qt normalizes in a way this build does not model is caught here rather
        # than mis-coded later.
        self._offsets = OffsetMap(self._text, qt_text=self.editor.toPlainText())
        self.editor.offset_map = self._offsets
        self.editor.moveCursor(QTextCursor.MoveOperation.Start)
        self._speaker_spans = []
        self.set_spans([], {})

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def text(self) -> str:
        """The loaded document's text, verbatim as it came from the source.

        Exposed so callers can quote a passage without re-reading a 40-page
        transcript out of SQLite on every coding.
        """
        return self._text

    @property
    def is_codeable(self) -> bool:
        """False when the offset map could not verify itself against Qt.

        The view must disable coding in that case. An unverified map means the
        offsets stored on an excerpt might not be the passage the analyst
        selected, and a silently wrong evidence link is the one failure this
        tool cannot have.
        """
        return self._offsets.is_exact

    def set_spans(self, spans: Sequence[Dict[str, Any]], colors: Dict[str, QColor]) -> None:
        """Show these coded spans (source offsets, as `core.documents.coding_spans`)."""
        self._spans = [dict(s) for s in spans]
        self._colors = dict(colors)
        self.stripes.set_spans(self._spans, self._colors)
        self._apply_highlights()

    def set_speaker_spans(self, spans: Sequence[Tuple[int, int]]) -> None:
        """Show these source spans in italics (the interviewer's turns)."""
        self._speaker_spans = [(int(s), int(e)) for s, e in spans]
        # Real character formatting, not an extra selection: Qt draws only colours and
        # underlines from those. The text itself, and so every offset, is unchanged.
        cursor = QTextCursor(self.editor.document())
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        plain = QTextCharFormat()
        plain.setFontItalic(False)
        cursor.mergeCharFormat(plain)
        for start, end in self._speaker_spans:
            cursor.setPosition(self._offsets.to_qt(start))
            cursor.setPosition(self._offsets.to_qt(end), QTextCursor.MoveMode.KeepAnchor)
            italic = QTextCharFormat()
            italic.setFontItalic(True)
            cursor.mergeCharFormat(italic)
        cursor.endEditBlock()
        self.editor.moveCursor(QTextCursor.MoveOperation.Start)
        self._apply_highlights()

    def _apply_highlights(self) -> None:
        """Paint inline highlights from `segment_by_spans` -- the tested splitter.

        Reusing it means overlap behaves identically in both front ends, and the
        rule "a segment carries every code covering it" is asserted by the
        engine suite rather than reimplemented here.
        """
        selections: List[QTextEdit.ExtraSelection] = []
        if self._spans:
            for segment in segment_by_spans(self._text, self._spans):
                codes = segment["codes"]
                if not codes:
                    continue
                base = self._colors.get(codes[0], _unknown_color(self._theme_mode))
                alphas = _FILL_ALPHA[self._theme_mode]
                alpha = alphas["multi"] if len(codes) > 1 else alphas["single"]
                fmt = QTextCharFormat()
                fmt.setBackground(with_alpha(base, alpha))
                fmt.setUnderlineColor(base)
                fmt.setUnderlineStyle(
                    QTextCharFormat.UnderlineStyle.SingleUnderline
                    if len(codes) == 1
                    else QTextCharFormat.UnderlineStyle.WaveUnderline
                )
                fmt.setToolTip(", ".join(codes))

                selection = QTextEdit.ExtraSelection()
                selection.format = fmt
                cursor = QTextCursor(self.editor.document())
                qt_start = self._offsets.to_qt(segment["start"])
                qt_end = self._offsets.to_qt(segment["end"])
                cursor.setPosition(qt_start)
                cursor.setPosition(qt_end, QTextCursor.MoveMode.KeepAnchor)
                selection.cursor = cursor
                selections.append(selection)
        self.editor.setExtraSelections(selections)
        self.stripes.update()

    # -- selection -----------------------------------------------------------
    def selected_span(self) -> Optional[Tuple[int, int]]:
        """The current selection as **source** offsets, or None if nothing is selected."""
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            return None
        start, end = self._offsets.span_to_source(
            cursor.selectionStart(), cursor.selectionEnd())
        return (start, end) if end > start else None

    def selected_text(self) -> str:
        """The selected passage, taken **from the source string** by offset.

        Deliberately not `cursor.selectedText()`: that returns Qt's normalized
        copy (U+2029 for paragraph breaks, LF for CRLF). Everything downstream
        must see the document's own characters, so the text shown in the coding
        panel is the text that will be stored.
        """
        span = self.selected_span()
        return "" if span is None else self._text[span[0]:span[1]]

    def select_span(self, char_start: int, char_end: int) -> None:
        """Select a source span and scroll it into view."""
        qt_start, qt_end = self._offsets.span_to_qt(char_start, char_end)
        cursor = self.editor.textCursor()
        cursor.setPosition(qt_start)
        cursor.setPosition(qt_end, QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()

    def expand_selection_to_sentence(self) -> None:
        """Grow the selection to whole sentences, using the engine's splitter.

        `core.text_units.split_sentences` is what the Streamlit build's "pick
        units" tier uses, so a sentence here has exactly the boundaries a
        sentence has there -- convenience without a second definition of the
        unit.
        """
        span = self.selected_span()
        if span is None:
            cursor = self.editor.textCursor()
            here = self._offsets.to_source(cursor.position())
            span = (here, here)
        from core.text_units import split_sentences

        units = split_sentences(self._text) or [(self._text, 0, len(self._text))]
        covering = [(s, e) for _t, s, e in units if e > span[0] and s < max(span[1], span[0] + 1)]
        if not covering:
            return
        self.select_span(min(s for s, _e in covering), max(e for _s, e in covering))

    def _on_selection_changed(self) -> None:
        span = self.selected_span()
        if span is None:
            self.selection_changed.emit(-1, -1, "")
        else:
            self.selection_changed.emit(span[0], span[1], self._text[span[0]:span[1]])

    def _on_cursor_moved(self) -> None:
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            return
        here = self._offsets.to_source(cursor.position())
        for span in self._spans:
            if span["char_start"] <= here < span["char_end"]:
                self.span_activated.emit(span["excerpt_id"])
                return

    def _on_stripe_clicked(self, excerpt_id: str) -> None:
        for span in self._spans:
            if span["excerpt_id"] == excerpt_id:
                self.select_span(span["char_start"], span["char_end"])
                self.span_activated.emit(excerpt_id)
                return


def _assign_lanes(spans: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """Give overlapping spans separate margin lanes; reuse a lane once free.

    Greedy by start offset -- the standard interval-partitioning assignment. A
    document coded in non-overlapping passages therefore uses one lane and the
    margin stays quiet, which is the common case.
    """
    lanes: Dict[str, int] = {}
    lane_ends: List[int] = []
    for span in sorted(spans, key=lambda s: (s["char_start"], s["char_end"])):
        start, end = int(span["char_start"]), int(span["char_end"])
        placed = False
        for index, lane_end in enumerate(lane_ends):
            if lane_end <= start:
                lane_ends[index] = end
                lanes[span["excerpt_id"]] = index
                placed = True
                break
        if not placed:
            if len(lane_ends) < _MAX_LANES:
                lane_ends.append(end)
                lanes[span["excerpt_id"]] = len(lane_ends) - 1
            else:
                # Past the lane budget: stack in the last lane rather than
                # widening the margin without limit.
                lanes[span["excerpt_id"]] = _MAX_LANES - 1
                lane_ends[_MAX_LANES - 1] = max(lane_ends[_MAX_LANES - 1], end)
    return lanes
