import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtWidgets import QApplication, QLabel
from shiboken6 import isValid

from freezer import agent as agent_module
from freezer import sessions
from freezer.guardian import Guardian, GuardianConfig
from ui import cards, fx, mocks
from ui.app import Controller
from ui.consent import ConsentCard, rule_words
from ui.fx import MotionOverlay
from ui.gauge import Gauge, Ram
from ui.guardian import GuardianCard
from ui.sessions import SessionPicker, ago
from ui.stats import Stats, StatsCard
from ui.voicebar import VoiceBar

ALLOWED = {"discord.exe", "steam.exe", "ms-teams.exe", "slack.exe"}


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def mock_planner(monkeypatch):
    monkeypatch.setattr(agent_module, "plan", mocks.mock_plan)
    monkeypatch.setattr(mocks, "PLAN_DELAY_S", 0)
    monkeypatch.setattr(mocks, "plan_gate", None)
    monkeypatch.setattr(mocks, "fallback_reason", None)


def make_ctl(**kw):
    actuator = mocks.SlowActuator(0, 0)
    return Controller(mocks.DeskSensor(), mocks.mock_policy, actuator, read_ram=lambda: mocks.ram_for(actuator), **kw)


@pytest.fixture
def ctl(qapp):
    c = make_ctl()
    yield c
    c.shutdown()


def wait_until(qapp, cond, timeout=5.0):
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "timed out"
        qapp.processEvents()
        time.sleep(0.005)
    qapp.processEvents()


def frozen(ctl):
    return {e.app_id for e in ctl.actuator.frozen()}


def card_texts(card):
    return [w.text() for w in card.findChildren(QLabel)]


def row(card, app_id):
    return next(r for r in card.rows if r.app_id == app_id)


def open_login_card(ctl, qapp):
    sessions.start("login bug", mocks.LOGIN_TASK)
    ctl.handle_transcript("I'm fixing the login bug")
    wait_until(qapp, lambda: isinstance(ctl.card, ConsentCard))
    return ctl.card


def test_mock_ram_lands_exactly_on_the_spec():
    a = mocks.SlowActuator(0, 0)
    assert round(mocks.ram_for(a).pct, 1) == 91.3
    for snap in mocks.DESK:
        if snap.app_id in ALLOWED:
            a.freeze(snap, "")
    assert round(mocks.ram_for(a).pct, 1) == 22.9
    assert sum(e.freed_mb for e in a.frozen()) == 2700


def test_card_shows_decisions_blocked_reasons_and_total(ctl, qapp):
    card = open_login_card(ctl, qapp)
    texts = card_texts(card)
    assert {r.app_id for r in card.rows} == ALLOWED
    assert card.width() == 640 and card.height() == 560
    assert card.heading.text() == mocks.LOGIN_TASK
    assert card.total.text() == "~2.6 GB to free"
    assert "explorer.exe — BLOCKED: Protected process" in texts
    assert "msedge.exe — BLOCKED: Injection attempt in title — blocked" in texts
    assert "spotify.exe — BLOCKED: Playing audio" in texts
    assert "code.exe — BLOCKED: Currently in use" in texts
    assert any("a timer would freeze this" in t for t in texts)
    assert any("may disconnect" in t for t in texts)
    assert card.blocked_box.parent() is card.frame   # pinned, never scrolled away
    card.cancel()
    wait_until(qapp, lambda: not ctl.busy)
    assert not frozen(ctl)


def test_all_text_is_filmable_size_and_plain(ctl, qapp):
    card = open_login_card(ctl, qapp)
    for w in card.findChildren(QLabel):
        assert w.textFormat() == Qt.TextFormat.PlainText
        w.ensurePolished()
        assert w.font().pixelSize() >= 17 or w.font().pointSize() >= 13, w.text()
    card.cancel()
    wait_until(qapp, lambda: not ctl.busy)


