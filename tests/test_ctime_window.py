"""F8: create-time match window (live reuse case is below, FakeOs pins first).

The actuator suspends only when the live creation time matches the snapshot
within CTIME_TOL_S. These tests pin both sides of that window: a same-PID
recreation inside the window IS hit (accepted residual risk, stated
honestly), one outside it is skipped and never suspended.
"""
import pytest

from freezer.actuator import CTIME_TOL_S, FreezeError, RealActuator
from freezer.contracts import ProcRef
from freezer.ledger import Ledger
from tests.test_actuator import FakeOs, FakeProc, snap

PID = 424251
SNAP_CTIME = 100.0


def test_recreation_inside_window_is_hit():
    """A reused PID created inside the window is suspended: the residual risk."""
    fake = FakeOs([FakeProc(PID, ctime=SNAP_CTIME + CTIME_TOL_S / 2)])
    act = RealActuator(os_layer=fake, ledger=Ledger())
    act.freeze(snap("a.exe", ProcRef(PID, SNAP_CTIME)), "s")
    assert fake.suspended == [PID]


def test_recreation_outside_window_is_skipped():
    """A reused PID created outside the window is skipped, never suspended."""
    # 0.05 s: outside the 1 ms window but inside the old 2 s one (red pre-fix).
    fake = FakeOs([FakeProc(PID, ctime=SNAP_CTIME + 0.05)])
    act = RealActuator(os_layer=fake, ledger=Ledger())
    with pytest.raises(FreezeError, match="nothing suspended"):
        act.freeze(snap("a.exe", ProcRef(PID, SNAP_CTIME)), "s")
    assert fake.suspended == []
    assert Ledger().load() == {}


import os as _os
import subprocess as _subprocess
import sys as _sys
import time as _time

from freezer.actuator import WindowsOs
from tests.test_audit_fixes import _ticks_advancing, _ticks_stalled

_live_only = pytest.mark.skipif(_os.name != "nt", reason="needs Windows suspend")

_TICK_SRC = (
    "import sys, time\n"
    "p = sys.argv[1]\n"
    "while True:\n"
    "    open(p, 'a').write(f'{time.time()}\\n')\n"
    "    time.sleep(0.2)\n"
)


@pytest.fixture()
def live_app(tmp_path):
    """One real timestamp-writing child; terminated on teardown."""
    marker = tmp_path / "ticks.txt"
    marker.write_text("", encoding="utf-8")
    proc = _subprocess.Popen(
        [_sys.executable, "-c", _TICK_SRC, str(marker)],
        stdout=_subprocess.DEVNULL, stderr=_subprocess.DEVNULL)
    try:
        assert _ticks_advancing(marker), "child never started ticking"
        yield proc, marker
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except _subprocess.TimeoutExpired:
            proc.kill()


@_live_only
def test_live_freeze_tolerates_sub_millisecond_snapshot_wobble(live_app):
    """A snapshot ctime rounded by half the window still freezes the live proc."""
    proc, marker = live_app
    ctime = WindowsOs().resolve(proc.pid).create_time
    info = WindowsOs().resolve(proc.pid)
    snap_ = snap("tickchild.exe", ProcRef(proc.pid, ctime + CTIME_TOL_S / 2))
    assert info is not None and info.exe == "python.exe"
    act = RealActuator()
    try:
        act.freeze(snap_, "s")
        assert _ticks_stalled(marker)
    finally:
        act.thaw_all()
    assert _ticks_advancing(marker)


@_live_only
def test_live_reused_pid_outside_window_is_not_suspended(live_app):
    """A snapshot ctime 0.05 s off (the reuse case) refuses, proc untouched."""
    proc, marker = live_app
    ctime = WindowsOs().resolve(proc.pid).create_time
    act = RealActuator()
    try:
        with pytest.raises(FreezeError, match="nothing suspended"):
            act.freeze(snap("tickchild.exe", ProcRef(proc.pid, ctime + 0.05)), "s")
        assert _ticks_advancing(marker)  # never suspended, still ticking
        assert Ledger().load() == {}
    finally:
        act.thaw_all()
