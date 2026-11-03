"""Voice commands: push-to-talk -> muse-voice-transcribe-1.0 -> Command.

    python -m freezer.voice      # hold Ctrl+Alt+Space, speak, see the parsed command

The mic is open only while the hotkey is held, and nothing else leaves the
machine. The transcript is user input, but parse_command() still only picks
what to do: a focus task goes to the planner, then the consent card.

Protocol: https://dev.meta.ai/docs/api-reference/voice/realtime
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, Literal

log = logging.getLogger(__name__)

WS_URL = os.environ.get("FF_ASR_URL", "wss://api.meta.ai/v1/asr/realtime")
MODEL = "muse-voice-transcribe-1.0"
SAMPLE_RATE = 24_000
FRAME_SAMPLES = 1920         # 80 ms, 3840 bytes of 16-bit mono PCM
KEYWORDS = ["focus", "freeze", "session", "I'm done", "bring them back"]
MAX_HOLD_S = 60              # a stuck key must not stream (and bill) forever
CLOSE_TIMEOUT_S = 8         # after endStream: longer than this and the server has gone silent
USD_PER_MINUTE = 0.003
NOT_CAUGHT = "Didn't catch that. Hold Ctrl+Alt+Space and try again."


# ---- Commands --------------------------------------------------------------

@dataclass(frozen=True)
class Command:
    kind: Literal["focus", "session", "done", "confirm", "cancel"]
    text: str = ""           # task sentence or session name


_FOCUS = re.compile(r"^(?:please )?(?:focus on|i am working on|i'm working on|im working on)\s+(.+)$")
_SESSION = re.compile(r"^(?:please )?(?:start|load|open)\s+(?:the |my )?(.+?)\s+session$")
_DONE = re.compile(r"^(?:ok(?:ay)? |so )?(?:i'm|i am|im) done\b|\bbring (?:them|it|everything|my apps) back\b"
                   r"|^(?:thaw|unfreeze|restore)\b")
_CONFIRM = {"yes", "yeah", "yep", "ok", "okay", "confirm", "go ahead", "do it", "freeze", "freeze them",
            "freeze it", "freeze all", "freeze all of them", "yes freeze them"}
_CANCEL = {"no", "nope", "cancel", "stop", "never mind", "nevermind", "not now", "dismiss", "don't"}


def parse_command(transcript: str) -> Command | None:
    """Keywords first (fast, free). Anything else is a task for the planner."""
    raw = " ".join(transcript.split()).strip(" .,!?")
    if not raw:
        return None
    text = raw.lower().replace("’", "'")
    if m := _FOCUS.match(text):
        return Command("focus", raw[-len(m.group(1)):])
    if m := _SESSION.match(text):
        return Command("session", m.group(1))
    if _DONE.search(text):
        return Command("done")
    if text in _CONFIRM:
        return Command("confirm")
    if text in _CANCEL:
        return Command("cancel")
    return Command("focus", raw)


# ---- Transcription ---------------------------------------------------------

class VoiceError(RuntimeError):
    """Message is safe to show to the user; it never contains the API key."""


_CLOSE_REASONS = {
    1008: "The voice service rejected the audio stream.",
    1011: "The voice service failed. Try again.",
    1013: "The voice service is rate limiting us. Wait a moment.",
}


async def transcribe(frames: "queue.Queue[bytes | None]", api_key: str,
                     on_partial: Callable[[str], None] | None = None) -> tuple[str, int]:
    """Stream PCM frames until a None arrives. Returns (transcript, audio ms)."""
    import websockets

    loop = asyncio.get_running_loop()
    try:
        async with websockets.connect(WS_URL, max_size=2**20, open_timeout=10, close_timeout=2) as ws:
            # This endpoint ignores the Authorization header: the key goes in the first frame.
            await ws.send(json.dumps({
                "authorization": {"accessToken": f"Bearer {api_key}"},
                "audioEncoding": "PCM_24KHZ",
                "model": MODEL,
                "mode": "PUSH_TO_TALK",
                "keywords": KEYWORDS,
            }))
            ack = json.loads(await asyncio.wait_for(ws.recv(), 10))
            if ack.get("type") == "error" or "sessionId" not in ack:
                raise VoiceError(ack.get("message") or "The voice service refused the session.")

            ended = asyncio.Event()

            async def send_audio() -> None:
                while (frame := await loop.run_in_executor(None, frames.get)) is not None:
                    await ws.send(frame)
                # Half-close: keep reading, closing now would drop the final transcript.
                await ws.send(json.dumps({"type": "endStream"}))
                ended.set()

            sender = asyncio.create_task(send_audio())
            text, audio_ms = "", 0
            deadline = None
            try:
                while True:
                    # Until endStream the user may still be talking; after it the server
                    # has CLOSE_TIMEOUT_S to send the final transcript, or we give up.
                    if ended.is_set() and deadline is None:
                        deadline = loop.time() + CLOSE_TIMEOUT_S
                    wait = 0.25 if deadline is None else deadline - loop.time()
                    if wait <= 0:
                        raise VoiceError(NOT_CAUGHT)
                    try:
                        raw = await asyncio.wait_for(ws.recv(), wait)
                    except asyncio.TimeoutError:
                        continue
                    except websockets.ConnectionClosedOK:
                        break
                    if isinstance(raw, bytes):
                        continue
                    event = json.loads(raw)
                    kind = event.get("type")
                    if kind == "transcript":
                        text = event.get("transcript", "")
                        audio_ms = event.get("audioProcessedMs", audio_ms)
                        if on_partial and text:
                            on_partial(text)
                        if event.get("final"):
                            break
                    elif kind == "error":
                        raise VoiceError(event.get("message") or "The voice service failed.")
                    # Other types (speechStart, audioProgress, ...) are ignored by design.
            finally:
                frames.put(None)  # lets a sender still waiting on the queue finish
                sender.cancel()
            return text, audio_ms
    except websockets.ConnectionClosedError as e:
        code = e.rcvd.code if e.rcvd else 0
        raise VoiceError(_CLOSE_REASONS.get(code, f"The voice connection dropped (code {code}).")) from None
    except (OSError, asyncio.TimeoutError, websockets.WebSocketException) as e:
        raise VoiceError(f"Could not reach the voice service ({type(e).__name__}).") from None


class PushToTalk:
    """press() opens the mic and starts streaming; release() ends it and reports."""

    def __init__(self, on_transcript: Callable[[str, float], None], on_error: Callable[[str], None],
                 on_partial: Callable[[str], None] | None = None, api_key: str | None = None,
                 on_level: Callable[[float], None] | None = None):
        self.on_transcript, self.on_error, self.on_partial = on_transcript, on_error, on_partial
        self.on_level = on_level     # mic loudness 0..1, for the gauge's waveform
        self.api_key = api_key or os.environ.get("MODEL_API_KEY")
        self._frames: queue.Queue[bytes | None] | None = None
        self._stream = None
        self._lock = threading.Lock()
        self._started = 0.0

    @property
    def active(self) -> bool:
        return self._stream is not None

    def press(self) -> None:
        import numpy as np
        import sounddevice as sd

        with self._lock:
            if self._stream is not None:
                return
            if not self.api_key:
                self.on_error("Voice needs MODEL_API_KEY. Use the tray menu instead.")
                return
            frames: queue.Queue[bytes | None] = queue.Queue()

            def on_audio(data, _count, _time, _status) -> None:
                frames.put(bytes(data))
                if self.on_level:
                    pcm = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                    self.on_level(min(float(np.sqrt(np.mean(pcm * pcm))) / 6000, 1.0))

            try:
                stream = sd.RawInputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                           blocksize=FRAME_SAMPLES, callback=on_audio)
                stream.start()
            except Exception as e:  # no mic, device busy, permission denied
                self.on_error(f"Could not open the microphone: {e}")
                return
            self._frames, self._stream, self._started = frames, stream, time.monotonic()
        threading.Thread(target=self._run, args=(frames,), daemon=True, name="ff-voice").start()
        threading.Timer(MAX_HOLD_S, self._expire, args=(frames,)).start()

    def release(self) -> None:
        with self._lock:
            stream, frames = self._stream, self._frames
            self._stream = self._frames = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            finally:
                frames.put(None)   # always: without it the transcription waits for audio forever

    def _expire(self, frames: queue.Queue) -> None:
        if self._frames is frames:
            self.release()

    def _run(self, frames: queue.Queue) -> None:
        try:
            text, audio_ms = asyncio.run(transcribe(frames, self.api_key, self.on_partial))
        except VoiceError as e:
            self.release()
            self.on_error(str(e))
        except Exception:  # noqa: BLE001 - a voice bug must not end in silence
            log.exception("transcription failed")
            self.release()
            self.on_error(NOT_CAUGHT)
        else:
            self.release()  # the server can finish first; the mic must not outlive the stream
            self.on_transcript(text, audio_ms / 60_000 * USD_PER_MINUTE)


def listen_once(scripted: list[str] | None = None, max_s: float = 6.0, silence_s: float = 0.8) -> str:
    """One utterance as text; "" if nothing was heard. Blocks, so call it off the GUI thread.

    With scripted lines it returns the first one and touches no mic, so tests and the
    mock demo run without audio. Otherwise it listens until a pause after speech.
    """
    if scripted:
        return scripted[0]
    done = threading.Event()
    heard = {"text": ""}
    quiet = {"since": 0.0, "spoke": False}

    def on_level(level: float) -> None:
        if level > 0.05:
            quiet["spoke"], quiet["since"] = True, 0.0
        elif quiet["spoke"]:
            quiet["since"] = quiet["since"] or time.monotonic()

    def on_text(text: str, _usd: float) -> None:
        heard["text"] = text
        done.set()

    ptt = PushToTalk(on_text, lambda _m: done.set(), on_level=on_level)
    ptt.press()
    if not ptt.active:
        return ""
    end = time.monotonic() + max_s
    while time.monotonic() < end and not done.is_set():
        if quiet["since"] and time.monotonic() - quiet["since"] >= silence_s:
            break
        time.sleep(0.05)
    ptt.release()
    done.wait(CLOSE_TIMEOUT_S)
    return heard["text"]


# ---- Win32 hotkey ----------------------------------------------------------

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x4000
VK_SPACE, VK_V = 0x20, 0x56
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012

# Tried in order; the first one free wins. Other apps (launchers, AI quick-entry
# boxes) like to grab Ctrl+Alt+Space, and voice must not die with it.
HOTKEYS: tuple[tuple[str, int, int], ...] = (
    ("Ctrl+Alt+Space", MOD_CONTROL | MOD_ALT, VK_SPACE),
    ("Ctrl+Shift+Space", MOD_CONTROL | MOD_SHIFT, VK_SPACE),
    ("Ctrl+Alt+V", MOD_CONTROL | MOD_ALT, VK_V),
)


class HoldHotkey:
    """Push-to-talk, global. RegisterHotKey sees the press; release is polled.

    Takes the first free combo in HOTKEYS. If all are taken, voice is off and
    registration is retried every RETRY_S, so closing the other app brings it back.
    """

    RETRY_S = 2.0
    combos = HOTKEYS

    def __init__(self, on_press: Callable[[], None], on_release: Callable[[], None],
                 on_status: Callable[[str], None]):
        self.on_press, self.on_release, self.on_status = on_press, on_release, on_status
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ff-hotkey")
        self._thread_id = 0
        self._stopped = threading.Event()
        self.active: str | None = None   # label of the combo we hold

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        import ctypes
        self._stopped.set()
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

    def _loop(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        blocked = False
        while True:
            held = next(((label, vk) for label, mods, vk in self.combos
                         if user32.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, vk)), None)
            if held:
                break
            if not blocked:
                names = ", ".join(label for label, _, _ in self.combos)
                self.on_status(f"{names} are all taken by other apps. "
                               "Voice is off until one is free.")
                blocked = True
            if self._stopped.wait(self.RETRY_S):
                return
        self.active, vk_hold = held
        if blocked or self.active != self.combos[0][0]:
            self.on_status(f"Voice is on. Hold {self.active} and speak.")
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    self._hold(lambda: bool(user32.GetAsyncKeyState(vk_hold) & 0x8000))
        finally:
            user32.UnregisterHotKey(None, 1)

    def _hold(self, key_down: Callable[[], bool]) -> None:
        """One press-hold-release. Errors are logged and reported, never raised: a raise
        here ends the hotkey thread, and voice would be dead until restart."""
        self._safe(self.on_press, "press")
        while key_down():
            time.sleep(0.03)
        self._safe(self.on_release, "release")   # always, so the UI leaves "listening"

    def _safe(self, fn: Callable[[], None], what: str) -> None:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - see _hold
            log.exception("hotkey %s failed", what)
            try:
                self.on_status(f"Voice failed ({type(e).__name__}). Try again.")
            except Exception:  # noqa: BLE001
                log.exception("hotkey error report failed")


# ---- Speech out ------------------------------------------------------------

class Speaker:
    """Windows SAPI via pyttsx3 (Meta has no TTS). Text on screen is the fallback."""

    def __init__(self) -> None:
        self._queue: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._loop, daemon=True, name="ff-tts").start()

    def say(self, text: str) -> None:
        self._queue.put(text)

    def _loop(self) -> None:
        try:
            import pyttsx3
            engine = pyttsx3.init()
        except Exception:
            return
        while True:
            text = self._queue.get()
            try:
                engine.say(text)
                engine.runAndWait()
            except Exception:
                return


def _main() -> None:
    def show(text: str, cost: float) -> None:
        print(f"\n{text!r} -> {parse_command(text)}  (${cost:.5f})")

    ptt = PushToTalk(show, lambda m: print(f"\n[error] {m}"), lambda t: print(f"\r{t}", end=""))
    hotkey = HoldHotkey(ptt.press, ptt.release, lambda m: print(f"[error] {m}"))
    hotkey.start()
    print("Hold Ctrl+Alt+Space and speak. Ctrl+C quits.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        ptt.release()
        hotkey.stop()


if __name__ == "__main__":
    _main()
