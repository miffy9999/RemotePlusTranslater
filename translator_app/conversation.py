from __future__ import annotations

import queue
import re
import threading
import time
from dataclasses import dataclass, asdict
from typing import Protocol

from .audio import AudioCapture, PlaybackGate, Utterance
from .config import AppConfig
from .events import EventBus
from .languages import get_language
from .stt import Recognition, WhisperRecognizer, contains_japanese_kana
from .hymt2 import create_translator
from .tts import SapiSpeaker


class RecognizerLike(Protocol):
    def load(self) -> None: ...
    def transcribe(self, audio) -> Recognition: ...


class TranslatorLike(Protocol):
    def load(self) -> None: ...
    def translate(self, text: str, source_code: str, target_code: str) -> str: ...


@dataclass(slots=True)
class ConversationState:
    phase: str = "starting"
    message: str = "Starting"
    active_language: str | None = None
    input_language: str = "auto"
    reply_language: str = "auto"
    input_device: str | int = "default"
    output_device: str | int = "default"
    enabled_languages: list[str] | None = None
    active_language_at: float = 0.0
    paused: bool = False
    tts_enabled: bool = True
    processed: int = 0
    dropped: int = 0


_NOISE_TEXT = re.compile(
    r"^(thank you|thanks for watching|subscribe|ご視聴ありがとうございました|字幕視聴ありがとうございました)$",
    re.IGNORECASE,
)