def test_full_voice_loop_with_stats(ctl, qapp):
    freed, stats = [], []
    ctl.freed_changed.connect(freed.append)
    ctl.stats_ready.connect(stats.append)
    open_login_card(ctl, qapp)
    ctl.handle_transcript("Freeze.")
    wait_until(qapp, lambda: not ctl.busy)
    assert frozen(ctl) == ALLOWED
    wait_until(qapp, lambda: freed and abs(freed[-1] - 2700 / 1024) < 0.01)
    ctl.handle_transcript("Bring them back")
    wait_until(qapp, lambda: stats)
    s = stats[0]
    assert not frozen(ctl) and s.apps == 4 and s.freed_mb == 2700 and s.restored_mb == 2700
    assert abs(s.usd - mocks.PLAN_COST_USD) < 1e-9 and abs(s.minutes - 48) < 0.5


def test_stats_card_lands_on_exact_values(qapp):
    card = StatsCard(Stats(2700, 4, 48, 0.0021, 2700, 3.2))
    card.present()
    wait_until(qapp, lambda: not any(i is card for i in fx.ticker()._items), timeout=4)
    assert [c[0].text() for c in card.counters] == ["2.6 GB", "48 min", "4", "$0.0021"]
    assert "Restored 2.6 GB in 3.2s" in card_texts(card)
    card.close()


def test_blocked_app_can_never_be_frozen(ctl, qapp):
    card = open_login_card(ctl, qapp)
    assert "msedge.exe" not in {r.app_id for r in card.rows}
    card.accept()
    wait_until(qapp, lambda: not ctl.busy)
    assert not frozen(ctl) & {"msedge.exe", "explorer.exe", "spotify.exe", "code.exe"}


def test_untick_popup_yes_saves_never_freeze_only_after_freeze(ctl, qapp):
    card = open_login_card(ctl, qapp)
    row(card, "discord.exe").check.setChecked(False)
    assert card.ask.isVisibleTo(card)
    assert card.ask_text.text() == "Never freeze discord.exe during 'login bug'?"
    assert card.total.text() == "~2.2 GB to free"
    card._answer(True)
    assert sessions.get("login bug").never_freeze == []   # nothing saved until Freeze
    row(card, "slack.exe").check.setChecked(False)
    card._answer(False)
    card.accept()
    wait_until(qapp, lambda: not ctl.busy)
    assert sessions.get("login bug").never_freeze == ["discord.exe"]
    assert frozen(ctl) == ALLOWED - {"discord.exe", "slack.exe"}


def test_cancel_writes_no_rule(ctl, qapp):
    card = open_login_card(ctl, qapp)
    row(card, "discord.exe").check.setChecked(False)
    card._answer(True)
    card.cancel()
    wait_until(qapp, lambda: not ctl.busy)
    assert sessions.get("login bug").never_freeze == []


def test_bad_rule_is_caught_not_fatal(ctl, qapp, monkeypatch):
    messages = []
    ctl.status.connect(messages.append)
    card = open_login_card(ctl, qapp)
    row(card, "discord.exe").check.setChecked(False)
    card._answer(True)

    def refuse(*_a):
        raise ValueError("bad app_id")

    monkeypatch.setattr(sessions, "add_rule", refuse)
    card.accept()
    wait_until(qapp, lambda: not ctl.busy)
    wait_until(qapp, lambda: any("Could not save" in m for m in messages))


def test_session_keeps_rules_and_starts_with_none_task(ctl, qapp):
    mocks.seed_sessions()
    ctl.handle_transcript("Start thesis session")
    wait_until(qapp, lambda: ctl.card)
    assert ctl.card.heading.text() == "writing my thesis on urban heat islands"
    assert sessions.get("thesis").task == "writing my thesis on urban heat islands"
    ctl.card.cancel()
    wait_until(qapp, lambda: not ctl.busy)


def test_fallback_banner_shows(ctl, qapp, monkeypatch):
    monkeypatch.setattr(mocks, "fallback_reason", "spend cap reached")
    card = open_login_card(ctl, qapp)
    assert card.banner is not None and any("Simple mode" in t for t in card_texts(card))
    card.cancel()
    wait_until(qapp, lambda: not ctl.busy)


