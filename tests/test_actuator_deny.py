"""Actuator deny-list backstop (F1): B's deny lists enforced at freeze time.

The agent loop enforces the deny lists through policy, but a direct
actuator.freeze() bypasses policy. These tests prove the actuator itself
refuses every deny-list exe, case-insensitively, before suspending anything.

Scope note: refusal covers B's deny lists MINUS the system-plumbing skip
set (svchost, msmpeng, ...), which keep their long-standing per-process
skip, pinned by test_freeze_skips_conhost_system_and_session0. A missing
exe name stays on the skip path too (dead PIDs resolve unnamed on
Windows), pinned by test_freeze_fails_when_nothing_suspendable.

All tests run on an in-memory FakeOs: nothing real is suspended.
"""
import pytest

from freezer.actuator import FreezeError, RealActuator
from freezer.contracts import ProcRef
from freezer.ledger import Ledger
from tests.test_actuator import FakeOs, FakeProc, snap

PID = 424241

# One mixed-case exe per deny category: proves case-insensitive matching.
DENY_CASES = [
    ("taskmgr", "TaskMgr.EXE"),              # SYSTEM
    ("defender", "NisSrv.exe"),              # SECURITY_SOFTWARE
    ("edr", "CSFalconService.exe"),          # SECURITY_SOFTWARE
    ("accessibility", "JFW.exe"),            # ACCESSIBILITY
    ("password-manager", "BitWarden.exe"),   # PASSWORD_MANAGERS
]


@pytest.mark.parametrize("exe", [c[1] for c in DENY_CASES],
                         ids=[c[0] for c in DENY_CASES])
def test_direct_freeze_refuses_deny_list_exe(exe):
    """Direct actuator.freeze() of a deny-list exe raises, suspends nothing."""
    fake = FakeOs([FakeProc(PID, exe=exe, ctime=0.0)])
    act = RealActuator(os_layer=fake, ledger=Ledger())
    with pytest.raises(FreezeError) as ei:
        act.freeze(snap("victim.exe", ProcRef(PID, 0.0)), "s")
    assert "refused" in str(ei.value)
    assert ei.value.entry is None  # refused before anything recorded
    assert fake.suspended == []  # nothing suspended, not even transiently
    assert Ledger().load() == {}


def test_direct_freeze_refuses_whole_app_when_tree_holds_denied_proc():
    """A denied process anywhere in the tree refuses the whole app (no half tree)."""
    fake = FakeOs([FakeProc(PID, exe="app.exe", ctime=0.0),
                   FakeProc(PID + 1, exe="KeePass.exe", ctime=0.0)])
    act = RealActuator(os_layer=fake, ledger=Ledger())
    with pytest.raises(FreezeError) as ei:
        act.freeze(snap("victim.exe", ProcRef(PID, 0.0), ProcRef(PID + 1, 0.0)), "s")
    assert ei.value.entry is None
    assert fake.suspended == []  # the innocent proc stays running too
    assert Ledger().load() == {}


def test_actuator_deny_set_matches_policy_lists():
    """One source of truth: the actuator sets derive from B's four exe lists."""
    from freezer import actuator, policy
    assert actuator.ACTUATOR_DENY_EXES == (
        policy.SYSTEM | policy.SECURITY_SOFTWARE
        | policy.ACCESSIBILITY | policy.PASSWORD_MANAGERS)
    assert actuator.ACTUATOR_REFUSE_EXES == (
        actuator.ACTUATOR_DENY_EXES - actuator.SYSTEM_EXES)
    # Overlap keeps its long-standing skip: svchost is expected in trees.
    assert "svchost.exe" not in actuator.ACTUATOR_REFUSE_EXES
    assert "taskmgr.exe" in actuator.ACTUATOR_REFUSE_EXES


# CLI path: `ff freeze` with an allow-all policy must still be stopped by the
# actuator backstop. The FakeOs exe carries the mixed case (the CLI lowercases
# only --app), proving the case-insensitivity lives in the actuator.
CLI_CASES = [
    ("defender-2", "mssense.exe", "MsSense.exe"),
    ("edr-2", "cb.exe", "CB.exe"),
    ("accessibility-2", "osk.exe", "Osk.exe"),
    ("accessibility-3", "nvda.exe", "NVDA.exe"),
    ("password-manager-2", "1password.exe", "1Password.exe"),
    ("password-manager-3", "keepass.exe", "KeePass.exe"),
]


@pytest.mark.parametrize("app_arg,exe",
                         [(c[1], c[2]) for c in CLI_CASES],
                         ids=[c[0] for c in CLI_CASES])
def test_cli_freeze_refuses_deny_list_exe(monkeypatch, capsys, app_arg, exe):
    """ff freeze --pids of a deny-list exe fails closed even when policy allows."""
    from freezer import cli
    from freezer.contracts import PolicyResult
    fake = FakeOs([FakeProc(PID, exe=exe, ctime=0.0)])
    monkeypatch.setattr(cli, "build_actuator",
                        lambda: RealActuator(os_layer=fake, ledger=Ledger()))
    rc = cli.main(["freeze", "--pids", str(PID), "--app", app_arg],
                  policy=lambda ids, snaps: PolicyResult(allowed=list(ids)))
    err = capsys.readouterr().err
    assert rc == 1
    assert "refused" in err
    assert fake.suspended == []
    assert Ledger().load() == {}
