"""Tray app: wires gauge, cards and voice to the agent loop.

    python -m ui.app                 # the demo desk on mock parts, offline
    python -m ui.app --live-planner  # same desk, real Muse Spark (titles are made up)
    python -m ui.app --live          # real sensor, policy and actuator: suspends real apps

--live starts a watchdog process that thaws everything if this one dies. Set
FF_HOME to a scratch folder for demos, or it defaults to a fresh temp one.

Threads: the agent runs on one worker because planning and freezing block. It
waits inside consent() while the card is open on the GUI thread. Thawing never
depends on that worker being free: panic and quit call the actuator directly.
The cards stay above other windows but are not application-modal: a modal card
would lock the tray menu, and Panic thaw must always work.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Callable

from PySide6.QtCore import QObject, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
from shiboken6 import isValid

from freezer import sessions
from freezer.agent import FocusAgent, Outcome, Proposal
from freezer.contracts import Actuator, PressureEvent
from freezer.guardian import Guardian
from freezer.planner import DEFAULT_MODEL
from freezer.watchdog import Heartbeat
from freezer.voice import Command, HoldHotkey, PushToTalk, Speaker, listen_once, parse_command
from ui import mocks, theme
from ui.cards import PromptCard
from ui.consent import CardResult, ConsentCard, gb, rule_words
from ui.fx import TRAVEL_S, MotionOverlay
from ui.gauge import Gauge, Ram, read_ram
from ui.guardian import GuardianCard
from ui.sessions import SessionPicker
from ui.stats import Stats, StatsCard
from ui.voicebar import VoiceBar

GUARDIAN_POLL_MS = 5000


class Controller(QObject):
    """All user intents land here, on the GUI thread, from clicks or voice."""
    status = Signal(str)
    freed_changed = Signal(float)         # GB currently frozen
    listening = Signal(bool)
    level = Signal(float)                 # mic loudness
    thinking = Signal(bool)               # planner at work
    froze = Signal(float)                 # MB just frozen
    thawed = Signal(float)                # MB coming back
    stats_ready = Signal(object)
    card_opened = Signal(object)
    transcript = Signal(str)
    _show_card = Signal(object, object)
    _show_question = Signal(str, object)
    _voice_text = Signal(str, float)

    def __init__(self, sensor, policy, actuator: Actuator, *, client=None, model: str = DEFAULT_MODEL,
                 speak: Callable[[str], None] = lambda _t: None,
                 on_guardian_dismiss: Callable[[], None] = lambda: None,
                 read_ram: Callable[[], Ram] = read_ram):
        super().__init__()
        self.sensor, self.actuator, self.speak = sensor, actuator, speak
        self.read_ram = read_ram
        self.card_center = QPointF()      # where the freeze effect starts
        self.on_guardian_dismiss = on_guardian_dismiss
        self.agent = FocusAgent(sensor, policy, actuator, self._consent, model=model, client=client,
                                on_fallback=self._on_fallback, on_progress=self._on_progress)
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ff-agent")
        self._job: Future | None = None
        self._ram_pct: float | None = None
        self._last_result: CardResult | None = None
        self._abort = threading.Event()
        self.card = None                  # ConsentCard or GuardianCard
        self.prompt: PromptCard | None = None
        self.stats = Stats()
        self._show_card.connect(self._open_card)
        self._show_question.connect(self._open_question)
        self._voice_text.connect(self.handle_transcript)

    # ---- intents -----------------------------------------------------------

    @property
    def busy(self) -> bool:
        return self._job is not None and not self._job.done()

    def focus(self, task: str | None, session: str | None = None) -> None:
        if self.busy:
            self.status.emit("Still working on the last request.")
            return
        self._close_prompt()
        self._abort.clear()
        self.status.emit("Reading your open apps...")
        self.thinking.emit(True)
        self._job = self._worker.submit(self._guarded, self._run_focus, task, session)

    def done(self) -> None:
        self._cancel_card()
        self.status.emit("Restoring your apps...")
        self._job = self._worker.submit(self._guarded, self._run_done)

    def panic(self) -> None:
        """Thaw now, whatever the worker is doing. Queue a second pass in case
        a freeze was mid-flight when this ran."""
        self._cancel_card()
        restored = self._thaw_all()
        self._worker.submit(self._guarded, self._thaw_all)
        self.status.emit(f"Panic thaw: {len(restored)} restored.")
        self.stats = Stats()

    def on_pressure(self, event: PressureEvent) -> None:
        """From A's guardian. One card at a time, never a storm."""
        if self.busy or self.card:
            return
        self._ram_pct = event.ram_pct
        self._abort.clear()
        self._job = self._worker.submit(self._guarded, self._run_pressure, event)

    def shutdown(self) -> None:
        """Never leave apps frozen behind us, even on a plain Quit."""
        self._cancel_card()
        self._thaw_all()  # first, in case the planner holds the worker for a while
        self._worker.shutdown(wait=True, cancel_futures=True)
        self._thaw_all()  # then anything a mid-flight freeze added

    # ---- voice -------------------------------------------------------------

    def voice_heard(self, text: str, usd: float = 0.0) -> None:
        """Any thread."""
        self._voice_text.emit(text, usd)

    def handle_transcript(self, text: str, usd: float = 0.0) -> None:
        self.stats.usd += usd
        self.transcript.emit(text)
        cmd: Command | None = parse_command(text)
        if cmd is None:
            self.status.emit("Didn't catch that.")
        elif cmd.kind == "done":
            self.done()
        elif cmd.kind == "confirm" or cmd.kind == "cancel":
            if self.card:
                self.card.accept() if cmd.kind == "confirm" else self.card.cancel()
            else:
                self.status.emit("Nothing to confirm.")
        elif self.card:
            self.status.emit('Say "freeze" or "cancel" first.')
        elif cmd.kind == "session":
            self.focus(None, cmd.text)
        else:
            self.say_task(cmd.text)

    def say_task(self, task: str) -> None:
        """A sentence that starts a saved session's task continues that session."""
        said = task.strip().lower()
        match = next((s for s in sessions.load() if s.task.lower().startswith(said)), None)
        if match:
            self.focus(None, match.name)
        else:
            self.focus(task, self.agent.session_name)

    # ---- worker thread -----------------------------------------------------

    def _guarded(self, fn, *args) -> None:
        try:
            fn(*args)
        except Exception as e:  # a failed step must not kill the worker; thaw still works
            self.status.emit(f"Something went wrong: {type(e).__name__}. Your apps are not affected.")
            raise
        finally:
            self.thinking.emit(False)

    def _consent(self, proposal: Proposal) -> list[str] | None:
        answer: Future = Future()
        self._last_result = CardResult(approved=None)
        if self._abort.is_set():
            return None
        self._show_card.emit(proposal, answer)
        while True:  # polled: on quit the GUI thread is gone and would never answer
            try:
                self._last_result = answer.result(timeout=0.1)
                return self._last_result.approved
            except FutureTimeout:
                if self._abort.is_set():
                    answer.cancel()
                    return None

    def _run_focus(self, task: str | None, session: str | None) -> None:
        self._last_result = None
        out = self.agent.focus(task, session)
        self._account(out)
        if out.question:
            self.speak(out.question)
            self._show_question.emit(out.question, session)
            self.status.emit("One question first.")
            return
        self._save_rules(out)
        self._report(out)

    def _run_pressure(self, event: PressureEvent) -> None:
        self._last_result = None
        out = self.agent.on_pressure(event)
        self._account(out)
        if out.declined:
            self.on_guardian_dismiss()
            self.status.emit("Dismissed. No new card for 10 minutes.")
            return
        self._report(out)

    def _run_done(self) -> None:
        entries = self.actuator.frozen()
        returning_mb = sum(e.freed_mb for e in entries)
        started = time.monotonic()
        restored = self.agent.done()
        self.freed_changed.emit(self._frozen_gb())
        if not restored:
            self.status.emit("Nothing was frozen.")
            return
        self.thawed.emit(returning_mb)
        self.stats.restored_mb = returning_mb
        self.stats.restore_s = time.monotonic() - started
        self.stats.minutes = (time.time() - min(e.frozen_at for e in entries)) / 60 if entries else 0.0
        message = f"Restored {gb(returning_mb)} in {self.stats.restore_s:.1f}s"
        self.stats_ready.emit(self.stats)
        self.stats = Stats()
        self.speak("Your apps are back.")
        self.status.emit(message)

    def _account(self, out: Outcome) -> None:
        if out.proposal:
            self.stats.usd += out.proposal.plan.cost_usd
        self.stats.freed_mb += sum(e.freed_mb for e in out.frozen)
        self.stats.apps += len(out.frozen)
        if out.frozen:
            self.froze.emit(sum(e.freed_mb for e in out.frozen))
        self.freed_changed.emit(self._frozen_gb())

    def _save_rules(self, out: Outcome) -> None:
        """The user clicked Yes on the card. Rules come from clicks and voice only."""
        result, session = self._last_result, out.proposal.session if out.proposal else None
        if not session or not result:
            return
        for app_id in set(result.never_freeze) & set(out.unticked):
            try:
                sessions.add_rule(session, app_id, "never_freeze")
            except (ValueError, KeyError):
                self.status.emit(f"Could not save the rule for {app_id}.")

    def _report(self, out: Outcome) -> None:
        if out.declined:
            self.status.emit("Cancelled, nothing frozen.")
        elif out.frozen:
            mb = sum(e.freed_mb for e in out.frozen)
            text = f"Froze {len(out.frozen)} apps, ~{gb(mb)} freed."
            if out.failed:
                text += f" Could not freeze: {', '.join(out.failed)}."
            if out.skipped:
                text += " Left alone: " + ", ".join(f"{b.app_id} ({rule_words(b.rule)})" for b in out.skipped) + "."
            self.status.emit(text)
            self.speak(f"Froze {len(out.frozen)} apps.")
        elif out.failed:
            self.status.emit(f"Could not freeze: {', '.join(out.failed)}.")
        elif out.note:
            self.status.emit("Nothing has been idle for 5 minutes, so there is nothing to freeze.")
        else:
            self.status.emit("Nothing worth freezing right now.")

    def _on_fallback(self, _why: str) -> None:
        # _why can hold raw API errors, so it stays off the screen. The card shows
        # Proposal.fallback_message, which is written for people.
        self.status.emit("AI unavailable, using the simple idle rule.")

    def _on_progress(self, stage: str, attempt: int) -> None:
        if stage == "request":
            self.status.emit("Asking Muse Spark..." if attempt <= 1 else f"Asking Muse Spark again ({attempt})...")

    def _thaw_all(self) -> list[str]:
        restored = self.actuator.thaw_all()
        self.freed_changed.emit(self._frozen_gb())
        return restored

    def _frozen_gb(self) -> float:
        return sum(e.freed_mb for e in self.actuator.frozen()) / 1024

    # ---- GUI thread --------------------------------------------------------

    def _open_card(self, proposal: Proposal, answer: Future) -> None:
        if answer.done() or self._abort.is_set():  # panic, done or quit got here first
            return
        self.thinking.emit(False)

        def finish(result: CardResult) -> None:
            self.card = None
            if answer.set_running_or_notify_cancel():
                answer.set_result(result)

        def open_consent() -> None:
            card = ConsentCard(proposal)
            self.card = card
            card.decided.connect(finish)
            card.present()
            self.card_center = QPointF(card.frameGeometry().center())
            self.card_opened.emit(card)
            self.status.emit('Say "freeze" or "cancel".')

        if proposal.source == "guardian":
            card = GuardianCard(proposal, self._ram_pct or 0.0)
            self.card = card
            card.review.connect(open_consent)
            card.dismissed.connect(lambda: finish(CardResult(approved=None)))
            card.present()
            self.card_opened.emit(card)
            self.status.emit('Say "freeze" to review, or "cancel".')
            self.speak(card.text)
        else:
            open_consent()
            self.speak(f"Freeze {len(proposal.to_freeze)} apps?")

    def _open_question(self, question: str, session) -> None:
        self._open_prompt(question, lambda text: self.focus(text, session))

    def open_focus_prompt(self) -> None:
        self._open_prompt("What are you working on?", self.say_task, "fixing the login bug")

    def _open_prompt(self, question: str, then: Callable[[str], None], placeholder: str = "") -> None:
        self._close_prompt()
        self.prompt = PromptCard(question, placeholder)
        self.prompt.submitted.connect(then)
        self.prompt.present()

    def _close_prompt(self) -> None:
        if self.prompt:
            prompt, self.prompt = self.prompt, None
            if isValid(prompt):   # it may have closed itself already
                prompt.close()

    def _cancel_card(self) -> None:
        """Also stops a card that is still being planned from opening later."""
        self._abort.set()
        if self.card:
            self.card.cancel()