def test_guardian_needs_idle_apps_then_card_text_matches_spec(qapp):
    dismissed = []
    c = make_ctl(on_guardian_dismiss=lambda: dismissed.append(1))
    c.on_pressure(mocks.PRESSURE)                 # discord and slack are too recent
    wait_until(qapp, lambda: c.card)
    assert c.card.text == "RAM 91%. Freeze 2 idle apps, free ~1.5 GB?"
    c.card.cancel()
    wait_until(qapp, lambda: dismissed and not c.busy)
    c.sensor.age(300)                             # the rig's "open them 5+ minutes ahead"
    c.on_pressure(mocks.PRESSURE)
    c.on_pressure(mocks.PRESSURE)                 # second event while busy is dropped
    wait_until(qapp, lambda: c.card)
    card = c.card
    assert isinstance(card, GuardianCard) and (card.width(), card.height()) == (380, 180)
    assert card.text == "RAM 91%. Freeze 4 idle apps, free ~2.6 GB?"
    c.on_pressure(mocks.PRESSURE)
    assert c.card is card
    card.accept()                                 # Review opens the full card
    wait_until(qapp, lambda: isinstance(c.card, ConsentCard))
    assert not frozen(c)
    c.card.accept()
    wait_until(qapp, lambda: not c.busy)
    assert frozen(c) == ALLOWED
    c.shutdown()


def test_guardian_dismiss_starts_a_real_cooldown(qapp):
    now = [0.0]
    g = Guardian(ram_pct=lambda: 91.3, clock=lambda: now[0], config=GuardianConfig())
    g.poll([])
    now[0] = 34
    assert g.poll(mocks.DESK) is not None
    c = make_ctl(on_guardian_dismiss=g.dismissed)
    c.sensor.age(300)
    c.on_pressure(mocks.PRESSURE)
    wait_until(qapp, lambda: c.card)
    c.card.cancel()
    wait_until(qapp, lambda: not c.busy and g.in_cooldown)
    c.shutdown()


def test_closing_the_card_releases_the_agent(ctl, qapp):
    card = open_login_card(ctl, qapp)
    card.close()
    wait_until(qapp, lambda: not ctl.busy)
    assert not frozen(ctl) and ctl.card is None


def test_decision_reaches_the_agent_before_the_outro_finishes(ctl, qapp):
    card = open_login_card(ctl, qapp)
    card.accept()
    assert ctl.card is None and card.isVisible()
    wait_until(qapp, lambda: not isValid(card) or not card.isVisible())


def test_closed_cards_are_deleted_by_qt_not_by_the_gc(ctl, qapp):
    card = open_login_card(ctl, qapp)
    card.close()
    wait_until(qapp, lambda: not ctl.busy)
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    wait_until(qapp, lambda: not isValid(card))
    assert card not in cards._open_cards


def test_panic_thaws_and_no_card_opens_after(ctl, qapp):
    card = open_login_card(ctl, qapp)
    card.accept()
    wait_until(qapp, lambda: not ctl.busy)
    assert frozen(ctl)
    ctl.sensor.age(300)
    ctl.on_pressure(mocks.PRESSURE)
    ctl.panic()
    wait_until(qapp, lambda: not ctl.busy)
    assert not frozen(ctl) and ctl.card is None


def test_shutdown_never_leaves_apps_frozen(qapp):
    c = make_ctl()
    sessions.start("login bug", mocks.LOGIN_TASK)
    c.say_task("I'm fixing the login bug")
    wait_until(qapp, lambda: c.card)
    c.card.accept()
    wait_until(qapp, lambda: not c.busy)
    assert frozen(c)
    c.shutdown()
    assert not frozen(c)


def test_quit_during_planning_does_not_hang(qapp, monkeypatch):
    monkeypatch.setattr(mocks, "PLAN_DELAY_S", 0.2)
    c = make_ctl()
    c.focus("fixing the login bug")
    t0 = time.monotonic()
    c.shutdown()
    assert time.monotonic() - t0 < 3 and not frozen(c)


def test_done_during_planning_does_not_open_a_card(qapp, monkeypatch):
    monkeypatch.setattr(mocks, "PLAN_DELAY_S", 0.1)
    c = make_ctl()
    c.focus("fixing the login bug")
    c.done()
    wait_until(qapp, lambda: not c.busy)
    time.sleep(0.05)
    qapp.processEvents()
    assert c.card is None
    c.shutdown()


def test_stray_confirm_and_cancel_do_not_reach_the_planner(ctl):
    ctl.handle_transcript("yes")
    ctl.handle_transcript("cancel")
    assert not ctl.busy and not ctl.card


