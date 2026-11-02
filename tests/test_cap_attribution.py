"""Attribution: exact skipped rules in plan order when both limiters bite (side C).

Runs the agent loop against the real freezer.policy.filter with MockActuator.
(a) propose-time per-call cap (floor(0.8 * N)) plus the rolling rate limit;
(b) the cross-call total ceiling (80% of all apps minus the ledger) with history.
"""
from freezer.agent import FocusAgent
from freezer.contracts import AppSnapshot, ProcRef
from freezer.mocks import MockActuator
from freezer.policy import filter as real_filter
from tests.test_planner import FakeClient, all_decisions, call, reply

_PID = 424242  # never a real test-runner PID: the policy never reports "self"


def _snap(app_id, **kw):
    args = dict(app_id=app_id, display_name=app_id,
                procs=[ProcRef(_PID, 1.0)],
                window_titles=[],
                working_set_mb=100.0, last_focus_s=3600.0,
                is_foreground=False, plays_audio=False, is_elevated=False,
                has_network=False)
    args.update(kw)
    return AppSnapshot(**args)


class _Sensor:
    def __init__(self, snaps):
        self._snaps = snaps

    def snapshot(self):
        return list(self._snaps)


def _agent(snaps, client, actuator=None):
    seen = []

    def consent(p):
        seen.append(p)
        return [d.app_id for d in p.to_freeze]

    act = actuator if actuator is not None else MockActuator()
    return FocusAgent(_Sensor(snaps), real_filter, act, consent, client=client), act, seen


def test_propose_cap_and_rate_limit_keep_plan_order(monkeypatch):
    from freezer import agent as agent_mod
    monkeypatch.setattr(agent_mod, "MAX_FREEZES_PER_MIN", 2)
    snaps = [_snap(f"app{i}.exe") for i in range(10)]
    want = {f"app{i}.exe" for i in range(9)}  # plan freezes 9 of 10, none frozen yet
    client = FakeClient(reply(call("freeze_apps", all_decisions(snaps, want))))
    agent, act, seen = _agent(snaps, client)
    out = agent.focus("doing things")
    # Per-call cap floor(0.8 * 10) = 8: the 9th freeze is refused at propose time.
    assert [(b.app_id, b.rule) for b in out.proposal.blocked] == [("app8.exe", "too_many")]
    assert "app8.exe" not in [b.app_id for b in out.skipped]
    # Rolling rate limit 2 applies in plan order; over-limit approvals are skipped.
    assert [d.app_id for d in out.proposal.to_freeze] == [f"app{i}.exe" for i in range(8)]
    assert [e.app_id for e in out.frozen] == [d.app_id for d in out.proposal.to_freeze[:2]]
    assert [e.app_id for e in out.frozen] == ["app0.exe", "app1.exe"]
    assert [(b.app_id, b.rule) for b in out.skipped] == [
        (f"app{i}.exe", "rate_limited") for i in range(2, 8)]
    assert out.failed == []


def test_total_ceiling_with_ledger_history_keeps_plan_order(monkeypatch):
    from freezer import agent as agent_mod
    monkeypatch.setattr(agent_mod, "MAX_FREEZES_PER_MIN", 10)
    snaps = [_snap(f"app{i}.exe") for i in range(10)]
    act = MockActuator()
    for s in snaps[:6]:
        act.freeze(s, "cap")
    # The plan still wants the 6 frozen apps frozen (so no task-switch thaw),
    # plus 4 new ones; the ceiling int(10 * 0.8) - 6 = 2 lets 2 more through.
    client = FakeClient(reply(call("freeze_apps", all_decisions(snaps, {s.app_id for s in snaps}))))
    agent, _, seen = _agent(snaps, client, actuator=act)
    out = agent.focus("doing things")
    assert out.thawed == []
    assert out.proposal.blocked == []
    assert [d.app_id for d in out.proposal.to_freeze] == [f"app{i}.exe" for i in range(6, 10)]
    assert [e.app_id for e in out.frozen] == ["app6.exe", "app7.exe"]
    assert [(b.app_id, b.rule) for b in out.skipped] == [("app8.exe", "too_many"),
                                                        ("app9.exe", "too_many")]
    assert out.failed == []
