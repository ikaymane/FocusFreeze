"""Safety policy: the hard deny-list between the planner and the actuator.

Pure function: no I/O, no syscalls. Everything the policy needs beyond the
snapshot arrives as parameters (session rules, extra PIDs), so tests inject
fakes and the agent loop keeps its 2-argument call shape.
"""
from __future__ import annotations

import os
from typing import Callable, Collection, Iterable

from freezer.contracts import AppSnapshot, Blocked, FocusSession, PolicyResult

# Inbox Windows processes the PC needs. taskmgr.exe is here on purpose: it is
# the user's escape hatch, freezing it strands everyone else.
SYSTEM = frozenset({
    "csrss.exe", "winlogon.exe", "wininit.exe", "services.exe", "lsass.exe",
    "smss.exe", "svchost.exe", "dwm.exe", "explorer.exe", "fontdrvhost.exe",
    "sihost.exe", "ctfmon.exe", "taskmgr.exe",
    # Inbox shell hosts: text input (touch keyboard, emoji, IME), UWP
    # hosting (freezing applicationframehost freezes every UWP app),
    # shell experience, start menu, search, lock screen.
    "textinputhost.exe", "applicationframehost.exe",
    "shellexperiencehost.exe", "startmenuexperiencehost.exe",
    "searchhost.exe", "lockapp.exe",
})

# Antivirus / EDR. MsMpEng, NisSrv and MsSense are Defender; the rest is a
# starter list — extend it when the team meets a new agent on the demo VM.
SECURITY_SOFTWARE = frozenset({
    "msmpeng.exe", "nissrv.exe", "mssense.exe", "securityhealthservice.exe",
    "csfalconservice.exe", "cb.exe",
})

# Screen readers, magnifier, on-screen keyboard. Freezing these strands users
# who navigate without a mouse.
ACCESSIBILITY = frozenset({
    "narrator.exe", "magnify.exe", "osk.exe", "nvda.exe", "jfw.exe",
})

# Unlocking the vault matters more than the RAM it sits in.
PASSWORD_MANAGERS = frozenset({
    "keepass.exe", "1password.exe", "bitwarden.exe",
    # Real exe names, checked against vendor/process listings: KeePassXC,
    # Dashlane, NordPass (+ background helper), Proton Pass, Enpass (+ helper).
    "keepassxc.exe", "dashlane.exe", "nordpass.exe",
    "nordpass-background-app.exe", "protonpass.exe", "enpass.exe",
    "enpasshelper.exe",
})

# Single source of truth for the actuator's last-line backstop: every exe
# basename the actuator must never suspend, however it was asked. The agent
# loop enforces these through filter(); the actuator re-checks them at
# freeze time so a direct actuator.freeze() (e.g. `ff freeze`) cannot
# bypass them. Additive only: filter() behaviour is unchanged. PROTECTED is
# deliberately excluded (pseudo-process names with no exe behind them), as
# is WORK_TOOLS_NO_AUTO (needs-card is not never-freeze).
ACTUATOR_DENY_EXES = SYSTEM | SECURITY_SOFTWARE | ACCESSIBILITY | PASSWORD_MANAGERS

# Critical pseudo-processes with no freezable exe behind them. Name list only:
# no OpenProcess / IsProcessCritical probing, so this stays pure and portable.
PROTECTED = frozenset({
    "system", "secure system", "registry", "memory compression",
})

# Every rule id filter() can emit. The consent card needs a BLOCK_REASONS
# entry for each one (see freezer.agent).
# Terminals and IDEs that must always go through a consent card, never
# auto-freeze: killing one can lose running work the sensor cannot see, and
# their titles are attacker-writable. C imports this after the merge; the
# agent loop keeps using its own copy until then (no behavior change here).
WORK_TOOLS_NO_AUTO = frozenset({"windowsterminal.exe", "code.exe", "studio64.exe"})


RULES = (
    "unknown_app", "self", "system_process", "security_software",
    "protected_process", "accessibility", "password_manager",
    "user_never_freeze", "user_keep", "elevated", "foreground", "plays_audio",
    "too_many",
)


def _rule(app_id: str, snap: AppSnapshot, *, never_freeze: Collection[str],
          keep: Collection[str], self_pids: Collection[int]) -> str | None:
    """First matching deny rule for one app, or None when it may freeze."""
    if snap is None:
        return "unknown_app"
    if any(p.pid in self_pids for p in snap.procs):
        return "self"
    if app_id in SYSTEM:
        return "system_process"
    if app_id in SECURITY_SOFTWARE:
        return "security_software"
    if app_id in PROTECTED:
        return "protected_process"
    if app_id in ACCESSIBILITY:
        return "accessibility"
    if app_id in PASSWORD_MANAGERS:
        return "password_manager"
    if app_id in never_freeze:
        return "user_never_freeze"
    if app_id in keep:
        return "user_keep"
    if snap.is_elevated:
        return "elevated"
    if snap.is_foreground:
        return "foreground"
    if snap.plays_audio:
        return "plays_audio"
    return None


def filter(freeze_ids: Iterable[str], snapshots: Iterable[AppSnapshot], *,
           never_freeze: Collection[str] = (),
           keep: Collection[str] = (),
           self_pids: Collection[int] | None = None) -> PolicyResult:
    """Split a planner-proposed freeze list into allowed + blocked-with-rule.

    never_freeze: app_ids (any case) the user protected in the active session.
    keep: app_ids (any case) the session always keeps.
    self_pids: PIDs that count as "us" — agent, watchdog, parent shell.
    Defaults to just this process, matching the old mock behavior.
    Cap: at most floor(0.8 * visible apps) may freeze per call (T6); the
    deny rules run first, so refused apps never consume cap budget, and the
    spillover drops from the end of the allowed list as "too_many".
    """
    by_id = {s.app_id.lower(): s for s in snapshots}
    denied = {str(a).lower() for a in never_freeze}
    kept = {str(a).lower() for a in keep}
    me = set(self_pids) if self_pids is not None else {os.getpid()}
    result = PolicyResult(allowed=[])
    for app_id in freeze_ids:
        key = app_id.lower()
        rule = _rule(key, by_id.get(key), never_freeze=denied, keep=kept,
                      self_pids=me)
        if rule is None:
            result.allowed.append(app_id)
        else:
            result.blocked.append(Blocked(app_id, rule))
    cap = int(len(by_id) * 0.8)
    if len(result.allowed) > cap:
        for app_id in result.allowed[cap:]:
            result.blocked.append(Blocked(app_id, "too_many"))
        del result.allowed[cap:]
    return result


def policy_for(session: FocusSession | None = None, *,
               self_pids: Collection[int] | None = None
               ) -> Callable[[list[str], list[AppSnapshot]], PolicyResult]:
    """A 2-argument policy closing over one session's never_freeze + keep lists.

    This is what the agent loop and `ff freeze` hold: same call shape as the
    mock, with the session's hard denies baked in.
    """
    never = list(session.never_freeze) if session else []
    keep = list(session.keep_rules) if session else []

    def policy(freeze_ids: list[str],
               snapshots: list[AppSnapshot]) -> PolicyResult:
        return filter(freeze_ids, snapshots, never_freeze=never, keep=keep,
                      self_pids=self_pids)

    return policy
