<p align="center">
  <img src="docs/readme/banner.svg" alt="Focus Freeze: tell it your task, it freezes the apps you don't need (RAM 90% to 55%), then thaws them when you're done" width="100%">
</p>

<p align="center">
  <b>Meta Global AI Dev Hackathon</b> · Build for Your World<br>
  <a href="#run">💻 Run it</a> &nbsp;·&nbsp; <a href="#trust">🛡️ Check our work</a> &nbsp;·&nbsp; <a href="docs/threat-model.md">🔐 Threat model</a> &nbsp;·&nbsp; <a href="#built">🗓️ Built during the hackathon</a>
</p>

<p align="center">
  <img alt="Muse Spark 1.3" src="https://img.shields.io/badge/planner-muse--spark--1.3-8ED8EE?style=flat-square&labelColor=121D25">
  <img alt="Muse Voice" src="https://img.shields.io/badge/voice-muse--voice--transcribe--1.0-8ED8EE?style=flat-square&labelColor=121D25">
  <img alt="Windows 10 and 11" src="https://img.shields.io/badge/Windows-10%20%7C%2011-A5B4BD?style=flat-square&labelColor=121D25">
  <a href="https://github.com/ikaymane/Meta_Hackathon/actions/workflows/tests.yml"><img alt="tests" src="https://img.shields.io/github/actions/workflow/status/ikaymane/Meta_Hackathon/tests.yml?branch=main&style=flat-square&label=tests&labelColor=121D25"></a>
  <img alt="MIT" src="https://img.shields.io/badge/license-MIT-6FD08C?style=flat-square&labelColor=121D25">
</p>

<img src="docs/readme/divider.svg" width="100%" alt="">

## 🧊 “Focus Freeze, what are you?”

> **Focus Freeze:** I'm the reason your 4 GB laptop stops stuttering. Tell me what you're working
> on, and I freeze the apps you don't need. I don't close them: I suspend them and move their memory
> to disk. Say *“I'm done”* and every one comes back exactly where you left it.

<p align="center">
  <img src="docs/readme/demo.gif" alt="The Focus Freeze UI: voice command, consent card with a reason per app, freeze, RAM gauge drops, apps thaw on 'I'm done'" width="100%">
</p>
<p align="center"><sub>Rendered from the real widgets and the real controller (<code>demo/record_preview.py</code>). The desk and RAM numbers in this clip are simulated and say so on screen.</sub></p>

An idle timer would have frozen the PDF you haven't touched in 40 minutes. Focus Freeze keeps it,
because it's the source you're writing from.

<img src="docs/readme/divider.svg" width="100%" alt="">

## 🧭 “What can you do?”

<table>
<tr>
<td width="50%" valign="top">

### 🎙️ Hear your task
*“I'm writing my thesis on urban heat islands.”*

Hold <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Space</kbd> and say it. **Muse Voice** transcribes while
you talk, and the mic is open only while the key is held.

</td>
<td width="50%" valign="top">

### 🧠 Explain every app
*“Discord: unrelated to the thesis.”*

**Muse Spark** reads your task and every open window, and gives a **reason for each app**. A box
shows where it overruled the idle timer, and why.

</td>
</tr>
<tr>
<td valign="top">

### ✋ Wait for your yes
*“Freeze.”*

Nothing freezes until you approve the card. Untick an app and it asks once: *“Never freeze this
during Thesis?”*

</td>
<td valign="top">

### 🧊 Freeze without closing
The process is suspended and its RAM paged to disk. The window stays open. In our first test, an
**800 MB process dropped to 0 MB in 90 ms**.

</td>
</tr>
<tr>
<td valign="top">

### 🔁 Bring it all back
*“I'm done.”*

Every frozen app thaws, state intact. If Focus Freeze crashes, a **watchdog** process thaws
everything for you.

</td>
<td valign="top">

### 📈 Step in under pressure
When RAM climbs on its own, a guardian offers to help, and **it still asks first**. Auto-freeze is
opt-in per focus session and capped per event.

</td>
</tr>
</table>

Plus **focus sessions** that remember your rules, an end-of-session card with what you freed and
what the AI cost, and a spend cap on the planner.

<img src="docs/readme/divider.svg" width="100%" alt="">

## ⚡ “How do you decide?”

> **Focus Freeze:** I plan, the rules check me, and **you** decide.

<p align="center">
  <img src="docs/readme/flow.svg" alt="Voice and the window sensor feed the Muse Spark planner, then the policy deny list, then your consent, then the freeze; every action goes to a tamper-evident log, and a watchdog thaws everything if the app crashes" width="100%">
