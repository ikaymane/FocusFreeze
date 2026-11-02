"""Sequential guardian stress: the 80% total ceiling holds across calls.

Side C (branch cap/t2-sequence): a 10-app world driven through six
successive on_pressure guardian calls, each targeting new unfrozen apps,
plus a seventh call once the ceiling is reached. Every call uses a fresh
FakeClient reply and an approve-all consent, against the real
freezer.policy.filter and MockActuator. After every call the frozen total
must stay within floor(0.8 * 10) = 8, and every approved-but-unfrozen app
must show up in Outcome.skipped with rule "too_many" (never silently
dropped, never failed).
"""

from freezer.agent import FocusAgent
from freezer.contracts import AppSnapshot, PressureEvent, ProcRef
from freezer.mocks import MockActuator
from freezer.policy import filter as real_filter
from tests.test_planner import FakeClient, all_decisions, call, reply

_SEQ_PID = 424242  # never the test-runner PID: the policy never reports "self"
_SEQ_RAM_PCT = 91.0


def _seq_snap(app_id):
    """One idle, freezable app snapshot built locally (no scenario file)."""
    return AppSnapshot(
        app_id=app_id,
        display_name=app_id,
        procs=[ProcRef(_SEQ_PID, 1.0)],
        window_titles=[],
        working_set_mb=100.0,
        last_focus_s=3600.0,
        is_foreground=False,
        plays_audio=False,
        is_elevated=False,
        has_network=False,
    )


class _SeqSensor:
    """Serves a fixed 10-app snapshot list (deep copy not needed: read-only)."""

    def __init__(self, snaps):
        self._snaps = snaps

    def snapshot(self):
        return list(self._snaps)


def _seq_replies(snaps, groups):
    """One fresh freeze-everything reply per guardian call, in plan order."""
    by_id = {s.app_id: s for s in snaps}
    return [
        reply(call("freeze_apps", all_decisions([by_id[a] for a in group], set(group)), i))
        for i, group in enumerate(groups)
    ]


def _assert_no_silent_drop(call_no, out, actuator):
    """Approved apps are either frozen now or skipped as too_many."""
    assert out.proposal is not None, f"call {call_no}: guardian skipped, expected a plan"
    assert out.failed == [], f"call {call_no}: unexpected actuator failures"
    assert len(actuator.frozen()) <= 8, f"call {call_no}: froze past the 80% ceiling"
    approved = [d.app_id for d in out.proposal.to_freeze]
    frozen_ids = {e.app_id for e in out.frozen}
    skipped = {(b.app_id, b.rule) for b in out.skipped}
    assert {r for _, r in skipped} <= {"too_many"}, f"call {call_no}: unexpected skip rules"
    for app_id in approved:
        assert app_id in frozen_ids or (app_id, "too_many") in skipped, (
            f"call {call_no}: {app_id} approved but neither frozen nor skipped as too_many"
        )
    return approved


def test_cap_sequential_guardian_calls_hold_eighty_percent():
    snaps = [_seq_snap(f"app{i}.exe") for i in range(10)]
    groups = [
        ["app0.exe", "app1.exe"],
        ["app2.exe", "app3.exe"],
        ["app4.exe", "app5.exe"],
        ["app6.exe", "app7.exe"],
        ["app8.exe"],
        ["app9.exe"],
    ]
    seventh = ["app8.exe", "app9.exe"]

    def consent(p):
        return [d.app_id for d in p.to_freeze]

    actuator = MockActuator()
    agent = FocusAgent(
        _SeqSensor(snaps), real_filter, actuator, consent,
        client=FakeClient(*_seq_replies(snaps, groups + [seventh])),
    )

    for n, group in enumerate(groups):
        out = agent.on_pressure(
            PressureEvent(ram_pct=_SEQ_RAM_PCT, sustained_s=30, candidates=list(group))
        )
        _assert_no_silent_drop(n, out, actuator)

    # The first eight targets filled the ceiling; calls 5-6 froze nothing new.
    assert {e.app_id for e in actuator.frozen()} == {f"app{i}.exe" for i in range(8)}

    # Seventh call: everything still eligible, yet nothing new may freeze.
    before = {e.app_id for e in actuator.frozen()}
    out7 = agent.on_pressure(
        PressureEvent(ram_pct=_SEQ_RAM_PCT, sustained_s=30, candidates=list(seventh))
    )
    assert [e.app_id for e in out7.frozen] == []
    assert {e.app_id for e in actuator.frozen()} == before
    _assert_no_silent_drop(6, out7, actuator)
