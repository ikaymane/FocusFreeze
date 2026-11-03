"""End-of-session card: four numbers and Done."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout

from ui import fx, theme
from ui.cards import Card
from ui.consent import gb
from ui.theme import label

COUNT_S = 0.9


@dataclass
class Stats:
    freed_mb: float = 0.0
    apps: int = 0
    minutes: float = 0.0
    usd: float = 0.0
    restored_mb: float = 0.0
    restore_s: float = 0.0


def cost_caption(usd: float) -> str:
    """Plans cost fractions of a cent: say so in words, next to '$0.004'."""
    return "AI cost · under 1 cent" if 0 < usd < 0.01 else "AI cost"


class StatsCard(Card):
    def __init__(self, s: Stats):
        super().__init__(560)
        self.body.addWidget(label("Your apps are back", theme.TITLE, bold=True))
        self.body.addWidget(label(f"Restored {gb(s.restored_mb)} in {s.restore_s:.1f}s", color=theme.MUTED))
        self.body.addSpacing(6)
        grid = QHBoxLayout()
        self.counters: list[tuple] = []
        for value, fmt, name in ((s.freed_mb / 1024, "{:.1f} GB", "Freed"), (s.minutes, "{:.0f} min", "Focus"),
                                 (float(s.apps), "{:.0f}", "apps frozen"), (s.usd, "${:.3f}", cost_caption(s.usd))):
            cell = QVBoxLayout()
            cell.setSpacing(0)
            number = label(fmt.format(0), 24, theme.ICE, bold=True)
            self.counters.append((number, value, fmt))
            cell.addWidget(number)
            cell.addWidget(label(name, color=theme.MUTED))
            grid.addLayout(cell)
        self.body.addLayout(grid)
        self.body.addSpacing(6)
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(QPushButton("Done", objectName="primary", clicked=self.close))
        self.body.addLayout(foot)

    def step(self, dt: float) -> bool:
        self.fx_t += dt
        self._enter()
        u = fx.ease_out((self.fx_t - 0.15) / COUNT_S)
        for number, value, fmt in self.counters:
            number.setText(fmt.format(value * u))
        self.fx.update()
        return self.fx_t < COUNT_S + 0.3