def test_rule_words_use_the_spec_then_fall_back():
    assert rule_words("plays_audio") == "Playing audio"
    assert rule_words("security_software") == "Security software — cannot freeze"
    assert rule_words("some_new_rule") == "Protected by a safety rule"


def test_session_picker_shows_seeded_sessions(qapp):
    mocks.seed_sessions()
    picker = SessionPicker()
    texts = card_texts(picker)
    assert "thesis" in texts and "vlog edit" in texts and any("2h ago, 2 rules" == t for t in texts)
    assert picker.toggles["vlog edit"].isChecked()
    assert "will freeze without asking" in picker.toggles["thesis"].text()
    picker.toggles["thesis"].setChecked(True)
    assert sessions.get("thesis").auto_freeze
    picked = []
    picker.start_session.connect(picked.append)
    picker._start("thesis")
    assert picked == ["thesis"]


def test_ago():
    assert ago(1000, 1000 + 2 * 3600) == "2h ago"
    assert ago(0) == "never used"


def test_voice_bar_routes_buttons_and_typing(qapp):
    bar = VoiceBar(mocks.TRANSCRIPTS)
    said = []
    bar.spoken.connect(said.append)
    bar.phrase_buttons[0].click()
    bar.edit.setText("I'm done")
    bar.edit.returnPressed.emit()
    assert said == ["I'm fixing the login bug", "I'm done"]
    assert bar.transcript.text() == "I'm done"
    bar.close()


def test_gauge_waits_for_the_chip_then_lands_on_the_spec_values(qapp):
    ram = [Ram(91.3, 3.74, 4.0)]
    g = Gauge(lambda: ram[0])
    used = sum(c.used == 1 for c in g._cells)
    g.hold(0.3)
    ram[0] = Ram(22.9, 0.94, 4.0)
    g.set_freed(2.6)
    assert g._shown_pct == 91.3 and not any(c.goal_ice for c in g._cells)
    wait_until(qapp, lambda: g._shown_pct == 22.9 and sum(c.ice == 1 for c in g._cells) > 0)
    n = len(g._cells)
    assert sum(c.used == 1 for c in g._cells) == round(0.229 * n)
    g.grab()
    ram[0] = Ram(91.3, 3.74, 4.0)
    g.set_freed(0.0)
    wait_until(qapp, lambda: g._shown_pct == 91.3 and sum(c.used == 1 for c in g._cells) == used
               and not any(c.ice for c in g._cells))
    g._timer.stop()


def test_gauge_drop_takes_about_a_second(qapp):
    ram = [Ram(91.3, 3.74, 4.0)]
    g = Gauge(lambda: ram[0])
    ram[0] = Ram(22.9, 0.94, 4.0)
    g.tick()
    for _ in range(60):
        g.step(1 / 60)
    assert abs(g._shown_pct - 22.9) < 1.0
    g._timer.stop()


@pytest.mark.parametrize("pct", [7.0, 22.9, 45.5, 89.9, 99.96, 100.0])
def test_rolling_digits_paint_at_every_value(qapp, pct):
    g = Gauge(lambda: Ram(pct, 1.0, 4.0))
    g.grab()
    g._timer.stop()


def test_ticker_goes_idle_when_nothing_moves(qapp):
    g = Gauge(lambda: Ram(50.0, 2.0, 4.0))
    g.tick()
    wait_until(qapp, lambda: not any(i is g for i in fx.ticker()._items))
    g._timer.stop()


def test_overlay_never_catches_input_and_cleans_up(qapp):
    o = MotionOverlay(headless=True)
    o.resize(800, 600)
    assert o.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert o.windowFlags() & Qt.WindowType.WindowTransparentForInput
    o.play_freeze(QPointF(400, 300), QPointF(700, 50), "2.6 GB")
    wait_until(qapp, lambda: not o.mode, timeout=8)
    o.play_thaw(QPointF(400, 300), QPointF(700, 50), "2.6 GB")
    o.grab()
    wait_until(qapp, lambda: not o.mode, timeout=8)


