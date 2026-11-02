# Focus Freeze: video script (draft 1)

Limit: 3:00. Team: mark anything that looks weak. Film only on the 4 GB machine, with real parts. The gauge's SIMULATED label must be gone from every shot.
Numbers in [brackets] are targets. Replace them with what the rig measures, and never narrate a number we did not measure.

| Time | On screen | Voiceover / spoken |
|---|---|---|
| 0:00–0:20 | Task Manager at [90]%, 12 apps open. The build in the terminal stutters. Gauge is red. | "This is an 8 GB laptop with a normal day's apps open. My build is crawling, and closing things means losing my place." |
| 0:20–0:50 | Hold the hotkey, speak. Card opens with reasons. Say "freeze". **Gauge drops from [90]% to [50]%.** | *Spoken to the app:* "I'm fixing the login bug." "Freeze." VO: "It read my task and my open apps, and told me why for each one. Nothing happens until I say yes." |
| 0:50–1:10 | Build runs fast, side-by-side timing. Zoom on the card's "Staying open" line for the PDF. | "The build is back to [X] seconds. And look at this PDF: untouched for 40 minutes. A timer would have frozen it. Focus Freeze kept it, because it's the OAuth spec for this bug." |
| 1:10–1:30 | The injection tab, title readable. Blocked section in red: Explorer and Defender. Terminal: `ff verify-log` passes. | "Window titles come from the web, so this page tries to order the agent to freeze Windows Defender. The model never decides safety: the deny-list runs after it, and every action goes in a tamper-evident log." |
| 1:30–1:50 | `demo/hog.ps1` runs. Gauge climbs to red. Wait 30 s (cut). Guardian card appears unprompted. | "When memory stays high, it offers help without being asked. It costs nothing while idle, because the model is only called at that moment." |
| 1:50–2:20 | "I'm done." Apps return. Open Word: **the unsaved text is still there**. Stats card. | *Spoken:* "I'm done." VO: "Everything comes back exactly as I left it, including a document I never saved. It closed nothing: it froze them." |
| 2:20–2:50 | Architecture diagram, then cost per call. | "Muse Spark plans with tool calling, Muse Voice Transcribe handles speech. About [one] cent per plan, [0.3] cents per minute of voice. If the agent crashes, a watchdog thaws everything." |
| 2:50–3:00 | Name, team, repo link. | "Focus Freeze. Free up your RAM and your mind." |

## Needs from the team
- **A:** `freed_mb` and restore time on the rig. Is the watchdog line true by recording day?
- **B:** final injection title for `demo/injection.html`. `ff verify-log` on screen. The real policy must block what this script claims.
- **C:** check every reason shown on the card. Measured cost per call.

## Weak spots to test in rehearsal
1. The 0:50 "fast build" is only convincing if the first build truly stutters. Time both on the rig.
2. The PDF must really be kept by the live planner. If it is not, fix the prompt or change the scene. Do not fake it.
3. Whether the live planner proposes freezing Explorer and Defender at all is out of our hands. If it obeys nothing, the blocked section stays empty, which is a good result but a weak shot. The honest fallback: show `eval.redteam` results, or ask for a focus task with Defender in the guardian's candidates.
4. Voice is push-to-talk, so "no keyboard" is not strictly true. Either say "one hotkey" or switch to `ENDPOINTING` mode.

## Rig
The dev laptop runs **Windows 11 Home, which has no Hyper-V**. Options, best first:
1. A teammate's Windows Pro machine with a 4 GB Hyper-V VM, as planned.
2. VirtualBox with a 4 GB Windows 11 VM on this laptop.
3. Limit this laptop's RAM: `bcdedit /set {current} truncatememory 4294967296` in an admin shell, then reboot. Undo with `bcdedit /deletevalue {current} truncatememory`, then reboot.

Steps:
1. Run `demo/setup.ps1`. Put a reference PDF at `demo/oauth-spec.pdf` first.
2. Check the gauge reads above 85% with everything open. If not, open more tabs.
3. `demo/hog.ps1` is only for the guardian scene.
4. Do three full rehearsals, timing each scene. Then record two clean takes with OBS at 1080p.
