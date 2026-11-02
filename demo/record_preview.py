"""Renders a UI preview video from the real widgets and the real Controller, frame by frame.

    python demo/record_preview.py                     # demo/recordings/focus-freeze-preview.mp4
    python demo/record_preview.py --stills DIR        # also save key frames as PNG

This is NOT the submission video. The desk, the plan and the RAM numbers are simulated,
and the video says so on screen. The submission video is filmed on the 4 GB machine.
"""
from __future__ import annotations

import argparse
import math
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_FONTDIR"] = str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts")  # offscreen has none
os.environ["QT_SCALE_FACTOR"] = "2"                              # stays sharp under the camera's zoom
os.environ["FF_HOME"] = tempfile.mkdtemp(prefix="ff-preview-")   # never touches real sessions or spend
sys.path.insert(0, str(Path(__file__).parent.parent))

import imageio_ffmpeg
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from ui import fx, mocks, theme
from ui.app import Controller, connect_gauge
from ui.consent import ConsentCard
from ui.fx import MotionOverlay
from ui.gauge import H as GAUGE_H
from ui.gauge import W as GAUGE_W
from ui.gauge import Gauge
from ui.guardian import GuardianCard
from ui.stats import StatsCard

W, H, FPS = 1920, 1080, 30
GAUGE_POS = QPoint(W - GAUGE_W - 24, 24)
GAUGE_MID = QPointF(GAUGE_POS.x() + GAUGE_W / 2, GAUGE_POS.y() + GAUGE_H / 2)
TASKBAR_H = 48
SHADOW = 26
OUT = Path(__file__).parent / "recordings" / "focus-freeze-preview.mp4"

# Back to front. (app_id, x, y, w, h)
WINDOWS = [("steam.exe", 70, 96, 760, 500), ("discord.exe", 1040, 300, 640, 480), ("slack.exe", 860, 90, 600, 420),
           ("ms-teams.exe", 930, 470, 640, 470), ("winword.exe", 96, 450, 620, 520), ("msedge.exe", 200, 60, 900, 560),
           ("chrome.exe", 300, 150, 900, 620), ("acrord32.exe", 1360, 330, 470, 610), ("code.exe", 420, 260, 1000, 690)]
ICONS = {"code.exe": "#2F8FDD", "windowsterminal.exe": "#3A4450", "acrord32.exe": "#D1352B", "chrome.exe": "#D9A52B",
         "msedge.exe": "#2BA8A0", "ms-teams.exe": "#5B5FC7", "discord.exe": "#5865F2", "slack.exe": "#7A3E8E",
         "steam.exe": "#3C6E91", "winword.exe": "#2B6BC2", "spotify.exe": "#1DB954", "explorer.exe": "#E8B23A"}


def font(px: int, weight: QFont.Weight = QFont.Weight.Normal, family: str = theme.FONT) -> QFont:
    f = QFont(family)
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


# ---- believable app windows -------------------------------------------------

def _bars(p, rng, x, y, w, rows, gap, color, height=7):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    for i in range(rows):
        p.drawRoundedRect(QRectF(x, y + i * gap, w * rng.uniform(0.45, 1), height), height / 2, height / 2)


