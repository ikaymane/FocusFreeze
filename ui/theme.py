"""Colours, type and shared widget helpers. Looks native to Windows: one typeface,
a calm slate, and colour used only when it means something."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel

INK = "#F1F5F7"
MUTED = "#A5B4BD"
PANEL = "#18232B"
RAISED = "#212E37"
LINE = "#31404A"
FREE = "#2A3843"       # an empty memory cell
ICE = "#8ED8EE"        # frozen: the one accent
WARM = "#F0B37E"       # thawing
OK = "#6FD08C"
WARN = "#E9C04C"
HOT = "#EF6F5E"
ON_ACCENT = "#0C2430"

FONT = "Segoe UI"      # ships with Windows, so this reads as part of the OS
# Readable at 1080p on video: 13 pt is 17 px at 96 dpi, and nothing goes below it.
TEXT = 17
TITLE = 24
# The always-on gauge and its voice drawer stay compact so they never crowd your work.
SMALL = 15
_CHECK = (Path(__file__).parent / "assets" / "check.svg").as_posix()

STYLE = f"""
* {{ font-family: "{FONT}"; color: {INK}; }}
#card {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 10px; }}
#row {{ background: transparent; border-bottom: 1px solid {LINE}; }}
#plainrow {{ background: {RAISED}; border-radius: 6px; }}
#blocked {{ background: rgba(239, 111, 94, 24); border-radius: 6px; }}
#contrast {{ background: rgba(142, 216, 238, 22); border-radius: 6px; }}
#banner {{ background: rgba(233, 192, 76, 34); border-radius: 6px; }}
#ask {{ background: {RAISED}; border-radius: 6px; }}
QScrollArea, #rows {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; }}
QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 4px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QPushButton {{ background: {RAISED}; border: 1px solid {LINE}; border-radius: 6px;
               padding: 7px 18px; font-size: {TEXT}px; }}
QPushButton:hover {{ background: {LINE}; }}
QPushButton:focus {{ border-color: {ICE}; }}
QPushButton:disabled {{ color: {MUTED}; }}
QPushButton#primary {{ background: {ICE}; border-color: {ICE}; color: {ON_ACCENT}; font-weight: 600; }}
QPushButton#primary:hover {{ background: #B4E7F5; }}
QPushButton#primary:disabled {{ background: {LINE}; border-color: {LINE}; color: {MUTED}; }}
QLineEdit {{ background: {RAISED}; border: 1px solid {LINE}; border-radius: 6px; padding: 8px; font-size: {TEXT}px; }}
QLineEdit:focus {{ border-color: {ICE}; }}
QCheckBox {{ font-size: {TEXT}px; font-weight: 600; spacing: 10px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 4px; border: 1px solid {MUTED}; }}
QCheckBox::indicator:checked {{ background: {ICE}; border-color: {ICE}; image: url({_CHECK}); }}
"""


def label(text: str, size: int = TEXT, color: str = INK, bold: bool = False, wrap: bool = False) -> QLabel:
    """Always plain text: reasons and titles trace back to untrusted window titles,
    and QLabel would otherwise render any HTML they contain."""
    w = QLabel(text)
    w.setTextFormat(Qt.TextFormat.PlainText)
    w.setWordWrap(wrap)
    w.setStyleSheet(f"font-size: {size}px; color: {color}; font-weight: {600 if bold else 400};"
                    " background: transparent;")
    return w


def ram_color(pct: float) -> QColor:
    return QColor(HOT if pct >= 85 else WARN if pct >= 60 else OK)