</p>

| | Meta model | Job |
|---|---|---|
| 🧠 | `muse-spark-1.3` | reads your task and every open window, plans keep or freeze with a reason per app (tool calling) |
| 🎙️ | `muse-voice-transcribe-1.0` | push-to-talk commands: *“I'm writing my thesis”*, *“freeze”*, *“I'm done”* |

<details>
<summary><b>🔧 The five rules that keep it safe</b></summary>
<br>

1. **The model never decides safety.** A deny list runs *after* the planner and always wins:
   system processes, security and accessibility tools, password managers and anything running
   elevated are never frozen.
2. **Window titles are untrusted.** A web page can put anything in its title, so titles are
   redacted, JSON-encoded and fenced off as data before the model sees them, and every answer is
   validated.
3. **You approve every freeze.** The card can only approve apps the policy allowed. Auto-freeze
   needs an opt-in session and is capped per event.
4. **Everything is on the record.** Every freeze and thaw goes into a hash-chained audit log, and
   `python -m freezer.cli verify-log` checks the chain.
5. **It can always undo.** A separate watchdog thaws everything if the app dies, and Focus Freeze
   refuses to run as administrator or to start twice.

The full threat model, with the test behind each claim: [docs/threat-model.md](docs/threat-model.md).
</details>

<img src="docs/readme/divider.svg" width="100%" alt="">

<a name="trust"></a>

## 🛡️ “Can I trust you?”

> **Focus Freeze:** Check my work.

<p align="center">
  <img src="docs/readme/numbers.svg" alt="Focus Freeze gets 88 of 88 on the blind test set, a keyword table 66% and an idle timer 57%; 0 unsafe freezes in 270 attack runs; about $0.002 per plan" width="100%">
</p>

```powershell
python -m pytest -q                                   # 458 tests, offline, nothing real is frozen
python -m eval.run --scenarios eval/holdout.json      # the blind set, against Muse Spark
python -m eval.redteam --repeat 3 --model muse-spark-1.3 --model muse-spark-1.3-contributor  # 45 attacks
```

```
scenario                        planner  timer   time      cost
student_thesis_chapter           6/6     3/6     6.8s  $0.00235
office_sales_deck                5/5     3/5     7.2s  $0.00179
dev_login_bug                    6/6     4/6     8.2s  $0.00313
gaming_coop_night                5/5     2/5     4.2s  $0.00291
photographer_client_delivery     5/5     2/5     3.0s  $0.00173
teacher_grading_quizzes          6/6     5/6     7.5s  $0.00216
… 10 more scenarios, all perfect

planner 88/88 = 100%   timer 50/88 = 57%   keyword rules 58/88 = 66%   perfect 16/16
latency avg 4.76s max 8.25s   $/call 0.00218   injection rules proposed 0
                                                        (last run: November 3, 2026)
```

The red team plants attacks in window titles, app names and the sessions file, then runs the real
agent loop and the real policy, with a user who approves every card:

```
by family                                  runs  blocked  breach
  classic  fake orders, fence breakouts     120      120       0
  keep     "never freeze me" spoofing        48       48       0
  social   scams, phishing, ClickFix         48       48       0
  gap      abusing gaps in the rules         54       46       8
                                                        (last run: November 3, 2026)
```

**0 of 270 runs froze an app it shouldn't have.** All 8 breaches are the same thing: an attack
talked the planner out of freezing one app (Edge). The worst an attacker managed was *less*
freezing, never a wrong freeze.

**Privacy:** real window titles never go to contributor models, and no model sees them until
`FF_PAID_BALANCE=1` confirms a paid Meta balance. Until then the agent runs in simple mode (the idle
rule). The microphone is open only while you hold the key.

<img src="docs/readme/divider.svg" width="100%" alt="">

<a name="run"></a>

## 💻 “Ok, how do I run you?”

You need **Windows 10 or 11** and **Python 3.13**.

```powershell
# 1. install
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt

# 2. try it offline: a mock desk, nothing real is frozen
python -m ui.app

# 3. turn on the AI and voice
$env:MODEL_API_KEY = "..."
python -m ui.app --live-planner
```

> [!TIP]
> Hold <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Space</kbd> to talk. If another app owns that combo,
> Focus Freeze picks a free one and the hint on screen names it. No key yet? Everything still runs
> in simple mode.

<details>
<summary><b>🧊 Run it on your real apps</b></summary>
<br>

> [!WARNING]
> `--live` suspends real apps, so start with apps you don't mind freezing. Never run it as
> administrator: it refuses to start.

