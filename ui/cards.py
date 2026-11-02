"""Base card and the typed prompt. Consent, guardian, sessions and stats build on these.

Python's GC must never destroy a Qt widget (it can run on any thread), so each card
stays referenced until Qt has deleted it on the GUI thread after closing.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ui import fx, theme
from ui.theme import label

ENTER_S = 0.26
ENTER_DY = 10

_open_cards: list = []


def _forget(card_id: int) -> None:
    _open_cards[:] = [c for c in _open_cards if id(c) != card_id]


class _CardFx(QWidget):
    """Painted over the card, never catches clicks."""

    def __init__(self, card: "Card", parent: QWidget):
        super().__init__(parent)
        self.card = card
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        p.setClipPath(path)
        self.card.paint_fx(p)


class Card(QWidget):
    """Frameless, always-on-top panel that fades in and settles upward by a few pixels."""

    def __init__(self, width: int, height: int | None = None):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(theme.STYLE)
        if height:
            self.setFixedSize(width, height)
        else:
            self.setFixedWidth(width)
        self.fx_t = 0.0
        self.fx_opacity = 0.0
        self.fx_dy = float(ENTER_DY)
        self._home = QPoint()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.frame = QFrame(objectName="card")
        outer.addWidget(self.frame)
        self.body = QVBoxLayout(self.frame)
        self.body.setContentsMargins(22, 18, 22, 16)
        self.body.setSpacing(8)
        self.fx = _CardFx(self, self.frame)
        _open_cards.append(self)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.destroyed.connect(lambda _=None, me=id(self): _forget(me))

    def home_position(self, area) -> QPoint:
        return QPoint(area.center().x() - self.width() // 2, area.center().y() - self.height() // 2)

    def present(self) -> None:
        for child in self.findChildren(QWidget):
            child.ensurePolished()
        self.layout().invalidate()
        if self.minimumHeight() != self.maximumHeight():
            self.resize(self.width(), self.layout().totalHeightForWidth(self.width()))
        if screen := QGuiApplication.primaryScreen():
            self._home = self.home_position(screen.availableGeometry())
            self.move(self._home + QPoint(0, ENTER_DY))
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self.fx.setGeometry(self.frame.rect())
        self.fx.raise_()
        fx.ticker().add(self)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.fx.setGeometry(self.frame.rect())

    def _apply(self, opacity: float, dy: float) -> None:
        self.fx_opacity, self.fx_dy = opacity, dy
        self.setWindowOpacity(opacity)
        self.move(self._home + QPoint(0, round(dy)))

    def _enter(self) -> None:
        u = fx.ease_out(self.fx_t / ENTER_S)
        self._apply(min(self.fx_t / (ENTER_S * 0.7), 1.0), ENTER_DY * (1 - u))

    def step(self, dt: float) -> bool:
        self.fx_t += dt
        self._enter()
        self.fx.update()
        return self.fx_t < ENTER_S + 0.05

    def paint_fx(self, _p: QPainter) -> None:
        pass


class PromptCard(Card):
    """Typed fallback for "Focus..." and for questions the planner asks."""
    submitted = Signal(str)

    def __init__(self, question: str, placeholder: str = ""):
        super().__init__(460)
        self.body.addWidget(label(question, 19, bold=True, wrap=True))
        self.edit = QLineEdit(placeholderText=placeholder)
        self.edit.returnPressed.connect(self._submit)
        self.body.addWidget(self.edit)
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(QPushButton("Cancel", clicked=self.close))
        foot.addWidget(QPushButton("Go", objectName="primary", clicked=self._submit))
        self.body.addLayout(foot)

    def present(self) -> None:
        super().present()
        self.activateWindow()
        self.edit.setFocus()

    def _submit(self) -> None:
        if text := self.edit.text().strip():
            self.submitted.emit(text)
            self.close()
