"""Always-on-top RAM gauge: a memory map with three states.

Each cell is a slice of RAM: in use, frozen, or free. When apps freeze, cells
change from in use to frozen in a wave, and the digits roll down. You can read
at a glance how much is frozen and will come back. This is the hero of the video.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Callable, NamedTuple

import psutil
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ui import fx, theme

W, H = 360, 216
COLS, ROWS = 40, 3
CELL = 6.0
GAP = 1.2
GRID_X = 16
GRID_Y = 110
STAGGER_S = 0.016       # the wave, per column
DIGIT_H = 62


class Ram(NamedTuple):
    pct: float
    used_gb: float
    total_gb: float


def read_ram() -> Ram:
    m = psutil.virtual_memory()
    used = m.total - m.available
    return Ram(m.percent, used / 2**30, m.total / 2**30)


class _Cell:
    __slots__ = ("col", "row", "used", "ice", "goal_used", "goal_ice", "wait")

    def __init__(self, col: int, row: int):
        self.col, self.row = col, row
        self.used = self.ice = self.goal_used = self.goal_ice = 0.0
        self.wait = 0.0


class Gauge(QWidget):
    def __init__(self, read: Callable[[], Ram] = read_ram, simulated: bool = False):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(W, H)
        self.read, self.simulated = read, simulated
        self.freed_gb = 0.0
        self.status = ""
        self.listening = False
        self.thinking = False
        self.level = 0.0
        self.levels: deque[float] = deque([0.0] * 48, maxlen=48)
        self._drag: QPoint | None = None
        self._time = 0.0
        self._level_clock = 0.0
        self._hold = 0.0         # waits for the chip to land before reacting

        self.ram = read()
        self._shown_pct = round(self.ram.pct, 1)
        self._shown_frozen = 0.0
        self._color = theme.ram_color(self.ram.pct)
        self._cells = [_Cell(c, r) for c in range(COLS) for r in range(ROWS)]
        self._retarget()
        for cell in self._cells:
            cell.used, cell.ice, cell.wait = cell.goal_used, cell.goal_ice, 0.0

        self._timer = QTimer(self, interval=1000, timeout=self.tick)
        self._timer.start()
        if screen := QGuiApplication.primaryScreen():
            area = screen.availableGeometry()
            self.move(area.right() - W - 16, area.top() + 16)

    def _retarget(self) -> None:
        n = len(self._cells)
        used = round(min(self.ram.pct, 100) / 100 * n)
        frozen = round(self.freed_gb / max(self.ram.total_gb, 0.1) * n)
        frozen = min(frozen, n - used)
        for i, c in enumerate(self._cells):
            goal_used, goal_ice = (1.0, 0.0) if i < used else (0.0, 1.0) if i < used + frozen else (0.0, 0.0)
            if (goal_used, goal_ice) != (c.goal_used, c.goal_ice):
                c.goal_used, c.goal_ice = goal_used, goal_ice
                # The wave starts at the boundary between in use and frozen, and runs outward.
                c.wait = abs(c.col - used / ROWS) * STAGGER_S

    # ---- inputs ------------------------------------------------------------

    def tick(self) -> None:
        self.ram = self.read()
        if self._hold <= 0:
            self._retarget()
        self._wake()

    def set_freed(self, gb: float) -> None:
        self.freed_gb = gb
        self.tick()

    def hold(self, seconds: float) -> None:
        """Keep showing the old value until the transition reaches the gauge."""
        self._hold = seconds
        self._wake()

    def set_status(self, text: str) -> None:
        self.status = text
        self.update()

    def set_listening(self, on: bool) -> None:
        self.listening = on
        if on:
            self.levels.extend([0.0] * self.levels.maxlen)
        self._wake()

    def set_thinking(self, on: bool) -> None:
        self.thinking = on
        self._wake()

    def set_level(self, level: float) -> None:
        self.level = level

    def center_point(self) -> QPointF:
        return QPointF(self.frameGeometry().center())

    def _wake(self) -> None:
        fx.ticker().add(self)
        self.update()

    # ---- animation ---------------------------------------------------------

    def step(self, dt: float) -> bool:
        self._time += dt
        if self._hold > 0:
            self._hold -= dt
            if self._hold <= 0:
                self._retarget()
            self.update()
            return True

        moving = self.listening or self.thinking
        for c in self._cells:
            if c.wait > 0:
                c.wait -= dt
                moving = True
                continue
            before = (c.used, c.ice)
            c.used = fx.approach(c.used, c.goal_used, dt, 13)
            c.ice = fx.approach(c.ice, c.goal_ice, dt, 13)
            if abs(c.used - c.goal_used) < 0.01 and abs(c.ice - c.goal_ice) < 0.01:
                c.used, c.ice = c.goal_used, c.goal_ice
            if before != (c.used, c.ice):
                moving = True

        goal = round(self.ram.pct, 1)        # digits must rest level, not half-rolled
        self._shown_pct = fx.approach(self._shown_pct, goal, dt, 4.6)
        self._shown_frozen = fx.approach(self._shown_frozen, self.freed_gb, dt, 4.6)
        self._color = fx.mix(self._color, theme.ram_color(self._shown_pct), min(dt * 5, 1.0))
        if abs(self._shown_pct - goal) > 0.02 or abs(self._shown_frozen - self.freed_gb) > 0.004:
            moving = True
        else:
            self._shown_pct, self._shown_frozen = goal, self.freed_gb

        if self.listening:
            self._level_clock += dt
            if self._level_clock >= 0.04:
                self._level_clock = 0.0
                self.levels.append(self.level)
        self.update()
        return moving

    # ---- painting ----------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(theme.ICE if self.listening else theme.LINE), 1))
        p.setBrush(QColor(theme.PANEL))
        p.drawRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 10, 10)

        self._paint_number(p)
        moving = abs(self._shown_pct - round(self.ram.pct, 1)) > 0.02
        scale = self.ram.used_gb / max(self.ram.pct, 0.1)          # keeps the source's own GB units
        used = self._shown_pct * scale if moving else self.ram.used_gb   # follows the digits
        p.setPen(QColor(theme.INK))
        p.setFont(self._font(theme.TEXT))
        p.drawText(QRectF(180, 18, W - 196, 24), Qt.AlignmentFlag.AlignRight,
                   f"{used:.2f}/{self.ram.total_gb:.2f} GB")
        p.setPen(QColor(theme.ICE if self._shown_frozen > 0.005 else theme.MUTED))
        p.setFont(self._font(theme.TEXT, QFont.Weight.DemiBold))
        p.drawText(QRectF(16, 78, W - 32, 26), Qt.AlignmentFlag.AlignLeft,
                   f"freed this session: {self._shown_frozen * 1024:,.0f} MB")

        self._paint_cells(p)

        y = GRID_Y + ROWS * (CELL + GAP) + 8
        if self.listening:
            self._paint_wave(p, y)
            return
        p.setPen(QColor(theme.MUTED))
        p.setFont(self._font(theme.TEXT))
        text = self.status or "Hold Ctrl+Alt+Space and say what you're working on"
        if self.simulated:
            text = f"Simulated. {text}"
        rect = QRectF(16, y, W - 32, H - y - 6)
        flags = Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignTop
        p.drawText(rect, flags, text)

    def _paint_number(self, p: QPainter) -> None:
        """Odometer digits, to one decimal: the tenths roll continuously, and each higher
        digit turns over only while the one below it passes from 9 to 0."""
        p.setFont(self._font(54, QFont.Weight.Light))
        metrics = p.fontMetrics()
        digit_w = metrics.horizontalAdvance("0")
        tenths = min(self._shown_pct, 100.0) * 10
        if abs(tenths - round(tenths)) < 1e-6:
            tenths = float(round(tenths))
        p.save()
        p.setClipRect(QRectF(12, 10, 170, DIGIT_H + 6))
        p.setPen(self._color)
        x = 16.0
        places = (1000, 100, 10, 1) if tenths >= 999.5 else (100, 10, 1)
        for place in places:
            whole = int(tenths // place)
            below = tenths % place
            frac = below if place == 1 else max(below - (place - 1), 0.0)
            if place == 1:
                p.drawText(QRectF(x, 10, digit_w * 0.5, DIGIT_H), Qt.AlignmentFlag.AlignCenter, ".")
                x += digit_w * 0.5
            for digit, shift in ((whole % 10, 0.0), ((whole + 1) % 10, 1.0)):
                top = 10 + DIGIT_H * (shift - frac)
                if -DIGIT_H < top - 10 < DIGIT_H:
                    p.drawText(QRectF(x, top, digit_w, DIGIT_H), Qt.AlignmentFlag.AlignCenter, str(digit))
            x += digit_w
        p.restore()
        p.setPen(QColor(theme.MUTED))
        p.setFont(self._font(22, QFont.Weight.Light))
        p.drawText(QRectF(x + 3, 16, 30, DIGIT_H - 10), Qt.AlignmentFlag.AlignVCenter, "%")

    def _paint_cells(self, p: QPainter) -> None:
        free, frozen = QColor(theme.FREE), QColor(theme.ICE)
        sweep = (self._time * 0.8 % 1.3 - 0.15) * COLS if self.thinking else None
        p.setPen(Qt.PenStyle.NoPen)
        pitch = (W - 2 * GRID_X + GAP) / COLS
        for c in self._cells:
            color = fx.mix(free, self._color, c.used)
            color = fx.mix(color, frozen, c.ice * 0.8)
            if sweep is not None:
                color = fx.mix(color, QColor(theme.INK), max(0.0, 1 - abs(c.col - sweep) / 3) * 0.5)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(GRID_X + c.col * pitch, GRID_Y + c.row * (CELL + GAP), pitch - GAP, CELL), 1.2, 1.2)

    def _paint_wave(self, p: QPainter, y: float) -> None:
        mid = y + 10
        step = (W - 32) / len(self.levels)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.ICE))
        for i, level in enumerate(self.levels):
            h = max(1.5, level * 18)
            p.drawRoundedRect(QRectF(16 + i * step, mid - h / 2, max(step - 2.4, 1.2), h), 1, 1)

    @staticmethod
    def _font(px: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
        f = QFont(theme.FONT)
        f.setPixelSize(px)
        f.setWeight(weight)
        return f

    def mousePressEvent(self, e) -> None:
        self._drag = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e) -> None:
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _e) -> None:
        self._drag = None
