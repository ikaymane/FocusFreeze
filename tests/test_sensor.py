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
        return SimpleNamespace(rss=self._mb * 1e6)

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
