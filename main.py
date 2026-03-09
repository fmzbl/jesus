#!/usr/bin/env python3
"""
Jesus - Voice Assistant for Raspberry Pi

Wake:         "Jesus start conversation"
Stop reading: "jesus stop"
End session:  "Jesus stop conversation"
"""

import io
import json
import queue
import struct
import subprocess
import sys
import tempfile
import threading
import time
import wave
from datetime import datetime
from pathlib import Path

import re
import numpy as np
import pyaudio
from faster_whisper import WhisperModel
import ollama

# ── Constants ──────────────────────────────────────────────────────────────────

WAKE_PHRASES      = {"jesus"}
END_PHRASES       = {"jesus stop"}
RESTART_PHRASES   = {"jesus stop conversation"}
STOP_WORD         = "jesus stop"
ENERGY_THRESHOLD  = 50     # RMS below this is treated as silence
SILENCE_TIMEOUT   = 1.5    # seconds of silence after speech before forcing final result
CONVERSATIONS_DIR = Path("conversations")
CONFIG_FILE      = Path("config.json")

DEFAULT_CONFIG = {
    "model": "llama3.2:3b",
    "available_models": [
        "llama3.2:1b",
        "llama3.2:3b",
        "phi3:mini",
        "gemma2:2b",
        "mistral:7b",
    ],
    "tts_engine": "piper",         # "espeak" or "piper"
    "tts_voice": "en",
    "speech_rate": 150,
    "piper_model": "en_US-ryan-high",
    "user_name": "Facu",
    "whisper_model": "small",
    "sample_rate": 16000,
}

SYSTEM_PROMPT = (
    "You are Jesus, a helpful voice assistant. "
    "Respond naturally and concisely since your replies will be read aloud. "
    "Avoid markdown formatting, bullet points, or special characters. "
    "Use plain, conversational language."
)

# ── Config ─────────────────────────────────────────────────────────────────────

class Config:
    def __init__(self):
        self._d = DEFAULT_CONFIG.copy()
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE) as f:
                self._d.update(json.load(f))
        else:
            self._write()

    def _write(self):
        with open(CONFIG_FILE, "w") as f:
            json.dump(self._d, f, indent=2)

    def get(self, key, default=None):
        return self._d.get(key, default)

    def set(self, key, value):
        self._d[key] = value
        self._write()

# ── Microphone capture (dedicated thread → queue) ──────────────────────────────

def _rms(data: bytes) -> float:
    """RMS energy of a raw 16-bit mono PCM chunk."""
    count = len(data) // 2
    if count == 0:
        return 0.0
    shorts = struct.unpack(f"{count}h", data)
    return (sum(s * s for s in shorts) / count) ** 0.5


class MicCapture:
    """Continuously reads from the microphone into a thread-safe queue."""

    def __init__(self, rate: int = 16000, chunk: int = 1024):
        self.rate  = rate
        self.chunk = chunk
        self._q    = queue.Queue()
        self._pa   = pyaudio.PyAudio()
        self._running = False

    def start(self):
        stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.rate,
            input=True,
            frames_per_buffer=self.chunk,
        )
        self._running = True

        def _loop():
            while self._running:
                try:
                    data = stream.read(self.chunk, exception_on_overflow=False)
                    self._q.put(data)
                except Exception:
                    break
            stream.close()

        threading.Thread(target=_loop, daemon=True).start()

    def read(self, timeout: float = 0.5):
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self):
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break

    def close(self):
        self._running = False
        self._pa.terminate()

# ── Speech recognition ─────────────────────────────────────────────────────────

class STT:
    """Wraps faster-whisper for offline speech recognition."""

    def __init__(self, model_size: str = "small"):
        print(f"Loading Whisper model '{model_size}'...")
        self._model = WhisperModel(model_size, device="cpu", compute_type="int8")
        print("Whisper ready.")

    def transcribe(self, audio_bytes: bytes) -> str:
        audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = self._model.transcribe(
            audio, language="en", beam_size=5, vad_filter=True
        )
        text = " ".join(seg.text for seg in segments).strip().lower()
        return re.sub(r"[^\w\s]", "", text)

# ── Text-to-speech ─────────────────────────────────────────────────────────────

