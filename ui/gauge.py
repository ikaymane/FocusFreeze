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
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ui import fx, theme

W, H = 300, 164
PAD = 14
COLS, ROWS = 40, 3
CELL = 5.0
GAP = 1.2
GRID_X = PAD
GRID_Y = 86
STAGGER_S = 0.016       # the wave, per column
DIGIT_PX = 42
DIGIT_H = 48
DIGIT_TOP = 8
FREED_Y = 58
STATUS_Y = GRID_Y + ROWS * (CELL + GAP) + 7
ENTER_S = 0.32          # fade-in when the gauge first appears
STATUS_FADE_S = 0.22


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


CLICK_SLOP = 4   # px: a press that moves less than this is a click, not a drag


class Gauge(QWidget):
    clicked = Signal()   # not after a drag
    moved = Signal()     # the voice drawer follows it

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
        # Eased 0..1 values, so every state change blends instead of snapping.
        self._enter_t = 0.0      # first appearance
        self._listen_t = 0.0     # border glow, and the wave in place of the status line
        self._hover_t = 0.0
        self._hovered = False
        self._status_prev = ""
        self._status_t = 1.0     # crossfade from the previous status line
        self._press_at = QPoint()
        self.hotkey = "Ctrl+Alt+Space"   # replaced by the combo the app actually got

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

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if self._enter_t == 0.0:
            self.setWindowOpacity(0.0)
            self._wake()

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
        if text == self.status:
            return
        self._status_prev, self.status, self._status_t = self.status, text, 0.0
        self._wake()

    def set_hotkey(self, label: str) -> None:
        self.hotkey = label
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

        moving = self._ease(dt) or self.listening or self.thinking
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

    def _ease(self, dt: float) -> bool:
        """Advance the small UI blends. True while any is still moving."""
        if self._enter_t < 1.0:
            self._enter_t = min(1.0, self._enter_t + dt / ENTER_S)
            self.setWindowOpacity(fx.ease_out(self._enter_t))
        self._listen_t = fx.approach(self._listen_t, 1.0 if self.listening else 0.0, dt, 10)
        self._hover_t = fx.approach(self._hover_t, 1.0 if self._hovered else 0.0, dt, 12)
        self._status_t = min(1.0, self._status_t + dt / STATUS_FADE_S)
        settled = (self._enter_t >= 1.0 and self._status_t >= 1.0
                   and abs(self._listen_t - round(self._listen_t)) < 0.005
                   and abs(self._hover_t - round(self._hover_t)) < 0.005)
        if settled:
            self._listen_t, self._hover_t = float(round(self._listen_t)), float(round(self._hover_t))
        return not settled

    # ---- painting ----------------------------------------------------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Border: hover lifts it a little; listening turns it ice and lets it breathe.
        border = fx.mix(QColor(theme.LINE), QColor(theme.MUTED), self._hover_t * 0.35)
        breathe = 0.75 + 0.25 * math.sin(self._time * 4.0) if self.listening else 1.0
        border = fx.mix(border, QColor(theme.ICE), self._listen_t * breathe)
        p.setPen(QPen(border, 1))
        p.setBrush(QColor(theme.PANEL))
        p.drawRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 10, 10)
        p.translate(0, round((1 - fx.ease_out(self._enter_t)) * 6))   # settles as it fades in

        self._paint_number(p)
        moving = abs(self._shown_pct - round(self.ram.pct, 1)) > 0.02
        scale = self.ram.used_gb / max(self.ram.pct, 0.1)          # keeps the source's own GB units
        used = self._shown_pct * scale if moving else self.ram.used_gb   # follows the digits
        p.setPen(QColor(theme.MUTED))
        p.setFont(self._font(theme.SMALL))
        p.drawText(QRectF(W / 2, 14, W / 2 - PAD, 20), Qt.AlignmentFlag.AlignRight,
                   f"{used:.2f}/{self.ram.total_gb:.2f} GB")
        p.setPen(QColor(theme.ICE if self._shown_frozen > 0.005 else theme.MUTED))
        p.setFont(self._font(theme.SMALL, QFont.Weight.DemiBold))
        p.drawText(QRectF(PAD, FREED_Y, W - 2 * PAD, 22), Qt.AlignmentFlag.AlignLeft,
                   f"freed this session: {self._shown_frozen * 1024:,.0f} MB")

        self._paint_cells(p)

        # The status line and the voice wave share one slot and crossfade.
        if self._listen_t > 0.0:
            p.setOpacity(self._listen_t)
            self._paint_wave(p, STATUS_Y)
        if self._listen_t < 1.0:
            rect = QRectF(PAD, STATUS_Y, W - 2 * PAD, H - STATUS_Y - 4)
            flags = Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignTop
            p.setFont(self._font(theme.SMALL))
            p.setPen(QColor(theme.MUTED))
            if self._status_t < 1.0:
                p.setOpacity((1 - self._listen_t) * (1 - self._status_t))
                p.drawText(rect, flags, self._status_text(self._status_prev))
            p.setOpacity((1 - self._listen_t) * self._status_t)
            p.drawText(rect, flags, self._status_text(self.status))
        p.setOpacity(1.0)

    def _status_text(self, status: str) -> str:
        text = status or f"Hold {self.hotkey} and say what you're working on"
        return f"Simulated. {text}" if self.simulated else text

    def _paint_number(self, p: QPainter) -> None:
        """Odometer digits, to one decimal: the tenths roll continuously, and each higher
        digit turns over only while the one below it passes from 9 to 0."""
        p.setFont(self._font(DIGIT_PX, QFont.Weight.Light))
        metrics = p.fontMetrics()
        digit_w = metrics.horizontalAdvance("0")
        tenths = min(self._shown_pct, 100.0) * 10
        if abs(tenths - round(tenths)) < 1e-6:
            tenths = float(round(tenths))
        p.save()
        p.setClipRect(QRectF(PAD - 4, DIGIT_TOP, 140, DIGIT_H + 6))
        p.setPen(self._color)
        x = float(PAD)
        places = (1000, 100, 10, 1) if tenths >= 999.5 else (100, 10, 1)
        for place in places:
            whole = int(tenths // place)
            below = tenths % place
            frac = below if place == 1 else max(below - (place - 1), 0.0)
            if place == 1:
                p.drawText(QRectF(x, DIGIT_TOP, digit_w * 0.5, DIGIT_H), Qt.AlignmentFlag.AlignCenter, ".")
                x += digit_w * 0.5
            for digit, shift in ((whole % 10, 0.0), ((whole + 1) % 10, 1.0)):
                top = DIGIT_TOP + DIGIT_H * (shift - frac)
                if -DIGIT_H < top - DIGIT_TOP < DIGIT_H:
                    p.drawText(QRectF(x, top, digit_w, DIGIT_H), Qt.AlignmentFlag.AlignCenter, str(digit))
            x += digit_w
        p.restore()
        p.setPen(QColor(theme.MUTED))
        p.setFont(self._font(18, QFont.Weight.Light))
        p.drawText(QRectF(x + 2, DIGIT_TOP + 6, 26, DIGIT_H - 10), Qt.AlignmentFlag.AlignVCenter, "%")

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
        mid = y + 12
        step = (W - 2 * PAD) / len(self.levels)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.ICE))
        for i, level in enumerate(self.levels):
            h = max(1.5, level * 20)
            p.drawRoundedRect(QRectF(PAD + i * step, mid - h / 2, max(step - 2.4, 1.2), h), 1, 1)

    @staticmethod
    def _font(px: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
        f = QFont(theme.FONT)
        f.setPixelSize(px)
        f.setWeight(weight)
        return f

    def mousePressEvent(self, e) -> None:
        self._drag = e.globalPosition().toPoint() - self.pos()
        self._press_at = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e) -> None:
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e) -> None:
        dragged = (e.globalPosition().toPoint() - self._press_at).manhattanLength()
        self._drag = None
        if dragged < CLICK_SLOP:
            self.clicked.emit()

    def enterEvent(self, e) -> None:
        self._hovered = True
        self._wake()

    def leaveEvent(self, e) -> None:
        self._hovered = False
        self._wake()

    def moveEvent(self, e) -> None:
        super().moveEvent(e)
        self.moved.emit()
