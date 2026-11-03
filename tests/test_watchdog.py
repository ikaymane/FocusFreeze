"""Watchdog: stale heartbeat thaws; panic hotkey lifecycle + dispatch."""
import json
import os
import threading
import time

import pytest

from freezer import watchdog
from freezer.mocks import MockActuator
from freezer.watchdog import Heartbeat, PanicKey


class CountingActuator(MockActuator):
    def __init__(self):
        super().__init__()
        self.thaw_all_calls = 0

    def thaw_all(self):
        self.thaw_all_calls += 1
        return super().thaw_all()


def write_beat(pid, ts):
    p = watchdog.heartbeat_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"pid": pid, "ts": ts}), encoding="utf-8")


def test_fresh_heartbeat_thaws_nothing():
    watchdog.beat()
    act = CountingActuator()
    assert watchdog.check(act, clock=lambda: time.time()) is False
    assert act.thaw_all_calls == 0


def test_stale_heartbeat_thaws_everything():
    write_beat(1234, time.time() - 100)
    act = CountingActuator()
    assert watchdog.check(act) is True
    assert act.thaw_all_calls == 1


def test_missing_heartbeat_does_nothing():
    assert watchdog.check(CountingActuator()) is False


def _freeze_one(act):
    from freezer.contracts import AppSnapshot, ProcRef
    act.freeze(AppSnapshot("x.exe", "x", [ProcRef(1, 2.0)], [], 1.0, 0.0,
                           False, False, False, False), "")
    return act


def test_missing_heartbeat_with_frozen_apps_thaws():
    watchdog.heartbeat_path().unlink(missing_ok=True)
    act = _freeze_one(CountingActuator())
    assert watchdog.check(act) is True
    assert act.thaw_all_calls == 1


def test_future_heartbeat_with_frozen_apps_thaws():
    act = _freeze_one(CountingActuator())
    write_beat(1234, time.time() + 3600)
    assert watchdog.check(act) is True
    assert act.thaw_all_calls == 1


def test_future_heartbeat_empty_ledger_ignored():
    write_beat(1234, time.time() + 3600)
    assert watchdog.check(CountingActuator()) is False


def test_run_watchdog_checks_once_then_stops():
    write_beat(1234, time.time() - 100)
    act = CountingActuator()
    watchdog.run_watchdog(act, interval_s=0.01, stop=lambda: True)
    assert act.thaw_all_calls == 1


@pytest.mark.parametrize("body", ["[]", "null", '{"pid": "x"}'])
def test_malformed_heartbeat_is_ignored(body):
    p = watchdog.heartbeat_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    assert watchdog.check(CountingActuator()) is False


@pytest.mark.skipif(os.name != "nt", reason="Windows-only hotkey")
def test_panic_key_lifecycle():
    key = PanicKey(lambda: None)
    key.start()
    assert key.running and key.thread_id
    with pytest.raises(RuntimeError):
        key.start()
    key.stop()
    assert not key.running
    key.start()  # restart works, hotkey was released
    key.stop()
    assert not key.running


@pytest.mark.skipif(os.name != "nt", reason="Windows-only hotkey")
def test_heartbeat_advances_while_running():
    hb = Heartbeat(interval_s=0.05)
    hb.start()
    try:
        assert hb.running
        first = watchdog.read_beat()
        assert first is not None and first[0] == os.getpid()
        deadline = time.time() + 5
        while watchdog.read_beat()[1] <= first[1]:
            assert time.time() < deadline, "heartbeat never ticked again"
            time.sleep(0.05)
    finally:
        hb.stop()
    assert not hb.running


def test_heartbeat_double_start_raises_and_stop_is_idempotent():
    hb = Heartbeat(interval_s=60)
    hb.start()
    try:
        with pytest.raises(RuntimeError):
            hb.start()
    finally:
        hb.stop()
    hb.stop()  # stopping a stopped heartbeat is fine


