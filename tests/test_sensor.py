import os
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

psutil = pytest.importorskip("psutil")
sensor = pytest.importorskip("freezer.sensor")


class _FakeProc:
    def __init__(self, pid, mb=100.0, conns=()):
        self.pid = pid
        self._mb = mb
        self._conns = conns

    def create_time(self):
        return 1.0

    def memory_info(self):
        return SimpleNamespace(rss=self._mb * 2**20)

    def net_connections(self, kind=None):
        return self._conns


@pytest.fixture
def rig(monkeypatch):
    """Two windowed apps (100 + child 101, 200) with stubbed OS reads."""
    procs = {100: _FakeProc(100, mb=300.0), 101: _FakeProc(101, mb=50.0),
             200: _FakeProc(200, mb=700.0)}
    monkeypatch.setattr(sensor, "_enum_windows",
                        lambda: [(1, "T1", 100), (2, "T2", 100), (3, "T3", 200)])
    monkeypatch.setattr(sensor, "_foreground_pid", lambda: 100)
    monkeypatch.setattr(sensor, "_proc_name",
                        lambda pid: {100: "app.exe", 101: "app.exe", 200: "other.exe"}.get(pid, ""))
    monkeypatch.setattr(sensor, "_tree",
                        lambda pid: [procs[pid]] + ([procs[101]] if pid == 100 else []))
    monkeypatch.setattr(sensor, "_is_elevated", lambda pid: False)
    monkeypatch.setattr(sensor, "_has_network", lambda procs: False)
    monkeypatch.setattr(sensor, "_audio_pids", lambda: {200})
    return procs


def test_grouping_lowercases_and_merges_windows(rig):
    snaps = sensor.RealSensor().snapshot()
    assert [s.app_id for s in snaps] == ["other.exe", "app.exe"]  # MB desc
    app = next(s for s in snaps if s.app_id == "app.exe")
    assert app.window_titles == ["T1", "T2"]
    assert {p.pid for p in app.procs} == {100, 101}
    assert app.working_set_mb == pytest.approx(350.0)


def test_foreground_zero_and_tracker_idle(rig):
    tracker = sensor.ForegroundTracker()
    tracker.note("other.exe", when=1000.0)
    snaps = sensor.RealSensor(tracker).snapshot(now=4600.0)
    by_id = {s.app_id: s for s in snaps}
    assert by_id["app.exe"].is_foreground and by_id["app.exe"].last_focus_s == 0.0
    assert not by_id["other.exe"].is_foreground
    assert by_id["other.exe"].last_focus_s == pytest.approx(3600.0)
    assert by_id["other.exe"].plays_audio  # pid 200 in fake audio set


def test_unknown_idle_is_zero_without_tracker(rig):
    snaps = sensor.RealSensor().snapshot()
    assert all(s.last_focus_s == 0.0 for s in snaps)


def test_dead_and_nameless_windows_skipped(monkeypatch):
    monkeypatch.setattr(sensor, "_enum_windows",
                        lambda: [(1, "Ghost", 999), (2, "Nameless", 998), (3, "Real", 997)])
    monkeypatch.setattr(sensor, "_foreground_pid", lambda: None)
    monkeypatch.setattr(sensor, "_proc_name",
                        lambda pid: {999: "ghost.exe", 998: "", 997: "real.exe"}.get(pid, ""))
    monkeypatch.setattr(sensor, "_tree",
                        lambda pid: [] if pid == 999 else [_FakeProc(pid)])
    monkeypatch.setattr(sensor, "_is_elevated", lambda pid: False)
    monkeypatch.setattr(sensor, "_has_network", lambda procs: False)
    monkeypatch.setattr(sensor, "_audio_pids", lambda: set())
    snaps = sensor.RealSensor().snapshot()
    assert [s.app_id for s in snaps] == ["real.exe"]


