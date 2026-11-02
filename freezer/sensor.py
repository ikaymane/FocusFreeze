"""Live Windows sensor: running processes -> :class:`AppSnapshot` lists.

B-cover implementation of ``plans/roles/B-os-data-security.md`` step 1
(B is out; this fills their sensor slot, same contract, same grouping).

Grouping: top-level visible windows (``EnumWindows`` +
``GetWindowThreadProcessId``) give the owning process; each app is the
owner's exe (lowercase ``app_id``) plus all PIDs ever seen for it, and the
freeze tree is the owner plus ``psutil`` recursive children, minus any child
that is another windowed app and everything under it (see :func:`_prune`). Only processes
alive at sampling time are emitted; a PID that dies mid-sample is skipped,
never guessed (sampling instant documented for the U1 audit gap).

Fail-closed choices: elevation unknown -> elevated (policy then blocks);
idle unknown -> 0.0 s (recently used: the guardian leaves it alone until
the :class:`ForegroundTracker` has watched it idle); audio/network lookup
failure -> False, documented (warning UX, not a safety gate).

Plays-audio needs ``pycaw`` (B's specified stack); without it every app
reports ``plays_audio=False``.
"""

from __future__ import annotations

import threading
import time

import psutil

from freezer.contracts import AppSnapshot, ProcRef

try:  # B's audio stack; absent -> plays_audio stays False (documented above)
    from pycaw.pycaw import AudioUtilities
except ImportError:  # pragma: no cover - environment without pycaw
    AudioUtilities = None

_AUDIO_ACTIVE = 1  # AudioSessionState.Active
_MAX_TITLES_PER_APP = 16


# ---- raw OS reads (tiny, monkeypatchable in tests) --------------------------

def _enum_windows() -> list[tuple[int, str, int]]:
    """(hwnd, stripped non-empty title, owner pid) for visible top windows."""
    import win32gui
    import win32process

    found: list[tuple[int, str, int]] = []

    def cb(hwnd: int, _extra: None) -> None:
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = (win32gui.GetWindowText(hwnd) or "").strip()
            if not title:
                return
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            found.append((hwnd, title, pid))
        except Exception:  # noqa: BLE001 - one hostile window skips, not all
            return

    win32gui.EnumWindows(cb, None)
    return found


def _foreground_pid() -> int | None:
    import win32gui
    import win32process

    try:
        _, pid = win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())
        return pid
    except Exception:  # noqa: BLE001 - unknown foreground, not fatal
        return None


def _proc_name(pid: int) -> str:
    try:
        return (psutil.Process(pid).name() or "").lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return ""


def _live(p: psutil.Process) -> bool:
    try:
        p.create_time()
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False


def _tree(pid: int) -> list[psutil.Process]:
    """Owner process plus recursive children; live processes only."""
    try:
        root = psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return []
    procs = [root]
    try:
        procs += root.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass
    return [p for p in procs if _live(p)]


def _prune(exe: str, procs: list, owners: set[str]) -> list:
    """Drop processes that belong to another windowed app, and everything under them.

    A launcher's children are their own apps (explorer -> code.exe, a chat app
    -> chrome.exe): freezing the launcher must never suspend them.
    """
    names = {p.pid: _proc_name(p.pid) for p in procs}
    cut = {pid for pid, name in names.items() if name in owners and name != exe}
    if not cut:
        return procs
    by_pid = {p.pid: p for p in procs}

    def under_cut(p) -> bool:
        pid, seen = p.pid, set()
        while pid in by_pid and pid not in seen:
            if pid in cut:
                return True
            seen.add(pid)
            try:
                pid = by_pid[pid].ppid()
            except (psutil.Error, AttributeError):
                return False
        return False

    return [p for p in procs if not under_cut(p)]


def _working_set_mb(procs: list[psutil.Process]) -> float:
    total = 0.0
    for p in procs:
        try:
            total += p.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return total / 1e6


def _is_elevated(pid: int) -> bool:
    """Token-elevation check; True (blocked) when it cannot be answered."""
    try:
        import win32api
        import win32security
        import win32con

        handle = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        try:
            token = win32security.OpenProcessToken(handle, win32security.TOKEN_QUERY)
            try:
                return bool(win32security.GetTokenInformation(token, win32security.TokenElevation))
            finally:
                win32api.CloseHandle(token)
        finally:
            win32api.CloseHandle(handle)
    except Exception:  # noqa: BLE001 - fail closed, see module docstring
        return True


def _has_network(procs: list[psutil.Process]) -> bool:
    for p in procs:
        try:
            conns = p.net_connections(kind="tcp")
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception:  # noqa: BLE001 - unknown stack, keep scanning
            continue
        if any(c.status == "ESTABLISHED" for c in conns):
            return True
    return False