def test_beat_retries_transient_replace_failure(monkeypatch):
    """One transient WinError-32-style lock must not lose a beat."""
    real_replace = os.replace
    state = {"calls": 0}

    def flaky_replace(src, dst):
        state["calls"] += 1
        if state["calls"] == 1:
            raise PermissionError(13, "file in use (injected WinError 32)")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    before = time.time()
    watchdog.beat()  # must not raise
    data = watchdog.read_beat()
    assert data is not None and data[0] == os.getpid()
    assert data[1] >= before
    assert state["calls"] >= 2  # first attempt failed, a retry landed it


def test_read_beat_retries_transient_read_failure(monkeypatch):
    """One transient read lock must not look like a missing heartbeat."""
    from pathlib import Path
    watchdog.beat()
    real_read_text = Path.read_text
    state = {"calls": 0}

    def flaky_read_text(self, *args, **kwargs):
        state["calls"] += 1
        if state["calls"] == 1:
            raise PermissionError(13, "file in use (injected)")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)
    assert watchdog.read_beat() is not None


def test_beat_logs_and_skips_after_repeated_replace_failure(monkeypatch):
    """A sustained lock degrades to a missing beat (watchdog still fires), never raises."""
    def always_locked(src, dst):
        raise PermissionError(13, "disk locked (injected)")

    monkeypatch.setattr(os, "replace", always_locked)
    watchdog.beat()  # must not raise
    assert watchdog.read_beat() is None  # fail closed: looks missing, watchdog fires


def test_concurrent_beats_never_raise_or_corrupt():
    """Concurrent beats (thread + direct, like agent loop + Heartbeat) share no
    tmp path: every call lands a whole heartbeat and none raise."""
    barrier = threading.Barrier(8)
    errors: list = []

    def worker():
        try:
            barrier.wait(timeout=10)
            for _ in range(50):
                watchdog.beat()
        except Exception as e:  # noqa: BLE001 - collected, asserted below
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not [t for t in threads if t.is_alive()]
    assert errors == []
    data = watchdog.read_beat()
    assert data is not None and data[0] == os.getpid()


def test_heartbeat_thread_survives_repeated_replace_failures(monkeypatch):
    """A total replace outage must not kill the beat thread; it recovers after."""
    real_replace = os.replace
    gate = {"fail": True}

    def gated_replace(src, dst):
        if gate["fail"]:
            raise PermissionError(13, "disk locked (injected)")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", gated_replace)
    started = time.time()
    hb = Heartbeat(interval_s=0.05)
    hb.start()
    try:
        time.sleep(0.3)  # several beats fail inside the thread
        assert hb.running  # the thread survived them all
        gate["fail"] = False
        deadline = time.time() + 5
        while True:
            data = watchdog.read_beat()
            if data is not None and data[1] >= started:
                break
            assert time.time() < deadline, "heartbeat never recovered"
            time.sleep(0.05)
    finally:
        hb.stop()


def test_panic_key_dispatches_to_callback():
    import ctypes

    fired = threading.Event()
    key = PanicKey(fired.set)
    key.start()
    try:
        u32 = ctypes.WinDLL("user32")
        assert key.thread_id is not None
        assert u32.PostThreadMessageW(key.thread_id, PanicKey.WM_HOTKEY, 0, 0)
        assert fired.wait(5)
    finally:
        key.stop()


def test_watchdog_process_thaws_when_parent_dies_with_fresh_beat(monkeypatch):
    """A crash leaves a fresh heartbeat; the parent check still thaws."""
    import sys

    import psutil

    from freezer import actuator

    watchdog.beat()
    act = _freeze_one(CountingActuator())
    monkeypatch.setattr(actuator, "RealActuator", lambda: act)
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: False)
    monkeypatch.setattr(sys, "argv", ["watchdog", "--parent", "4242"])
    watchdog._main()
    assert act.frozen() == []
    assert act.thaw_all_calls == 1
