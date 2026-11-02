import os
from argparse import Namespace
from dataclasses import replace

from freezer.agent import FocusAgent
from freezer.cli import cmd_thaw
from freezer.contracts import AppSnapshot, ProcRef
from freezer.mocks import MockActuator, mock_policy
from freezer.policy import filter as _real_filter
from tests.test_planner import FakeClient, all_decisions, call, reply


_PID = 424242  # never a real runner PID


def _snap(app_id, pid=_PID, **kw):
    args = dict(app_id=app_id, display_name=app_id,
                procs=[ProcRef(pid, 1.0)], window_titles=[],
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


def _agent(sensor, policy, client, actuator=None, **kw):
    act = actuator if actuator is not None else MockActuator()
    seen = []
    agent = FocusAgent(sensor, policy, act,
                       lambda p: (seen.append(p), [d.app_id for d in p.to_freeze])[1],
                       client=client, **kw)
    return agent, act, seen


def test_backstop_parent_shell_blocked_at_propose():
    # The mock policy knows only the agent PID: the parent shell would sail
    # through without the agent-side backstop.
    snaps = [_snap("shell.exe", pid=os.getppid()), _snap("app1.exe")]
    sensor = _Sensor(snaps)
    client = FakeClient(reply(call("freeze_apps", all_decisions(snaps, {"shell.exe", "app1.exe"}))))
    agent, act, seen = _agent(sensor, mock_policy, client)
    out = agent.focus("doing things")
    assert ("shell.exe", "self") in [(b.app_id, b.rule) for b in seen[0].blocked]
    assert [e.app_id for e in out.frozen] == ["app1.exe"]
    assert "shell.exe" not in [e.app_id for e in act.frozen()]


def test_backstop_custom_self_pids():
    snaps = [_snap("shell.exe", pid=424242), _snap("app1.exe", pid=434343)]
    sensor = _Sensor(snaps)
    client = FakeClient(reply(call("freeze_apps", all_decisions(snaps, {"shell.exe", "app1.exe"}))))
    agent, act, seen = _agent(sensor, mock_policy, client, extra_self_pids={424242})
    out = agent.focus("doing things")
    assert ("shell.exe", "self") in [(b.app_id, b.rule) for b in seen[0].blocked]
    assert [e.app_id for e in out.frozen] == ["app1.exe"]


def test_backstop_shell_blocked_at_freeze_time():
    # Clean at propose time; the shell PID appears while the card is open.
    snaps = [_snap("victim.exe"), _snap("app1.exe")]
    sensor = _Sensor(snaps)
    client = FakeClient(reply(call("freeze_apps", all_decisions(snaps, {"victim.exe", "app1.exe"}))))

    def consent(p):
        sensor._snaps = [replace(s, procs=[ProcRef(os.getppid(), 1.0)])
                         if s.app_id == "victim.exe" else s for s in sensor._snaps]
        return [d.app_id for d in p.to_freeze]

    act = MockActuator()
    agent = FocusAgent(sensor, mock_policy, act, consent, client=client)
    out = agent.focus("doing things")
    assert [(b.app_id, b.rule) for b in out.skipped] == [("victim.exe", "self")]
    assert [e.app_id for e in out.frozen] == ["app1.exe"]
    assert out.failed == []


def test_backstop_failed_slot_backfilled_in_plan_order():
    snaps = [_snap(f"app{i}.exe") for i in range(10)]
    act = MockActuator()
    for s in snaps[:6]:
        act.freeze(s, "cap")
    # Plan keeps the frozen apps (no thaw) and wants 4 new ones; budget is 2.
    client = FakeClient(reply(call("freeze_apps", all_decisions(snaps, {s.app_id for s in snaps}))))
    agent, _, _ = _agent(_Sensor(snaps), _real_filter, client, actuator=act)
    real = act.freeze

    def flaky(app, session):
        if app.app_id == "app6.exe":
            raise OSError("access denied")
        return real(app, session)
    act.freeze = flaky
    out = agent.focus("doing things")
    assert out.thawed == []
    assert [e.app_id for e in out.frozen] == ["app7.exe", "app8.exe"]
    assert out.failed == ["app6.exe"]
    assert [(b.app_id, b.rule) for b in out.skipped] == [("app9.exe", "too_many")]


def test_backstop_failures_burn_rate_budget(monkeypatch):
    from freezer import agent as agent_mod
    monkeypatch.setattr(agent_mod, "MAX_FREEZES_PER_MIN", 1)
    snaps = [_snap("bad.exe"), _snap("good.exe")]

    def flaky(app, session):
        if app.app_id == "bad.exe":
            raise OSError("access denied")
        return real(app, session)

    act = MockActuator()
    real = act.freeze
    act.freeze = flaky
    client = FakeClient(reply(call("freeze_apps", all_decisions(snaps, {"bad.exe", "good.exe"}))),
                        reply(call("freeze_apps", all_decisions(snaps, {"bad.exe", "good.exe"}), 1)))
    agent, _, _ = _agent(_Sensor(snaps), mock_policy, client, actuator=act)
    out1 = agent.focus("doing things")
    assert out1.failed == ["bad.exe"]
    assert [(b.app_id, b.rule) for b in out1.skipped] == [("good.exe", "rate_limited")]
    assert len(agent._freeze_times) == 1
    out2 = agent.focus("doing things")
    assert out2.failed == [] and out2.frozen == []
    assert [(b.app_id, b.rule) for b in out2.skipped] == [
        ("bad.exe", "rate_limited"), ("good.exe", "rate_limited")]


def test_backstop_thaw_matches_freeze_case():
    act = MockActuator()
    act.freeze(_snap("steam.exe"), "s")
    assert cmd_thaw(Namespace(app_id="Steam.exe", all=False), act) == 0
    assert act.frozen() == []


def test_backstop_thaw_exact_still_works():
    act = MockActuator()
    act.freeze(_snap("Steam.exe"), "s")
    assert cmd_thaw(Namespace(app_id="Steam.exe", all=False), act) == 0
    assert act.frozen() == []
