# Focus Freeze — threat model

What this app can do: suspend any process it can open, on the user's own
machine, driven by an LLM planner. This page lists what we trust, what can
go wrong, and which layer stops it. Every claim below is backed by a test
or a red-team run in this repo, not by intent.

## Trust boundaries

| # | Boundary | Rule |
|---|---|---|
| T1 | Window titles are attacker input | Titles are untrusted data: redacted before the model, never executed, injection attempts blocked with rule `injection` |
| T2 | The planner can be wrong or tricked | The planner proposes only; `freezer/policy.py` decides, and the agent re-checks on a fresh snapshot before freezing |
| T3 | The ledger must survive tampering | HMAC-SHA256 over entries (A); bad HMAC refuses writes, backup never shrinks |
| T4 | Frozen apps must always come back | Resume-all path, rollback on partial freeze, `thaw_all` works even in tamper mode |
| T5 | The user must stay in control | Consent card on every freeze; `never_freeze` / `keep` rules are hard denies; `thaw --all` always available |
| T6 | The agent must never freeze itself | Own PID blocked in policy, parent shell blocked in the agent loop, watchdog PID tracked |
| T7 | System, security and accessibility apps are off limits | Deny lists in policy with an actuator backstop; Task Manager stays usable as the escape hatch |
| T8 | No silent privilege use | Elevation is denied by policy; the actuator fails closed on access-denied instead of guessing |
| T9 | Someone must be able to check later | Every freeze / thaw / block lands in `audit.jsonl`; `ff verify-log` walks the hash chain |

## Abuse cases we tested

- Prompt injection in a window title (`msedge.exe` case): blocked, red-teamed (`social-03`, `social-06`, `social-08` all BLOCKED).
- Planner says freeze everything: per-call cap `floor(0.8 * N)` plus the cross-call 80% ceiling in the agent loop; over-budget apps are reported `too_many`, never dropped silently.
- App exits between card and freeze: re-check marks it `unknown_app`, skipped not failed; rollback resumes suspended siblings on partial failure.
- PID reuse: every freeze/thaw verifies process create time; a 2 s tolerance documents the residual risk.
- Ledger tampering: HMAC check refuses, `.bak` union restores, `verify-log` points at the edited line.

## Known limits (honest)

- Audio/network/elevation detection degrades gracefully when the OS will not answer; unknown elevation reads as elevated (blocked), unknown idle reads as recently used (left alone).
- The audit chain detects casual edits, not a full-file rewrite; keyed forgery protection lives in the ledger HMAC, not here.
- No protection against an administrator turning the tool itself off; physical access wins, as always.

## Mapping to code

- Policy: `freezer/policy.py` (`tests/test_policy.py`, 23 cases; `keep` rules land with `c/policy-keep`)
- Agent loop caps + consent: `freezer/agent.py` (`tests/test_agent.py`, `tests/test_cap_*.py`)
- Actuator + ledger: `freezer/actuator.py`, `freezer/ledger.py` (`tests/test_actuator.py`, `tests/test_audit_fixes.py`)
- Audit: `freezer/audit.py` + `ff verify-log` (`tests/test_audit_log.py`)
- Adversary suite: `eval/attacks.json` (45 attacks) + `eval/redteam.py`