def test_launcher_never_owns_the_apps_it_started(monkeypatch):
    """explorer.exe -> code.exe -> powershell.exe: code is its own app, and its
    windowless shell stays with code, never with the launcher."""
    procs = {10: _FakeProc(10, mb=100.0), 11: _FakeProc(11, mb=50.0),   # launcher + its helper
             20: _FakeProc(20, mb=900.0), 21: _FakeProc(21, mb=80.0)}   # code + its shell
    parent = {11: 10, 20: 10, 21: 20}
    for pid, p in procs.items():
        p.ppid = lambda pid=pid: parent.get(pid, 0)
    monkeypatch.setattr(sensor, "_enum_windows", lambda: [(1, "Desktop", 10), (2, "Editor", 20)])
    monkeypatch.setattr(sensor, "_foreground_pid", lambda: None)
    monkeypatch.setattr(sensor, "_proc_name",
                        lambda pid: {10: "explorer.exe", 11: "helper.exe", 20: "code.exe",
                                     21: "powershell.exe"}.get(pid, ""))
    monkeypatch.setattr(sensor, "_tree", lambda pid: {10: [procs[10], procs[11], procs[20], procs[21]],
                                                      20: [procs[20], procs[21]]}[pid])
    monkeypatch.setattr(sensor, "_is_elevated", lambda pid: False)
    monkeypatch.setattr(sensor, "_has_network", lambda procs: False)
    monkeypatch.setattr(sensor, "_audio_pids", lambda: set())
    by_id = {s.app_id: s for s in sensor.RealSensor().snapshot()}
    assert {p.pid for p in by_id["explorer.exe"].procs} == {10, 11}
    assert by_id["explorer.exe"].working_set_mb == pytest.approx(150.0)
    assert {p.pid for p in by_id["code.exe"].procs} == {20, 21}


def test_garbage_negative_pid_is_nameless_not_fatal():
    """A window that closes mid-call can report a negative PID; psutil raises ValueError."""
    assert sensor._proc_name(-126960096) == ""
    tracker = sensor.ForegroundTracker()
    sensor_fg = sensor._foreground_pid
    try:
        sensor._foreground_pid = lambda: -5
        tracker._poll_once()   # must not raise: the tracker thread would die silently
    finally:
        sensor._foreground_pid = sensor_fg


def test_network_true_on_established():
    est = SimpleNamespace(status="ESTABLISHED")
    assert sensor._has_network([_FakeProc(1, conns=[est])])
    assert not sensor._has_network([_FakeProc(1, conns=[])])
    assert not sensor._has_network([_FakeProc(1, conns=[SimpleNamespace(status="LISTEN")])])


def test_audio_empty_without_stack(monkeypatch):
    monkeypatch.setattr(sensor, "AudioUtilities", None)
    assert sensor._audio_pids() == set()


def test_tracker_start_stop_no_crash():
    tracker = sensor.ForegroundTracker(interval_s=0.01).start()
    time.sleep(0.05)
    tracker.stop()
    assert tracker._thread is None


def test_tracker_idle_math():
    tracker = sensor.ForegroundTracker()
    assert tracker.idle_s("never.exe", now=100.0) == float("inf")
    tracker.note("a.exe", when=40.0)
    assert tracker.idle_s("a.exe", now=100.0) == pytest.approx(60.0)


@pytest.mark.skipif(os.name != "nt", reason="live Windows processes")
def test_live_notepad_snapshot():
    import psutil as _psutil
    # Modern notepad launches via a stub PID that exits: the live windowed
    # process (what the sensor must report) usually has a different PID.
    before = {p.pid for p in _psutil.process_iter(["name"])
              if (p.info["name"] or "").lower() == "notepad.exe"}
    subprocess.Popen(["notepad.exe"])
    note = None
    try:
        time.sleep(1.5)
        snaps = sensor.RealSensor().snapshot()
        ours = [s for s in snaps if s.app_id == "notepad.exe"]
        assert ours, "fresh notepad missing from live snapshot"
        note = ours[0]
        assert note.window_titles and note.working_set_mb > 0
        assert all(_psutil.pid_exists(p.pid) for p in note.procs)
        assert isinstance(note.is_elevated, bool)
        assert all(s.app_id == s.app_id.lower() for s in snaps)
    finally:
        for p in (note.procs if note is not None else []):
            if p.pid not in before:
                try:
                    _psutil.Process(p.pid).kill()
                except Exception:
                    pass


def _stub_win32(monkeypatch, open_process):
    """Fake win32api/security/con modules for _is_elevated tests."""
    import sys
    import types
    api = types.ModuleType("win32api")
    api.OpenProcess = open_process
    api.CloseHandle = lambda h: None
    sec = types.ModuleType("win32security")
    sec.OpenProcessToken = lambda h, acc: "tok"
    sec.GetTokenInformation = lambda t, c: 1
    sec.TOKEN_QUERY = 8
    sec.TokenElevation = 20
    con = types.ModuleType("win32con")
    con.PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    monkeypatch.setitem(sys.modules, "win32api", api)
    monkeypatch.setitem(sys.modules, "win32security", sec)
    monkeypatch.setitem(sys.modules, "win32con", con)


def _denied(*args):
    raise OSError(5, "access denied")


def _os_stubs(monkeypatch):
    monkeypatch.setattr(sensor, "_is_elevated", lambda pid: False)
    monkeypatch.setattr(sensor, "_has_network", lambda procs: False)
    monkeypatch.setattr(sensor, "_audio_pids", lambda: set())


