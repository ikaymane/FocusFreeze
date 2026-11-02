"""F12/F13: case-insensitive app keys in ledger + actuator (live suspends).

A direct twin freeze (Chrome.exe + chrome.exe) must not double-freeze, and
thawing either spelling must thaw the single merged entry fully.

Every test suspends real throwaway children (timestamp-writing sleep loops),
touches nothing else, and resumes via try/finally. FF_HOME is isolated per
test by tests/conftest.py. Windows-only: suspend needs ntdll.
"""
import os
import subprocess
import sys
import time

import pytest

from freezer.actuator import FreezeError, RealActuator, WindowsOs
from freezer.contracts import AppSnapshot, LedgerEntry, ProcRef
from freezer.ledger import Ledger, _encode, ledger_path
from tests.test_audit_fixes import _ticks_advancing, _ticks_stalled

pytestmark = pytest.mark.skipif(os.name != "nt", reason="needs Windows suspend")

_TICK_SRC = (
    "import sys, time\n"
    "p = sys.argv[1]\n"
    "while True:\n"
    "    open(p, 'a').write(f'{time.time()}\\n')\n"
    "    time.sleep(0.2)\n"
)


@pytest.fixture()
def live_pair(tmp_path):
    """Two real timestamp-writing children; both terminated on teardown."""
    kids = []
    for name in ("a.txt", "b.txt"):
        marker = tmp_path / name
        marker.write_text("", encoding="utf-8")
        proc = subprocess.Popen(
            [sys.executable, "-c", _TICK_SRC, str(marker)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        kids.append((proc, marker))
    try:
        for _, marker in kids:
            assert _ticks_advancing(marker), "child never started ticking"
        yield kids
    finally:
        for proc, _ in kids:
            proc.terminate()
        for proc, _ in kids:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def _snap(pid: int, app_id: str) -> AppSnapshot:
    info = WindowsOs().resolve(pid)
    assert info is not None and info.exe == "python.exe"
    return AppSnapshot(app_id, app_id, [ProcRef(pid, info.create_time)], [],
                       10.0, 3600.0, False, False, False, False)


def test_twin_freeze_second_spelling_reports_already_frozen(live_pair):
    """Freezing chrome.exe while Chrome.exe (same proc) is frozen must refuse."""
    (proc_a, marker_a), (proc_b, marker_b) = live_pair
    act = RealActuator()
    try:
        act.freeze(_snap(proc_a.pid, "Chrome.exe"), "s")
        assert _ticks_stalled(marker_a)
        with pytest.raises(FreezeError, match="already frozen"):
            act.freeze(_snap(proc_a.pid, "chrome.exe"), "s")
        assert set(Ledger().load()) == {"chrome.exe"}  # one entry, folded key
        assert [e.app_id for e in act.frozen()] == ["Chrome.exe"]  # first spelling kept
        assert _ticks_stalled(marker_a)  # still suspended exactly once
        assert _ticks_advancing(marker_b)  # untouched proc keeps ticking
    finally:
        act.thaw_all()
    assert _ticks_advancing(marker_a)


def test_thaw_by_other_spelling_resumes(live_pair):
    """thaw() of any spelling must thaw the single merged entry fully."""
    (proc_a, marker_a), (proc_b, marker_b) = live_pair
    act = RealActuator()
    try:
        act.freeze(_snap(proc_a.pid, "Chrome.exe"), "s")
        assert _ticks_stalled(marker_a)
        act.thaw("cHrOmE.eXe")
        assert _ticks_advancing(marker_a)  # resumed, not stranded
        assert RealActuator().frozen() == []
    finally:
        act.thaw_all()
    assert _ticks_advancing(marker_b)


def _write_twin_file(proc_a, proc_b):
    """Suspend both children and hand-craft a signed ledger with twin spellings."""
    os_layer = WindowsOs()
    cta = os_layer.resolve(proc_a.pid).create_time
    ctb = os_layer.resolve(proc_b.pid).create_time
    assert os_layer.suspend_verified(proc_a.pid, cta)
    assert os_layer.suspend_verified(proc_b.pid, ctb)
    now = time.time()
    entries = {
        "Chrome.exe": LedgerEntry("Chrome.exe", [ProcRef(proc_a.pid, cta)],
                                  now, 10.0, "s"),
        "chrome.exe": LedgerEntry("chrome.exe", [ProcRef(proc_b.pid, ctb)],
                                  now + 1, 20.0, "s"),
    }
    raw = _encode(entries)
    ledger_path().write_bytes(raw)
    ledger_path().parent.joinpath(ledger_path().name + ".bak").write_bytes(raw)


def test_preexisting_twin_spellings_merge_and_thaw_fully(live_pair):
    """A ledger file holding both spellings loads as one union entry; thaw
    of either spelling resumes every proc; the backup is never shrunk."""
    (proc_a, marker_a), (proc_b, marker_b) = live_pair
    act = RealActuator()
    try:
        _write_twin_file(proc_a, proc_b)
        loaded = Ledger().load()
        assert set(loaded) == {"chrome.exe"}  # merged to one folded key
        merged = loaded["chrome.exe"]
        assert {p.pid for p in merged.procs} == {proc_a.pid, proc_b.pid}  # union, nothing dropped
        assert _ticks_stalled(marker_a) and _ticks_stalled(marker_b)
        act.thaw("CHROME.EXE")
        assert _ticks_advancing(marker_a) and _ticks_advancing(marker_b)
        assert Ledger().load() == {}
        bak = Ledger(ledger_path().parent.joinpath(ledger_path().name + ".bak"))
        bak_pids = {p.pid for e in bak.load().values() for p in e.procs}
        assert bak_pids == {proc_a.pid, proc_b.pid}  # backup never shrunk
    finally:
        act.thaw_all()
    assert _ticks_advancing(marker_a) and _ticks_advancing(marker_b)


def test_crash_mid_write_loses_nothing(live_pair):
    """A crash during the post-merge write leaves file+backup intact; retry works."""
    from unittest import mock
    (proc_a, marker_a), (proc_b, marker_b) = live_pair
    act = RealActuator()
    try:
        _write_twin_file(proc_a, proc_b)
        with mock.patch("os.replace", side_effect=OSError("injected crash")):
            with pytest.raises(OSError, match="injected crash"):
                act.thaw("CHROME.EXE")
        # Resume happened before the failed write; the files still hold everything.
        assert _ticks_advancing(marker_a) and _ticks_advancing(marker_b)
        pids = {p.pid for e in Ledger().load().values() for p in e.procs}
        assert pids == {proc_a.pid, proc_b.pid}
        bak = Ledger(ledger_path().parent.joinpath(ledger_path().name + ".bak"))
        bak_pids = {p.pid for e in bak.load().values() for p in e.procs}
        assert bak_pids == {proc_a.pid, proc_b.pid}
        act.thaw("chrome.exe")  # retry after the crash works
        assert Ledger().load() == {}
    finally:
        act.thaw_all()
    assert _ticks_advancing(marker_a) and _ticks_advancing(marker_b)
