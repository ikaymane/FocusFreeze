"""Tests for the real safety policy (role B). One test per deny rule, plus the
no-bypass proof: planner output — user path and guardian path — always goes
through policy before anything freezes.
"""
import os

from freezer.agent import FocusAgent
from freezer.contracts import AppSnapshot, FocusSession, ProcRef
from freezer.mocks import MockActuator
from freezer.policy import RULES, filter, policy_for
from tests.test_planner import FakeClient, all_decisions, call, reply

PID = 4242


def snap(app_id, **kw):
    args = dict(app_id=app_id, display_name=app_id, procs=[ProcRef(PID, 1.0)],
                window_titles=[], working_set_mb=100.0, last_focus_s=3600.0,
                is_foreground=False, plays_audio=False, is_elevated=False,
                has_network=False)
    args.update(kw)
    return AppSnapshot(**args)


def verdict(app_id, **kw):
    never = kw.pop("never_freeze", ())
    pids = kw.pop("self_pids", {999999})
    # A filler snapshot keeps the 80% cap (floor) off this single verdict.
    snaps = [snap(app_id, **kw), snap("filler.exe")]
    return filter([app_id], snaps, never_freeze=never,
                  self_pids=pids)


def rule_of(app_id, **kw):
    v = verdict(app_id, **kw)
    assert app_id not in v.allowed, f"{app_id} should be blocked"
    assert len(v.blocked) == 1
    return v.blocked[0].rule


def test_normal_app_is_allowed():
    v = verdict("spotify.exe")
    assert v.allowed == ["spotify.exe"] and v.blocked == []


def test_unknown_app_blocked():
    v = filter(["ghost.exe"], [snap("spotify.exe")], self_pids={999999})
    assert v.allowed == [] and v.blocked[0].rule == "unknown_app"


def test_system_processes_blocked():
    for exe in ("explorer.exe", "dwm.exe", "svchost.exe", "taskmgr.exe"):
        assert rule_of(exe) == "system_process", exe


def test_self_blocked_by_own_pid():
    v = filter(["whatever.exe"], [snap("whatever.exe",
                                       procs=[ProcRef(os.getpid(), 1.0)])])
    assert v.blocked[0].rule == "self"


def test_self_covers_injected_pids():
    assert rule_of("code.exe", self_pids={PID}) == "self"


def test_elevated_foreground_audio_blocked():
    assert rule_of("app.exe", is_elevated=True) == "elevated"
    assert rule_of("app.exe", is_foreground=True) == "foreground"
    assert rule_of("app.exe", plays_audio=True) == "plays_audio"


def test_security_software_blocked():
    for exe in ("msmpeng.exe", "nissrv.exe", "securityhealthservice.exe"):
        assert rule_of(exe) == "security_software", exe


def test_accessibility_apps_blocked():
    for exe in ("narrator.exe", "magnify.exe", "osk.exe", "nvda.exe"):
        assert rule_of(exe) == "accessibility", exe


def test_password_managers_blocked():
    for exe in ("keepass.exe", "1password.exe", "bitwarden.exe"):
        assert rule_of(exe) == "password_manager", exe


def test_protected_processes_blocked():
    assert rule_of("system") == "protected_process"


def test_user_never_freeze_is_a_hard_deny():
    assert rule_of("spotify.exe", never_freeze=["Spotify.exe"]) == \
        "user_never_freeze"


def test_policy_for_bakes_in_session_rules():
    session = FocusSession(name="thesis", task="t", keep_rules=[],
                           never_freeze=["zotero.exe"])
    v = policy_for(session, self_pids={999999})(["zotero.exe"],
                                                [snap("zotero.exe")])
    assert v.allowed == [] and v.blocked[0].rule == "user_never_freeze"


def test_first_matching_rule_wins():
    assert rule_of("explorer.exe", plays_audio=True) == "system_process"


def test_every_rule_has_a_card_label():
    from freezer.agent import BLOCK_REASONS, block_reason
    for rule in RULES:
        assert rule in BLOCK_REASONS, f"no card label for {rule}"
        assert block_reason(rule) != "Protected by a safety rule"


