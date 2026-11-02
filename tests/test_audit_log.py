import json
from argparse import Namespace

from freezer import audit
from freezer.agent import FocusAgent
from freezer.cli import cmd_thaw, cmd_verify_log
from freezer.contracts import AppSnapshot, ProcRef
from freezer.mocks import MockActuator
from freezer.policy import filter as _real_filter
from tests.test_planner import FakeClient, all_decisions, call, reply


def _home_file(monkeypatch, tmp_path):
    monkeypatch.setenv("FF_HOME", str(tmp_path))
    return tmp_path / "audit.jsonl"


def test_chain_verifies(tmp_path, monkeypatch):
    _home_file(monkeypatch, tmp_path)
    audit.log("user", "freeze", "steam.exe", "freed 600 MB")
    audit.log("guardian", "block", "code.exe", "foreground")
    audit.log("user", "thaw", "steam.exe", "task switch")
    assert audit.verify() == (True, None, 3)


def test_prev_links_to_previous_line(tmp_path, monkeypatch):
    p = _home_file(monkeypatch, tmp_path)
    audit.log("user", "freeze", "a.exe")
    audit.log("user", "freeze", "b.exe")
    import hashlib
    lines = p.read_bytes().splitlines()
    assert json.loads(lines[1])["prev_hash"] == hashlib.sha256(lines[0]).hexdigest()
    assert json.loads(lines[0])["prev_hash"] == "0" * 64


def test_edit_old_entry_fails_at_exactly_that_line(tmp_path, monkeypatch):
    p = _home_file(monkeypatch, tmp_path)
    audit.log("user", "freeze", "a.exe")
    audit.log("user", "freeze", "b.exe")
    audit.log("user", "freeze", "c.exe")
    lines = p.read_bytes().splitlines()
    body = json.loads(lines[1])
    body["app_id"] = "evil.exe"
    lines[1] = json.dumps(body, sort_keys=True).encode()
    p.write_bytes(b"\n".join(lines) + b"\n")
    assert audit.verify() == (False, 1, 3)


def test_malformed_line_fails_there(tmp_path, monkeypatch):
    p = _home_file(monkeypatch, tmp_path)
    audit.log("user", "freeze", "a.exe")
    with open(p, "ab") as f:
        f.write(b"not json\n")
    assert audit.verify() == (False, 1, 2)


def test_missing_file_is_vacuously_ok(tmp_path, monkeypatch):
    _home_file(monkeypatch, tmp_path)
    assert audit.verify() == (True, None, 0)


def test_agent_run_leaves_freeze_and_block(tmp_path, monkeypatch):
    p = _home_file(monkeypatch, tmp_path)
    snaps = [__snap("app0.exe"), __snap("app1.exe")]
    client = FakeClient(reply(call("freeze_apps", all_decisions(snaps, {"app0.exe", "app1.exe"}))))
    agent = FocusAgent(__sensor(snaps), _real_filter, MockActuator(),
                       lambda pr: [d.app_id for d in pr.to_freeze], client=client)
    out = agent.focus("doing things")
    assert len(out.frozen) == 1
    assert [(b.app_id, b.rule) for b in out.proposal.blocked] == [("app1.exe", "too_many")]
    actions = sorted(json.loads(line)["action"] for line in p.read_bytes().splitlines())
    assert actions == ["block", "freeze"]
    assert audit.verify() == (True, None, 2)


def test_thaw_command_is_logged(tmp_path, monkeypatch):
    _home_file(monkeypatch, tmp_path)
    act = MockActuator()
    act.freeze(__snap("steam.exe"), "s")
    assert cmd_thaw(Namespace(app_id="steam.exe", all=False), act) == 0
    lines = (__home(monkeypatch, tmp_path)).read_bytes().splitlines()
    assert [json.loads(line)["action"] for line in lines] == ["thaw"]


def test_verify_log_command_codes(tmp_path, monkeypatch, capsys):
    _home_file(monkeypatch, tmp_path)
    audit.log("user", "freeze", "a.exe")
    audit.log("user", "freeze", "b.exe")
    assert cmd_verify_log(Namespace()) == 0
    assert "ok: 2 entries" in capsys.readouterr().out
    p = __home(monkeypatch, tmp_path)
    raw = p.read_bytes()
    p.write_bytes(raw.replace(b"a.exe", b"evil.exe", 1))
    assert cmd_verify_log(Namespace()) == 1
    assert "BROKEN at line 0" in capsys.readouterr().err


def __snap(app_id):
    return AppSnapshot(app_id=app_id, display_name=app_id,
                       procs=[ProcRef(424242, 1.0)], window_titles=[],
                       working_set_mb=100.0, last_focus_s=3600.0,
                       is_foreground=False, plays_audio=False, is_elevated=False,
                       has_network=False)


class __sensor:
    def __init__(self, snaps):
        self._snaps = snaps

    def snapshot(self):
        return list(self._snaps)


def __home(monkeypatch, tmp_path):
    monkeypatch.setenv("FF_HOME", str(tmp_path))
    return tmp_path / "audit.jsonl"
