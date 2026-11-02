"""Motion engine: one ticker, and the overlay for the freeze and thaw transitions.

Everything animated implements step(dt) -> still_alive, so the same code runs
live at 60 fps and frame by frame in demo/record_preview.py. The ticker stops
when nothing is moving: a RAM tool must not burn CPU on its own decoration.
FF_REDUCED_MOTION=1 turns the full-screen transition off.

Motion rule: every movement explains a change. The amount leaves the card and
arrives in the gauge, so you see where the memory went. Nothing is decoration.
"""
from __future__ import annotations

import math
import os
import time

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from ui import theme

REDUCED_MOTION = os.environ.get("FF_REDUCED_MOTION") == "1"
TRAVEL_S = 0.72        # the chip's flight; the gauge waits this long, then reacts


class Ticker(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.manual = False   # the recorder drives time itself
        self._items: list = []
        self._last = 0.0
        self._timer = QTimer(self, interval=16, timeout=self._fire)

    def add(self, item) -> None:
        if not any(i is item for i in self._items):
            self._items.append(item)
        if not self.manual and not self._timer.isActive():
            self._last = time.monotonic()
            self._timer.start()

    def advance(self, dt: float) -> None:
        for item in list(self._items):
            try:
                alive = item.step(dt)
            except RuntimeError:  # its Qt object is gone
                alive = False
            if not alive:
                self._items = [i for i in self._items if i is not item]
        if not self._items:
            self._timer.stop()

    def _fire(self) -> None:
        now = time.monotonic()
        dt, self._last = min(now - self._last, 0.05), now
        self.advance(dt)


_ticker: Ticker | None = None


def ticker() -> Ticker:
    global _ticker
    if _ticker is None:
        _ticker = Ticker()
    return _ticker


def approach(value: float, target: float, dt: float, rate: float) -> float:
    return target + (value - target) * math.exp(-rate * dt)


def mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t), round(a.alpha() + (b.alpha() - a.alpha()) * t))


def ease_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def ease_in_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


class MotionOverlay(QWidget):
    """Click-through and never takes focus. It only ever paints, and hides itself."""
    LENGTH_S = 1.7

    def __init__(self, headless: bool = False):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.headless = headless
        self.mode = ""
        self.t = 0.0
        self.start = QPointF()
        self.end = QPointF()
        self.text = ""

    def play_freeze(self, origin: QPointF, target: QPointF, text: str) -> None:
        self._play("freeze", origin, target, text)

    def play_thaw(self, origin: QPointF, target: QPointF, text: str) -> None:
        self._play("thaw", origin, target, text)

    def _play(self, mode: str, start: QPointF, end: QPointF, text: str) -> None:
        if REDUCED_MOTION:
            return
        self.mode, self.t, self.start, self.end, self.text = mode, 0.0, QPointF(start), QPointF(end), text
        if not self.headless:
            self.show()
        ticker().add(self)

    def step(self, dt: float) -> bool:
        self.t += dt
        self.update()
        if self.t < self.LENGTH_S:
            return True
        self.mode = ""
        if not self.headless:
            self.hide()
        return False

    def paintEvent(self, _e) -> None:
        self.draw(QPainter(self))

    def draw(self, p: QPainter) -> None:
        if not self.mode:
            return
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._draw_temperature(p)
        self._draw_chip(p)
        self._draw_arrival(p)
        p.restore()

    def _color(self) -> QColor:
        return QColor(theme.ICE if self.mode == "freeze" else theme.WARM)

    def _draw_temperature(self, p: QPainter) -> None:
        """The room changes temperature for a moment: barely there, felt more than seen."""
        strength = math.sin(min(self.t / self.LENGTH_S, 1.0) * math.pi) * 46
        w, h = self.width(), self.height()
        glow = QRadialGradient(QPointF(w / 2, h / 2), math.hypot(w, h) / 2)
        tint = self._color()
        tint.setAlpha(0)
        glow.setColorAt(0.55, tint)
        tint.setAlpha(round(strength))
        glow.setColorAt(1.0, tint)
        p.fillRect(QRectF(0, 0, w, h), glow)

    def _position(self, u: float) -> QPointF:
        v = ease_in_out(u)
        lift = QPointF(0, -70 * math.sin(v * math.pi))  # a shallow arc, as a thrown thing moves
        return self.start + (self.end - self.start) * v + lift

    def _draw_chip(self, p: QPainter) -> None:
        u = self.t / TRAVEL_S
        if u > 1:
            return
        at = self._position(u)
        for i in range(1, 15):  # the trail: fades back along the path
            back = self._position(max(u - i * 0.018, 0))
            c = self._color()
            c.setAlpha(round(75 * (1 - i / 15) * min(u * 6, 1)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawEllipse(back, 2.4 * (1 - i / 18), 2.4 * (1 - i / 18))
        scale = 1 - 0.3 * ease_in_out(u)
        alpha = min(u * 8, 1.0) * min((1 - u) * 8, 1.0)
        w, h = 96 * scale, 34 * scale
        rect = QRectF(at.x() - w / 2, at.y() - h / 2, w, h)
        c = self._color()
        c.setAlphaF(alpha)
        p.setBrush(c)
        p.drawRoundedRect(rect, h / 2, h / 2)
        ink = QColor(theme.ON_ACCENT)
        ink.setAlphaF(alpha)
        p.setPen(ink)
        f = QFont(theme.FONT)
        f.setPixelSize(max(round(15 * scale), 8))
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text)

    def _draw_arrival(self, p: QPainter) -> None:
        u = (self.t - TRAVEL_S) / 0.55
        if not 0 <= u <= 1:
            return
        c = self._color()
        c.setAlphaF(0.65 * (1 - u))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(c, 1.5))
        r = 18 + 58 * ease_out(u)
        p.drawEllipse(self.end, r, r)