def _code(p, w, h, rng):
    p.fillRect(QRectF(0, 0, w, h), QColor("#1E1E1E"))
    p.fillRect(QRectF(0, 0, 48, h), QColor("#333333"))
    p.fillRect(QRectF(48, 0, 220, h), QColor("#252526"))
    p.setFont(font(13))
    p.setPen(QColor("#CCCCCC"))
    for i, name in enumerate(("shop-frontend", "  src", "    auth.ts", "    session.ts", "    tokens.ts", "  tests",
                              "    auth.test.ts", "  package.json")):
        p.drawText(QPointF(64, 30 + i * 24), name)
    p.setFont(font(14, family="Consolas"))
    lines = [[("#6A9955", "// Bug: JWT expires right after refresh")],
             [("#C586C0", "export async function "), ("#DCDCAA", "login"), ("#D4D4D4", "(req: Request) {")],
             [("#C586C0", "  const "), ("#D4D4D4", "user = "), ("#C586C0", "await "), ("#DCDCAA", "authenticate"), ("#D4D4D4", "(req.body);")],
             [("#C586C0", "  if "), ("#D4D4D4", "(!user) "), ("#C586C0", "return "), ("#DCDCAA", "error"), ("#D4D4D4", "("), ("#B5CEA8", "401"), ("#D4D4D4", ");")],
             [("#C586C0", "  const "), ("#D4D4D4", "token = "), ("#DCDCAA", "issueToken"), ("#D4D4D4", "(user, { ttl: "), ("#B5CEA8", "3600"), ("#D4D4D4", " });")],
             [("#D4D4D4", "  session."), ("#9CDCFE", "refresh"), ("#D4D4D4", " = token.refresh;")],
             [("#C586C0", "  return "), ("#DCDCAA", "redirect"), ("#D4D4D4", "("), ("#CE9178", "\"/home\""), ("#D4D4D4", ");")],
             [("#D4D4D4", "}")]]
    fm = p.fontMetrics()
    for i, line in enumerate(lines):
        x, y = 320.0, 34 + i * 24
        p.setPen(QColor("#858585"))
        p.drawText(QPointF(284, y), str(41 + i))
        for color, text in line:
            p.setPen(QColor(color))
            p.drawText(QPointF(x, y), text)
            x += fm.horizontalAdvance(text)
    term = h * 0.62
    p.fillRect(QRectF(268, term, w - 268, h - term), QColor("#181818"))
    p.setPen(QColor("#CCCCCC"))
    for i, text in enumerate(("$ npm run dev", "webpack compiling...", "[====>                ] 23%  3m 12s elapsed")):
        p.drawText(QPointF(284, term + 28 + i * 22), text)


def _browser(url, heading):
    def paint(p, w, h, rng):
        p.fillRect(QRectF(0, 0, w, h), QColor("#FFFFFF"))
        p.fillRect(QRectF(0, 0, w, 40), QColor("#E8EBEE"))
        p.setBrush(QColor("#FFFFFF"))
        p.setPen(QColor("#B8C0C7"))
        p.drawRoundedRect(QRectF(16, 8, w - 32, 24), 12, 12)
        p.setPen(QColor("#50606B"))
        p.setFont(font(12))
        p.drawText(QPointF(30, 25), url)
        p.setPen(QColor("#1C2730"))
        p.setFont(font(30, QFont.Weight.DemiBold))
        p.drawText(QPointF(70, 110), heading)
        _bars(p, rng, 70, 140, w - 140, 9, 26, "#D3DAE0", 9)
    return paint


def _doc(p, w, h, rng):
    p.fillRect(QRectF(0, 0, w, h), QColor("#F1F3F5"))
    p.fillRect(QRectF(0, 0, w, 54), QColor("#FAFBFC"))
    p.setBrush(QColor("#FFFFFF"))
    p.setPen(QColor("#DDE2E6"))
    p.drawRect(QRectF(60, 76, w - 120, h))
    p.setPen(QColor("#22303A"))
    p.setFont(font(20, QFont.Weight.DemiBold))
    p.drawText(QPointF(100, 124), "Chapter 3: Urban heat islands")
    _bars(p, rng, 100, 148, w - 200, 11, 24, "#C7D0D6", 7)


def _pdf(p, w, h, rng):
    p.fillRect(QRectF(0, 0, w, h), QColor("#4A4F55"))
    p.fillRect(QRectF(34, 22, w - 68, h), QColor("#FFFFFF"))
    p.setPen(QColor("#22303A"))
    p.setFont(font(16, QFont.Weight.DemiBold))
    p.drawText(QPointF(58, 62), "The energetic basis of the urban")
    p.drawText(QPointF(58, 84), "heat island")
    _bars(p, rng, 58, 108, w - 116, 17, 20, "#CBD3D9", 6)


