"""Live-wire check: the real sensor, policy, actuator and UI on a window this script owns.

    python -m demo.live_check            # study session -> card -> freeze -> done -> restore,
                                         # then pressure -> card -> freeze -> crash -> watchdog
    python -m demo.live_check --planner  # real Muse Spark (needs MODEL_API_KEY)

The script starts its own small window process and approves only that app, and only
while every process in it is one the script started. Windows 11 Notepad cannot be
used: it opens files as tabs in the user's own Notepad, which would then be frozen.
If the check cannot tell its process apart from yours (another python.exe window is
open), it refuses to run. Without --planner a stub plan proposes only the check's app,
so no key is needed. Screens land in demo/recordings/live-check/.
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
CHILD_ENV = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}   # its window must be real
os.environ["QT_QPA_PLATFORM"] = "offscreen"   # ours must not exist, or our PID would join its app

import psutil  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from freezer import agent as agent_module  # noqa: E402
from freezer import sessions  # noqa: E402
from freezer.contracts import AppSnapshot, Decision, Plan, PressureEvent  # noqa: E402
from freezer.watchdog import Heartbeat  # noqa: E402
from ui.app import Controller, connect_gauge, make_parts  # noqa: E402
from ui.fx import MotionOverlay  # noqa: E402
from ui.gauge import Gauge, read_ram  # noqa: E402

TITLE = f"Focus Freeze live check {os.getpid()}"
OUT = Path(__file__).parent / "recordings" / "live-check"
_WINDOW = ("import sys\nfrom PySide6.QtWidgets import QApplication, QLabel\n"
           "app = QApplication([])\nw = QLabel('This window gets frozen and thawed by demo.live_check.')\n"
           "w.setWindowTitle(sys.argv[1]); w.resize(420, 120); w.showMinimized()\napp.exec()\n")


class Refused(SystemExit):
    def __init__(self, why: str):
        super().__init__(f"live_check refused: {why}")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def pump(app: QApplication, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)


def wait_for(app: QApplication, cond, timeout_s: float = 30.0, what: str = "") -> None:
    deadline = time.monotonic() + timeout_s
    while not cond():
        if time.monotonic() > deadline:
            raise TimeoutError(f"timed out waiting for {what}")
        app.processEvents()
        time.sleep(0.02)


class Sacrifice:
    """The one process tree this check may freeze."""

    def __init__(self) -> None:
        self.proc = subprocess.Popen([sys.executable, "-c", _WINDOW, TITLE], env=CHILD_ENV)
        self.app_id = ""
        self.app_pids: set[int] = set()   # the PIDs the sensor groups as our app

    def owned(self) -> set[int]:
        try:
            root = psutil.Process(self.proc.pid)
            return {root.pid} | {c.pid for c in root.children(recursive=True)}
        except psutil.Error:
            return set()

    def find(self, snaps: list[AppSnapshot]) -> AppSnapshot | None:
        mine = self.owned()
        return next((s for s in snaps if {p.pid for p in s.procs} & mine), None)

    def check(self, snap: AppSnapshot | None) -> AppSnapshot:
        """Refuse unless every process in the app is ours: freezing it must touch nothing else."""
        if snap is None:
            raise Refused("the check's own window is not in the snapshot")
        others = {p.pid for p in snap.procs} - self.owned()
        if others:
            raise Refused(f"{snap.app_id} also holds processes this check did not start "
                          f"(PIDs {sorted(others)}). Close your other {snap.app_id} windows and rerun.")
        self.app_pids = {p.pid for p in snap.procs}
        return snap

    def pids(self) -> list[int]:
        return sorted(self.owned())

    def suspended(self) -> bool:
        return all(psutil.Process(p).status() == psutil.STATUS_STOPPED for p in self.app_pids if psutil.pid_exists(p))

    def close(self) -> None:
        for p in self.pids():
            try:
                psutil.Process(p).kill()
            except psutil.Error:
                pass


def park(app: QApplication, me: Sacrifice) -> None:
    """Minimize our window until something else is foreground: policy never freezes
    the app in use, and a restored window comes back activated."""
    import win32api
    import win32con
    import win32gui
    import win32process
    from freezer.sensor import _foreground_pid
    for _ in range(20):
        mine = me.owned()
        win32gui.EnumWindows(lambda h, _: win32gui.ShowWindow(h, 6) if win32gui.IsWindowVisible(h)
                             and win32process.GetWindowThreadProcessId(h)[1] in mine else None, None)
        pump(app, 0.5)
        if _foreground_pid() not in mine:
            return
        # A minimized window can stay foreground. The Alt tap lets us hand focus to the taskbar.
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
        try:
            win32gui.SetForegroundWindow(win32gui.FindWindow("Shell_TrayWnd", None))
        except win32gui.error:
            pass
        pump(app, 0.5)
        if _foreground_pid() not in mine:
            return
    raise RuntimeError("the check's window keeps the foreground: click another window and rerun")


def approve_only_ours(app, ctl, me: Sacrifice, shot: str) -> None:
    wait_for(app, lambda: ctl.card is not None, 60, "card")
    card = ctl.card
    pump(app, 1.0)   # entrance animation
    if not hasattr(card, "rows"):   # guardian card first: Review opens the consent card
        card.grab().save(str(OUT / f"guardian-{shot}"))
        card.accept()
        wait_for(app, lambda: ctl.card is not None and ctl.card is not card, 10, "consent card")
        card = ctl.card
        pump(app, 1.0)
    try:
        me.check(card.proposal.apps.get(me.app_id))   # what the card would freeze, checked again
    except Refused:
        card.cancel()
        raise
    for row in card.rows:
        row.check.setChecked(row.app_id == me.app_id)
    log(f"card rows: {[(r.app_id, r.check.isChecked()) for r in card.rows]}")
    card.grab().save(str(OUT / shot))
    card.accept()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--planner", action="store_true", help="real Muse Spark instead of the stub")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    log(f"FF_HOME={os.environ['FF_HOME']}")
    app = QApplication(sys.argv)
    me = Sacrifice()
    try:
        return run(app, me, args.planner)
    finally:
        me.close()


def run(app: QApplication, me: Sacrifice, planner: bool) -> int:
    parts = make_parts(True, live=True)
    actuator, sensor = parts["actuator"], parts["sensor"]
    wait_for(app, lambda: me.find(sensor.snapshot()) is not None, 20, "the check's window")
    snap = me.check(me.find(sensor.snapshot()))
    me.app_id = snap.app_id

    if not planner:
        def stub_plan(task, snapshots, session=None, *, on_progress=None, **_kw) -> Plan:
            decisions = [Decision(s.app_id, "freeze" if s.app_id == me.app_id else "keep", "live check")
                         for s in snapshots]
            return Plan(task, decisions, "stub (no key)", 0.0)
        agent_module.plan = stub_plan
    sessions.start("thesis", "writing my thesis on urban heat islands")   # one plain session, no auto_freeze
    actuator.thaw_all()
    heartbeat = Heartbeat()
    heartbeat.start()
    watchdog = subprocess.Popen([sys.executable, "-m", "freezer.watchdog", "--parent", str(os.getpid())])
    parts["policy"].watchdog_pid = watchdog.pid
    ctl = Controller(**parts, read_ram=read_ram)
    parts["policy"].active = lambda: ctl.agent.session_name
    gauge = Gauge(ctl.read_ram)
    overlay = MotionOverlay()
    connect_gauge(ctl, gauge, overlay)
    gauge.show()
    ctl.status.connect(lambda s: log(f"status: {s}"))
    stats: list = []
    ctl.stats_ready.connect(stats.append)

    park(app, me)
    log(f"ours: {me.app_id} pids {me.pids()}, {snap.working_set_mb} MB, RAM {read_ram().pct:.1f}%")

    # 1. Study session -> card -> freeze
    t0 = time.monotonic()
    ctl.focus(None, "thesis")
    approve_only_ours(app, ctl, me, "1-card.png")
    log(f"card in {time.monotonic() - t0:.1f}s")
    t0 = time.monotonic()
    wait_for(app, lambda: not ctl.busy, 30, "freeze")
    assert [e.app_id for e in actuator.frozen()] == [me.app_id], actuator.frozen()
    assert me.suspended(), "still running after freeze"
    log(f"FROZEN in {time.monotonic() - t0:.1f}s: threads suspended")
    pump(app, 2.0)
    gauge.grab().save(str(OUT / "2-gauge-frozen.png"))

    # 2. Done -> restore
    ctl.done()
    wait_for(app, lambda: not ctl.busy and stats, 30, "restore")
    assert actuator.frozen() == [] and not me.suspended(), "not restored"
    log(f"RESTORED in {stats[0].restore_s:.2f}s")

    # 3. Pressure -> card -> freeze, then crash: the watchdog must thaw.
    park(app, me)   # thaw restored and activated the window
    sensor.tracker.note(me.app_id, time.time() - 900)   # as if idle 15 min
    snaps = sorted(sensor.snapshot(), key=lambda s: s.last_focus_s * s.working_set_mb, reverse=True)
    ctl.on_pressure(PressureEvent(max(read_ram().pct, 85.0), 30.0, [s.app_id for s in snaps]))
    approve_only_ours(app, ctl, me, "3-pressure-card.png")
    wait_for(app, lambda: not ctl.busy, 30, "pressure freeze")
    assert me.suspended(), "pressure freeze did not suspend"
    heartbeat.stop()
    if os.environ.get("FF_LIVE_CHECK_NO_CRASH"):
        log("FROZEN via pressure card. Shutting down cleanly.")
        ctl.shutdown()
        return 0
    log("FROZEN via pressure card. Simulating a crash: heartbeat stops, process exits hard.")
    # The watchdog must thaw our window after we die; a helper waits and reports it.
    subprocess.Popen([sys.executable, "-c",
                      "import sys, time, psutil\n"
                      "pids, t0 = [int(p) for p in sys.argv[1].split(',')], time.time()\n"
                      "while time.time() - t0 < 15:\n"
                      "    if all(psutil.Process(p).status() != 'stopped' for p in pids if psutil.pid_exists(p)):\n"
                      "        print(f'WATCHDOG THAWED in {time.time() - t0:.1f}s', flush=True)\n"
                      "        [psutil.Process(p).kill() for p in pids if psutil.pid_exists(p)]\n"
                      "        sys.exit(0)\n"
                      "    time.sleep(0.1)\n"
                      "print('WATCHDOG DID NOT THAW', flush=True); sys.exit(1)\n",
                      ",".join(map(str, sorted(me.app_pids)))])
    sys.stdout.flush()
    os._exit(3)   # no shutdown, no thaw, no cleanup: only the watchdog can restore the window


if __name__ == "__main__":
    sys.exit(main())
