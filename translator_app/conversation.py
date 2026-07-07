from __future__ import annotations

import logging
import os
import queue
import re
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .audio import AudioCapture, PlaybackGate, Utterance
from .config import AppConfig
from .events import EventBus
from .hymt2 import create_translator
from .languages import get_language
from .stt import Recognition, WhisperRecognizer
from .tts import EdgeSpeaker


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
    input_language: str = "en"
    reply_language: str = "auto"
    speech_mode: str = "customer"
    input_device: str | int = "default"
    output_device: str | int = "default"
    enabled_languages: list[str] | None = None
    active_language_at: float = 0.0
    paused: bool = False
    tts_enabled: bool = True
    processed: int = 0
    dropped: int = 0


@dataclass(slots=True)
class RecognitionJob:
    result: Recognition
    language: str
    speech_mode: str
    duration: float
    stt_started_at: float
    stt_seconds: float
    utterance_id: int
    speech_ended_at: float
    ready_at: float
    speech_seconds: float
    vad_tail_seconds: float


_NOISE_TEXT = re.compile(r"^(thank you|thanks for watching|subscribe|ご視聴ありがとうございました|字幕視聴ありがとうございました)$", re.IGNORECASE)


def _create_debug_logger() -> logging.Logger | None:
    if os.getenv("REMOTEPLUS_DEBUG") != "1":
        return None
    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    logger = logging.getLogger(f"remoteplus.timing.{os.getpid()}.{run_id}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.FileHandler(log_dir / f"timing-{run_id}.log", mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    logger.info("timing_log_started path=%s pid=%s", log_dir / f"timing-{run_id}.log", os.getpid())
    return logger


class ConversationController:
    """Low-latency two-worker conversation pipeline.

    Whisper consumes utterances independently from Hy-MT2 translation. A slow
    translation therefore no longer prevents the next utterance from entering
    STT. Both queues keep only the latest unstarted turn.
    """

    def __init__(self, cfg: AppConfig, bus: EventBus | None = None, recognizer: RecognizerLike | None = None, translator: TranslatorLike | None = None):
        self.cfg = cfg
        self.bus = bus or EventBus()
        enabled = list(cfg.conversation.enabled_languages)
        customer = self._initial_customer_language(cfg, enabled)
        self.state = ConversationState(
            active_language=customer,
            input_language=customer,
            reply_language=cfg.conversation.reply_language,
            input_device=cfg.audio.input_device,
            output_device=cfg.audio.output_device,
            enabled_languages=enabled,
            active_language_at=time.time(),
            tts_enabled=cfg.tts.enabled,
        )
        self._state_lock = threading.Lock()
        self._utterances: queue.Queue[Utterance] = queue.Queue(maxsize=3)
        self._recognitions: queue.Queue[RecognitionJob] = queue.Queue(maxsize=3)
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._translator_ready = threading.Event()
        self._translator_failed = threading.Event()
        self._debug_logger: logging.Logger | None = None

        self.gate = PlaybackGate(cfg.audio.post_tts_mute_ms)
        self.recognizer = recognizer or WhisperRecognizer(cfg.stt, self._status)
        self.recognizer.set_enabled_languages(enabled) if hasattr(self.recognizer, "set_enabled_languages") else None
        self.recognizer.set_selected_language(customer) if hasattr(self.recognizer, "set_selected_language") else None
        self.translator = translator or create_translator(cfg.translation, self._status)
        self.speaker = EdgeSpeaker(cfg.tts, cfg.audio, self.gate, self._status, metrics=self._log_perf)
        self.capture = self._make_capture()
        self._stt_worker = threading.Thread(target=self._run_stt, name="conversation-stt", daemon=True)
        self._translation_worker = threading.Thread(target=self._run_translation, name="conversation-translation", daemon=True)
        self._translator_warmup: threading.Thread | None = None

    @staticmethod
    def _initial_customer_language(cfg: AppConfig, enabled: list[str]) -> str:
        configured = str(cfg.conversation.language_lock).lower()
        if configured != "auto" and configured != "ja" and get_language(configured) is not None:
            return configured
        return next((str(code).lower() for code in enabled if str(code).lower() != "ja" and get_language(str(code).lower()) is not None), "en")

    def _make_capture(self) -> AudioCapture:
        return AudioCapture(self.cfg.audio, self._utterances, self.gate, self._status, metrics=self._log_perf, context=self._capture_context, speech_started_sink=self._speech_started)

    def _capture_context(self) -> tuple[str, str]:
        with self._state_lock:
            mode = self.state.speech_mode
            customer = self.state.input_language
        return ("staff", self.cfg.conversation.japanese_code) if mode == "staff" else ("customer", customer)

    def _speech_started(self, speech_mode: str, language: str) -> None:
        self._log_perf("speech_started", speech_mode=speech_mode, forced_language=language)

    def start(self) -> None:
        if self._stt_worker.is_alive():
            return
        self._debug_logger = _create_debug_logger()
        self._log_perf("run_started", pid=os.getpid(), customer_language=self.state.input_language, speech_mode=self.state.speech_mode, tts_enabled=self.state.tts_enabled, tts_backend="edge", pipeline="stt_translation_split", speech_control="space_hold")
        self.speaker.start()
        self._translator_warmup = threading.Thread(target=self._warm_translator, name="translator-warmup", daemon=True)
        self._translator_warmup.start()
        self._translation_worker.start()
        self._stt_worker.start()

    def stop(self) -> None:
        self._log_perf("run_stopping")
        self._stop.set()
        self.capture.stop()
        self.speaker.stop()
        if hasattr(self.translator, "close"):
            self.translator.close()
        for thread in (self.capture, self.speaker, self._translator_warmup, self._stt_worker, self._translation_worker):
            if thread is not None and thread.is_alive():
                thread.join(timeout=3)

    def _status(self, phase: str, message: str) -> None:
        with self._state_lock:
            self.state.phase = phase
            self.state.message = message
        self.bus.publish("status", phase=phase, message=message)
        if phase in {"error", "warning"}:
            self.bus.publish(phase, message=message)

    def _log_perf(self, event: str, **fields: object) -> None:
        if self._debug_logger is None:
            return
        details = " ".join(f"{key}={str(value).replace(chr(10), r'\\n').replace(chr(13), '')}" for key, value in fields.items())
        self._debug_logger.info("%s %s", event, details)
        for handler in self._debug_logger.handlers:
            handler.flush()

    def _take_latest(self, source: queue.Queue, first):
        dropped = []
        item = first
        while True:
            try:
                newer = source.get_nowait()
            except queue.Empty:
                break
            dropped.append(item)
            item = newer
        return item, dropped

    def _put_latest_recognition(self, job: RecognitionJob) -> None:
        dropped: list[RecognitionJob] = []
        while True:
            try:
                dropped.append(self._recognitions.get_nowait())
            except queue.Empty:
                break
        for old in dropped:
            with self._state_lock:
                self.state.dropped += 1
            self._log_perf("translation_job_dropped", utterance_id=old.utterance_id, replacement_utterance_id=job.utterance_id, reason="superseded_before_translation")
        try:
            self._recognitions.put_nowait(job)
        except queue.Full:
            # Defensive fallback; queue was cleared just above.
            with self._state_lock:
                self.state.dropped += 1
            self._log_perf("translation_job_dropped", utterance_id=job.utterance_id, reason="translation_queue_full")
            return
        self._log_perf("translation_job_queued", utterance_id=job.utterance_id, speech_mode=job.speech_mode, queue_depth=self._recognitions.qsize())

    def _run_stt(self) -> None:
        try:
            started = time.monotonic()
            self._status("loading", "음성·번역 모델을 동시에 준비 중")
            self._log_perf("whisper_load_started")
            self.recognizer.load()
            self._ready.set()
            self._log_perf("whisper_ready", seconds=f"{time.monotonic() - started:.3f}")
            if self._stop.is_set():
                return
            self.capture.start()
            self._status("listening", "듣는 중 · 고객 언어 고정 / Space 누르는 동안 일본어")
            while not self._stop.is_set():
                try:
                    item = self._utterances.get(timeout=0.2)
                except queue.Empty:
                    continue
                item, stale = self._take_latest(self._utterances, item)
                for old in stale:
                    with self._state_lock:
                        self.state.dropped += 1
                    self._log_perf("utterance_dropped", utterance_id=old.utterance_id, replacement_utterance_id=item.utterance_id, reason="superseded_before_stt")
                with self._state_lock:
                    paused = self.state.paused
                if paused:
                    self._log_perf("utterance_skipped", utterance_id=item.utterance_id, reason="paused")
                    continue
                forced = item.recognition_language or (self.cfg.conversation.japanese_code if item.speech_mode == "staff" else self.state.input_language)
                if hasattr(self.recognizer, "set_selected_language"):
                    self.recognizer.set_selected_language(forced)
                if hasattr(self.recognizer, "set_context_language"):
                    self.recognizer.set_context_language(forced)
                stt_started = time.monotonic()
                queue_wait = max(0.0, stt_started - item.ready_at) if item.ready_at else 0.0
                self._log_perf("stt_started", utterance_id=item.utterance_id, speech_mode=item.speech_mode, forced_language=forced, audio_seconds=f"{item.duration:.3f}", speech_seconds=f"{item.speech_seconds:.3f}", vad_tail_seconds=f"{item.vad_tail_seconds:.3f}", queue_wait_seconds=f"{queue_wait:.3f}")
                self._status("recognizing", "음성 인식 중")
                try:
                    result = self.recognizer.transcribe(item.audio)
                except Exception as exc:
                    self._log_perf("stt_failed", utterance_id=item.utterance_id, error=repr(exc))
                    self._status("error", f"음성 인식 실패: {exc}")
                    continue
                stt_seconds = time.monotonic() - stt_started
                self._log_perf("stt_done", utterance_id=item.utterance_id, speech_mode=item.speech_mode, forced_language=forced, stt_seconds=f"{stt_seconds:.3f}", realtime_factor=f"{stt_seconds / item.duration:.3f}" if item.duration else "0.000", speech_end_to_stt_done_seconds=f"{max(0.0, time.monotonic()-item.speech_ended_at):.3f}" if item.speech_ended_at else "0.000", language=result.language, probability=f"{result.probability:.3f}")
                text = result.text.strip()
                if not text or _NOISE_TEXT.match(text):
                    self._log_perf("recognition_skipped", utterance_id=item.utterance_id, speech_mode=item.speech_mode, reason="empty_or_noise")
                    self._status("listening", "듣는 중")
                    continue
                self.bus.publish("transcript", text=text, language=forced, probability=round(result.probability, 3))
                self._put_latest_recognition(RecognitionJob(result, forced, item.speech_mode, item.duration, stt_started, stt_seconds, item.utterance_id, item.speech_ended_at, item.ready_at, item.speech_seconds, item.vad_tail_seconds))
        except Exception as exc:
            self._log_perf("stt_worker_failed", error=repr(exc))
            self._status("error", f"음성 인식 초기화 실패: {exc}")

    def _warm_translator(self) -> None:
        started = time.monotonic()
        try:
            self._log_perf("translator_load_started")
            self.translator.load()
            if self._stop.is_set() or getattr(self.translator, "ready", True) is False:
                self._translator_failed.set()
                return
            process_seconds = time.monotonic() - started
            self._log_perf("translator_process_ready", seconds=f"{process_seconds:.3f}")
            warmup_started = time.monotonic()
            if hasattr(self.translator, "warmup"):
                self.translator.warmup()
            self._translator_ready.set()
            self._log_perf("translator_ready", seconds=f"{time.monotonic() - started:.3f}", warmup_seconds=f"{time.monotonic() - warmup_started:.3f}")
        except Exception as exc:
            self._translator_failed.set()
            self._log_perf("translator_failed", error=repr(exc))
            self._status("warning", f"번역 엔진 준비 실패: {exc}")

    def _run_translation(self) -> None:
        pending: RecognitionJob | None = None
        while not self._stop.is_set():
            if self._translator_failed.is_set():
                try:
                    dropped = self._recognitions.get(timeout=0.2)
                    self._log_perf("translation_job_dropped", utterance_id=dropped.utterance_id, reason="translator_failed")
                except queue.Empty:
                    pass
                continue
            if pending is None:
                try:
                    pending = self._recognitions.get(timeout=0.2)
                except queue.Empty:
                    continue
            pending, stale = self._take_latest(self._recognitions, pending)
            for old in stale:
                with self._state_lock:
                    self.state.dropped += 1
                self._log_perf("translation_job_dropped", utterance_id=old.utterance_id, replacement_utterance_id=pending.utterance_id, reason="superseded_before_translation")
            if not self._translator_ready.is_set():
                self._log_perf("translation_waiting_for_model", utterance_id=pending.utterance_id)
                self._translator_ready.wait(timeout=0.2)
                continue
            job, pending = pending, None
            self._translate_job(job)

    def _translate_job(self, job: RecognitionJob) -> None:
        text = job.result.text.strip()
        japanese = self.cfg.conversation.japanese_code
        if job.speech_mode == "staff":
            with self._state_lock:
                target = self.state.input_language
                tts_enabled = self.state.tts_enabled
            source, target, direction = japanese, target, "reply"
        else:
            source, target, direction = job.language, japanese, "incoming"
            tts_enabled = False
        if get_language(source) is None or get_language(target) is None:
            self._log_perf("translation_skipped", utterance_id=job.utterance_id, reason="unsupported_language")
            return
        started = time.monotonic()
        self._log_perf("translation_started", utterance_id=job.utterance_id, speech_mode=job.speech_mode, source_language=source, target_language=target, stt_to_translation_queue_seconds=f"{max(0.0, started - (job.stt_started_at + job.stt_seconds)):.3f}")
        try:
            translated = self.translator.translate(text, source, target)
        except Exception as exc:
            self._log_perf("translation_failed", utterance_id=job.utterance_id, error=repr(exc))
            self._status("warning", f"번역 실패: {exc}")
            return
        finished = time.monotonic()
        translation_seconds = finished - started
        if job.speech_mode == "customer":
            with self._state_lock:
                self.state.active_language = source
                self.state.active_language_at = time.time()
                self.state.processed += 1
        else:
            with self._state_lock:
                self.state.processed += 1
        tts_queued = False
        request_id = 0
        if direction == "reply" and tts_enabled:
            try:
                request_id = self.speaker.speak(translated, target, utterance_id=job.utterance_id, speech_ended_at=job.speech_ended_at, translation_ready_at=finished) or 0
                tts_queued = bool(request_id)
            except Exception as exc:
                self._log_perf("tts_enqueue_failed", utterance_id=job.utterance_id, error=repr(exc))
        latency = max(0.0, finished - job.speech_ended_at) if job.speech_ended_at else translation_seconds
        self._log_perf("translation_done", utterance_id=job.utterance_id, speech_mode=job.speech_mode, direction=direction, source_language=source, target_language=target, stt_seconds=f"{job.stt_seconds:.3f}", translation_seconds=f"{translation_seconds:.3f}", speech_end_to_translation_seconds=f"{latency:.3f}", tts_queued=tts_queued, tts_request_id=request_id, text_characters=len(text))
        self.bus.publish("translation", direction=direction, source=text, translated=translated, source_language=source, target_language=target, speech_mode=job.speech_mode, audio_seconds=round(job.duration, 2), speech_seconds=round(job.speech_seconds, 2), vad_tail_seconds=round(job.vad_tail_seconds, 3), stt_seconds=round(job.stt_seconds, 2), translation_seconds=round(translation_seconds, 2), tts_queued=tts_queued, latency_seconds=round(latency, 2))
        self._status("listening", "듣는 중")

    def snapshot(self) -> dict:
        with self._state_lock:
            result = asdict(self.state)
        result["dropped"] += self.capture.dropped_utterances
        result["ready"] = self._ready.is_set()
        result["translator_ready"] = self._translator_ready.is_set()
        result["translator_failed"] = self._translator_failed.is_set()
        result["stt_queue_depth"] = self._utterances.qsize()
        result["translation_queue_depth"] = self._recognitions.qsize()
        result["tts_backend"] = self.cfg.tts.backend
        result["tts_online"] = self.cfg.tts.backend == "edge"
        return result

    def control(self, *, paused: bool | None = None, tts_enabled: bool | None = None, active_language: str | None = None, reply_language: str | None = None, speech_mode: str | None = None, input_device: str | int | None = None, output_device: str | int | None = None, enabled_languages: list[str] | None = None) -> dict:
        if speech_mode is not None and speech_mode not in {"customer", "staff"}:
            raise ValueError("speech_mode must be 'customer' or 'staff'")
        restart_capture = False
        previous_mode = None
        with self._state_lock:
            if enabled_languages is not None:
                valid = list(dict.fromkeys(str(code).lower().strip() for code in enabled_languages if code))
                if not valid or any(code == "ja" or get_language(code) is None for code in valid):
                    raise ValueError("At least one supported foreign language is required")
                self.state.enabled_languages = valid
                self.cfg.conversation.enabled_languages = valid
                if self.state.input_language not in valid:
                    self.state.input_language = valid[0]
                    self.state.active_language = valid[0]
            if active_language is not None:
                language = active_language.lower().strip()
                if language == "auto" or language == "ja" or language not in (self.state.enabled_languages or []) or get_language(language) is None:
                    raise ValueError("Choose one enabled customer language; automatic recognition is disabled")
                self.state.input_language = language
                self.state.active_language = language
                self.state.active_language_at = time.time()
                self.cfg.conversation.language_lock = language
            if reply_language is not None:
                self.state.reply_language = reply_language
            if speech_mode is not None:
                previous_mode = self.state.speech_mode
                self.state.speech_mode = speech_mode
            if paused is not None:
                self.state.paused = paused
            if tts_enabled is not None:
                self.state.tts_enabled = tts_enabled
                self.speaker.cfg.enabled = tts_enabled
            if input_device is not None and input_device != self.state.input_device:
                self.state.input_device = input_device
                self.cfg.audio.input_device = input_device
                restart_capture = True
            if output_device is not None:
                self.state.output_device = output_device
                self.cfg.audio.output_device = output_device
            forced = self.cfg.conversation.japanese_code if self.state.speech_mode == "staff" else self.state.input_language
        if hasattr(self.recognizer, "set_enabled_languages") and enabled_languages is not None:
            self.recognizer.set_enabled_languages(self.state.enabled_languages or [])
        if hasattr(self.recognizer, "set_selected_language"):
            self.recognizer.set_selected_language(forced)
        if hasattr(self.recognizer, "set_context_language"):
            self.recognizer.set_context_language(forced)
        # Space key enters staff mode. Stop older speech immediately so the
        # microphone becomes live for the employee's new utterance.
        if speech_mode == "staff" and previous_mode != "staff":
            self.speaker.interrupt(clear_queue=True, reason="staff_mode_started")
            self._log_perf("tts_interrupted_for_staff_mode")
        if paused:
            self.speaker.interrupt(clear_queue=True, reason="paused")
        if restart_capture:
            old = self.capture
            old.stop()
            if old.is_alive():
                old.join(timeout=3)
            self.capture = self._make_capture()
            if self._ready.is_set() and not self._stop.is_set():
                self.capture.start()
        state = self.snapshot()
        self.bus.publish("state", **state)
        return state
