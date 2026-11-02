"""Compat pin: omitting policy_snaps behaves exactly as passing snaps explicitly.

Covers FocusAgent.propose() on the user path (source="user") and the
guardian path (source="guardian"), comparing proposal.to_freeze/blocked
for a fixed FakeClient reply. Synthetic data only; no real API calls.
"""

from freezer.agent import FocusAgent
from freezer.contracts import AppSnapshot, ProcRef
from freezer.mocks import MockActuator
from freezer.policy import filter as real_filter
from tests.test_planner import FakeClient, all_decisions, call, reply

_PID = 424242  # never a real test-runner PID: policy never reports "self"
_SELF_PIDS = {999999}


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


def _agent(snaps, decisions, policy):
    client = FakeClient(
        reply(call("freeze_apps", decisions)),
        reply(call("freeze_apps", decisions, 1)),
    )
    agent = FocusAgent(
        _Sensor(snaps), policy, MockActuator(), lambda p: [], client=client
    )
    return agent


def _recording_policy(seen):
    def policy(ids, snapshots):
        seen.append([s.app_id for s in snapshots])
        return real_filter(ids, snapshots, self_pids=_SELF_PIDS)

    return policy


def _check_equal(a, b):
    assert [d.app_id for d in a.to_freeze] == [d.app_id for d in b.to_freeze]
    assert [(x.app_id, x.rule) for x in a.blocked] == [
        (x.app_id, x.rule) for x in b.blocked
    ]


def test_compat_default_equals_explicit_user_path():
    snaps = [_snap(f"app{i}.exe") for i in range(5)]
    decisions = all_decisions(snaps, {s.app_id for s in snaps})
    seen = []
    agent = _agent(snaps, decisions, _recording_policy(seen))
    default = agent.propose("doing things", snaps, None)
    explicit = agent.propose("doing things", snaps, None, policy_snaps=list(snaps))
    _check_equal(default, explicit)
    assert seen[0] == seen[1] == [s.app_id for s in snaps]
    assert len(default.to_freeze) == 4  # floor(0.8 * 5): the cap bites, not vacuous
    assert [(b.app_id, b.rule) for b in default.blocked] == [
        (snaps[4].app_id, "too_many")
    ]


def test_compat_default_equals_explicit_guardian_path():
    snaps = [_snap(f"app{i}.exe") for i in range(5)]
    cands = [s.app_id for s in snaps]
    decisions = all_decisions(snaps, set(cands))
    seen = []
    agent = _agent(snaps, decisions, _recording_policy(seen))
    default = agent.propose(
        "doing things", snaps, None, source="guardian", candidates=cands
    )
    explicit = agent.propose(
        "doing things",
        snaps,
        None,
        source="guardian",
        candidates=cands,
        policy_snaps=list(snaps),
    )
    _check_equal(default, explicit)
    assert seen[0] == seen[1] == [s.app_id for s in snaps]
    assert len(default.to_freeze) == 4  # floor(0.8 * 5): the cap bites, not vacuous
    assert [(b.app_id, b.rule) for b in default.blocked] == [
        (snaps[4].app_id, "too_many")
    ]