def _chat(side, bg, bubble):
    def paint(p, w, h, rng):
        lines = ("Standup moved to 11", "Did the deploy finish?", "Looks good, merging")
        p.fillRect(QRectF(0, 0, w, h), QColor(bg))
        p.fillRect(QRectF(0, 0, 170, h), QColor(side))
        _bars(p, rng, 18, 22, 130, 11, 30, "#8A93A6", 9)
        p.setFont(font(13))
        for i in range(6):
            y = 26 + i * 66
            p.setBrush(QColor(rng.choice(("#E06C75", "#61AFEF", "#98C379", "#D19A66"))))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(202, y + 15), 15, 15)
            p.setBrush(QColor(bubble))
            p.drawRoundedRect(QRectF(228, y, min(w - 260, rng.uniform(220, 360)), 40), 8, 8)
            p.setPen(QColor("#E6E9EC"))
            p.drawText(QPointF(240, y + 25), lines[i % len(lines)])
    return paint


def _steam(p, w, h, rng):
    p.fillRect(QRectF(0, 0, w, h), QColor("#1B2838"))
    p.setPen(Qt.PenStyle.NoPen)
    for row in range(3):
        for col in range(5):
            p.setBrush(QColor.fromHsv(rng.randint(0, 359), 110, 150))
            p.drawRoundedRect(QRectF(22 + col * 146, 22 + row * 150, 134, 136), 5, 5)


PAINTERS = {"code.exe": _code, "winword.exe": _doc, "acrord32.exe": _pdf, "steam.exe": _steam,
            "msedge.exe": _browser("file:///demo/injection.html", "An ordinary-looking web page"),
            "chrome.exe": _browser("localhost:3000/login", "Sign in to Shop"),
            "ms-teams.exe": _chat("#292A40", "#1F1F2B", "#34354D"),
            "slack.exe": _chat("#3F0E40", "#1A1D21", "#2B2F36"),
            "discord.exe": _chat("#2B2D31", "#313338", "#3F4248")}
CHROME = {"code.exe": ("#323233", "#CCCCCC"), "msedge.exe": ("#DEE3E8", "#1C2730"), "chrome.exe": ("#DEE3E8", "#1C2730"),
          "winword.exe": ("#2B579A", "#FFFFFF"), "acrord32.exe": ("#3A3D42", "#E6E6E6"), "steam.exe": ("#171D25", "#C7D5E0"),
          "ms-teams.exe": ("#292A40", "#E6E6F0"), "slack.exe": ("#3F0E40", "#F0E6F0"), "discord.exe": ("#1E1F22", "#DCDDDE")}


def window_pixmap(app_id: str, w: int, h: int) -> QPixmap:
    """Pre-rendered at 2x with a soft shadow, so every frame is only a transform."""
    snap = next(a for a in mocks.DESK if a.app_id == app_id)
    pix = QPixmap((w + 2 * SHADOW) * 2, (h + 2 * SHADOW) * 2)
    pix.setDevicePixelRatio(2)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(SHADOW, 0, -2):
        p.setBrush(QColor(0, 0, 0, 7))
        p.drawRoundedRect(QRectF(SHADOW - i, SHADOW - i + 8, w + 2 * i, h + 2 * i), 10 + i, 10 + i)
    p.translate(SHADOW, SHADOW)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w, h), 9, 9)
    p.setClipPath(path)
    bar, ink = CHROME[app_id]
    p.fillRect(QRectF(0, 0, w, 34), QColor(bar))
    p.setPen(QColor(ink))
    p.setFont(font(12))
    p.drawText(QRectF(14, 0, w - 140, 34), Qt.AlignmentFlag.AlignVCenter,
               p.fontMetrics().elidedText(snap.window_titles[0], Qt.TextElideMode.ElideRight, w - 140))
    p.setPen(QPen(QColor(ink), 1))
    for i, kind in enumerate(("min", "max", "close")):
        cx = w - 22 - (2 - i) * 40
        if kind == "min":
            p.drawLine(QPointF(cx - 5, 17), QPointF(cx + 5, 17))
        elif kind == "max":
            p.drawRect(QRectF(cx - 5, 12, 10, 10))
        else:
            p.drawLine(QPointF(cx - 5, 12), QPointF(cx + 5, 22))
            p.drawLine(QPointF(cx - 5, 22), QPointF(cx + 5, 12))
    p.translate(0, 34)
    PAINTERS[app_id](p, w, h - 34, random.Random(app_id))
    p.end()
    return pix


