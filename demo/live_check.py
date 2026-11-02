"""Live-wire check: the real sensor, policy, actuator and UI on a sacrificial Notepad.

    python -m demo.live_check            # study session -> card -> freeze -> done -> restore,
                                         # then pressure -> card -> freeze -> crash -> watchdog
    python -m demo.live_check --planner  # real Muse Spark (needs MODEL_API_KEY)

Without --planner a stub plan proposes only notepad.exe, so the run needs no key
and nothing else can freeze. With it, the card is still unticked down to Notepad:
the check never approves a real app. Screens land in demo/recordings/live-check/.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("FF_HOME", tempfile.mkdtemp(prefix="ff-live-check-"))

import psutil  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from freezer import agent as agent_module  # noqa: E402
from freezer.contracts import Decision, Plan  # noqa: E402
from freezer.watchdog import Heartbeat  # noqa: E402
from ui import mocks  # noqa: E402
from ui.app import Controller, connect_gauge, make_parts  # noqa: E402
from ui.fx import MotionOverlay  # noqa: E402
from ui.gauge import Gauge, read_ram  # noqa: E402

SACRIFICE = "notepad.exe"
OUT = Path(__file__).parent / "recordings" / "live-check"


def stub_plan(task, snapshots, session=None, *, on_progress=None, **_kw) -> Plan:
    decisions = [Decision(s.app_id, "freeze" if s.app_id == SACRIFICE else "keep", "live check")
                 for s in snapshots]
    return Plan(task, decisions, "stub (no key)", 0.0)


def wait_for(app: QApplication, cond, timeout_s: float = 30.0, what: str = "") -> None:
    deadline = time.monotonic() + timeout_s
    while not cond():
        if time.monotonic() > deadline:
            raise TimeoutError(f"timed out waiting for {what}")
        app.processEvents()
        time.sleep(0.02)


def suspended(pids: list[int]) -> bool:
    return all(psutil.Process(p).status() == psutil.STATUS_STOPPED for p in pids if psutil.pid_exists(p))


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def pump(app: QApplication, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)


def park(app: QApplication) -> None:
    """Minimize Notepad until something else is foreground: policy never freezes
    the app in use, and Windows 11 Notepad activates itself when it opens a file."""
    import win32gui
    import win32process
    from freezer.sensor import _foreground_pid, _proc_name
    for _ in range(20):
        win32gui.EnumWindows(lambda h, _: win32gui.ShowWindow(h, 6) if win32gui.IsWindowVisible(h)
                             and _proc_name(win32process.GetWindowThreadProcessId(h)[1]) == SACRIFICE else None,
                             None)   # SW_MINIMIZE hands focus to the next window
        pump(app, 0.5)
        if _proc_name(_foreground_pid() or 0) != SACRIFICE:
            return
        # A minimized window can stay foreground. Hand focus to the taskbar; the Alt
        # tap is what lets a background process call SetForegroundWindow.
        import win32api
        import win32con
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
        try:
            win32gui.SetForegroundWindow(win32gui.FindWindow("Shell_TrayWnd", None))
        except win32gui.error:
            pass
        pump(app, 0.5)
        if _proc_name(_foreground_pid() or 0) != SACRIFICE:
            return
    raise RuntimeError("Notepad keeps the foreground: click another window and rerun")


def approve_only_sacrifice(app, ctl, shot: str) -> None:
    wait_for(app, lambda: ctl.card is not None, 60, "card")
    card = ctl.card
    pump(app, 1.0)   # entrance animation
    if not hasattr(card, "rows"):   # guardian card first: Review opens the consent card
        card.grab().save(str(OUT / f"guardian-{shot}"))
        card.accept()
        wait_for(app, lambda: ctl.card is not None and ctl.card is not card, 10, "consent card")
        card = ctl.card
        pump(app, 1.0)
    for row in card.rows:
        row.check.setChecked(row.app_id == SACRIFICE)
    log(f"card rows: {[(r.app_id, r.check.isChecked()) for r in card.rows]}")
    card.grab().save(str(OUT / shot))
    card.accept()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--planner", action="store_true", help="real Muse Spark instead of the stub")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    log(f"FF_HOME={os.environ['FF_HOME']}")

    note = Path(os.environ["FF_HOME"]) / "sacrifice.txt"
    note.write_text("Focus Freeze live check: this Notepad gets frozen and thawed.", encoding="utf-8")
    before = {p.pid for p in psutil.process_iter() if p.name().lower() == SACRIFICE}
    # Minimized and not activated: a foreground app is never frozen, by policy.
    start = subprocess.STARTUPINFO(dwFlags=subprocess.STARTF_USESHOWWINDOW, wShowWindow=7)  # SW_SHOWMINNOACTIVE
    subprocess.Popen(["notepad.exe", str(note)], startupinfo=start)
    app = QApplication(sys.argv)
    wait_for(app, lambda: any(p.name().lower() == SACRIFICE and p.pid not in before
                              for p in psutil.process_iter()) or before, 15, "notepad")
    time.sleep(1.5)  # let its window appear

    if not args.planner:
        agent_module.plan = stub_plan
    parts = make_parts(True, live=True)
    actuator, sensor = parts["actuator"], parts["sensor"]
    mocks.seed_sessions()
    actuator.thaw_all()
    heartbeat = Heartbeat()
    heartbeat.start()
    watchdog = subprocess.Popen([sys.executable, "-m", "freezer.watchdog", "--parent", str(os.getpid())])
    ctl = Controller(**parts, read_ram=read_ram)
    gauge = Gauge(ctl.read_ram)
    overlay = MotionOverlay()
    connect_gauge(ctl, gauge, overlay)
    gauge.show()
    statuses: list[str] = []
    ctl.status.connect(lambda s: (statuses.append(s), log(f"status: {s}")))
    stats: list = []
    ctl.stats_ready.connect(stats.append)

    park(app)
    snaps = sensor.snapshot()
    log(f"sensor:{len(snaps)} apps: {[s.app_id for s in snaps]}")
    mine = next(s for s in snaps if s.app_id == SACRIFICE)
    pids = [r.pid for r in mine.procs]
    log(f"notepad pids {pids}, {mine.working_set_mb} MB, RAM {read_ram().pct:.1f}%")

    # 1. Study session -> card -> freeze
    ctl.focus(None, "thesis")
    approve_only_sacrifice(app, ctl, "1-card.png")
    wait_for(app, lambda: not ctl.busy, 30, "freeze")
    assert [e.app_id for e in actuator.frozen()] == [SACRIFICE], actuator.frozen()
    assert suspended(pids), "notepad still running after freeze"
    log("FROZEN: notepad threads suspended")
    pump(app, 2.0)
    gauge.grab().save(str(OUT / "2-gauge-frozen.png"))

    # 2. Done -> restore
    ctl.done()
    wait_for(app, lambda: not ctl.busy and stats, 30, "restore")
    assert actuator.frozen() == [] and not suspended(pids), "notepad not restored"
    log(f"RESTORED: {stats[0]}")

    # 3. Pressure -> card -> freeze, then crash: the watchdog must thaw.
    # Thaw restores windows and that activates them; park Notepad again first.
    park(app)
    sensor.tracker.note(SACRIFICE, time.time() - 900)   # as if idle 15 min
    snaps = sorted(sensor.snapshot(), key=lambda s: s.last_focus_s * s.working_set_mb, reverse=True)
    from freezer.contracts import PressureEvent
    ctl.on_pressure(PressureEvent(max(read_ram().pct, 85.0), 30.0, [s.app_id for s in snaps]))
    approve_only_sacrifice(app, ctl, "3-pressure-card.png")
    wait_for(app, lambda: not ctl.busy, 30, "pressure freeze")
    assert suspended(pids), "pressure freeze did not suspend notepad"
    log("FROZEN via pressure card. Simulating a crash: heartbeat stops, process exits hard.")
    heartbeat.stop()
    if os.environ.get("FF_LIVE_CHECK_NO_CRASH"):
        ctl.shutdown()
        return 0
    sys.stdout.flush()
    os._exit(3)   # no shutdown, no thaw: only the watchdog can restore notepad


if __name__ == "__main__":
    sys.exit(main())
