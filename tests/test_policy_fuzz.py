"""Property tests for the policy caps (B spec step 8: fuzz, 1000 calls).

Real filter: allowed count and too_many accounting hold for every random
world. Mock policy: random inputs never crash and always partition.
"""
import math

from hypothesis import given, settings
from hypothesis import strategies as st

from freezer.contracts import AppSnapshot, ProcRef
from freezer.mocks import mock_policy
from freezer.policy import filter as real_filter


NAMES = ["app%d.exe" % i for i in range(16)] + [
    "explorer.exe", "spotify.exe", "code.exe", "steam.exe",
    "keepass.exe", "osk.exe", "taskmgr.exe",
]
PIDS = [101, 102, 103, 999999]


def _snap(app_id, pid, fg=False, audio=False, elevated=False):
    return AppSnapshot(app_id=app_id, display_name=app_id,
                       procs=[ProcRef(pid, 1.0)], window_titles=["t"],
                       working_set_mb=100.0, last_focus_s=3600.0,
                       is_foreground=fg, plays_audio=audio,
                       is_elevated=elevated, has_network=False)


snap_strategy = st.builds(
    _snap,
    app_id=st.sampled_from(NAMES),
    pid=st.sampled_from(PIDS),
    fg=st.booleans(), audio=st.booleans(), elevated=st.booleans(),
)


@given(st.lists(snap_strategy, min_size=0, max_size=12, unique_by=lambda s: s.app_id))
@settings(max_examples=200)
def test_cap_never_exceeded(snaps):
    ids = [s.app_id for s in snaps]
    v = real_filter(ids, snaps, self_pids={999999})
    assert len(v.allowed) <= math.floor(0.8 * len(snaps))


@given(st.lists(snap_strategy, min_size=0, max_size=12, unique_by=lambda s: s.app_id))
@settings(max_examples=200)
def test_denied_apps_use_no_budget(snaps):
    ids = [s.app_id for s in snaps]
    v = real_filter(ids, snaps, self_pids={999999})
    allowed, blocked = v.allowed, {b.app_id: b.rule for b in v.blocked}
    denied = [a for a in ids if a in blocked and blocked[a] != "too_many"]
    eligible = [a for a in ids if a not in denied]
    cap = math.floor(0.8 * len(snaps))
    assert len(allowed) == min(len(eligible), cap)
    assert set(allowed) <= set(eligible)
    for a in ids:
        if a not in allowed and a not in denied:
            assert blocked[a] == "too_many"


@given(st.lists(st.text(min_size=1, max_size=30), min_size=0, max_size=10),
       st.lists(snap_strategy, min_size=0, max_size=10))
@settings(max_examples=200, deadline=None)
def test_mock_policy_partitions_without_crashing(ids, snaps):
    snaps = list({s.app_id: s for s in snaps}.values())
    v = mock_policy(ids, snaps)
    allowed, blocked = set(v.allowed), {b.app_id for b in v.blocked}
    assert allowed.isdisjoint(blocked)
    assert allowed | blocked <= set(ids) | {s.app_id for s in snaps}
