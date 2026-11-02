import asyncio
import json
import queue

import pytest

websockets = pytest.importorskip("websockets")

from freezer import voice
from freezer.voice import Command, VoiceError, parse_command


@pytest.mark.parametrize("said, expected", [
    ("Focus on the login bug.", Command("focus", "the login bug")),
    ("I’m working on my thesis", Command("focus", "my thesis")),
    ("I'm fixing the login bug", Command("focus", "I'm fixing the login bug")),
    ("Start thesis session.", Command("session", "thesis")),
    ("start my tax return session", Command("session", "tax return")),
    ("I'm done.", Command("done")),
    ("I am done for today", Command("done")),
    ("OK, bring them back!", Command("done")),
    ("Freeze them.", Command("confirm")),
    ("Yes", Command("confirm")),
    ("Cancel", Command("cancel")),
    ("  ...  ", None),
    ("", None),
])
def test_parse_command(said, expected):
    assert parse_command(said) == expected


def test_a_task_that_mentions_done_is_still_a_task():
    assert parse_command("focus on what I'm done with").kind == "focus"


def run_against(server_handler, frames, on_partial=None, key="test-key"):
    async def main():
        async with websockets.serve(server_handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            voice.WS_URL = f"ws://127.0.0.1:{port}"
            return await voice.transcribe(frames, key, on_partial)
    return asyncio.run(main())


@pytest.fixture(autouse=True)
def restore_url():
    url = voice.WS_URL
    yield
    voice.WS_URL = url


def feed(*items):
    q = queue.Queue()
    for item in items:
        q.put(item)
    return q


def test_protocol_handshake_audio_endstream_final():
    seen = {"audio": []}

    async def server(ws):
        seen["handshake"] = json.loads(await ws.recv())
        await ws.send(json.dumps({"sessionId": "s1"}))
        async for msg in ws:
            if isinstance(msg, bytes):
                seen["audio"].append(msg)
                await ws.send(json.dumps({"type": "audioProgress", "audioProcessedMs": 80}))
                await ws.send(json.dumps({"type": "transcript", "transcript": "I'm", "final": False,
                                          "audioProcessedMs": 80}))
            elif json.loads(msg) == {"type": "endStream"}:
                seen["ended"] = True
                await ws.send(json.dumps({"type": "transcript", "transcript": "I'm done", "final": True,
                                          "audioProcessedMs": 160}))
                await ws.close(1000)

    partials = []
    text, ms = run_against(server, feed(b"\0" * 3840, b"\1" * 3840, None), partials.append)
    assert (text, ms) == ("I'm done", 160)
    assert seen["ended"] and len(seen["audio"]) == 2
    h = seen["handshake"]
    assert h["authorization"] == {"accessToken": "Bearer test-key"}
    assert h["audioEncoding"] == "PCM_24KHZ" and h["model"] == "muse-voice-transcribe-1.0"
    assert h["mode"] == "PUSH_TO_TALK"
    assert partials[0] == "I'm" and partials[-1] == "I'm done"


def test_refused_handshake_is_a_clean_error():
    async def server(ws):
        await ws.recv()
        await ws.send(json.dumps({"type": "error", "message": "Bad key", "sessionId": ""}))
        await ws.close(1008)

    with pytest.raises(VoiceError, match="Bad key"):
        run_against(server, feed(None))


def test_error_never_echoes_the_key():
    async def server(ws):
        await ws.recv()
        await ws.send(json.dumps({"sessionId": "s1"}))
        await ws.close(1011, "boom")

    with pytest.raises(VoiceError) as e:
        run_against(server, feed(None), key="sk-secret")
    assert "sk-secret" not in str(e.value)


def test_listen_once_scripted_needs_no_mic():
    assert voice.listen_once(["I'm done", "Freeze"]) == "I'm done"


def test_listen_once_without_key_returns_empty(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    assert voice.listen_once() == ""


def test_no_key_reports_error_without_opening_the_mic(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    errors = []
    ptt = voice.PushToTalk(lambda *_: None, errors.append)
    ptt.press()
    assert errors and "MODEL_API_KEY" in errors[0] and not ptt.active