class ConversationController:
    def __init__(
        self,
        cfg: AppConfig,
        bus: EventBus | None = None,
        recognizer: RecognizerLike | None = None,
        translator: TranslatorLike | None = None,
    ):
        self.cfg = cfg
        self.bus = bus or EventBus()
        self.state = ConversationState(
            tts_enabled=cfg.tts.enabled,
            input_language=cfg.conversation.language_lock,
            reply_language=cfg.conversation.reply_language,
            input_device=cfg.audio.input_device,
            output_device=cfg.audio.output_device,
            enabled_languages=list(cfg.conversation.enabled_languages),
        )
        self._state_lock = threading.Lock()
        self._utterances: queue.Queue[Utterance] = queue.Queue(maxsize=3)
        self._stop = threading.Event()
        self._ready = threading.Event()
        self.gate = PlaybackGate(cfg.audio.post_tts_mute_ms)
        self.recognizer = recognizer or WhisperRecognizer(cfg.stt, self._status)
        if hasattr(self.recognizer, "set_selected_language"):
            self.recognizer.set_selected_language(self.state.input_language)
        if hasattr(self.recognizer, "set_enabled_languages"):
            self.recognizer.set_enabled_languages(self.state.enabled_languages or [])
        self.translator = translator or create_translator(cfg.translation, self._status)
        self.speaker = SapiSpeaker(cfg.tts, cfg.audio, self.gate, self._status)
        self.capture = AudioCapture(cfg.audio, self._utterances, self.gate, self._status)
        self._worker = threading.Thread(target=self._run, name="conversation", daemon=True)

    def start(self) -> None:
        if self._worker.is_alive():
            return
        self.speaker.start()
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        self.capture.stop()
        self.speaker.stop()
        if hasattr(self.translator, "close"):
            self.translator.close()
        for thread in (self.capture, self.speaker, self._worker):
            if thread.is_alive():
                thread.join(timeout=3)

    def _status(self, phase: str, message: str) -> None:
        with self._state_lock:
            self.state.phase = phase
            self.state.message = message
        self.bus.publish("status", phase=phase, message=message)
        if phase in {"error", "warning"}:
            self.bus.publish(phase, message=message)

    def _run(self) -> None:
        try:
            self.recognizer.load()
            self.translator.load()
            self._ready.set()
            if not self.capture.is_alive():
                self.capture.start()
            while not self._stop.is_set():
                try:
                    item = self._utterances.get(timeout=0.2)
                except queue.Empty:
                    continue
                with self._state_lock:
                    paused = self.state.paused
                if paused:
                    continue
                started = time.perf_counter()
                self._status("recognizing", "Recognizing speech")
                try:
                    result = self.recognizer.transcribe(item.audio)
                    self.process_recognition(result, item.duration, started)
                except Exception as exc:
                    self._status("error", f"Processing failed: {exc}")
        except Exception as exc:
            self._status("error", f"Model initialization failed: {exc}")

    def _resolve_language(self, result: Recognition) -> str:
        raw = result.language.lower()
        if contains_japanese_kana(result.text):
            return "ja"
        with self._state_lock:
            lock = self.state.input_language
            active_language = self.state.active_language
            active_language_at = self.state.active_language_at
        now = time.time()
        active_is_fresh = (
            active_language is not None
            and now - active_language_at
            <= self.cfg.conversation.language_memory_seconds
        )
        if raw == "ja" and result.probability >= self.cfg.conversation.minimum_language_probability:
            return "ja"
        if lock != "auto":
            return lock
        if result.probability < self.cfg.conversation.minimum_language_probability and active_is_fresh:
            return active_language or raw
        return raw

    def process_recognition(
        self, result: Recognition, duration: float = 0.0, started: float | None = None
    ) -> None:
        text = result.text.strip()
        if not text or _NOISE_TEXT.match(text):
            self._status("listening", "Listening")
            return
        language = self._resolve_language(result)
        info = get_language(language)
        if info is None:
            self._status("warning", f"Detected unsupported language: {language}")
            return
        self.bus.publish(
            "transcript",
            text=text,
            language=language,
            probability=round(result.probability, 3),
        )
        japanese = self.cfg.conversation.japanese_code
        if language != japanese:
            if hasattr(self.recognizer, "set_context_language"):
                self.recognizer.set_context_language(language)
            translated = self.translator.translate(text, language, japanese)
            with self._state_lock:
                self.state.active_language = language
                self.state.active_language_at = time.time()
                self.state.processed += 1
            direction = "incoming"
            source_code, target_code = language, japanese
        else:
            with self._state_lock:
                reply_language = self.state.reply_language
                target = (
                    reply_language
                    if reply_language != "auto"
                    else self.state.active_language
                )
                age = time.time() - self.state.active_language_at
            if target is None or (
                reply_language == "auto"
                and age > self.cfg.conversation.language_memory_seconds
            ):
                self._status("warning", "Japanese reply heard, but no recent partner language is set")
                return
            translated = self.translator.translate(text, japanese, target)
            with self._state_lock:
                self.state.processed += 1
            direction = "reply"
            source_code, target_code = japanese, target
            with self._state_lock:
                tts_enabled = self.state.tts_enabled
            if tts_enabled:
                self.speaker.speak(translated, target)

        elapsed = (time.perf_counter() - started) if started else 0.0
        self.bus.publish(
            "translation",
            direction=direction,
            source=text,
            translated=translated,
            source_language=source_code,
            target_language=target_code,
            audio_seconds=round(duration, 2),
            latency_seconds=round(elapsed, 2),
        )
        self._status("listening", "Listening")

    def snapshot(self) -> dict:
        with self._state_lock:
            result = asdict(self.state)
        result["dropped"] += self.capture.dropped_utterances
        result["ready"] = self._ready.is_set()
        return result

    def control(
        self,
        *,
        paused: bool | None = None,
        tts_enabled: bool | None = None,
        active_language: str | None = None,
        reply_language: str | None = None,
        input_device: str | int | None = None,
        output_device: str | int | None = None,
        enabled_languages: list[str] | None = None,
    ) -> dict:
        restart_capture = False
        if input_device is not None:
            if isinstance(input_device, str):
                valid_input = (
                    input_device == "default"
                    or (input_device.startswith("loopback:") and len(input_device) > 9)
                    or input_device.isdigit()
                )
                if not valid_input:
                    raise ValueError(
                        "input_device must be a number, 'default', or a loopback device"
                    )
            elif not isinstance(input_device, int):
                raise ValueError("input_device must be a number or device identifier")
        if output_device is not None and not (
            output_device == "default"
            or (
                isinstance(output_device, str)
                and output_device.startswith("output:")
                and len(output_device) > 7
            )
        ):
            raise ValueError("output_device must be 'default' or an output device identifier")
        with self._state_lock:
            if paused is not None:
                self.state.paused = paused
            if tts_enabled is not None:
                self.state.tts_enabled = tts_enabled
                self.speaker.cfg.enabled = tts_enabled
            if active_language is not None:
                if active_language != "auto" and get_language(active_language) is None:
                    raise ValueError(f"Unsupported language: {active_language}")
                if (
                    active_language != "auto"
                    and active_language not in (self.state.enabled_languages or [])
                ):
                    raise ValueError(f"Language is not enabled: {active_language}")
                self.state.active_language = None if active_language == "auto" else active_language
                self.state.active_language_at = time.time() if active_language != "auto" else 0.0
                self.state.input_language = active_language
                if hasattr(self.recognizer, "set_selected_language"):
                    self.recognizer.set_selected_language(active_language)
            if reply_language is not None:
                if reply_language != "auto" and reply_language not in (
                    self.state.enabled_languages or []
                ):
                    raise ValueError(f"Reply language is not enabled: {reply_language}")
                self.state.reply_language = reply_language
                self.cfg.conversation.reply_language = reply_language
            if input_device is not None and input_device != self.state.input_device:
                self.state.input_device = input_device
                self.cfg.audio.input_device = input_device
                restart_capture = True
            if output_device is not None:
                self.state.output_device = output_device
                self.cfg.audio.output_device = output_device
            if enabled_languages is not None:
                valid = list(dict.fromkeys(code.lower() for code in enabled_languages))
                if not valid or any(get_language(code) is None or code == "ja" for code in valid):
                    raise ValueError("At least one supported foreign language is required")
                self.state.enabled_languages = valid
                self.cfg.conversation.enabled_languages = valid
                if self.state.input_language not in {"auto", *valid}:
                    self.state.input_language = "auto"
                    self.state.active_language = None
                if self.state.reply_language not in {"auto", *valid}:
                    self.state.reply_language = "auto"
                    self.cfg.conversation.reply_language = "auto"
                if hasattr(self.recognizer, "set_enabled_languages"):
                    self.recognizer.set_enabled_languages(valid)
        if restart_capture:
            old_capture = self.capture
            old_capture.stop()
            if old_capture.is_alive():
                old_capture.join(timeout=3)
            with self._state_lock:
                self.state.dropped += old_capture.dropped_utterances
            self.capture = AudioCapture(
                self.cfg.audio,
                self._utterances,
                self.gate,
                self._status,
            )
            if self._ready.is_set() and not self._stop.is_set():
                self.capture.start()
        state = self.snapshot()
        self.bus.publish("state", **state)
        return state