def test_live_parts_are_real_and_never_freeze_us():
    """--live swaps every mock: real sensor, policy and actuator, default model."""
    import os

    from freezer.actuator import RealActuator
    from freezer.contracts import AppSnapshot, ProcRef
    from freezer.sensor import RealSensor
    from ui.app import make_parts

    parts = make_parts(True, live=True)
    try:
        assert isinstance(parts["sensor"], RealSensor) and isinstance(parts["actuator"], RealActuator)
        assert "model" not in parts   # real titles never go to the contributor model
        us = AppSnapshot("python.exe", "python.exe", [ProcRef(os.getpid(), 1.0)], [], 50.0, 900.0,
                         False, False, False, False)
        verdict = parts["policy"](["python.exe"], [us])
        assert verdict.allowed == [] and verdict.blocked[0].rule == "self"
    finally:
        parts["sensor"].tracker.stop()


def test_live_exe_names_read_as_app_names_but_ids_stay_exact():
    from freezer.contracts import AppSnapshot, ProcRef
    from ui.consent import app_name

    live = AppSnapshot("discord.exe", "discord.exe", [ProcRef(1, 1.0)], [], 1.0, 0.0, False, False, False, False)
    mock = AppSnapshot("steam.exe", "Steam (library)", [ProcRef(2, 1.0)], [], 1.0, 0.0, False, False, False, False)
    assert app_name("discord.exe", live) == "Discord"
    assert app_name("steam.exe", mock) == "Steam (library)"
    assert app_name("unknown.exe", None) == "unknown.exe"


def test_live_never_seeds_the_made_up_sessions():
    """The mock desk's sessions include an auto_freeze one. On a real PC that would
    freeze real apps with no card, so --live starts with no sessions at all."""
    from ui.app import seed_demo_sessions

    seed_demo_sessions(live=True, live_planner=False)
    assert not any(s.auto_freeze for s in sessions.load())
    assert sessions.load() == []
    seed_demo_sessions(live=False, live_planner=False)   # the mock desk still gets them
    assert any(s.auto_freeze for s in sessions.load())


def test_snapshot_runs_off_the_gui_thread_and_lands_back_on_it(qapp):
    """A live snapshot takes up to a second: on the GUI thread the gauge would stall."""
    import threading

    from ui.app import OffGui

    gui = threading.current_thread()
    ran_on, landed_on, got = [], [], []
    gate = threading.Event()

    def snapshot():
        ran_on.append(threading.current_thread())
        gate.wait(2)
        return ["app.exe"]

    off = OffGui()
    try:
        assert off.submit(snapshot, lambda r: (landed_on.append(threading.current_thread()), got.append(r)))
        assert not off.submit(snapshot, got.append)   # still busy: that poll is skipped
        gate.set()
        wait_until(qapp, lambda: got)
        assert ran_on[0] is not gui and landed_on == [gui] and got == [["app.exe"]]
        assert off.submit(lambda: 1 / 0, got.append)  # a failing snapshot skips, then frees the slot
        wait_until(qapp, lambda: off.submit(lambda: "ok", got.append))
        wait_until(qapp, lambda: got[-1] == "ok")
    finally:
        off.shutdown()


def test_live_policy_hard_blocks_the_active_sessions_rules():
    """policy_for(None) ignored the session: its never-freeze and keep rules must be
    hard blocks in --live, and follow the user when they switch session."""
    from freezer.contracts import AppSnapshot, ProcRef
    from ui.app import SessionPolicy

    def snap(app_id, pid):
        return AppSnapshot(app_id, app_id, [ProcRef(pid, 1.0)], [], 300.0, 3600.0, False, False, False, False)

    desk = [snap("discord.exe", 9101), snap("acrord32.exe", 9102), snap("steam.exe", 9103),
            snap("slack.exe", 9104), snap("notepad.exe", 9105)]
    sessions.start("thesis", "writing my thesis")
    sessions.add_rule("thesis", "discord.exe", "never_freeze")
    sessions.add_rule("thesis", "acrord32.exe", "keep")
    active = {"name": "thesis"}
    policy = SessionPolicy(set())
    policy.active = lambda: active["name"]

    verdict = policy(["discord.exe", "acrord32.exe", "steam.exe"], desk)
    assert verdict.allowed == ["steam.exe"]
    assert {(b.app_id, b.rule) for b in verdict.blocked} == {("discord.exe", "user_never_freeze"),
                                                            ("acrord32.exe", "user_keep")}
    sessions.add_rule("thesis", "steam.exe", "never_freeze")   # a rule saved mid-session applies at once
    assert policy(["steam.exe"], desk).allowed == []
    active["name"] = None                                      # switched away: no session rules
    assert policy(["discord.exe", "acrord32.exe"], desk).allowed == ["discord.exe", "acrord32.exe"]


