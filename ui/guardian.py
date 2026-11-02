"""Guardian card, non-modal, top-right. Review opens the full consent card."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton

from freezer.agent import Proposal
from ui import theme
from ui.cards import Card
from ui.consent import gb
from ui.theme import label

WIDTH, HEIGHT = 380, 180


class GuardianCard(Card):
    review = Signal()
    dismissed = Signal()

    def __init__(self, proposal: Proposal, ram_pct: float):
        super().__init__(WIDTH, HEIGHT)
        n = len(proposal.to_freeze)
        self.proposal = proposal
        self._done = False
        self.text = (f"RAM {ram_pct:.0f}%. Freeze {n} idle {'app' if n == 1 else 'apps'}, "
                     f"free ~{gb(proposal.free_mb)}?")
        self.heading = label(self.text, 21, bold=True, wrap=True)
        self.body.addWidget(self.heading)
        self.body.addStretch(1)
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(QPushButton("Dismiss", clicked=self.cancel))
        foot.addWidget(QPushButton("Review", objectName="primary", clicked=self.accept))
        self.body.addLayout(foot)

    def home_position(self, area) -> QPoint:
        return QPoint(area.right() - WIDTH - 16, area.top() + 240)  # under the gauge

    def accept(self) -> None:
        self._finish(self.review)

    def cancel(self) -> None:
        self._finish(self.dismissed)

    def _finish(self, signal) -> None:
        if not self._done:
            self._done = True
            signal.emit()
            self.close()

    def closeEvent(self, event) -> None:
        self.cancel()  # any way of closing must release the waiting agent thread
        super().closeEvent(event)
