"""Counting edge cases for the total 80% freeze ceiling (side C/Muse).

Covers freezer/agent.py _execute on branch cap/t1-edges: already = lowercase
ledger app_ids, total = lowercase fresh-snapshot ids UNION already,
budget = max(0, int(len(total) * MAX_FROZEN_FRACTION) - len(already));
plan order kept; over-budget approvals land in Outcome.skipped as
Blocked(app, "too_many"), never silent, never failed.

Drives FocusAgent with the real freezer.policy.filter and MockActuator.
Snaps are synthetic AppSnapshot/ProcRef rows (PID 424242, idle 3600s,
not foreground); FakeClient/all_decisions/call/reply come from
tests/test_planner.py. No real API calls.
"""
from freezer.agent import FocusAgent
from freezer.contracts import AppSnapshot, ProcRef
from freezer.mocks import MockActuator
from freezer.policy import filter as real_filter
from tests.test_planner import FakeClient, all_decisions, call, reply

_PID = 424242  # never a real test-runner PID: policy never reports "self"


def _snap(app_id):
    return AppSnapshot(
        app_id=app_id,
        display_name=app_id,
        procs=[ProcRef(_PID, 1.0)],
        window_titles=[],
        working_set_mb=100.0,
        last_focus_s=3600.0,
        is_foreground=False,
        plays_audio=False,
        is_elevated=False,
        has_network=False,
    )


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


def test_cap_union_counts_case_insensitively():
    # (a) Ledger holds APP0.EXE uppercase while the snapshot lists app0.exe
    # lowercase plus 9 more apps; 7 more of those are frozen too. Lowercased
    # union counts 10 distinct apps, already counts 8, budget is 0, so app8/app9
    # are refused as too_many; app0.exe is a case-twin of a ledger entry, so it
    # is reported as duplicate (never silent/failed).
    snaps = [_snap("app%d.exe" % i) for i in range(10)]
    act = MockActuator()
    act.freeze(_snap("APP0.EXE"), "cap")
    for s in snaps[1:8]:
        act.freeze(s, "cap")
    assert len(act.frozen()) == 8
    client = FakeClient(reply(call("freeze_apps", all_decisions(snaps, {s.app_id for s in snaps}))))
    agent, act, seen = _agent(snaps, client, actuator=act)
    out = agent.focus("doing things")
    already = {e.app_id.lower() for e in act.frozen()}
    total = {s.app_id.lower() for s in snaps} | already
    assert len(already) == 8 and len(total) == 10
    assert max(0, int(len(total) * 0.8) - len(already)) == 0
    assert out.thawed == []
    assert [e.app_id for e in out.frozen] == []
    assert out.failed == []
    assert out.proposal.blocked == []
    assert [(b.app_id, b.rule) for b in out.skipped] == [
        ("app0.exe", "duplicate"),
        ("app8.exe", "too_many"),
        ("app9.exe", "too_many"),
    ]


def test_cap_six_app_world_freezes_at_most_four():
    # (b) 6-app world, none frozen, plan freezes 5: floor(6 * 0.8) = 4, so at
    # most 4 freeze and the leftover is reported as too_many, never silent.
    snaps = [_snap("app%d.exe" % i) for i in range(6)]
    want = {"app%d.exe" % i for i in range(5)}
    client = FakeClient(reply(call("freeze_apps", all_decisions(snaps, want))))
    agent, act, seen = _agent(snaps, client)
    out = agent.focus("doing things")
    assert [e.app_id for e in out.frozen] == ["app0.exe", "app1.exe", "app2.exe", "app3.exe"]
    leftovers = [b for b in list(out.proposal.blocked) + list(out.skipped) if b.rule == "too_many"]
    assert [(b.app_id, b.rule) for b in leftovers] == [("app4.exe", "too_many")]
    assert {e.app_id for e in out.frozen} | {b.app_id for b in leftovers} == want
    assert out.failed == []


def test_cap_fifth_app_skipped_when_four_frozen():
    # (c) 5-app world, 4 already frozen and the plan still wants them frozen
    # (so no task-switch thaw) plus a 5th: int(5 * 0.8) - 4 = 0, so nothing
    # new freezes and the 5th lands in Outcome.skipped as (app, too_many).
    snaps = [_snap("app%d.exe" % i) for i in range(5)]
    act = MockActuator()
    for s in snaps[:4]:
        act.freeze(s, "cap")
    client = FakeClient(reply(call("freeze_apps", all_decisions(snaps, {s.app_id for s in snaps}))))
    agent, act, seen = _agent(snaps, client, actuator=act)
    out = agent.focus("doing things")
    assert out.thawed == []
    assert [e.app_id for e in out.frozen] == []
    assert out.failed == []
    assert [(b.app_id, b.rule) for b in out.skipped] == [("app4.exe", "too_many")]
    assert out.unticked == []


def test_cap_mixed_case_ledger_still_skips_fifth():
    # (d) Case-variant of (c): same 5-app shape with mixed-case ids in both
    # the snapshot and the ledger. Lowercased union still counts 5 distinct,
    # already still counts 4, budget is still 0, and the 5th still lands in
    # Outcome.skipped as (app, too_many) with its snapshot case preserved.
    ids = ["App0.exe", "App1.exe", "App2.exe", "App3.exe", "App4.exe"]
    snaps = [_snap(i) for i in ids]
    act = MockActuator()
    for s in snaps[:4]:
        act.freeze(s, "cap")
    client = FakeClient(reply(call("freeze_apps", all_decisions(snaps, set(ids)))))
    agent, act, seen = _agent(snaps, client, actuator=act)
    out = agent.focus("doing things")
    already = {e.app_id.lower() for e in act.frozen()}
    total = {s.app_id.lower() for s in snaps} | already
    assert len(already) == 4 and len(total) == 5
    assert out.thawed == []
    assert [e.app_id for e in out.frozen] == []
    assert out.failed == []
    assert [(b.app_id, b.rule) for b in out.skipped] == [("App4.exe", "too_many")]
    assert out.unticked == []
