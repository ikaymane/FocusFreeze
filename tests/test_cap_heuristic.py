"""Heuristic-fallback cap tests (side C/Muse).

Runs the agent loop against the REAL policy (freezer.policy.filter) with
FakeClient(RuntimeError('down')) so the planner falls back to the model
heuristic. Proves the total 80% ceiling in freezer/agent.py._execute holds
on the heuristic path too, and that the heuristic still never thaws.
"""
from freezer.agent import FocusAgent
from freezer.contracts import AppSnapshot, PressureEvent, ProcRef
from freezer.mocks import MockActuator
from freezer.policy import filter as real_filter
from tests.test_planner import FakeClient

_CAP_PID = 424242  # never a real test-runner PID: policy never reports "self"


def _snap(app_id, working_set_mb=100.0, last_focus_s=3600.0, **kw):
    args = dict(
        app_id=app_id,
        display_name=app_id,
        procs=[ProcRef(_CAP_PID, 1.0)],
        window_titles=[],
        working_set_mb=working_set_mb,
        last_focus_s=last_focus_s,
        is_foreground=False,
        plays_audio=False,
        is_elevated=False,
        has_network=False,
    )
    args.update(kw)
    return AppSnapshot(**args)


class _Sensor:
    def __init__(self, snaps):
        self._snaps = snaps

    def snapshot(self):
        return list(self._snaps)


def _agent(snaps, actuator=None):
    seen = []

    def consent(p):
        seen.append(p)
        return [d.app_id for d in p.to_freeze]

    act = actuator if actuator is not None else MockActuator()
    agent = FocusAgent(
        _Sensor(snaps), real_filter, act, consent,
        client=FakeClient(RuntimeError("down")),
    )
    return agent, act, seen


def test_heuristic_guardian_single_candidate_still_freezes():
    # (a) guardian path, 4-app world, 1 candidate: heuristic falls back but
    # the one idle+large candidate still freezes.
    snaps = [_snap("app0.exe", working_set_mb=500.0)]
    snaps += [_snap(f"app{i}.exe") for i in range(1, 4)]
    agent, act, seen = _agent(snaps)
    out = agent.on_pressure(
        PressureEvent(ram_pct=91, sustained_s=30, candidates=["app0.exe"])
    )
    assert out.proposal is not None
    assert out.proposal.plan.model == "heuristic"
    assert [e.app_id for e in out.frozen] == ["app0.exe"]
    assert out.skipped == []


def test_heuristic_focus_ninth_freeze_refused_as_too_many():
    # (b) focus path, 10 apps with 8 frozen: heuristic wants app0-app8 frozen
    # (app9 is small so it stays keep) but the ledger already holds 8/10, so
    # the budget is int(10*0.8)-8 == 0 and the 9th freeze is refused.
    snaps = [_snap(f"app{i}.exe", working_set_mb=500.0) for i in range(9)]
    snaps.append(_snap("app9.exe", working_set_mb=100.0))
    act = MockActuator()
    for s in snaps[:8]:
        act.freeze(s, "cap")
    agent, act, seen = _agent(snaps, actuator=act)
    out = agent.focus("doing things")
    assert out.proposal is not None
    assert out.proposal.plan.model == "heuristic"
    assert out.proposal.thaw == []
    assert out.thawed == []
    assert out.frozen == []
    assert out.failed == []
    assert [(b.app_id, b.rule) for b in out.skipped] == [("app8.exe", "too_many")]
    assert len(act.frozen()) == 8


def test_heuristic_keep_of_frozen_app_never_thaws():
    # (c) heuristic never thaws: app0 is frozen yet heuristic says keep for it
    # (small), and the agent still thaws nothing while the ceiling stays on.
    snaps = [_snap("app0.exe", working_set_mb=100.0)]
    snaps.append(_snap("app1.exe", working_set_mb=500.0))
    snaps += [_snap(f"app{i}.exe", working_set_mb=100.0) for i in range(2, 4)]
    act = MockActuator()
    act.freeze(snaps[0], "cap")
    agent, act, seen = _agent(snaps, actuator=act)
    out = agent.focus("doing things")
    assert out.proposal.plan.model == "heuristic"
    decisions = {d.app_id: d.action for d in out.proposal.plan.decisions}
    assert decisions["app0.exe"] == "keep"  # heuristic keeps it, yet no thaw
    assert out.proposal.thaw == []
    assert out.thawed == []
    assert [e.app_id for e in out.frozen] == ["app1.exe"]
    assert sorted(e.app_id for e in act.frozen()) == ["app0.exe", "app1.exe"]
    assert ("thaw", "app0.exe") not in act.log