def test_cloaked_and_tool_windows_skipped(monkeypatch):
    """textinputhost-style shell windows never become apps."""
    import win32gui
    import win32process
    monkeypatch.setattr(win32gui, "EnumWindows",
                        lambda cb, _: [cb(h, None) for h in (1, 2, 3)])
    monkeypatch.setattr(win32gui, "IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr(win32gui, "GetWindowText",
                        lambda hwnd: {1: "Shell", 2: "Tool", 3: "Real"}[hwnd])
    monkeypatch.setattr(win32process, "GetWindowThreadProcessId",
                        lambda hwnd: (0, {1: 11, 2: 12, 3: 13}[hwnd]))
    monkeypatch.setattr(sensor, "_is_cloaked", lambda hwnd: hwnd == 1)
    monkeypatch.setattr(sensor, "_is_tool_window", lambda hwnd: hwnd == 2)
    monkeypatch.setattr(sensor, "_proc_name",
                        lambda pid: {11: "textinputhost.exe", 12: "tool.exe",
                                     13: "real.exe"}[pid])
    monkeypatch.setattr(sensor, "_tree", lambda pid: [_FakeProc(pid)])
    _os_stubs(monkeypatch)
    assert [s.app_id for s in sensor.RealSensor().snapshot()] == ["real.exe"]


def test_dead_pid_is_not_elevated(monkeypatch):
    """A process that exited mid-sample must not read as admin."""
    _stub_win32(monkeypatch, _denied)
    monkeypatch.setattr(sensor.psutil, "pid_exists", lambda pid: False)
    assert sensor._is_elevated(424242) is False


def test_live_but_denied_pid_stays_elevated(monkeypatch):
    """Fail-closed survives: a living process we cannot read stays blocked."""
    _stub_win32(monkeypatch, _denied)
    monkeypatch.setattr(sensor.psutil, "pid_exists", lambda pid: True)
    assert sensor._is_elevated(4) is True


def test_shared_pid_goes_to_most_specific_app(monkeypatch):
    """helper pid 5 sits in both trees; the smaller tree keeps it."""
    monkeypatch.setattr(sensor, "_enum_windows",
                        lambda: [(1, "A", 1), (2, "B", 2)])
    monkeypatch.setattr(sensor, "_foreground_pid", lambda: None)
    monkeypatch.setattr(sensor, "_proc_name",
                        lambda pid: {1: "a.exe", 2: "b.exe", 5: "helper.exe",
                                     6: "helper.exe"}[pid])
    monkeypatch.setattr(sensor, "_tree",
                        lambda pid: {1: [_FakeProc(1), _FakeProc(5), _FakeProc(6)],
                                     2: [_FakeProc(2), _FakeProc(5)]}[pid])
    _os_stubs(monkeypatch)
    by_id = {s.app_id: s for s in sensor.RealSensor().snapshot()}
    a = {p.pid for p in by_id["a.exe"].procs}
    b = {p.pid for p in by_id["b.exe"].procs}
    assert a & b == set()
    assert 5 in b and 5 not in a


def test_shared_pid_stays_with_its_window_owner(monkeypatch):
    """Mid-sample race: pid 5 owns B's window but lands in A's tree too.

    _prune is bypassed to simulate the race (its live name lookups can
    disagree with grouping-time names); the post-pass must still dedupe
    with the window owner's app winning over the most specific tree.
    """
    monkeypatch.setattr(sensor, "_prune",
                        lambda exe, procs, owners: procs)
    monkeypatch.setattr(sensor, "_enum_windows",
                        lambda: [(1, "A", 1), (2, "B", 5)])
    monkeypatch.setattr(sensor, "_foreground_pid", lambda: None)
    monkeypatch.setattr(sensor, "_proc_name",
                        lambda pid: {1: "a.exe", 5: "b.exe", 7: "helper.exe",
                                     8: "helper.exe"}[pid])
    monkeypatch.setattr(sensor, "_tree",
                        lambda pid: {1: [_FakeProc(1), _FakeProc(5)],
                                     5: [_FakeProc(5), _FakeProc(7),
                                         _FakeProc(8)]}[pid])
    _os_stubs(monkeypatch)
    by_id = {s.app_id: s for s in sensor.RealSensor().snapshot()}
    a = {p.pid for p in by_id["a.exe"].procs}
    b = {p.pid for p in by_id["b.exe"].procs}
    assert a & b == set()
    assert 5 in b and 5 not in a


def test_working_set_uses_mib():
    """5 MiB resident must read as 5.0, not 5.24 (decimal MB)."""
    proc = _FakeProc(1)
    proc.memory_info = lambda: SimpleNamespace(rss=5 * 2**20)
    assert sensor._working_set_mb([proc]) == pytest.approx(5.0)
