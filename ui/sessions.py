"""Session picker: saved sessions, last used, rule count, auto-freeze toggle."""
from __future__ import annotations

import time

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QPushButton, QVBoxLayout

from freezer import sessions
from ui import theme
from ui.cards import Card
from ui.theme import label


def ago(ts: float, now: float | None = None) -> str:
    if not ts:
        return "never used"
    minutes = ((now or time.time()) - ts) / 60
    if minutes < 60:
        return f"{minutes:.0f} min ago"
    if minutes < 48 * 60:
        return f"{minutes / 60:.0f}h ago"
    return f"{minutes / 1440:.0f} days ago"


class SessionPicker(Card):
    start_session = Signal(str)

    def __init__(self):
        super().__init__(560)
        self.body.addWidget(label("Focus sessions", theme.TITLE, bold=True))
        saved = sorted(sessions.load(), key=lambda s: s.last_used, reverse=True)
        if not saved:
            self.body.addWidget(label('Say "start thesis session" to create your first one.', color=theme.MUTED, wrap=True))
        self.toggles: dict[str, QCheckBox] = {}
        for s in saved:
            row = QFrame(objectName="plainrow")
            box = QVBoxLayout(row)
            box.setContentsMargins(12, 9, 12, 9)
            box.setSpacing(3)
            top = QHBoxLayout()
            top.addWidget(label(s.name, 18, bold=True), 1)
            start = QPushButton("Start")
            start.clicked.connect(lambda _=False, name=s.name: self._start(name))
            top.addWidget(start)
            box.addLayout(top)
            box.addWidget(label(s.task, color=theme.MUTED, wrap=True))
            rules = len(s.keep_rules) + len(s.never_freeze)
            box.addWidget(label(f"{ago(s.last_used)}, {rules} {'rule' if rules == 1 else 'rules'}", color=theme.MUTED))
            auto = QCheckBox("Auto-freeze: will freeze without asking")
            auto.setChecked(s.auto_freeze)
            auto.toggled.connect(lambda on, name=s.name: sessions.set_auto_freeze(name, on))
            self.toggles[s.name] = auto
            box.addWidget(auto)
            self.body.addWidget(row)
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(QPushButton("Close", clicked=self.close))
        self.body.addLayout(foot)

    def _start(self, name: str) -> None:
        self.start_session.emit(name)
        self.close()
