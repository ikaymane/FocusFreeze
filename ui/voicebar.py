"""Small mic window: shows the transcript, and a fallback when there is no mic.

On mock parts the phrase buttons stand in for speaking, so the loop runs hands-free
apart from the mouse. Enter in the box does the same.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton

from ui import theme
from ui.cards import Card
from ui.theme import label

WIDTH = 620


class VoiceBar(Card):
    spoken = Signal(str)

    def __init__(self, phrases: list[str] | None = None):
        super().__init__(WIDTH)
        self.transcript = label("Hold Ctrl+Alt+Space and speak", color=theme.ICE, wrap=True)
        self.body.addWidget(self.transcript)
        row = QHBoxLayout()
        self.edit = QLineEdit(placeholderText="Or type here and press Enter")
        self.edit.returnPressed.connect(self._typed)
        row.addWidget(self.edit, 1)
        row.addWidget(QPushButton("Send", clicked=self._typed))
        self.body.addLayout(row)
        self.phrase_buttons: list[QPushButton] = []
        if phrases:
            chips = QHBoxLayout()
            for text in phrases:
                btn = QPushButton(text)
                btn.setStyleSheet("padding: 5px 8px;")
                btn.clicked.connect(lambda _=False, t=text: self.say(t))
                self.phrase_buttons.append(btn)
                chips.addWidget(btn)
            self.body.addLayout(chips)

    def home_position(self, area) -> QPoint:
        return QPoint(area.center().x() - WIDTH // 2, area.bottom() - self.height() - 16)

    def show_transcript(self, text: str) -> None:
        self.transcript.setText(text)

    def say(self, text: str) -> None:
        self.show_transcript(text)
        self.spoken.emit(text)

    def _typed(self) -> None:
        if text := self.edit.text().strip():
            self.edit.clear()
            self.say(text)
