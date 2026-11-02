"""Thaw-accounting tests for the 80% total ceiling (side C/Muse, branch cap/t4-thaw-churn).

Uses the real freezer.policy.filter with MockActuator and FakeClient.
Covers: thaw frees budget, churn never exceeds 8, done() resets budget.
"""
from freezer.agent import FocusAgent
from freezer.contracts import AppSnapshot, ProcRef
from freezer.mocks import MockActuator
from freezer.policy import filter as real_filter
from tests.test_planner import FakeClient, all_decisions, call, reply

_PID = 424242  # never a real test-runner PID: policy never reports "self"


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


def _make_agent(snaps, client, actuator=None, approve=None):
    seen = []

    def consent(p):
        seen.append(p)
        ids = [d.app_id for d in p.to_freeze]
        return approve(ids) if approve else ids

    act = actuator if actuator is not None else MockActuator()
    agent = FocusAgent(_Sensor(snaps), real_filter, act, consent, client=client)
    return agent, act, seen


def test_thaw_frees_budget_for_new_freezes():
    snaps = [_snap(f"app{i}.exe") for i in range(10)]
    first_freeze = {f"app{i}.exe" for i in range(8)}
    # Second plan: keep app0/app1 (they thaw via task-switch),
    # keep freezing app2-app7 (they stay), freeze app8/app9 (new).
    second_freeze = {f"app{i}.exe" for i in range(2, 10)}
    client = FakeClient(
        reply(call("freeze_apps", all_decisions(snaps, first_freeze))),
        reply(call("freeze_apps", all_decisions(snaps, second_freeze), 1)),
    )
    agent, act, _ = _make_agent(snaps, client)
    out1 = agent.focus("doing things")
    assert {e.app_id for e in out1.frozen} == first_freeze
    assert len(act.frozen()) == 8
    out2 = agent.focus("doing other things")
    assert set(out2.thawed) == {"app0.exe", "app1.exe"}
    assert {e.app_id for e in out2.frozen} == {"app8.exe", "app9.exe"}
    assert out2.failed == []
    assert out2.skipped == []
    assert sorted(e.app_id for e in act.frozen()) == sorted(second_freeze)
    assert len(act.frozen()) == 8


def test_churn_attack_never_exceeds_eighty_percent():
    snaps = [_snap(f"app{i}.exe") for i in range(10)]
    # Each round freezes one new disjoint pair while keeping prior frozen apps frozen.
    rounds = [{f"app{i}.exe" for i in range(2 * (r + 1))} for r in range(5)]
    client = FakeClient(*[
        reply(call("freeze_apps", all_decisions(snaps, freeze), i))
        for i, freeze in enumerate(rounds)
    ])
    agent, act, _ = _make_agent(snaps, client)
    sizes = []
    outs = []
    for r in range(5):
        out = agent.focus(f"churn round {r}")
        outs.append(out)
        sizes.append(len(act.frozen()))
        assert sizes[-1] <= 8, f"round {r} exceeded cap: {sizes[-1]}"
        assert out.failed == []
    assert sizes == [2, 4, 6, 8, 8]
    assert {e.app_id for e in act.frozen()} == {f"app{i}.exe" for i in range(8)}
    last = outs[-1]
    assert [e.app_id for e in last.frozen] == []
    assert sorted(b.app_id for b in last.skipped if b.rule == "too_many") == ["app8.exe", "app9.exe"]


def test_done_thaw_allows_refreeze_up_to_eight():
    snaps = [_snap(f"app{i}.exe") for i in range(10)]
    first_freeze = {f"app{i}.exe" for i in range(8)}
    client1 = FakeClient(reply(call("freeze_apps", all_decisions(snaps, first_freeze))))
    agent1, act, _ = _make_agent(snaps, client1)
    out1 = agent1.focus("doing things")
    assert len(out1.frozen) == 8
    assert len(act.frozen()) == 8
    done_ids = agent1.done()
    assert sorted(done_ids) == sorted(first_freeze)
    assert act.frozen() == []
    # Refreeze-all: try all 10, the cap allows 8 again.
    all_ids = {s.app_id for s in snaps}
    client2 = FakeClient(reply(call("freeze_apps", all_decisions(snaps, all_ids))))
    agent2, _, _ = _make_agent(snaps, client2, actuator=act)
    out2 = agent2.focus("doing things again")
    assert len(out2.frozen) == 8
    assert len(act.frozen()) == 8
    assert out2.failed == []
    leftovers = [b for b in list(out2.proposal.blocked) + list(out2.skipped) if b.rule == "too_many"]
    assert len(leftovers) == 2
    assert {e.app_id for e in out2.frozen} | {b.app_id for b in leftovers} == all_ids
