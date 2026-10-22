"""Plays an explainer clip (`core/ux/help/media/`) and offers it as slides (item 4.10).

The clip is an SVG whose animation Qt's renderer can play (rules in `core/ux/help/media.py`).
Qt has no player for it, so this one steps the renderer's frame itself:

* It starts **paused on the finished picture**, not playing: nothing moves until the person
  asks. That is also the answer to "reduced motion", which Qt cannot detect portably.
* **Next** and **Back** jump between the captions, so a clip can be read one slide at a time
  with no motion needed at all. The slider seeks anywhere.
* It stops on the last frame (Qt would otherwise start the clip again).
* **Read it as text** shows the clip's whole description in words, for a screen reader or anyone
  who would rather read.
* Space plays and pauses; the arrow keys step through the captions.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from PySide6.QtCore import QByteArray, QElapsedTimer, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSlider, QVBoxLayout, QWidget,
)

from core.ux.help import media
from qualsafe_qt.widgets.wrapping import WrappingLabel

FPS = 30
#: A slide is a caption plus this long for its picture to settle (the pictures take about a second).
SETTLE_SECONDS = 1.2


def _clock(seconds: float) -> str:
    whole = int(round(seconds))
    return f"{whole // 60}:{whole % 60:02d}"


class _Canvas(QWidget):
    """Draws one frame of the clip, 16:9, centred."""

    clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.renderer: Optional[QSvgRenderer] = None
        self.frame = 0
        self.setMinimumSize(320, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def heightForWidth(self, width: int) -> int:
        return width * 9 // 16

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1b1b1f"))
        if self.renderer is None:
            return
        width = min(self.width(), self.height() * 16 // 9)
        height = width * 9 // 16
        target = QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)
        self.renderer.setCurrentFrame(self.frame)
        self.renderer.render(painter, target)
        if self.hasFocus():
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.drawRect(target.adjusted(1, 1, -1, -1))

    def mousePressEvent(self, event) -> None:
        self.setFocus()
        self.clicked.emit()
        event.accept()


class ClipPlayer(QWidget):
    """One clip, with Play, Back, Next, a position slider and a text version."""

    #: True while it is playing.
    playing_changed = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.clip_id = ""
        self._moments: List[float] = []
        self._last_frame = 0
        self._playing = False
        self._clock = QElapsedTimer()
        self._clock_from = 0
        self._timer = QTimer(self)
        self._timer.setInterval(1000 // FPS)
        self._timer.timeout.connect(self._tick)

        self.canvas = _Canvas()
        self.canvas.clicked.connect(self.toggle)
        self.play_button = QPushButton("Play")
        self.play_button.setProperty("main", True)
        self.play_button.clicked.connect(self.toggle)
        self.back_button = QPushButton("Back")
        self.back_button.setToolTip("Go to the start of the previous caption.")
        self.back_button.clicked.connect(lambda: self.step(-1))
        self.next_button = QPushButton("Next")
        self.next_button.setToolTip("Go to the next caption.")
        self.next_button.clicked.connect(lambda: self.step(1))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setAccessibleName("Position in the clip")
        self.slider.valueChanged.connect(self._slider_moved)
        self.time_label = QLabel("0:00 / 0:00")
        self.text_button = QPushButton("Read it as text")
        self.text_button.setCheckable(True)
        self.text_button.setToolTip("Show what the clip says, in words.")
        self.text_button.toggled.connect(self._show_text)
        self.text_label = WrappingLabel("")
        self.text_label.setVisible(False)

        controls = QHBoxLayout()
        for widget in (self.play_button, self.back_button, self.next_button):
            controls.addWidget(widget)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.time_label)
        controls.addWidget(self.text_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas, 1)
        layout.addLayout(controls)
        layout.addWidget(self.text_label)

    # -- loading -----------------------------------------------------------------------
    def load(self, clip_id: str) -> bool:
        """Show a clip, paused on its finished picture. False if there is no such clip."""
        self.pause()
        text = media.read(clip_id)
        clip = media.get(clip_id)
        if text is None or clip is None:
            return False
        renderer = QSvgRenderer(QByteArray(text.encode("utf-8")))
        if not renderer.isValid():
            return False
        self.clip_id = clip_id
        self.canvas.renderer = renderer
        self._moments = media.moments(clip_id)
        self._last_frame = clip.seconds * FPS - 1
        self.slider.blockSignals(True)
        self.slider.setRange(0, self._last_frame)
        self.slider.blockSignals(False)
        self.canvas.setAccessibleName(clip.title)
        self.canvas.setAccessibleDescription(media_description(text))
        self.text_label.setText(f"<b>{clip.title}.</b> {media_description(text)}")
        self.seek(self._last_frame)
        return True

    # -- state -------------------------------------------------------------------------
    @property
    def frame(self) -> int:
        return self.canvas.frame

    @property
    def is_playing(self) -> bool:
        return self._playing

    def seek(self, frame: int) -> None:
        frame = max(0, min(int(frame), self._last_frame))
        self.canvas.frame = frame
        self.canvas.update()
        self.slider.blockSignals(True)
        self.slider.setValue(frame)
        self.slider.blockSignals(False)
        seconds = self._last_frame // FPS + 1
        self.time_label.setText(f"{_clock(frame / FPS)} / {_clock(seconds)}")
        self._refresh_buttons()

    def _slider_moved(self, value: int) -> None:
        was_playing = self._playing
        self.pause()
        self.seek(value)
        if was_playing:
            self.play()

    def _refresh_buttons(self) -> None:
        at_end = self.frame >= self._last_frame
        self.play_button.setText("Pause" if self._playing else ("Replay" if at_end else "Play"))
        stops = self._slide_frames()
        self.back_button.setEnabled(any(f < self.frame - 1 for f in stops))
        self.next_button.setEnabled(any(f > self.frame for f in stops))

    def _slide_frames(self) -> List[int]:
        return [min(self._last_frame, int((m + SETTLE_SECONDS) * FPS)) for m in self._moments]

    # -- playing -----------------------------------------------------------------------
    def play(self) -> None:
        if self.canvas.renderer is None:
            return
        if self.frame >= self._last_frame:
            self.seek(0)                                   # play again from the start
        self._playing = True
        self._clock_from = self.frame
        self._clock.start()
        self._timer.start()
        self._refresh_buttons()
        self.playing_changed.emit(True)

    def pause(self) -> None:
        if not self._playing:
            return
        self._playing = False
        self._timer.stop()
        self._refresh_buttons()
        self.playing_changed.emit(False)

    def toggle(self) -> None:
        self.pause() if self._playing else self.play()

    def _tick(self) -> None:
        target = self._clock_from + int(self._clock.elapsed() * FPS / 1000)
        if target >= self._last_frame:
            self.seek(self._last_frame)
            self.pause()                                   # stop on the last frame
            return
        self.seek(target)

    # -- slides ------------------------------------------------------------------------
    def step(self, direction: int) -> None:
        """Jump to the next (1) or previous (-1) caption, paused."""
        self.pause()
        stops: Sequence[int] = self._slide_frames()
        if direction > 0:
            later = [f for f in stops if f > self.frame]
            self.seek(later[0] if later else self._last_frame)
        else:
            earlier = [f for f in stops if f < self.frame - 1]
            self.seek(earlier[-1] if earlier else 0)

    def _show_text(self, on: bool) -> None:
        self.text_label.setVisible(on)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Space:
            self.toggle()
        elif key == Qt.Key.Key_Right:
            self.step(1)
        elif key == Qt.Key.Key_Left:
            self.step(-1)
        else:
            super().keyPressEvent(event)

    def hideEvent(self, event) -> None:
        self.pause()
        super().hideEvent(event)


def media_description(svg_text: str) -> str:
    """The clip's own `<desc>`: the whole clip, in words."""
    import xml.etree.ElementTree as ET

    root = ET.fromstring(svg_text)
    node = next((e for e in root if e.tag.endswith("desc")), None)
    return " ".join((node.text or "").split()) if node is not None else ""


class ClipDialog(QDialog):
    """The clips for one step, in a small window: a list to pick from if there are several."""

    def __init__(self, clip_ids: Sequence[str], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Watch")
        self.setMinimumWidth(720)
        self.resize(880, 640)
        layout = QVBoxLayout(self)
        self.picker = QComboBox()
        self.picker.setAccessibleName("Which clip")
        self._ids = list(clip_ids)
        for clip_id in self._ids:
            clip = media.get(clip_id)
            self.picker.addItem(clip.title if clip else clip_id, clip_id)
        self.picker.setVisible(len(self._ids) > 1)
        self.player = ClipPlayer()
        self.summary = WrappingLabel("")
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        layout.addWidget(self.picker)
        layout.addWidget(self.player, 1)
        layout.addWidget(self.summary)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        self.picker.currentIndexChanged.connect(self._pick)
        self._pick()

    def _pick(self) -> None:
        clip_id = self.picker.currentData()
        if clip_id and self.player.load(clip_id):
            clip = media.get(clip_id)
            self.summary.setText(clip.summary if clip else "")
