"""Mic drawer: slides out from under the gauge while you talk, tucks back when you're done.

It shows the live transcript, and a fallback when there is no mic: a typing box, and on
mock parts phrase buttons that stand in for speaking. Click the gauge to open it for
typing; it closes on its own once what you said has been handed to the agent.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEasingCurve, QPoint, QRect, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ui import theme
from ui.cards import Card
from ui.gauge import H as GAUGE_H
from ui.gauge import W as GAUGE_W
from ui.theme import label

WIDTH = GAUGE_W
GAP = 6            # between the gauge and the drawer
SLIDE = 16         # px it travels out from under the gauge
OPEN_MS = 240      # eases out, settles softly
CLOSE_MS = 170     # tucks away quicker than it came
# Compact, like the gauge above it.
COMPACT = (f"QPushButton {{ padding: 5px 12px; font-size: {theme.SMALL}px; }}"
           f"QLineEdit {{ padding: 6px 8px; font-size: {theme.SMALL}px; }}")
LINGER_MS = 1500   # after the last words, so you can read what was heard
CHIP_GAP = 6
HINT = "Hold Ctrl+Alt+Space and speak"


class VoiceBar(Card):
    spoken = Signal(str)

    def __init__(self, phrases: list[str] | None = None,
                 anchor: Callable[[], QRect] | None = None):
        super().__init__(WIDTH)
        self.anchor = anchor            # the gauge's frame; None = top-right of the screen
        self.frame.setStyleSheet(COMPACT)
        self.body.setContentsMargins(14, 12, 14, 12)
        self.body.setSpacing(8)
        self.transcript = label(HINT, theme.SMALL, color=theme.ICE, wrap=True)
        self.body.addWidget(self.transcript)
        row = QHBoxLayout()
        self.edit = QLineEdit(placeholderText="Or type, then Enter")
        self.edit.returnPressed.connect(self._typed)
        row.addWidget(self.edit, 1)
        row.addWidget(QPushButton("Send", clicked=self._typed))
        self.body.addLayout(row)
        self.phrase_buttons: list[QPushButton] = []
        if phrases:
            # Packed by measured width, so every phrase reads in full.
            room = WIDTH - self.body.contentsMargins().left() - self.body.contentsMargins().right()
            chips = QVBoxLayout()
            chips.setSpacing(CHIP_GAP)
            row, used = None, room
            for text in phrases:
                btn = QPushButton(text, self.frame)
                btn.clicked.connect(lambda _=False, t=text: self.say(t))
                btn.ensurePolished()
                w = btn.sizeHint().width()
                if row is None or used + CHIP_GAP + w > room:
                    row, used = QHBoxLayout(), -CHIP_GAP
                    row.setSpacing(CHIP_GAP)
                    chips.addLayout(row)
                row.addWidget(btn)
                used += CHIP_GAP + w
                self.phrase_buttons.append(btn)
            self.body.addLayout(chips)

        self.opened = False             # where it is heading, not where it is
        self.listening = False
        self._t = 0.0                   # 0 tucked under the gauge, 1 fully out
        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self._apply_t)
        self._anim.finished.connect(self._settled)
        self._linger = QTimer(self, singleShot=True, interval=LINGER_MS, timeout=self.close_drawer)

    # ---- placement -----------------------------------------------------------

    def home_position(self, area) -> QPoint:
        if self.anchor is not None:
            g = self.anchor()
            return QPoint(g.left() + (g.width() - WIDTH) // 2, g.bottom() + 1 + GAP)
        return QPoint(area.right() - WIDTH - 16, area.top() + 16 + GAUGE_H + GAP)

    def follow(self) -> None:
        """The gauge moved (it can be dragged): stay under it."""
        if self.isVisible():
            self._apply_t(self._t)

    def _apply_t(self, t) -> None:
        self._t = float(t)
        screen = QGuiApplication.primaryScreen()
        home = self.home_position(screen.availableGeometry() if screen else QRect())
        self.setWindowOpacity(min(1.0, self._t * 1.4))   # opaque before it lands: no ghosting
        self.move(home + QPoint(0, -round((1 - self._t) * SLIDE)))

    # ---- open / close ----------------------------------------------------------

    def present(self) -> None:
        """Built and laid out, but tucked away until there is something to show."""
        for child in self.findChildren(QWidget):
            child.ensurePolished()
        self._fit()

    def _fit(self) -> None:
        """Height follows the content: a long transcript wraps onto more lines."""
        self.layout().invalidate()
        self.layout().activate()
        h = max(self.layout().totalHeightForWidth(self.width()), self.layout().totalMinimumSize().height())
        if h != self.height():
            self.resize(self.width(), h)

    def open_drawer(self) -> None:
        self._linger.stop()
        if self.opened:
            return
        self.opened = True
        if not self.isVisible():
            self._apply_t(0.0)
            self.show()
        self.raise_()
        self._slide_to(1.0)

    def close_drawer(self) -> None:
        self._linger.stop()
        if not self.opened or self.listening or self.edit.hasFocus() and self.edit.text():
            return   # never pull it away mid-sentence or mid-typing
        self.opened = False
        self._slide_to(0.0)

    def toggle(self) -> None:
        """Gauge click: open to type, or put it away."""
        if self.opened:
            self.edit.clear()
            self.close_drawer()
        else:
            self.open_drawer()
            self.activateWindow()
            self.edit.setFocus()

    def _slide_to(self, end: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(end)
        opening = end > self._t
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic if opening else QEasingCurve.Type.InCubic)
        self._anim.setDuration(max(1, round((OPEN_MS if opening else CLOSE_MS) * abs(end - self._t))))
        self._anim.start()

    def _settled(self) -> None:
        if not self.opened and self._t <= 0.0:
            self.hide()
            self.transcript.setText(HINT)
            self._fit()

    # ---- voice ---------------------------------------------------------------

    def set_listening(self, on: bool) -> None:
        """Hotkey down: slide out. Hotkey up: stay while the last words arrive, then tuck."""
        self.listening = on
        if on:
            self.transcript.setText("Listening...")
            self._fit()
            self.open_drawer()
        else:
            self._linger.start()

    def show_transcript(self, text: str) -> None:
        self.transcript.setText(text)
        self._fit()
        if self.opened and not self.listening:
            self._linger.start()   # late words restart the countdown

    def say(self, text: str) -> None:
        self.show_transcript(text)
        self.spoken.emit(text)
        self._linger.start()       # handed to the agent: tuck away shortly

    def _typed(self) -> None:
        if text := self.edit.text().strip():
            self.edit.clear()
            self.say(text)

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.edit.clear()
            self.close_drawer()
        else:
            super().keyPressEvent(e)