class TTS:
    def __init__(self, config: Config):
        self._cfg   = config
        self._pa    = pyaudio.PyAudio()
        self._thread: threading.Thread | None = None
        self._stop  = threading.Event()
        self._piper_voice = None

        if config.get("tts_engine") == "piper":
            from piper import PiperVoice
            model_name = config.get("piper_model", "en_US-ryan-high")
            model_path = Path(f"{model_name}.onnx")
            print(f"Loading Piper voice '{model_name}'...")
            self._piper_voice = PiperVoice.load(model_path)
            print("Piper ready.")

    def speak(self, text: str):
        self.stop()
        self._stop.clear()
        self._thread = threading.Thread(target=self._play, args=(text,), daemon=True)
        self._thread.start()

    def _play(self, text: str):
        if self._piper_voice is not None:
            self._play_piper(text)
        else:
            self._play_espeak(text)

    def _play_piper(self, text: str):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            self._piper_voice.synthesize_wav(text, wf)
        buf.seek(0)
        with wave.open(buf, "rb") as wf:
            stream = self._pa.open(
                format=self._pa.get_format_from_width(wf.getsampwidth()),
                channels=wf.getnchannels(),
                rate=wf.getframerate(),
                output=True,
            )
            try:
                chunk = wf.readframes(1024)
                while chunk and not self._stop.is_set():
                    stream.write(chunk)
                    chunk = wf.readframes(1024)
            finally:
                stream.stop_stream()
                stream.close()

    def _play_espeak(self, text: str):
        voice = self._cfg.get("tts_voice", "en")
        speed = self._cfg.get("speech_rate", 150)
        tmpwav = tempfile.mktemp(suffix=".wav")
        try:
            subprocess.run(
                ["espeak-ng", "-v", voice, "-s", str(speed), "-w", tmpwav, text],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            with wave.open(tmpwav, "rb") as wf:
                stream = self._pa.open(
                    format=self._pa.get_format_from_width(wf.getsampwidth()),
                    channels=wf.getnchannels(),
                    rate=wf.getframerate(),
                    output=True,
                )
                try:
                    chunk = wf.readframes(1024)
                    while chunk and not self._stop.is_set():
                        stream.write(chunk)
                        chunk = wf.readframes(1024)
                finally:
                    stream.stop_stream()
                    stream.close()
        finally:
            Path(tmpwav).unlink(missing_ok=True)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None

    def wait(self):
        if self._thread:
            self._thread.join()

    def beep(self, freq: float = 880.0, duration: float = 0.12):
        """Play a short sine-wave tone (blocking)."""
        rate = 22050
        n = int(rate * duration)
        t = np.linspace(0, duration, n, endpoint=False)
        data = (np.sin(2 * np.pi * freq * t) * 0.9 * 32767).astype(np.int16)
        stream = self._pa.open(format=pyaudio.paInt16, channels=1, rate=rate, output=True)
        try:
            stream.write(data.tobytes())
        finally:
            stream.stop_stream()
            stream.close()

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def close(self):
        self.stop()
        self._pa.terminate()

# ── LLM via Ollama ─────────────────────────────────────────────────────────────

def llm_chat(model: str, messages: list) -> str:
    resp = ollama.chat(model=model, messages=messages)
    return resp.message.content or ""

# ── Conversation log ───────────────────────────────────────────────────────────

class ConvLog:
    def __init__(self):
        CONVERSATIONS_DIR.mkdir(exist_ok=True)
        self._msgs: list = []
        self._path: Path | None = None

    def new_session(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._path = CONVERSATIONS_DIR / f"session_{ts}.json"
        self._msgs = []
        self._save()

    def add(self, role: str, content: str):
        self._msgs.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        })
        self._save()

    def for_llm(self) -> list:
        return [{"role": m["role"], "content": m["content"]} for m in self._msgs]

    def _save(self):
        if self._path:
            with open(self._path, "w") as f:
                json.dump({"messages": self._msgs}, f, indent=2, ensure_ascii=False)

# ── Jesus ───────────────────────────────────────────────────────────────────────

