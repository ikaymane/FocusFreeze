"""Spend-cap x 80%-ceiling interplay (side C/Muse).

With the AI budget exhausted the planner falls back to the heuristic, which
wants to freeze every large idle app. The agent loop must still enforce the
80% total ceiling, surface the fallback reason on the proposal, and keep the
usage log inside the isolated FF_HOME.

Runs against the REAL policy (freezer.policy.filter), never the mock;
FakeClient only proves the planner made no API call. MockActuator keeps the
ledger in memory, so no freeze touches a real process.
"""

from pathlib import Path

from freezer import cost
from freezer.agent import FocusAgent
from freezer.contracts import AppSnapshot, ProcRef
from freezer.mocks import MockActuator
from freezer.policy import filter as real_filter
from tests.test_planner import FakeClient

_SPEND_PID = 424242  # never the test-runner PID: the policy never reports "self"


def _spend_snap(app_id):
    return AppSnapshot(
        app_id=app_id,
        display_name=app_id,
        procs=[ProcRef(_SPEND_PID, 1.0)],
        window_titles=[],
        working_set_mb=500.0,  # heuristic freezes: above SIZE_FREEZE_MB (200)
        last_focus_s=3600.0,  # heuristic freezes: above IDLE_FREEZE_S (20 min)
        is_foreground=False,
        plays_audio=False,
        is_elevated=False,
        has_network=False,
    )


class _SpendSensor:
    def __init__(self, snaps):
        self._snaps = snaps

    def snapshot(self):
        return list(self._snaps)


def _spend_agent(snaps, client, approve=None, actuator=None):
    seen = []

    def consent(p):
        seen.append(p)
        ids = [d.app_id for d in p.to_freeze]
        return approve(ids) if approve else ids

    act = actuator if actuator is not None else MockActuator()
    return FocusAgent(_SpendSensor(snaps), real_filter, act, consent, client=client), act, seen


def _exhaust_budget(monkeypatch, cap="0.001"):
    monkeypatch.setenv("FF_COST_CAP_USD", cap)
    cost.record("muse-spark-1.3", 3000, 500, 0, 1.0)  # ~$0.006, over a $0.001 cap
    assert cost.over_cap()


def test_spend_cap_fallback_still_enforces_total_ceiling(monkeypatch, isolated_home):
    # (a) Budget exhausted, so the heuristic wants all 3 remaining apps, but 7
    # of 10 are already frozen: the total ceiling allows exactly 1 more (80%).
    _exhaust_budget(monkeypatch)
    snaps = [_spend_snap(f"app{i}.exe") for i in range(10)]
    act = MockActuator()
    for s in snaps[:7]:
        act.freeze(s, "cap")
    client = FakeClient()  # would raise IndexError if the planner called the API
    agent, act, seen = _spend_agent(snaps, client, actuator=act)
    out = agent.focus("doing things")  # approve-all consent, never crashes
    assert seen and seen[0].plan.model == "heuristic"
    assert client.requests == []
    assert [e.app_id for e in out.frozen] == ["app7.exe"]  # plan order kept
    assert [(b.app_id, b.rule) for b in out.skipped] == [
        ("app8.exe", "too_many"), ("app9.exe", "too_many")]
    assert out.failed == [] and out.thawed == [] and out.unticked == []
    assert len(act.frozen()) == 8  # exactly 80%: over-budget is skipped, never silent


def test_spend_cap_fallback_reason_surfaces_while_caps_hold(monkeypatch, isolated_home):
    # (b) Zero cap falls back before any API call; the card still says why,
    # and the per-call policy cap holds: floor(0.8 * 5) = 4 freeze, 1 refused.
    monkeypatch.setenv("FF_COST_CAP_USD", "0")
    snaps = [_spend_snap(f"app{i}.exe") for i in range(5)]
    client = FakeClient()
    agent, act, seen = _spend_agent(snaps, client)
    out = agent.focus("doing things")
    assert client.requests == []
    proposal = seen[0]
    assert proposal.plan.model == "heuristic"
    assert proposal.fallback_reason is not None and "spend cap" in proposal.fallback_reason
    assert proposal.fallback_message.startswith("Simple mode:") and "budget" in proposal.fallback_message
    assert [e.app_id for e in out.frozen] == [f"app{i}.exe" for i in range(4)]
    leftovers = [b for b in list(proposal.blocked) + list(out.skipped) if b.rule == "too_many"]
    assert len(leftovers) == 1 and leftovers[0].app_id == "app4.exe"
    assert out.failed == []


def test_spend_cap_usage_log_stays_inside_isolated_home(monkeypatch, tmp_path, isolated_home):
    # (c) Every spend-cap write lands in the isolated FF_HOME; nothing leaks
    # into the repo or the real ~/.focusfreeze.
    _exhaust_budget(monkeypatch)
    assert cost.home() == isolated_home
    assert cost.usage_path().parent == isolated_home
    assert str(isolated_home).startswith(str(tmp_path))
    real_log = Path.home() / ".focusfreeze" / "usage.jsonl"
    before = real_log.read_bytes() if real_log.exists() else None
    snaps = [_spend_snap(f"app{i}.exe") for i in range(5)]
    agent, act, seen = _spend_agent(snaps, FakeClient())
    out = agent.focus("doing things")
    assert seen[0].plan.model == "heuristic"  # the fallback path was taken
    assert [e.app_id for e in out.frozen] == [f"app{i}.exe" for i in range(4)]
    log_path = isolated_home / "usage.jsonl"
    assert log_path.exists() and log_path.stat().st_size > 0
    repo_root = Path(__file__).resolve().parents[1]
    assert not (repo_root / "usage.jsonl").exists()
    assert list(repo_root.glob("usage*.jsonl")) == []
    assert list(repo_root.glob("ledger*.json")) == []
    after = real_log.read_bytes() if real_log.exists() else None
    assert after == before  # the real home log is untouched