def wallpaper() -> QPixmap:
    pix = QPixmap(W, H)
    p = QPainter(pix)
    base = QLinearGradient(0, 0, W, H)
    base.setColorAt(0, QColor("#13293D"))
    base.setColorAt(1, QColor("#28506B"))
    p.fillRect(pix.rect(), base)
    for x, y, r, color in ((360, 900, 1100, "#3F7C9B"), (1600, 180, 900, "#1D4A68"), (1300, 980, 800, "#6D8FA6")):
        g = QRadialGradient(QPointF(x, y), r)
        c = QColor(color)
        c.setAlpha(170)
        g.setColorAt(0, c)
        c.setAlpha(0)
        g.setColorAt(1, c)
        p.fillRect(pix.rect(), g)
    p.end()
    return pix


class Recorder:
    def __init__(self, stills: Path | None):
        self.app = QApplication([])
        fx.ticker().manual = True
        self.stills = stills
        mocks.install()
        mocks.seed_sessions()
        mocks.plan_gate = threading.Event()
        actuator = mocks.SlowActuator(0.0, 0.8)   # 3.2 s for four apps, as the spec's restore line
        self.ctl = Controller(mocks.DeskSensor(), mocks.mock_policy, actuator, read_ram=lambda: mocks.ram_for(actuator))
        self.gauge = Gauge(self.ctl.read_ram)
        self.gauge._timer.stop()
        self.overlay = MotionOverlay(headless=True)
        self.overlay.resize(W, H)
        connect_gauge(self.ctl, self.gauge, self.overlay, lambda: GAUGE_MID)
        self.stats = None
        self.card_screen = QPoint()
        self.ctl.card_opened.connect(self._card_opened)
        self.ctl.stats_ready.connect(self._stats_ready)
        self.caption = ""
        self.caption_a = 0.0
        self.shown_caption = ""
        self.speech = ""
        self.spot = None
        self.sink = {a[0]: 0.0 for a in WINDOWS}
        self.motion = dict(self.sink)
        self.frame_no = 0
        self.ram_clock = 0.0
        self.title = 0.0
        self.title_text = ("", "")
        self.cam = [W / 2, H / 2, 1.0]
        self.cam_v = [W / 2, H / 2, 1.0]    # double smoothing: starts and stops without a jerk
        self.goal = [W / 2, H / 2, 1.0]
        self.wall = wallpaper()
        self.windows = {a[0]: window_pixmap(a[0], a[3], a[4]) for a in WINDOWS}
        OUT.parent.mkdir(parents=True, exist_ok=True)
        self.ffmpeg = subprocess.Popen(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra",
             "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-crf", "16", "-preset", "medium", "-movflags", "+faststart", str(OUT)],
            stdin=subprocess.PIPE)

    @property
    def card(self):
        return self.ctl.card

    def _card_opened(self, _card) -> None:
        self.ctl.card_center = QPointF(W / 2, H / 2 - 240)

    def _stats_ready(self, stats) -> None:
        self.stats = StatsCard(stats)
        self.stats.present()

    # ---- the desk ----------------------------------------------------------

    def _draw_window(self, p: QPainter, app_id: str, x, y, w, h) -> None:
        s = self.motion[app_id]
        if s >= 0.995:
            return
        icon_x, icon_y = self._icon_pos(app_id)
        u = fx.ease_in_out(s)
        cx, cy = x + w / 2, y + h / 2
        p.save()
        p.setOpacity(1 - max(u - 0.55, 0) / 0.45)
        p.translate(cx + (icon_x - cx) * u, cy + (icon_y - cy) * u)
        p.scale(1 - 0.92 * u, 1 - 0.92 * u)
        p.drawPixmap(QPointF(-w / 2 - SHADOW, -h / 2 - SHADOW), self.windows[app_id])
        p.restore()

    def _icon_pos(self, app_id: str) -> tuple[float, float]:
        i = list(ICONS).index(app_id)
        return W / 2 + (i - (len(ICONS) - 1) / 2) * 46, H - TASKBAR_H / 2

    def _draw_taskbar(self, p: QPainter) -> None:
        p.fillRect(QRectF(0, H - TASKBAR_H, W, TASKBAR_H), QColor(16, 28, 38, 225))
        for app_id, color in ICONS.items():
            x, y = self._icon_pos(app_id)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(x - 13, y - 14, 26, 26), 6, 6)
            p.setPen(QColor("#FFFFFF"))
            p.setFont(font(13, QFont.Weight.DemiBold))
            name = next(a.display_name for a in mocks.DESK if a.app_id == app_id)
            p.drawText(QRectF(x - 13, y - 14, 26, 26), Qt.AlignmentFlag.AlignCenter, name[0])
            p.setPen(Qt.PenStyle.NoPen)
            is_frozen = self.sink.get(app_id, 0) > 0.5
            p.setBrush(QColor(theme.ICE if is_frozen else "#8D9AA3"))
            width = 16 if is_frozen else 6
            p.drawRoundedRect(QRectF(x - width / 2, y + 16, width, 3), 1.5, 1.5)

    # ---- one frame ---------------------------------------------------------

    def _on_screen(self) -> list:
        return [c for c in (self.card, self.stats, *getattr(self, "leaving", [])) if c is not None and isValid(c) and c.isVisible()]

    def frame(self, dt: float = 1 / FPS) -> None:
        fx.ticker().advance(dt)
        self.app.processEvents()
        self.ram_clock += dt
        if self.ram_clock >= 0.5:
            self.ram_clock = 0
            self.gauge.tick()
        frozen = {e.app_id for e in self.ctl.actuator.frozen()}
        for key in self.sink:
            goal = 1.0 if key in frozen else 0.0
            self.sink[key] = goal
            step = dt / 0.5
            self.motion[key] = min(self.motion[key] + step, 1.0) if goal else max(self.motion[key] - step, 0.0)
        for i in range(3):
            self.cam_v[i] = fx.approach(self.cam_v[i], self.goal[i], dt, 3.4)
            self.cam[i] = fx.approach(self.cam[i], self.cam_v[i], dt, 3.4)
        self.caption_a = fx.approach(self.caption_a, 1.0 if self.caption else 0.0, dt, 9)
        if self.caption:
            self.shown_caption = self.caption

        img = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        cx, cy, z = self.cam
        half_w, half_h = W / 2 / z, H / 2 / z
        cx, cy = min(max(cx, half_w), W - half_w), min(max(cy, half_h), H - half_h)
        p.save()
        p.translate(W / 2, H / 2)
        p.scale(z, z)
        p.translate(-cx, -cy)
        p.drawPixmap(0, 0, self.wall)
        for a in WINDOWS:
            self._draw_window(p, *a)
        self._draw_taskbar(p)
        for card in self._on_screen():
            pix = card.grab()
            size = pix.deviceIndependentSize()
            if isinstance(card, GuardianCard):
                pos = QPoint(GAUGE_POS.x() + GAUGE_W - round(size.width()), GAUGE_POS.y() + GAUGE_H + 14 + round(card.fx_dy))
            else:
                pos = QPoint(round((W - size.width()) / 2), round((H - TASKBAR_H - size.height()) / 2 + card.fx_dy))
            self.card_screen = pos
            p.setOpacity(card.fx_opacity)
            p.drawPixmap(pos, pix)
            p.setOpacity(1)
        self._spotlight(p)
        p.drawPixmap(GAUGE_POS, self.gauge.grab())
        self.overlay.draw(p)
        p.restore()
        self._captions(p)
        self._title(p)
        p.end()
        self.ffmpeg.stdin.write(bytes(img.constBits()))
        self._last = img
        self.frame_no += 1

    def hold(self, seconds: float) -> None:
        for _ in range(round(seconds * FPS)):
            self.frame()

    def still(self, name: str) -> None:
        if not self.stills:
            return
        self.frame()
        self.stills.mkdir(parents=True, exist_ok=True)
        self._last.save(str(self.stills / f"{name}.png"))

    def look(self, x: float = W / 2, y: float = H / 2, zoom: float = 1.0) -> None:
        self.goal = [x, y, zoom]

    def box_center(self, name: str) -> tuple[float, float]:
        box = getattr(self.card, name)
        at = box.mapTo(self.card, QPoint(0, 0)) + self.card_screen
        return at.x() + box.width() / 2, at.y() + box.height() / 2

    def _spotlight(self, p: QPainter) -> None:
        if not self.spot or not self.card or not isValid(self.card):
            return
        box = getattr(self.card, self.spot, None)
        if box is None:
            return
        at = box.mapTo(self.card, QPoint(0, 0)) + self.card_screen
        p.setPen(QPen(QColor(theme.INK), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(at.x() - 4, at.y() - 4, box.width() + 8, box.height() + 8), 8, 8)

    def _captions(self, p: QPainter) -> None:
        """Lower third: text on a soft fade, no boxes. The notice stays on every frame."""
        strength = max(self.caption_a, 1.0 if self.speech else 0.0)
        fade = QLinearGradient(0, H - 290, 0, H)
        c = QColor(6, 16, 24, 0)
        fade.setColorAt(0, c)
        c.setAlpha(round(235 * strength))
        fade.setColorAt(0.45, c)
        c.setAlpha(round(250 * strength))
        fade.setColorAt(1, c)
        p.fillRect(QRectF(0, H - 290, W, 290), fade)
        p.setPen(QColor(255, 255, 255, 170))
        p.setFont(font(14))
        p.drawText(QRectF(20, H - 34, 800, 26), Qt.AlignmentFlag.AlignVCenter,
                   "UI preview with simulated apps and RAM. Nothing is really frozen here.")
        if self.speech:
            p.setPen(QColor(theme.ICE))
            p.setFont(font(40, QFont.Weight.Light))
            p.drawText(QRectF(0, H - 170, W, 60), Qt.AlignmentFlag.AlignCenter, f"\u201c{self.speech}\u201d")
        ink = QColor(theme.INK)
        ink.setAlphaF(self.caption_a)
        p.setPen(ink)
        p.setFont(font(27))
        p.drawText(QRectF(0, H - 104, W, 50), Qt.AlignmentFlag.AlignCenter, self.shown_caption)

    def _title(self, p: QPainter) -> None:
        if self.title <= 0:
            return
        p.fillRect(QRectF(0, 0, W, H), QColor(16, 26, 33, round(255 * self.title)))
        p.setOpacity(self.title)
        p.setPen(QColor(theme.INK))
        p.setFont(font(84, QFont.Weight.Light))
        p.drawText(QRectF(0, H / 2 - 110, W, 110), Qt.AlignmentFlag.AlignCenter, self.title_text[0])
        p.setPen(QColor(theme.MUTED))
        p.setFont(font(26))
        p.drawText(QRectF(0, H / 2 + 12, W, 50), Qt.AlignmentFlag.AlignCenter, self.title_text[1])
        p.setOpacity(1)

    # ---- helpers for the script --------------------------------------------

    def fade_title(self, to: float, seconds: float = 0.8) -> None:
        start = self.title
        n = round(seconds * FPS)
        for i in range(1, n + 1):
            self.title = start + (to - start) * fx.ease_in_out(i / n)
            self.frame()

    def wait_for(self, cond, limit_s: float = 8.0) -> None:
        end = time.monotonic() + limit_s
        while not cond():
            if time.monotonic() > end:
                raise TimeoutError("scene did not reach its state")
            self.app.processEvents()
            time.sleep(0.002)

    def say(self, sentence: str, seconds_per_word: float = 0.3) -> None:
        """Push-to-talk, played back: waveform on the gauge, words arriving."""
        self.gauge.set_listening(True)
        words = sentence.split()
        t = 0.0
        for i in range(1, len(words) + 1):
            self.speech = " ".join(words[:i])
            for _ in range(round(seconds_per_word * FPS)):
                t += 1 / FPS
                self.gauge.set_level(min(1.0, 0.18 + 0.75 * abs(math.sin(t * 11) * math.sin(t * 3.1))))
                self.frame()
        self.gauge.set_listening(False)
        self.hold(0.35)
        self.speech = ""

    def transcript(self, text: str) -> None:
        self.leaving = [self.card] if self.card else []   # keep drawing a card through its outro
        self.ctl.handle_transcript(text)

    # ---- the film ----------------------------------------------------------

    def run(self) -> None:
        self.title, self.title_text = 1.0, ("Focus Freeze", "It freezes what your task doesn't need.")
        self.hold(1.8)
        self.fade_title(0)

        self.caption = "A 4 GB machine on a normal day. Everything is crawling."
        self.look(GAUGE_MID.x() - 180, GAUGE_MID.y() + 100, 1.32)
        self.hold(3.2)
        self.still("01-pressure")

        self.caption = "Hold one hotkey and say what you're working on."
        self.look(GAUGE_MID.x(), GAUGE_MID.y() + 60, 2.2)
        self.hold(0.8)
        self.say("I'm fixing the login bug")

        self.caption = "Muse Spark reads your task and your open apps."
        self.transcript("I'm fixing the login bug")
        self.hold(1.8)
        self.still("02-thinking")
        mocks.plan_gate.set()
        self.wait_for(lambda: self.ctl.card)
        self.caption = ""
        self.look(W / 2, (H - TASKBAR_H) / 2, 1.0)
        self.hold(1.5)
        self.still("03-card")
        self.hold(0.5)

        x, y = self.box_center("blocked_box")
        self.look(x, y - 20, 1.75)
        self.spot = "blocked_box"
        self.caption = "A web page's title tried to give the AI orders. Safety rules said no."
        self.hold(3.8)
        self.still("04-blocked")
        self.card.scroll.ensureWidgetVisible(self.card.keep_box, 0, 0)
        self.frame()
        x, y = self.box_center("keep_box")
        self.look(x, y, 1.75)
        self.spot = "keep_box"
        self.caption = "Idle for 40 minutes, a timer would freeze this PDF. It's relevant, so it stays."
        self.hold(4.0)
        self.still("05-staying-open")
        self.spot = None
        self.card.scroll.ensureVisible(0, 0)
        self.look(W / 2, (H - TASKBAR_H) / 2, 1.0)

        self.caption = "Nothing happens until you say yes."
        self.hold(1.2)
        self.say("Freeze", 0.7)
        self.transcript("Freeze")
        self.caption = ""
        self.hold(0.3)
        self.still("06-commit")
        self.hold(0.2)
        self.still("07-chip")
        self.look(GAUGE_MID.x(), GAUGE_MID.y() + 20, 2.5)
        self.wait_for(lambda: not self.ctl.busy)
        self.hold(1.6)
        self.still("08-rolling")
        self.hold(1.3)
        self.caption = "91.3% down to 22.9%, and every frozen app is still there."
        self.hold(1.0)
        self.still("09-gauge-after")
        self.hold(2.0)
        self.look(W / 2, H / 2, 1.0)
        self.caption = "The apps you need keep working. The rest wait in the taskbar."
        self.hold(3.4)
        self.still("10-desk-after")

        self.caption = "Finished? Just say so."
        self.say("I'm done")
        self.caption = ""
        self.transcript("I'm done")
        while self.stats is None:   # apps come back one by one on screen
            self.frame()
        self.hold(0.6)
        self.still("11-restore")
        self.hold(1.2)
        self.caption = "Everything returns as you left it. Nothing was ever closed."
        self.hold(2.6)
        self.still("12-stats")
        self.stats.close()
        self.stats = None
        self.caption = ""
        self.hold(0.5)

        self.caption = "And if RAM stays high without a command from you?"
        self.look(GAUGE_MID.x() - 120, GAUGE_MID.y() + 150, 1.7)
        self.hold(1.8)
        self.ctl.sensor.age(300)   # the guardian only offers apps idle for 5+ minutes
        self.ctl.on_pressure(mocks.PRESSURE)
        self.hold(0.6)
        mocks.plan_gate.set()
        self.wait_for(lambda: self.ctl.card)
        self.caption = "It offers help on its own, and it still asks first."
        self.hold(1.4)
        self.still("13-guardian")
        self.hold(2.4)
        self.transcript("Not now")
        self.caption = ""
        self.wait_for(lambda: not self.ctl.busy)
        self.hold(0.5)
        self.look(W / 2, H / 2, 1.0)

        self.title_text = ("Focus Freeze", "Built with Muse Spark and Muse Voice Transcribe")
        self.fade_title(1, 1.0)
        self.hold(2.2)

    def close(self) -> None:
        self.ctl.shutdown()
        self.ffmpeg.stdin.close()
        self.ffmpeg.wait()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stills", type=Path)
    args = ap.parse_args()
    r = Recorder(args.stills)
    r.run()
    r.close()
    print(f"{r.frame_no / FPS:.1f} s, {OUT}", flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()