def tray_icon() -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(theme.ICE), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.translate(32, 32)
    for _ in range(3):  # a six-armed snowflake
        p.drawLine(0, -27, 0, 27)
        for end in (-1, 1):
            p.drawLine(0, end * 16, -9, end * 25)
            p.drawLine(0, end * 16, 9, end * 25)
        p.rotate(60)
    p.end()
    return QIcon(pix)


def connect_gauge(ctl: Controller, gauge: Gauge, overlay: MotionOverlay,
                  anchor: Callable[[], QPointF] | None = None) -> None:
    """The choreography. Shared with demo/record_preview.py, so the video shows this code."""
    anchor = anchor or gauge.center_point
    ctl.status.connect(gauge.set_status)
    ctl.freed_changed.connect(gauge.set_freed)
    ctl.listening.connect(gauge.set_listening)
    ctl.level.connect(gauge.set_level)
    ctl.thinking.connect(gauge.set_thinking)

    def froze(mb: float) -> None:
        gauge.hold(TRAVEL_S)     # the gauge reacts when the chip lands, not before
        overlay.play_freeze(ctl.card_center, anchor(), gb(mb))

    def thawed(mb: float) -> None:
        overlay.play_thaw(ctl.card_center, anchor(), gb(mb))

    # Direct: froze must hold the gauge before freed_changed reaches it.
    ctl.froze.connect(froze)
    ctl.thawed.connect(thawed)