class Jesus:
    def __init__(self):
        print("Starting Jesus...")
        self.cfg  = Config()
        self.tts  = TTS(self.cfg)
        self.conv = ConvLog()

        self.stt = STT(self.cfg.get("whisper_model", "small"))

        rate = self.cfg.get("sample_rate", 16000)
        self.mic = MicCapture(rate=rate)
        self.mic.start()

        print(f"LLM model : {self.cfg.get('model')}")
        print("TTS engine: " + self.cfg.get("tts_engine", "espeak"))

    # ── Speak, interruptible by "stop" ────────────────────────────────────────

    def say(self, text: str):
        print(f"\nJesus: {text}")
        self.tts.speak(text)
        self.mic.drain()

        frames: list[bytes] = []
        last_check = time.time()

        while self.tts.busy:
            chunk = self.mic.read(timeout=0.1)
            if chunk is None:
                continue
            frames.append(chunk)
            if time.time() - last_check >= 2.0:
                heard = self.stt.transcribe(b"".join(frames))
                frames = []
                last_check = time.time()
                if STOP_WORD in heard:
                    print("[reading stopped]")
                    self.tts.stop()
                    self.mic.drain()
                    break

    # ── Listen until speech ends ───────────────────────────────────────────────

    def listen(self, beep: bool = True) -> str:
        fresh = True
        while True:
            self.mic.drain()
            if fresh and beep:
                self.tts.beep(freq=880, duration=0.12)
            fresh = False
            print("\n  [listening...]", end="", flush=True)

            frames: list[bytes] = []
            speech_started = False
            last_speech_time: float | None = None

            while True:
                chunk = self.mic.read(timeout=0.1)

                if chunk is None:
                    if speech_started and last_speech_time and \
                            time.time() - last_speech_time > SILENCE_TIMEOUT:
                        break
                    continue

                # Always record — no energy gate
                frames.append(chunk)

                energy = _rms(chunk)
                print(f"\r  [listening... energy: {energy:.0f}]  ", end="", flush=True)
                if energy > ENERGY_THRESHOLD:
                    if not speech_started:
                        speech_started = True
                        print("\r  [recording...]  ", end="", flush=True)
                    last_speech_time = time.time()

                if speech_started and last_speech_time and \
                        time.time() - last_speech_time > SILENCE_TIMEOUT:
                    break

                # Safety cap: 15s max recording
                if len(frames) * self.mic.chunk / self.mic.rate > 15:
                    break

            if not speech_started:
                continue

            print("\r  [transcribing...]", end="", flush=True)
            if beep:
                self.tts.beep(freq=880, duration=0.08)
            text = self.stt.transcribe(b"".join(frames))
            if text:
                if beep:
                    self.tts.beep(freq=880, duration=0.12)
                print(f"\r  You: {text}          ")
                return text
            print("\r  [didn't catch that, listening again...]", end="", flush=True)
            time.sleep(0.5)

    # ── Active conversation loop ───────────────────────────────────────────────

    def converse(self):
        self.conv.new_session()
        self.mic.drain()
        name = self.cfg.get("user_name", "Facu")
        self.say("Hello son, what is it")

        while True:
            text = self.listen()
            if not text:
                continue

            self.say(f"you said {text}")

            if any(p in text for p in RESTART_PHRASES):
                self.say("Ok, ill be here if you need me")
                return True

            if any(p in text for p in END_PHRASES):
                self.say("ok ill be here if you need me")
                return False

            # Bare "jesus stop" — user interrupted, don't send to LLM
            if text.strip() == STOP_WORD:
                continue

            self.conv.add("user", text)
            messages = [{"role": "system", "content": SYSTEM_PROMPT}, *self.conv.for_llm()]

            print("Thinking...")
            self.say("let me think")
            result_box: list = [None]
            error_box:  list = [None]

            def _think():
                try:
                    result_box[0] = llm_chat(self.cfg.get("model"), messages)
                except Exception as e:
                    error_box[0] = e

            t = threading.Thread(target=_think, daemon=True)
            t.start()

            # Monitor mic for "stop" while LLM / web-search is running
            self.mic.drain()
            frames: list[bytes] = []
            last_check = time.time()
            cancelled = False

            while t.is_alive():
                chunk = self.mic.read(timeout=0.1)
                if chunk is None:
                    continue
                frames.append(chunk)
                if time.time() - last_check >= 1.5:
                    heard = self.stt.transcribe(b"".join(frames))
                    frames = []
                    last_check = time.time()
                    if STOP_WORD in heard:
                        print("[cancelled]")
                        cancelled = True
                        break

            if cancelled:
                self.mic.drain()
                self.say("ok I will stop")
                continue

            if error_box[0]:
                answer = f"Sorry, I ran into an error: {error_box[0]}"
            else:
                answer = result_box[0] or ""

            self.conv.add("assistant", answer)
            self.say(answer)

    # ── Standby loop ──────────────────────────────────────────────────────────

    def run(self):
        print("\nReady — say 'Jesus'\n")
        try:
            while True:
                text = self.listen(beep=False)
                if any(p in text for p in WAKE_PHRASES):
                    self.tts.beep(freq=880, duration=0.12)
                    print("[wake phrase detected]")
                    self.converse()
                    print("\nStandby — say 'Jesus'\n")
        except KeyboardInterrupt:
            print("\nShutting down.")
        finally:
            self.tts.close()
            self.mic.close()

# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    Jesus().run()
