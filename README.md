# Focus Freeze

A Windows agent that understands what you're working on, freezes the apps you don't need (suspends them and pages their RAM to disk), and brings them back, with their state intact, when you say "I'm done".

Built for the Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026). Problem statement 1: **Build for Your World**.

**Meta models:** `muse-spark-1.3` (planning, tool calling), `muse-voice-transcribe-1.0` (voice commands).

**Video:** link added when uploaded.

## Why
On a 4 GB laptop, a normal day's apps fill the RAM and everything stutters. Closing apps
loses your place. An idle timer freezes the wrong things: the PDF you haven't touched in 40
minutes may be the spec you're working from. Focus Freeze asks Muse Spark which apps your
task needs, shows a reason for each one, and freezes nothing until you say yes.

- **Better than a timer:** 88/88 on a blind test set, vs 57% for an idle timer and 66% for a keyword table.
- **Hard to abuse:** 0 unsafe freezes in 270 attack runs against the real policy. The model never
  decides safety: a deny list runs after it, and every action goes into a tamper-evident log.
- **Cheap:** about $0.002 per plan.

**Real window titles are private by default.** Contributor models never receive them, and no
model does until `FF_PAID_BALANCE=1` confirms a paid Meta balance. Until then the agent runs in
simple mode (the idle rule).

## Team
Nassime Gharib (UI, voice, demo) · Aymane Idrissi Khamlichi (AI, sensor, policy) · Yassine Belaidi (systems: actuator, ledger, watchdog)

## Quick start
```
pip install -r requirements.txt
python -m pytest -q                                      # no API key needed
python -m freezer.agent "fixing the login bug" --scenario login_bug   # needs MODEL_API_KEY
python -m eval.run --offline                             # timer baseline, no API
python -m eval.redteam --offline                         # harness plumbing, no API
```

## Try the UI
```powershell
.\.venv\Scripts\python -m ui.app   # demo desk on mock parts, offline, gauge marked Simulated
```
Set `MODEL_API_KEY` for voice (push-to-talk: hold `Ctrl+Alt+Space` and speak) and for `--live-planner`.

## Run on real apps
`--live` suspends real apps, so try it with apps you don't mind freezing. Never run it as administrator: it refuses to start.
```powershell
$env:MODEL_API_KEY = "..."
$env:FF_PAID_BALANCE = "1"                    # needed for the AI: without it, the card uses the idle rule
$env:FF_HOME = "$env:TEMP\ff-live"            # a scratch folder for sessions, ledger and audit log
.\.venv\Scripts\python -m ui.app --live       # real sensor, policy, actuator; a watchdog thaws on crash
.\.venv\Scripts\python -m demo.live_check     # scripted check that freezes only a window it starts itself
```
Security claims and the tests behind them: [docs/threat-model.md](docs/threat-model.md).

## Repo map
| Path | What |
|---|---|
| [ui/](ui/) | Tray app, RAM gauge, consent and guardian cards, session picker, stats card |
| [freezer/voice.py](freezer/voice.py) | Push-to-talk, realtime transcription, command parsing |
| [freezer/agent.py](freezer/agent.py) | Agent loop: sensor, planner, policy, consent card, actuator |
| [demo/](demo/) | Shot list for the video, demo rig scripts, `live_check.py` |
| [plans/ram-freeze-agent.md](plans/ram-freeze-agent.md) | Full plan: feasibility test, evaluation, architecture, steps, budget, security |
| [plans/roles/](plans/roles/README.md) | Step-by-step guide for each of the 4 team roles |
| [freezer/contracts.py](freezer/contracts.py) | Shared types every role codes against |
| [freezer/planner.py](freezer/planner.py) | Muse Spark planner: injection-safe prompt, validation, heuristic fallback |
| [freezer/agent.py](freezer/agent.py) | Agent loop: sensor → planner → policy → consent card → actuator |
| [freezer/sessions.py](freezer/sessions.py), [freezer/cost.py](freezer/cost.py) | Focus sessions (user rules) and the spend cap |
| [freezer/mocks.py](freezer/mocks.py) | Stand-ins for A's and B's parts until integration day |
| [eval/](eval/) | Accuracy eval (`run.py`, `scenarios.json`, blind `holdout.json`: do not tune on it) and red-team (`redteam.py`, `attacks.json`) |
| [tools/freeze_test.ps1](tools/freeze_test.ps1) | Feasibility prototype: 800 MB process → 0 MB in 90 ms |

## License
[MIT](LICENSE)