def make_parts(live_planner: bool, live: bool = False) -> dict:
    """The one place to swap mocks for the real parts."""
    if live:
        from freezer.actuator import RealActuator
        from freezer.policy import policy_for
        from freezer.sensor import ForegroundTracker, RealSensor
        # Real titles: the default model, never the contributor one, which trains on
        # what it receives. The tracker supplies the idle times the guardian needs.
        return dict(sensor=RealSensor(ForegroundTracker().start()),
                    policy=policy_for(None, self_pids={os.getpid(), os.getppid()}),
                    actuator=RealActuator())
    if not live_planner:
        mocks.install()
    os.environ.setdefault("FF_SYNTHETIC_DATA", "1")  # the desk's titles are made up; remove with the real sensor
    return dict(sensor=mocks.DeskSensor(), policy=mocks.mock_policy, actuator=mocks.SlowActuator(),
                # Synthetic desk, so the cheap contributor model is allowed. Real titles must
                # use muse-spark-1.3: remove this line when the sensor is real.
                model="muse-spark-1.3-contributor")


def main() -> int:
    ap = argparse.ArgumentParser(description="Focus Freeze tray app, on mock parts.")
    ap.add_argument("--live-planner", action="store_true", help="call Muse Spark instead of the mock plan")
    ap.add_argument("--live", action="store_true",
                    help="real sensor, policy and actuator (implies --live-planner)")
    args = ap.parse_args()

    if args.live:
        from freezer.actuator import AdminRefusal, ensure_not_elevated
        try:
            ensure_not_elevated()
        except AdminRefusal as e:
            print(e, file=sys.stderr)
            return 2
        os.environ.setdefault("FF_HOME", tempfile.mkdtemp(prefix="ff-live-"))
    elif not args.live_planner:
        os.environ["FF_HOME"] = tempfile.mkdtemp(prefix="ff-demo-")  # demo data never touches real sessions
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    speaker = Speaker()
    parts = make_parts(args.live_planner, args.live)
    actuator = parts["actuator"]
    if not args.live_planner:
        mocks.seed_sessions()   # synthetic sessions, also in --live
    actuator.thaw_all()  # contract: recover anything a crashed run left frozen
    if args.live:
        ram = read_ram
        guardian = Guardian()
        heartbeat = Heartbeat()
        heartbeat.start()
        app.aboutToQuit.connect(heartbeat.stop)
        # Its own process: it thaws when the heartbeat goes stale or this process exits.
        subprocess.Popen([sys.executable, "-m", "freezer.watchdog", "--parent", str(os.getpid())],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        ram = lambda: mocks.ram_for(actuator)
        guardian = Guardian(ram_pct=lambda: ram().pct)
    ctl = Controller(**parts, speak=speaker.say, read_ram=ram, on_guardian_dismiss=guardian.dismissed)

    gauge = Gauge(ctl.read_ram, simulated=not args.live)
    overlay = MotionOverlay()
    if screen := app.primaryScreen():
        overlay.setGeometry(screen.geometry())
    connect_gauge(ctl, gauge, overlay)
    gauge.show()

    keep: list = []  # the window currently on screen

    def show_stats(stats: Stats) -> None:
        card = StatsCard(stats)
        keep[:] = [card]
        card.present()

    ctl.stats_ready.connect(show_stats)

    def open_sessions() -> None:
        picker = SessionPicker()
        picker.start_session.connect(lambda name: ctl.focus(None, name))
        keep[:] = [picker]
        picker.present()

    def simulate_pressure() -> None:
        if not args.live:
            ctl.sensor.age(300)   # guardian only offers apps idle 5+ minutes
            ctl.on_pressure(mocks.PRESSURE)
            return
        # Real apps, ranked the way the guardian ranks them; only RAM is pretended.
        frozen = {e.app_id for e in actuator.frozen()}
        snaps = sorted((s for s in ctl.sensor.snapshot() if s.app_id not in frozen),
                       key=lambda s: s.last_focus_s * s.working_set_mb, reverse=True)
        ctl.on_pressure(PressureEvent(max(ram().pct, 85.0), 30.0, [s.app_id for s in snaps]))

    def poll_guardian() -> None:
        snaps = ctl.sensor.snapshot()
        frozen = {e.app_id for e in actuator.frozen()}
        if event := guardian.poll(snaps, frozen):
            if not args.live:
                ctl.sensor.age(300)
            ctl.on_pressure(event)

    poll = QTimer(interval=GUARDIAN_POLL_MS, timeout=poll_guardian)
    poll.start()

    voicebar = VoiceBar(mocks.TRANSCRIPTS if not args.live_planner else None)
    voicebar.spoken.connect(ctl.handle_transcript)
    ctl.transcript.connect(voicebar.show_transcript)
    voicebar.present()

    menu = QMenu()
    menu.setStyleSheet(f"QMenu {{ background: {theme.PANEL}; color: {theme.INK}; padding: 4px; font-size: {theme.TEXT}px; }}"
                       f"QMenu::item {{ padding: 6px 22px; }} QMenu::item:selected {{ background: {theme.LINE}; }}")
    for text, slot in (("Focus...", ctl.open_focus_prompt), ("Done", ctl.done),
                       ("Sessions", open_sessions), ("Panic thaw", ctl.panic),
                       ("Simulate RAM pressure" if args.live else "Simulate RAM pressure (mock)",
                        simulate_pressure), ("Quit", app.quit)):
        menu.addAction(QAction(text, menu, triggered=slot))
    tray = QSystemTrayIcon(tray_icon())
    tray.setToolTip("Focus Freeze")
    tray.setContextMenu(menu)
    tray.show()

    ptt = PushToTalk(ctl.voice_heard, ctl.status.emit, on_partial=ctl.transcript.emit, on_level=ctl.level.emit)
    scripted = list(mocks.TRANSCRIPTS)

    def press() -> None:
        ctl.listening.emit(True)
        if ptt.api_key:
            ptt.press()

    def release() -> None:
        ptt.release()
        ctl.listening.emit(False)
        if not ptt.api_key:   # no key: the hotkey plays the demo's next line
            ctl.voice_heard(listen_once(scripted))
            scripted.append(scripted.pop(0))

    hotkey = HoldHotkey(press, release, ctl.status.emit)
    hotkey.start()

    app.aboutToQuit.connect(hotkey.stop)
    app.aboutToQuit.connect(ptt.release)
    app.aboutToQuit.connect(ctl.shutdown)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
