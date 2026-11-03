# Focus Freeze: shot list (final)

Runtime target **2:20** (limit 3:00). One loop, filmed for real on the 4 GB machine:
task → card → freeze → proof → `ff verify-log` → done → restore.
Numbers in [brackets] are read off the rig during the take. Never narrate one we did not measure.

| # | Time | On screen | Spoken / voiceover |
|---|---|---|---|
| 1 | 0:00–0:12 | Desktop with the demo apps open. Task Manager → Memory at [~90]%. Gauge top right, amber/red, no "Simulated" label. | VO: "This is a 4 GB laptop with a normal day's apps open. Memory is at [90] percent, and closing things means losing my place." |
| 2 | 0:12–0:20 | Hold Ctrl+Alt+Space. Voice bar shows the live transcript. | *Spoken:* "I'm writing my thesis on urban heat islands." |
| 3 | 0:20–0:45 | Consent card. Slow pan: Discord, Steam, Teams, Slack to freeze, each with its reason. Then hold on the **"Where the AI beat the idle timer"** box above the buttons: "Idle timer would freeze Adobe Acrobat Reader · AI keeps it: ...". | VO: "Muse Spark read my task and every open window, and gave a reason for each app. A 20-minute idle timer would have frozen my reference PDF. The AI keeps it, because I need it. Nothing happens until I say yes." *Spoken:* "Freeze." |
| 4 | 0:45–1:00 | The freeze effect, then the gauge number rolls from [90] to [55]%. The "freed this session" counter climbs. | VO: "[1.4] gigabytes back in [one] second." |
| 5 | 1:00–1:12 | Task Manager → Details tab, Status column: discord.exe, steam.exe and others show **Suspended**. | VO: "They're not closed. They're frozen: zero CPU, and their memory is free to reclaim." |
| 6 | 1:12–1:27 | Terminal: `python -m freezer.cli verify-log` → `audit log ok: [N] entries`. | VO: "The model never decides safety. A deny list runs after it, and every action goes into a tamper-evident log." |
| 7 | 1:27–1:50 | *Spoken:* "I'm done." The apps return. Click Word: **the unsaved text is still there**. Stats card counts up. | VO: "Everything comes back exactly as I left it, including a document I never saved." |
| 8 | 1:50–2:10 | Architecture slide: sensor → Muse Spark planner → policy → actuator, plus the watchdog. Cost line. | VO: "Muse Spark plans, Muse Voice Transcribe hears me. About $0.002 per plan. If the app crashes, a watchdog process thaws everything within [two] seconds." |
| 9 | 2:10–2:20 | Name, team, repo URL. | VO: "Focus Freeze. Free up your RAM and your mind." |

**Cut first if long:** shot 5. **Add only if the take is short (+20 s):** the guardian scene (`demo/hog.ps1`, card appears unprompted). It needs the prep below.

## Before each take (film machine)
1. `git pull`, then `.\.venv\Scripts\pip install -r requirements.txt`, then `python -m pytest tests -q`: all green.
2. `$env:MODEL_API_KEY` set, and `$env:FF_PAID_BALANCE = "1"` once someone confirms the Meta balance is paid. **Without the key, the hotkey replays scripted lines. Without the flag, real titles never reach Muse Spark and the card runs on the simple idle rule. Never film either way.**
3. `$env:FF_HOME = (New-Item -ItemType Directory "$env:TEMP\ff-take-$(Get-Date -f HHmmss)").FullName`: a fresh folder per take, so no real sessions are touched.
4. `powershell -File demo/setup.ps1`. Type a line in Word and **do not save**.
5. `python -m ui.app --live`. Do not run it as administrator: it refuses to start.
6. Discord, Steam, Teams and Slack: demo accounts only, no private chats visible.
7. Click Terminal or VS Code last, so no distraction app is in the foreground. Policy never freezes the app in use.
8. Guardian scene only: after step 5, click each distraction once, then leave them alone for **5+ minutes**. The idle tracker starts empty, and apps it has never seen count as in use.

## Known limits (do not claim otherwise on camera)
- Windows Defender has no window, so it is never a candidate and never shows on the card: no Defender shot. Only Explorer can appear as "BLOCKED", and only if the planner proposes it.
- The "Where the AI beat the idle timer" box only shows what this take's plan really disagreed on. If the PDF is not in it, do not narrate the PDF line: retake, or say what the box shows.
- Restoring an app brings its window to the front. Film the guardian scene before "I'm done".
- Voice is push-to-talk: call it "one hotkey".

## Measured on the dev box (15 GB, stub plan, the check's own window)
`python -m demo.live_check` (in the repo; prints each time): card 2.3–2.7 s after the request (the real planner adds its own latency), freeze 1.3–1.8 s, restore 0.04–0.08 s, and the watchdog thawed the window after each hard crash. 4/4 runs green on Nov 3. These are not for narration: re-measure on the film machine for shots 4, 7 and 8.