def _audio_pids() -> set[int]:
    """PIDs with an active audio session; empty when unknowable."""
    if AudioUtilities is None:
        return set()
    try:
        pids = set()
        for session in AudioUtilities.GetAllSessions():
            try:
                if session.State == _AUDIO_ACTIVE and session.Process is not None:
                    pids.add(session.Process.pid)
            except Exception:  # noqa: BLE001 - one bad session skips
                continue
        return pids
    except Exception:  # noqa: BLE001 - documented fallback to False
        return set()


class ForegroundTracker:
    """Watches the foreground window so snapshots carry real idle times.

    Polls :func:`_foreground_pid` at 1 Hz on a daemon thread (B's spec) and
    remembers the last-seen instant per exe. ``idle_s`` is ``inf`` for apps
    never seen: callers treat unknown as recently used (fail closed).
    """

    def __init__(self, interval_s: float = 1.0) -> None:
        self.interval_s = interval_s
        self._seen: dict[str, float] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def note(self, app_id: str, when: float | None = None) -> None:
        self._seen[app_id] = time.time() if when is None else when

    def idle_s(self, app_id: str, now: float | None = None) -> float:
        if app_id not in self._seen:
            return float("inf")
        return max(0.0, (time.time() if now is None else now) - self._seen[app_id])

    def _poll_once(self) -> None:
        pid = _foreground_pid()
        if pid is None:
            return
        exe = _proc_name(pid)
        if exe:
            self.note(exe)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            self._poll_once()

    def start(self) -> "ForegroundTracker":
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval_s + 1.0)
            self._thread = None


class RealSensor:
    """One-shot live snapshots; share one :class:`ForegroundTracker`."""

    def __init__(self, tracker: ForegroundTracker | None = None) -> None:
        self.tracker = tracker

    def snapshot(self, *, now: float | None = None) -> list[AppSnapshot]:
        moment = time.time() if now is None else now
        fg_pid = _foreground_pid()
        fg_exe = _proc_name(fg_pid) if fg_pid is not None else ""
        audio = _audio_pids()
        groups: dict[str, dict] = {}
        for _hwnd, title, pid in _enum_windows():
            exe = _proc_name(pid)
            if not exe:
                continue
            g = groups.setdefault(exe, {"pids": [], "titles": []})
            g["pids"].append(pid)
            if len(g["titles"]) < _MAX_TITLES_PER_APP:
                g["titles"].append(title)
        snaps: list[AppSnapshot] = []
        for exe, g in groups.items():
            tree: dict[int, psutil.Process] = {}
            for pid in g["pids"]:
                for proc in _tree(pid):
                    tree.setdefault(proc.pid, proc)
            procs = _prune(exe, list(tree.values()), set(groups))
            if not procs:
                continue
            refs = []
            for proc in procs:
                try:
                    refs.append(ProcRef(proc.pid, proc.create_time()))
                except (psutil.NoSuchProcess, psutil.AccessDenied,
                        psutil.ZombieProcess):
                    continue
            if not refs:
                continue
            foreground = bool(exe and exe == fg_exe)
            if foreground:
                idle = 0.0
            elif self.tracker is not None:
                idle = self.tracker.idle_s(exe, moment)
                idle = 0.0 if idle == float("inf") else idle
            else:
                idle = 0.0
            elevated = any(_is_elevated(p.pid) for p in procs)
            snaps.append(AppSnapshot(
                app_id=exe, display_name=exe, procs=refs,
                window_titles=list(g["titles"]),
                working_set_mb=round(_working_set_mb(procs), 1),
                last_focus_s=idle, is_foreground=foreground,
                plays_audio=any(p.pid in audio for p in procs),
                is_elevated=elevated,
                has_network=_has_network(procs)))
        snaps.sort(key=lambda s: s.working_set_mb, reverse=True)
        return snaps


def _main() -> None:
    """Step 1 verify: print a table to compare with Task Manager."""
    import sys

    sys.stdout.reconfigure(errors="replace")  # real titles carry any Unicode
    rows = RealSensor().snapshot()
    print(f"{'app':28} {'procs':>5} {'MB':>9}  flags  title")
    for s in rows:
        flags = "".join([
            "F" if s.is_foreground else "-",
            "A" if s.plays_audio else "-",
            "E" if s.is_elevated else "-",
            "N" if s.has_network else "-",
        ])
        print(f"{s.app_id:28} {len(s.procs):>5} {s.working_set_mb:>9.0f}  {flags}  "
              f"{s.window_titles[0][:60] if s.window_titles else ''}")


if __name__ == "__main__":
    _main()
