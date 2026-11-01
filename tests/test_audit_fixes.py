"""Live audit-fix tests (role A): real crash points, real throwaway processes.

Every test that suspends something spawns its own child (a timestamp-writing
sleep loop), touches nothing else, and terminates it in a fixture. FF_HOME is
already isolated per test by tests/conftest.py. Windows-only: suspend needs
ntdll.
"""
import os
import subprocess
import sys
import time

import pytest

from freezer.actuator import RealActuator, WindowsOs
from freezer.contracts import AppSnapshot, LedgerEntry, ProcRef
from freezer.cost import home
from freezer.ledger import Ledger, LedgerTampered, _decode, _union, key_path, ledger_path

pytestmark = pytest.mark.skipif(os.name != "nt", reason="needs Windows suspend")

CHILD_TICK_S = 0.2


@pytest.fixture()
def live_app(tmp_path):
    """A real child writing timestamps to a file; terminated on teardown."""
    marker = tmp_path / "ticks.txt"
    marker.write_text("", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-c",
         "import sys, time\n"
         "p = sys.argv[1]\n"
         "while True:\n"
         "    open(p, 'a').write(f'{time.time()}\\n')\n"
         "    time.sleep(0.2)\n",
         str(marker)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert _ticks_advancing(marker), "child never started ticking"
        yield proc, marker
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _last_tick(marker) -> float:
    try:
        lines = marker.read_text(encoding="utf-8").split()
    except OSError:
        return 0.0
    return float(lines[-1]) if lines else 0.0


def _ticks_advancing(marker, wait_s: float = 1.0) -> bool:
    before = _last_tick(marker)
    deadline = time.time() + wait_s + 2.0
    while time.time() < deadline:
        if _last_tick(marker) > before:
            return True
        time.sleep(0.1)
    return False


def _ticks_stalled(marker, wait_s: float = 0.9) -> bool:
    before = _last_tick(marker)
    time.sleep(wait_s)
    return _last_tick(marker) == before


def snap_for(pid: int, app_id: str = "tickchild.exe") -> AppSnapshot:
    info = WindowsOs().resolve(pid)
    assert info is not None and info.exe == "python.exe"
    return AppSnapshot(app_id, app_id, [ProcRef(pid, info.create_time)], [],
                       10.0, 3600.0, False, False, False, False)


# ---- item 1: damaged ledger.json ---------------------------------------------

def test_damaged_primary_falls_back_to_bak_and_thaws(live_app):
    """Real suspend + torn ledger.json on disk: union recovery, thaw works."""
    proc, marker = live_app
    act = RealActuator()
    act.freeze(snap_for(proc.pid), "audit")
    assert _ticks_stalled(marker), "child kept ticking while suspended"

    # Crash point: a torn write leaves half a ledger.json; .bak stays whole.
    primary = ledger_path()
    raw = primary.read_bytes()
    primary.write_bytes(raw[:len(raw) // 2])

    restarted = Ledger()  # fresh process view: no in-memory entries
    assert set(restarted.load()) == {"tickchild.exe"}
    assert restarted.tampered  # flag is set by the read that saw damage
    with pytest.raises(LedgerTampered):
        restarted.add(restarted.load()["tickchild.exe"])  # no new freezes

    thawed = RealActuator().thaw_all()  # separate instance, like a restart
    assert thawed == ["tickchild.exe"]
    assert proc.poll() is None, "child died instead of resuming"
    assert _ticks_advancing(marker), "child never resumed ticking"
    assert RealActuator().frozen() == []


def test_union_prefers_newer_frozen_at():
    old = LedgerEntry("a.exe", [], 1.0, 0.0, "")
    new = LedgerEntry("a.exe", [], 2.0, 5.0, "")
    other = LedgerEntry("b.exe", [], 1.5, 0.0, "")
    merged = _union({"a.exe": old}, {"a.exe": new, "b.exe": other})
    assert merged["a.exe"].freed_mb == 5.0
    assert set(merged) == {"a.exe", "b.exe"}


def _entry(app_id: str) -> LedgerEntry:
    return LedgerEntry(app_id, [ProcRef(1, 2.0)], 3.0, 0.0, "")


def test_remove_keeps_fuller_backup():
    led = Ledger()
    led.add(_entry("a.exe"))
    led.add(_entry("b.exe"))
    led.remove("a.exe")  # single-app thaw: primary moves on...
    assert set(led.load()) == {"b.exe"}
    bak = Ledger(led._backup_path())  # ...but the backup keeps the history
    assert set(bak.load()) == {"a.exe", "b.exe"}


def test_save_thawed_may_shrink_backup():
    led = Ledger()
    led.add(_entry("a.exe"))
    led.add(_entry("b.exe"))
    led.save_thawed({})  # deliberate thaw_all: shrinking is the truth
    assert led.load() == {}
    assert Ledger(led._backup_path()).load() == {}
    assert home().exists()


# ---- item 2: corrupt ledger.key --------------------------------------------------

def test_corrupt_key_thaw_still_works_but_freeze_refused(live_app):
    """Real suspend + trashed key file: thaw_all still resumes, freeze refused."""
    proc, marker = live_app
    RealActuator().freeze(snap_for(proc.pid), "audit")
    assert _ticks_stalled(marker)

    # Crash point: a torn (old non-atomic) key write leaves garbage behind.
    key_path().write_bytes(b"\x00" * 16)

    thawed = RealActuator().thaw_all()
    assert thawed == ["tickchild.exe"]
    assert proc.poll() is None
    assert _ticks_advancing(marker)
    with pytest.raises(LedgerTampered):
        RealActuator().freeze(snap_for(proc.pid), "audit")


def test_decode_with_corrupt_key_returns_tamper():
    led = Ledger()
    led.add(_entry("a.exe"))
    raw = ledger_path().read_bytes()
    key_path().write_bytes(b"not a dpapi blob")
    entries, ok = _decode(raw)
    assert ok is False
    assert set(entries) == {"a.exe"}
    led2 = Ledger()
    assert led2.tampered is False  # flag is per-read, set by load()
    assert set(led2.load()) == {"a.exe"}
    assert led2.tampered is True


# ---- item 5: partial freeze ----------------------------------------------------

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


def snap_for_pair(pid_ctimes, app_id="tickpair.exe"):
    prefs = [ProcRef(pid, ct) for pid, ct in pid_ctimes]
    return AppSnapshot(app_id, app_id, prefs, [], 10.0, 3600.0,
                       False, False, False, False)


def _live_ctimes(procs):
    os_layer = WindowsOs()
    return [(p.pid, os_layer.resolve(p.pid).create_time) for p in procs]


def test_partial_freeze_rolls_back_and_resumes(live_pair):
    """Injected mid-freeze failure on a REAL suspend: rollback resumes both."""
    from freezer.actuator import FreezeError
    (proc_a, marker_a), (proc_b, marker_b) = live_pair
    real_os = WindowsOs()
    orig_trim = real_os.trim
    state = {"done": False}

    def fail_once(pid):
        if pid == proc_b.pid and not state["done"]:
            state["done"] = True
            raise OSError("injected trim failure")
        return orig_trim(pid)

    real_os.trim = fail_once  # instance shadow; suspend/resume stay real
    act = RealActuator(os_layer=real_os)
    with pytest.raises(FreezeError) as ei:
        act.freeze(snap_for_pair(_live_ctimes([proc_a, proc_b])), "audit")
    assert list(ei.value.failures) == [proc_b.pid]
    assert ei.value.entry is None  # clean rollback: nothing recorded
    assert RealActuator().frozen() == []
    assert _ticks_advancing(marker_a) and _ticks_advancing(marker_b)


def test_unelevated_process_passes_check_and_freezes(live_app):
    """Live T8 companion: this unelevated process passes, freeze works."""
    from freezer.actuator import ensure_not_elevated, is_elevated
    assert is_elevated() is False  # premise: the suite runs unelevated
    assert ensure_not_elevated() is None
    proc, marker = live_app
    entry = RealActuator().freeze(snap_for(proc.pid), "audit")
    assert [p.pid for p in entry.procs] == [proc.pid]
    assert RealActuator().thaw_all() == ["tickchild.exe"]
    assert _ticks_advancing(marker)


def test_freeze_of_exited_app_fails_with_empty_ledger(live_app):
    """Live 8a: freezing an already-dead child fails, recording no ghost."""
    from freezer.actuator import FreezeError
    proc, _marker = live_app
    ctime = WindowsOs().resolve(proc.pid).create_time
    proc.terminate()
    proc.wait(timeout=5)
    with pytest.raises(FreezeError, match="nothing suspended"):
        RealActuator().freeze(
            AppSnapshot("tickchild.exe", "tickchild", [ProcRef(proc.pid, ctime)],
                        [], 10.0, 3600.0, False, False, False, False), "audit")
    assert RealActuator().frozen() == []


def test_pre_killed_child_narrowed_out_of_entry(live_pair):
    """A child dead before freeze is skipped and left out of the entry."""
    (proc_a, marker_a), (proc_b, _marker_b) = live_pair
    ctimes = _live_ctimes([proc_a, proc_b])
    proc_b.terminate()
    proc_b.wait(timeout=5)
    entry = RealActuator().freeze(snap_for_pair(ctimes), "audit")
    assert [p.pid for p in entry.procs] == [proc_a.pid]
    assert RealActuator().thaw_all() == ["tickpair.exe"]
    assert _ticks_advancing(marker_a)