def test_own_pids_protect_every_ancestor_and_the_watchdog():
    """Started as terminal -> shell -> venv launcher -> python, getppid() is only the
    launcher. The shell and terminal running Focus Freeze must be 'self' too."""
    import json
    import subprocess
    import sys

    from ui.app import own_pids

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    inner = f"import json, sys; sys.path.insert(0, {root!r}); from ui.app import own_pids; print(json.dumps(sorted(own_pids())))"
    middle = f"import subprocess, sys; sys.exit(subprocess.run([{sys.executable!r}, '-c', {inner!r}]).returncode)"
    base = getattr(sys, "_base_executable", sys.executable)   # one extra level, like a shell
    out = subprocess.run([base, "-c", middle], capture_output=True, text=True, timeout=60, check=True)
    assert os.getpid() in json.loads(out.stdout.strip().splitlines()[-1])   # two or more levels up

    dog = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        time.sleep(1.0)   # a venv launcher starts its real interpreter as a child
        import psutil
        kids = {c.pid for c in psutil.Process(dog.pid).children(recursive=True)}
        assert {dog.pid} | kids <= own_pids(dog.pid)
    finally:
        import psutil
        for c in psutil.Process(dog.pid).children(recursive=True):
            c.kill()
        dog.kill()


def test_card_shows_ai_vs_timer_with_names_keep_first(ctl, qapp):
    card = open_login_card(ctl, qapp)
    assert card.contrast_box is not None and card.contrast_box.parent() is card.frame   # pinned
    lines = [w.text() for w in card.contrast_box.findChildren(QLabel)]
    assert lines[0] == "Where the AI beat the idle timer"
    assert lines[1].startswith("Idle timer would freeze Adobe Acrobat Reader · AI keeps it: Reference PDF")
    first = card.contrast_box.findChildren(QLabel)[1]
    assert first.toolTip().endswith("a timer would freeze this")   # full reason, even when elided
    assert not any("msedge" in t or "Microsoft Edge" in t for t in lines)   # blocked: no "AI freezes it"
    assert len(lines) == 1 + 3   # at most 3, of the 4 disagreements
    layout = card.body
    assert layout.indexOf(card.contrast_box) > layout.indexOf(card.blocked_box)   # at the bottom
    card.cancel()
    wait_until(qapp, lambda: not ctl.busy)


def test_ai_vs_timer_hidden_in_simple_mode(ctl, qapp, monkeypatch):
    monkeypatch.setattr(mocks, "fallback_reason", "the AI didn't answer in time")
    card = open_login_card(ctl, qapp)
    assert card.proposal.vs_timer == [] and card.contrast_box is None
    card.cancel()
    wait_until(qapp, lambda: not ctl.busy)


def test_card_footer_says_who_planned_it_how_fast_and_for_how_much(ctl, qapp):
    import re

    card = open_login_card(ctl, qapp)
    assert card.planned is not None
    assert re.fullmatch(r"Planned by Muse Spark · \d+\.\d s · \$0\.002", card.planned.text())
    card.cancel()
    wait_until(qapp, lambda: not ctl.busy)


def test_card_footer_hidden_in_simple_mode(ctl, qapp, monkeypatch):
    monkeypatch.setattr(mocks, "fallback_reason", "the AI didn't answer in time")
    card = open_login_card(ctl, qapp)
    assert card.proposal.plan.model == "heuristic" and card.planned is None
    card.cancel()
    wait_until(qapp, lambda: not ctl.busy)


def test_plan_latency_runs_from_first_request_to_last_response(ctl):
    ctl._on_progress("request", 1)
    started = ctl._plan_started
    ctl._on_progress("request", 2)          # a retry keeps the first start
    ctl._on_progress("response", 2)
    assert ctl._plan_started == started and ctl.plan_latency_s() >= 0
