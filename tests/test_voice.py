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


def test_silent_server_after_endstream_times_out_as_didnt_catch_that(monkeypatch):
    """CLOSE_TIMEOUT_S was unused: a server that goes quiet after endStream hung the
    voice thread forever."""
    import time

    monkeypatch.setattr(voice, "CLOSE_TIMEOUT_S", 0.5)

    async def server(ws):
        await ws.recv()
        await ws.send(json.dumps({"sessionId": "s1"}))
        await ws.send(json.dumps({"type": "transcript", "transcript": "I'm", "final": False}))
        async for msg in ws:   # reads audio and endStream, then never answers
            pass

    started = time.monotonic()
    with pytest.raises(VoiceError, match="Didn't catch that"):
        run_against(server, feed(b"\0" * 3840, None))
    assert time.monotonic() - started < 5


def test_server_closing_cleanly_returns_what_it_heard():
    async def server(ws):
        await ws.recv()
        await ws.send(json.dumps({"sessionId": "s1"}))
        await ws.send(json.dumps({"type": "transcript", "transcript": "freeze", "final": False,
                                  "audioProcessedMs": 80}))
        await ws.close(1000)

    assert run_against(server, feed(b"\0" * 3840, None)) == ("freeze", 80)


class _BrokenStream:
    def stop(self):
        raise OSError("device lost")

    def close(self):
        pass


def test_release_always_ends_the_audio_even_if_the_mic_errors():
    ptt = voice.PushToTalk(lambda *_: None, lambda _m: None, api_key="k")
    frames = queue.Queue()
    ptt._stream, ptt._frames = _BrokenStream(), frames
    with pytest.raises(OSError):
        ptt.release()
    assert frames.get_nowait() is None and not ptt.active


def test_hotkey_survives_press_and_release_errors():
    """A raise in press() or release() used to kill the hotkey thread and leave the
    gauge on 'listening'. Both are caught, reported, and release always runs."""
    calls, errors = [], []

    def press():
        calls.append("press")
        raise RuntimeError("mic exploded")

    def release():
        calls.append("release")
        raise ValueError("also broken")

    hk = voice.HoldHotkey(press, release, errors.append)
    held = iter([True, False])
    hk._hold(lambda: next(held))   # must not raise
    assert calls == ["press", "release"]
    assert errors == ["Voice failed (RuntimeError). Try again.", "Voice failed (ValueError). Try again."]


def test_hotkey_reports_the_combo_it_got_when_the_first_is_taken():
    """Another app holds the first combo: voice falls back, and says which key to use."""
    import ctypes
    import threading
    import time

    first = ("Ctrl+Alt+F9", voice.MOD_CONTROL | voice.MOD_ALT, 0x78)
    second = ("Ctrl+Alt+F10", voice.MOD_CONTROL | voice.MOD_ALT, 0x79)
    held, release = threading.Event(), threading.Event()

    def other_app():
        u = ctypes.windll.user32
        u.RegisterHotKey(None, 50, first[1], first[2])
        held.set()
        release.wait()
        u.UnregisterHotKey(None, 50)

    threading.Thread(target=other_app, daemon=True).start()
    held.wait(2)
    ready, status = [], []
    hk = voice.HoldHotkey(lambda: None, lambda: None, status.append, on_ready=ready.append)
    hk.combos = (first, second)
    try:
        hk.start()
        deadline = time.monotonic() + 3
        while not ready and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready == ["Ctrl+Alt+F10"] and hk.active == "Ctrl+Alt+F10"
        assert status == ["Voice is on. Hold Ctrl+Alt+F10 and speak."]
    finally:
        hk.stop()
        release.set()


# ---- microphone choice -------------------------------------------------------
# Real case: Windows' default input was an empty Realtek jack ("Prise microphone",
# median RMS ~60) while the built-in mic one entry below heard the room (~700).

def test_an_empty_default_jack_loses_to_the_live_mic():
    assert voice.pick_mic({1: 60.0, 2: 717.0}, default=1) == 2


def test_the_default_mic_wins_when_it_is_alive():
    # A headset quieter than the laptop mic is still the user's choice.
    assert voice.pick_mic({1: 300.0, 2: 717.0}, default=1) == 1


def test_no_readable_inputs_keeps_the_default():
    assert voice.pick_mic({}, default=1) == 1
    assert voice.pick_mic({2: 500.0}, default=1) == 2   # default would not even open


def test_ff_mic_overrides_the_probe(monkeypatch):
    monkeypatch.setattr(voice, "input_devices", lambda: [(1, "Prise microphone"), (2, "Microphone (Realtek)")])
    monkeypatch.setattr(voice, "measure_inputs", lambda _d: pytest.fail("FF_MIC must skip the probe"))
    monkeypatch.setenv("FF_MIC", "realtek")
    ptt = voice.PushToTalk(lambda *_: None, lambda _m: None, api_key="k")
    assert ptt.choose_mic() == "Microphone (Realtek)" and ptt.device == 2


def test_a_silent_hold_switches_mic_instead_of_didnt_catch_that(monkeypatch):
    async def fake_transcribe(frames, key, on_partial=None):
        return "", 0
    monkeypatch.setattr(voice, "transcribe", fake_transcribe)
    errors, heard = [], []
    ptt = voice.PushToTalk(lambda t, _u: heard.append(t), errors.append, api_key="k")

    def choose():
        ptt.device, ptt.mic_name = 2, "Microphone (Realtek)"
    monkeypatch.setattr(ptt, "choose_mic", choose)
    ptt._run(queue.Queue(), {"peak": 90.0})
    assert not heard and "Switched to Microphone (Realtek)" in errors[0]


def test_a_loud_hold_with_no_words_is_still_a_transcript(monkeypatch):
    async def fake_transcribe(frames, key, on_partial=None):
        return "", 0
    monkeypatch.setattr(voice, "transcribe", fake_transcribe)
    heard = []
    ptt = voice.PushToTalk(lambda t, _u: heard.append(t), lambda _m: pytest.fail("no hint"), api_key="k")
    ptt._run(queue.Queue(), {"peak": 3000.0})
    assert heard == [""]
