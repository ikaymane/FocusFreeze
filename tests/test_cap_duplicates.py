from freezer.agent import FocusAgent, block_reason
from freezer.contracts import AppSnapshot, PressureEvent, ProcRef
from freezer.mocks import MockActuator
from freezer.policy import filter as _real_filter
from tests.test_planner import FakeClient, all_decisions, call, reply


_PID = 424242  # never a real runner PID: policy never reports "self"


def _snap(app_id, **kw):
    args = dict(app_id=app_id, display_name=app_id,
                procs=[ProcRef(_PID, 1.0)], window_titles=[],
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
    act = actuator if actuator is not None else MockActuator()
    agent = FocusAgent(_Sensor(snaps), _real_filter, act,
                       lambda p: [d.app_id for d in p.to_freeze], client=client)
    return agent, act


def test_cap_case_twins_freeze_once():
    snaps = [_snap("STEAM.EXE"), _snap("Steam.exe"),
             _snap("app2.exe"), _snap("app3.exe"), _snap("app4.exe")]
    client = FakeClient(reply(call("freeze_apps", all_decisions(snaps, {"STEAM.EXE", "Steam.exe"}))))
    agent, act = _agent(snaps, client)
    out = agent.focus("doing things")
    assert [e.app_id for e in out.frozen] == ["STEAM.EXE"]  # plan order, first spelling
    assert [(b.app_id, b.rule) for b in out.skipped] == [("Steam.exe", "duplicate")]
    assert [e.app_id for e in act.frozen()] == ["STEAM.EXE"]  # one ledger entry, not two
    assert out.failed == []


def test_cap_ledger_twin_is_not_refrozen():
    snaps = [_snap(f"app{i}.exe") for i in range(10)]
    snaps[0] = _snap("app0.exe")
    act = MockActuator()
    act.freeze(_snap("APP0.EXE"), "cap")
    for s in snaps[1:8]:
        act.freeze(s, "cap")
    # The plan still wants the frozen apps frozen (no task-switch thaw).
    client = FakeClient(reply(call("freeze_apps", all_decisions(snaps, {s.app_id for s in snaps[:8]}))))
    agent, _ = _agent(snaps, client, actuator=act)
    out = agent.focus("doing things")
    assert out.thawed == []
    assert [e.app_id for e in out.frozen] == []
    assert [(b.app_id, b.rule) for b in out.skipped] == [("app0.exe", "duplicate")]
    assert len(act.frozen()) == 8  # no ninth entry for the twin


def test_cap_duplicate_has_card_words():
    assert block_reason("duplicate") == "Already being frozen"


def test_cap_twins_do_not_burn_rate_budget(monkeypatch):
    from freezer import agent as agent_mod
    monkeypatch.setattr(agent_mod, "MAX_FREEZES_PER_MIN", 1)
    snaps = [_snap("STEAM.EXE"), _snap("Steam.exe"),
             _snap("app2.exe"), _snap("app3.exe"), _snap("app4.exe")]
    client = FakeClient(reply(call("freeze_apps", all_decisions(snaps, {s.app_id for s in snaps}))))
    agent, act = _agent(snaps, client)
    out = agent.focus("doing things")
    # The real policy counts distinct-lower snapshots, so 5 rows with one
    # case-twin is a 4-app world: cap 3, and app3 spills with app4.
    assert [(b.app_id, b.rule) for b in out.proposal.blocked] == [
        ("app3.exe", "too_many"), ("app4.exe", "too_many")]
    assert [e.app_id for e in out.frozen] == ["STEAM.EXE"]
    assert [(b.app_id, b.rule) for b in out.skipped] == [
        ("Steam.exe", "duplicate"), ("app2.exe", "rate_limited")]