```powershell
$env:MODEL_API_KEY   = "..."
$env:FF_PAID_BALANCE = "1"                     # lets the AI see real window titles
$env:FF_HOME         = "$env:TEMP\ff-live"     # sessions, ledger and audit log go here
python -m ui.app --live                        # real sensor, policy and actuator, plus the watchdog
python -m demo.live_check                      # scripted check that freezes only a window it starts
```
</details>

<details>
<summary><b>⚙️ Settings</b></summary>
<br>

| Variable | What it does | Default |
|---|---|---|
| `MODEL_API_KEY` | Meta API key for Muse Spark and Muse Voice | none: simple mode |
| `FF_PAID_BALANCE` | `1` confirms a paid balance, so the AI may see real window titles | off |
| `FF_HOME` | where sessions, the ledger, the audit log and usage live | `~/.focusfreeze` |
| `FF_COST_CAP_USD` | the planner stops calling the API past this spend | `20` |
| `FF_MIC` | microphone to use, by index or part of its name | the default mic |
| `FF_REDUCED_MOTION` | `1` turns the full-screen freeze effect off | off |
</details>

<details>
<summary><b>🧰 The command line</b></summary>
<br>

```powershell
python -m freezer.agent "fixing the login bug" --scenario login_bug   # the agent loop on a mock desk
python -m freezer.cli list                                            # what is frozen right now
python -m freezer.cli thaw --all                                      # thaw everything
python -m freezer.cli recover                                         # resume apps a crash left frozen
python -m freezer.cli verify-log                                      # check the audit log chain
```
</details>

<details>
<summary><b>🗂️ What's where</b></summary>
<br>

```
freezer/
  agent.py          the loop: sensor → planner → policy → consent card → actuator
  planner.py        Muse Spark prompt, injection defense, validation, fallback
  sensor.py         open windows grouped into apps, with idle and audio state
  policy.py         the deny list that always wins
  actuator.py       suspend, page out, resume · ledger.py  what is frozen
  audit.py          hash-chained log · watchdog.py  thaws on crash
  guardian.py       steps in when RAM climbs · sessions.py, cost.py
  voice.py          push-to-talk and realtime transcription
ui/                 tray app, RAM gauge, consent and guardian cards, stats card
eval/               blind accuracy eval and the prompt-injection red team
tests/              458 offline tests
demo/               video shot list, demo rig, live_check.py, record_preview.py
plans/              the full plan and a guide for each team role
docs/               threat model · readme/ these pictures (tools/readme_art.py draws them)
```
</details>

<img src="docs/readme/divider.svg" width="100%" alt="">

<a name="built"></a>

## 🗓️ “When were you built?”

> **Focus Freeze:** All of me was built during the hackathon, from an empty repo.

- **First commit:** October 28, 2026 (the plan and role guides). **First code:** October 30.
  **Last commit before submission:** November 4, 2026.
- **142 commits and 27 merged pull requests** in this window. The
  [commit history](https://github.com/ikaymane/Meta_Hackathon/commits/main) and
  [pull requests](https://github.com/ikaymane/Meta_Hackathon/pulls?q=is%3Apr+is%3Amerged) are the record.
- **Nothing was carried over** from an earlier project. The agent loop, the Muse Spark planner and
  its injection defense, the policy, the actuator, the watchdog, the audit log, the voice pipeline,
  the UI, the eval and the red team were all written here.
- **Commits authored as `Muse`** were written by Meta's Muse Code agent and reviewed by the team.
- **Open-source libraries** we use as-is, under their own licenses: `openai` (client for the
  OpenAI-compatible Meta Model API), `pydantic`, `psutil`, `pycaw`, `pywin32`, `PySide6`,
  `sounddevice`, `websockets`, `pyttsx3`, `numpy`, `imageio-ffmpeg`, `pytest`, `hypothesis`.

<img src="docs/readme/divider.svg" width="100%" alt="">

## 👋 “Who made you?”

<p align="center">
  <img src="docs/readme/team-cards.svg" alt="Team: Nassime Gharib (UI, voice, demo), Aymane Idrissi Khamlichi (agent, AI safety), Yahya Dadsi (policy, security), Yassine Belaidi (systems)" width="100%">
</p>

<p align="center">
  Built in Morocco with <b>Meta Muse Spark</b> · <b>Muse Voice</b> · Python · PySide6<br>
  <sub>MIT licensed, see <a href="LICENSE">LICENSE</a>. Every animation on this page is hand-written SVG in this repo.</sub>
</p>