def test_every_emitted_rule_is_a_known_id():
    apps = ["explorer.exe", "msmpeng.exe", "narrator.exe", "keepass.exe",
            "system", "ghost.exe"]
    snaps = [snap(a) for a in apps if a != "ghost.exe"]
    v = filter(apps, snaps, never_freeze=["spotify.exe"],
               self_pids={999999})
    assert v.allowed == []
    assert {b.rule for b in v.blocked} <= set(RULES)


# ---- no bypass: planner output always goes through policy -------------------

class FakeSensor:
    def __init__(self, snaps):
        self._snaps = snaps

    def snapshot(self):
        return list(self._snaps)


def venture_stack():
    """One freezable app next to three policy-blocked ones."""
    return [snap("steam.exe"),
            snap("explorer.exe"),
            snap("msmpeng.exe"),
            snap("zotero.exe")]


def agent_for(snaps, session=None):
    policy = policy_for(session, self_pids={999999})
    act = MockActuator()
    agent = FocusAgent(FakeSensor(snaps), policy, act,
                       lambda p: [d.app_id for d in p.to_freeze],
                       client=FakeClient(reply(call(
                           "freeze_apps",
                           all_decisions(snaps, {s.app_id for s in snaps})))))

    return agent, act


def test_planner_cannot_bypass_policy_on_user_path():
    # Session withheld from the planner, so nothing coerces the model's
    # freeze of zotero to keep: the policy backstop must catch it.
    snaps = venture_stack()
    session = FocusSession(name="thesis", task="writing", keep_rules=[],
                           never_freeze=["zotero.exe"])
    agent, _ = agent_for(snaps, session)
    proposal = agent.propose("writing my thesis", snaps, None)
    assert [d.app_id for d in proposal.to_freeze] == ["steam.exe"]
    assert {b.app_id: b.rule for b in proposal.blocked} == {
        "explorer.exe": "system_process",
        "msmpeng.exe": "security_software",
        "zotero.exe": "user_never_freeze"}


def test_planner_cannot_bypass_policy_on_guardian_path():
    from freezer.contracts import PressureEvent
    snaps = venture_stack()
    agent, act = agent_for(snaps)
    event = PressureEvent(ram_pct=91.0, sustained_s=30.0,
                          candidates=[s.app_id for s in snaps])
    out = agent.on_pressure(event)
    assert [e.app_id for e in out.frozen] == ["steam.exe", "zotero.exe"]
    assert {b.app_id: b.rule for b in out.proposal.blocked} == {
        "explorer.exe": "system_process",
        "msmpeng.exe": "security_software"}
    assert all(a != "explorer.exe" and a != "msmpeng.exe"
               for _, a in act.log)


def _plain(i):
    return snap(f"app{i}.exe")


def test_cap_allows_eight_of_ten():
    snaps = [_plain(i) for i in range(10)]
    v = filter([s.app_id for s in snaps], snaps, self_pids={999999})
    assert v.allowed == [s.app_id for s in snaps[:8]]
    assert [(b.app_id, b.rule) for b in v.blocked] == [
        (s.app_id, "too_many") for s in snaps[8:]]


def test_cap_five_apps():
    snaps = [_plain(i) for i in range(5)]
    v = filter([s.app_id for s in snaps], snaps, self_pids={999999})
    assert len(v.allowed) == 4 and len(v.blocked) == 1
    assert v.blocked[0].rule == "too_many"


def test_cap_single_app_blocked():
    v = filter(["solo.exe"], [snap("solo.exe")], self_pids={999999})
    assert v.allowed == []
    assert [(b.app_id, b.rule) for b in v.blocked] == [("solo.exe", "too_many")]


def test_cap_empty_list():
    v = filter([], [], self_pids={999999})
    assert v.allowed == [] and v.blocked == []


def test_cap_applies_after_deny_rules():
    snaps = [_plain(i) for i in range(10)] + [snap("explorer.exe")]
    v = filter([s.app_id for s in snaps], snaps, self_pids={999999})
    assert [b.app_id for b in v.blocked
            if b.rule == "system_process"] == ["explorer.exe"]
    assert len(v.allowed) == 8  # floor(0.8 * 11); refused apps use no budget
    assert [b.rule for b in v.blocked
            if b.app_id != "explorer.exe"] == ["too_many"] * 2
