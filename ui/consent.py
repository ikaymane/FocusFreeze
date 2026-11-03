"""The consent card, 640x560: task, app rows, blocked apps, total, Freeze / Cancel.

Animation never delays a decision: the result reaches the agent at the click, and
the outro plays afterwards. Rules are saved only from what the user clicks here.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from freezer import sessions
from freezer.agent import Proposal, block_reason
from freezer.contracts import RuleProposal
from ui import fx, theme
from ui.cards import ENTER_S, Card
from ui.theme import label

WIDTH, HEIGHT = 640, 560
WARNING_MARK = "⚠"
DISCONNECT_NOTE = f"{WARNING_MARK} may disconnect, reconnects on restore"
ROW_DELAY_S = 0.028

# What people call the apps the live sensor reports by exe. Display only: the planner,
# policy and blocked lines all keep the exact app_id.
FRIENDLY = {
    "chrome.exe": "Google Chrome", "msedge.exe": "Microsoft Edge", "firefox.exe": "Firefox",
    "code.exe": "Visual Studio Code", "windowsterminal.exe": "Windows Terminal",
    "explorer.exe": "File Explorer", "notepad.exe": "Notepad", "winword.exe": "Microsoft Word",
    "excel.exe": "Microsoft Excel", "powerpnt.exe": "PowerPoint", "acrord32.exe": "Adobe Acrobat Reader",
    "acrobat.exe": "Adobe Acrobat", "zotero.exe": "Zotero", "discord.exe": "Discord",
    "ms-teams.exe": "Microsoft Teams", "slack.exe": "Slack", "spotify.exe": "Spotify",
    "steam.exe": "Steam", "steamwebhelper.exe": "Steam", "whatsapp.root.exe": "WhatsApp",
    "obs64.exe": "OBS Studio", "vlc.exe": "VLC",
}


def usd(amount: float) -> str:
    """'$0.004': plan costs are fractions of a cent, so 4 decimals read as noise."""
    return f"${amount:.3f}"


def planned_line(proposal: Proposal, latency_s: float | None) -> str | None:
    """'Planned by Muse Spark · 1.8 s · $0.002'. None in simple mode: its banner says why."""
    if proposal.plan.model == "heuristic":
        return None
    parts = ["Planned by Muse Spark"]
    if latency_s is not None:
        parts.append(f"{latency_s:.1f} s")
    parts.append(usd(proposal.plan.cost_usd))
    return " · ".join(parts)


CONTRAST_LINES = 2   # pinned lines: more would push the freeze list off a 560 px card


def shown_contrasts(proposal: Proposal) -> list:
    """AI-vs-timer disagreements worth a line. Blocked apps are left out (the card already
    says policy refused them), and "AI keeps what a timer would freeze" comes first: it
    is the case a timer gets wrong and loses work over."""
    blocked = {b.app_id for b in proposal.blocked}
    return sorted((c for c in proposal.vs_timer if c.app_id not in blocked), key=lambda c: c.ai != "keep")


def contrast_line(c, name: str) -> str:
    """'Idle timer would freeze: Reference PDF  ·  AI keeps it: OAuth spec for this bug'"""
    return f"Idle timer would {c.timer}: {name}  ·  AI {'keeps' if c.ai == 'keep' else 'freezes'} it: {c.reason}"


def app_name(app_id: str, app=None) -> str:
    if app is not None and app.display_name and app.display_name.lower() != app_id.lower():
        return app.display_name   # the sensor already has a better name
    return FRIENDLY.get(app_id.lower(), app_id)
ROW_FADE_S = 0.24
SETTLE_S = 0.34        # rows dim one by one once approved
LEAVE_S = 0.18

RULE_WORDS = {
    "system_process": "Protected process",
    "protected_process": "Protected process",
    "security_software": "Security software — cannot freeze",
    "foreground": "Currently in use",
    "plays_audio": "Playing audio",
    "injection": "Injection attempt in title — blocked",
    "unknown_app": "Not in snapshot (ignored)",
    "user_never_freeze": "You protected this",
    "accessibility": "Accessibility tool",
    "password_manager": "Password manager",
    "elevated": "Running as administrator",
    "self": "Focus Freeze itself",
    "too_many": "Too many apps at once",
}


def rule_words(rule: str) -> str:
    return RULE_WORDS.get(rule) or block_reason(rule)


def gb(mb: float) -> str:
    return f"{mb / 1024:.1f} GB"


@dataclass
class CardResult:
    approved: list[str] | None              # None = cancelled or dismissed
    never_freeze: list[str] = field(default_factory=list)   # unticked, and the user said yes


class _AppRow(QFrame):
    """checkbox + name | MB | reason"""

    def __init__(self, card: "ConsentCard", app_id: str, name: str, mb: float, reason: str, warn: bool):
        super().__init__(objectName="row")
        self.app_id, self.mb, self.name = app_id, mb, name
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 7, 2, 7)
        grid.setHorizontalSpacing(10)
        grid.setColumnMinimumWidth(0, 205)
        grid.setColumnMinimumWidth(1, 70)
        grid.setColumnStretch(2, 1)
        self.check = QCheckBox(f"{name} {WARNING_MARK}" if warn else name)
        self.check.setChecked(True)
        self.check.toggled.connect(lambda on: card.row_toggled(self, on))
        grid.addWidget(self.check, 0, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(label(f"{mb:,.0f} MB"), 0, 1, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(label(reason, color=theme.MUTED, wrap=True), 0, 2, Qt.AlignmentFlag.AlignTop)


class ConsentCard(Card):
    decided = Signal(object)  # CardResult, exactly once

    def __init__(self, proposal: Proposal, latency_s: float | None = None):
        super().__init__(WIDTH, HEIGHT)
        self.proposal = proposal
        self.apps = proposal.apps
        self._done = False
        self._outro = ""          # "freeze" or "fade"
        self._outro_t = 0.0
        self.rows: list[_AppRow] = []
        self.never: set[str] = set()
        self._asking: _AppRow | None = None
        self.blocked_box: QWidget | None = None
        self.keep_box: QWidget | None = None

        self.heading = label(proposal.plan.task, theme.TITLE, bold=True, wrap=True)
        self.body.addWidget(self.heading)

        self.banner: QFrame | None = None
        if message := proposal.fallback_message:
            self.banner = QFrame(objectName="banner")
            box = QVBoxLayout(self.banner)
            box.setContentsMargins(12, 6, 12, 6)
            box.addWidget(label(message, color=theme.WARN, wrap=True))
            self.body.addWidget(self.banner)

        holder = QWidget(objectName="rows")
        rows = QVBoxLayout(holder)
        rows.setContentsMargins(0, 0, 6, 0)
        rows.setSpacing(0)
        warned = False
        for d in proposal.to_freeze:
            app = self.apps.get(d.app_id)
            warn = d.app_id in proposal.disconnects
            warned = warned or warn
            row = _AppRow(self, d.app_id, app_name(d.app_id, app),
                          app.working_set_mb if app else 0.0, d.reason, warn)
            self.rows.append(row)
            rows.addWidget(row)
        if warned:
            rows.addSpacing(6)
            rows.addWidget(label(DISCONNECT_NOTE, color=theme.MUTED))

        keeping = [d for d in proposal.keep if d.action == "keep"]
        if keeping:
            rows.addSpacing(10)
            self.keep_box = QWidget()
            box = QVBoxLayout(self.keep_box)
            box.setContentsMargins(0, 2, 0, 2)
            box.setSpacing(3)
            box.addWidget(label("Staying open", color=theme.OK, bold=True))
            for d in keeping:
                box.addWidget(self._keep_line(self._name(d.app_id), d.reason))
            rows.addWidget(self.keep_box)

        if proposal.session and proposal.plan.proposed_rules:
            rows.addSpacing(10)
            rows.addWidget(label("Suggested rules, saved only if you click", color=theme.MUTED, bold=True))
            for r in proposal.plan.proposed_rules:
                rows.addWidget(self._rule_row(r))
        rows.addStretch(1)

        self.scroll = QScrollArea(widgetResizable=True, frameShape=QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder.setFixedWidth(WIDTH - 54)
        self.scroll.setWidget(holder)
        self.body.addWidget(self.scroll, 1)

        # Pinned too: the apps where the AI overrules the idle timer are the proof it
        # is not bolted on, so they must read on camera without scrolling.
        self.contrast_box: QFrame | None = None
        if contrasts := shown_contrasts(proposal):
            self.contrast_box = QFrame(objectName="contrast")
            box = QVBoxLayout(self.contrast_box)
            box.setContentsMargins(12, 7, 10, 7)
            box.setSpacing(2)
            box.addWidget(label("AI vs a 20-minute idle timer", color=theme.ICE, bold=True))
            for c in contrasts[:CONTRAST_LINES]:
                box.addWidget(label(contrast_line(c, self._name(c.app_id)), wrap=True))
            if more := len(contrasts) - CONTRAST_LINES:
                box.addWidget(label(f"+{more} more where they disagree", color=theme.MUTED))
            self.body.addWidget(self.contrast_box)

        # Pinned, not in the scroll area: safety refusals must never be below the fold.
        if proposal.blocked:
            self.blocked_box = QFrame(objectName="blocked")
            box = QVBoxLayout(self.blocked_box)
            box.setContentsMargins(12, 7, 10, 7)
            box.setSpacing(1)
            for b in proposal.blocked:
                box.addWidget(label(f"{b.app_id} — BLOCKED: {rule_words(b.rule)}", color=theme.HOT))
            self.body.addWidget(self.blocked_box)

        self.ask = QFrame(objectName="ask")
        ask = QHBoxLayout(self.ask)
        ask.setContentsMargins(12, 6, 8, 6)
        self.ask_text = label("", wrap=True)
        ask.addWidget(self.ask_text, 1)
        self.ask_yes = QPushButton("Yes", clicked=lambda: self._answer(True))
        self.ask_no = QPushButton("No, just once", clicked=lambda: self._answer(False))
        ask.addWidget(self.ask_yes)
        ask.addWidget(self.ask_no)
        self.ask.hide()
        self.body.addWidget(self.ask)

        foot = QHBoxLayout()
        self.total = label("", 19, bold=True)
        left = QVBoxLayout()
        left.setSpacing(0)
        left.addWidget(self.total)
        self.planned: QLabel | None = None
        if text := planned_line(proposal, latency_s):
            self.planned = label(text, color=theme.MUTED)
            left.addWidget(self.planned)
        foot.addLayout(left)
        foot.addStretch(1)
        self.cancel_btn = QPushButton("Cancel", clicked=self.cancel)
        self.freeze_btn = QPushButton("Freeze", objectName="primary", clicked=self.accept)
        foot.addWidget(self.cancel_btn)
        foot.addWidget(self.freeze_btn)
        self.body.addLayout(foot)
        self.refresh()

    def _name(self, app_id: str) -> str:
        return app_name(app_id, self.apps.get(app_id))

    @staticmethod
    def _keep_line(name: str, why: str) -> QWidget:
        w = QWidget()
        box = QHBoxLayout(w)
        box.setContentsMargins(0, 1, 0, 1)
        left = label(name, wrap=True)
        left.setFixedWidth(205)
        box.addWidget(left, 0, Qt.AlignmentFlag.AlignTop)
        box.addWidget(label(why, color=theme.MUTED, wrap=True), 1, Qt.AlignmentFlag.AlignTop)
        return w

    def _rule_row(self, rule: RuleProposal) -> QWidget:
        w = self._keep_line(rule.app_id, f"{rule.rule.replace('_', ' ')}: {rule.reason}")
        btn = QPushButton("Save")

        def save() -> None:
            sessions.confirm_proposal(self.proposal.session, rule)
            btn.setEnabled(False)
            btn.setText("Saved")

        btn.clicked.connect(save)
        w.layout().addWidget(btn)
        return w

    # ---- untick ------------------------------------------------------------

    def row_toggled(self, row: _AppRow, on: bool) -> None:
        if on:
            self.never.discard(row.app_id)
            if self._asking is row:
                self._hide_ask()
        elif self.proposal.session and self.proposal.source == "user":
            self._asking = row
            self.ask_text.setText(f"Never freeze {row.app_id} during '{self.proposal.session}'?")
            self.ask.show()
        self.refresh()

    def _answer(self, never: bool) -> None:
        if self._asking and never:
            self.never.add(self._asking.app_id)
        self._hide_ask()

    def _hide_ask(self) -> None:
        self._asking = None
        self.ask.hide()

    # ---- state -------------------------------------------------------------

    def refresh(self) -> None:
        ticked = [r for r in self.rows if r.check.isChecked()]
        self.total.setText(f"~{gb(sum(r.mb for r in ticked))} to free")
        self.freeze_btn.setEnabled(bool(ticked))

    def accept(self) -> None:
        unticked = [r.app_id for r in self.rows if not r.check.isChecked()]
        self._finish(CardResult(approved=[r.app_id for r in self.rows if r.check.isChecked()],
                                never_freeze=[a for a in unticked if a in self.never]), "freeze")

    def cancel(self) -> None:
        self._finish(CardResult(approved=None), "fade")

    def _finish(self, result: CardResult, outro: str) -> None:
        if self._done:
            return
        self._done = True
        self.decided.emit(result)
        self._outro, self._outro_t = outro, 0.0
        self.setEnabled(False)
        if self.isVisible():
            fx.ticker().add(self)
        else:
            self.close()

    def step(self, dt: float) -> bool:
        self.fx_t += dt
        if self._outro:
            self._outro_t += dt
            settle = SETTLE_S if self._outro == "freeze" else 0.0
            u = (self._outro_t - settle) / LEAVE_S
            if u > 0:
                self._apply(max(1 - u, 0.0), -8 * fx.ease_out(u))
            self.fx.update()
            if u >= 1:
                self.close()
                return False
            return True
        self._enter()
        self.fx.update()
        return self.fx_t < ENTER_S + ROW_FADE_S + ROW_DELAY_S * len(self.rows)

    def paint_fx(self, p: QPainter) -> None:
        viewport = QRect(self.scroll.viewport().mapTo(self.frame, QPoint(0, 0)), self.scroll.viewport().size())
        panel = QColor(theme.PANEL)
        # Rows fade in one after another: your eye reads the list top to bottom.
        for i, row in enumerate(self.rows):
            u = (self.fx_t - 0.08 - i * ROW_DELAY_S) / ROW_FADE_S
            if u < 1:
                rect = QRect(row.mapTo(self.frame, QPoint(0, 0)), row.size()) & viewport
                panel.setAlphaF(1 - fx.ease_out(max(u, 0.0)))
                p.fillRect(rect, panel)
        if self._outro == "freeze":
            # Approved rows dim in sequence: this is the moment of commitment.
            cold = QColor(theme.PANEL)
            for i, row in enumerate(r for r in self.rows if r.check.isChecked()):
                u = (self._outro_t - i * 0.035) / 0.16
                if u > 0:
                    rect = QRect(row.mapTo(self.frame, QPoint(0, 0)), row.size()) & viewport
                    cold.setAlphaF(0.72 * min(u, 1.0))
                    p.fillRect(rect, cold)

    def closeEvent(self, event) -> None:
        self.cancel()  # any way of closing must release the waiting agent thread
        super().closeEvent(event)
