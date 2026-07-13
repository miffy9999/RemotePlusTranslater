from __future__ import annotations

import logging
import os
import queue
import re
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Protocol

from .audio import AudioCapture, LiveSnapshot, PlaybackGate, Utterance, validate_input_device
from .config import AppConfig
from .events import EventBus
from .hymt2 import create_translator
from .languages import get_language
from .stt import Recognition, WhisperRecognizer
from .tts import LEGACY_EDGE_OUTPUT_PREFIX, LOCAL_OUTPUT_PREFIX, LocalSpeaker


class RecognizerLike(Protocol):
    def load(self) -> None: ...
    def transcribe(self, audio, *, language: str | None = None) -> Recognition: ...


class TranslatorLike(Protocol):
    def load(self) -> None: ...
    def translate(self, text: str, source_code: str, target_code: str) -> str: ...


def _serialized_control(method):
    """Apply one complete UI control change before another one can begin.

    `_state_lock` protects individual fields. This wider lock protects the
    whole transaction: state -> recognizer context -> optional stream restart.
    """
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._control_lock:
            return method(self, *args, **kwargs)

    return wrapped


@dataclass(slots=True)
class ConversationState:
    phase: str = "starting"
    message: str = ""
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
    reply_language: str = "en"
    tts_enabled: bool = True


_NOISE_TEXT = re.compile(r"^(thanks for watching|subscribe|ご視聴ありがとうございました|字幕視聴ありがとうございました)$", re.IGNORECASE)

_FILLER_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    # Conservative, standalone fillers only. Do not remove words inside real terms.
    "ko": (
        re.compile(r"(?<!\S)(?:어+|음+|엄+|아+|에+)(?:요)?(?=\s|$|[,.!?…])", re.IGNORECASE),
    ),
    "ja": (
        re.compile(r"(?:(?<=^)|(?<=[\s、。,.!?！？]))(?:えー+|えっと|えーと|あのー*|あの|そのー*|まあ|まー|なんか)(?=$|[\s、。,.!?！？])"),
    ),
    "en": (
        re.compile(r"(?<!\w)(?:um+|uh+|er+|ah+|hmm+)(?!\w)", re.IGNORECASE),
    ),
}


def _clean_filler_text(text: str, language: str) -> tuple[str, int]:
    """Remove cheap standalone speech fillers before translation.

    This is deliberately regex-only and runs after final STT, never before or
    during STT/TTS. It avoids model calls, dictionary lookups, and network I/O.
    """
    cleaned = text.strip()
    if not cleaned:
        return cleaned, 0
    key = "ja" if language == "ja" else "ko" if language == "ko" else "en" if language == "en" else ""
    removed = 0
    for pattern in _FILLER_PATTERNS.get(key, ()): 
        cleaned, count = pattern.subn(" ", cleaned)
        removed += count
    if removed:
        cleaned = re.sub(r"\s+([,.!?。！？、])", r"\1", cleaned)
        cleaned = re.sub(r"([、。,.!?！？]){2,}", r"\1", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" \\t\\r\\n、。,.!?！？…")
    return cleaned, removed


def _create_debug_logger(data_root: Path) -> logging.Logger | None:
    if os.getenv("REMOTEPLUS_DEBUG") != "1":
        return None
    logger: logging.Logger | None = None
    handler: logging.Handler | None = None
    try:
        log_dir = data_root / "logs"
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
    except OSError:
        # Optional telemetry must not prevent the translator from starting.
        if handler is not None:
            try:
                handler.close()
            except OSError:
                pass
        if logger is not None and handler is not None:
            logger.removeHandler(handler)
        return None


class ConversationController:
    """Final-only latest-queue pipeline.

    Live preview is disabled in this profile because base preview competed with
    final Whisper and caused queue buildup during fast speech. The final small
    model gets the CPU, translation runs independently, and only the latest
    queued utterance is retained.
    """

    def __init__(self, cfg: AppConfig, bus: EventBus | None = None, recognizer: RecognizerLike | None = None, translator: TranslatorLike | None = None):
        self.cfg = cfg
        # Hard-disable live preview for this build. It was the main cause of
        # STT queue buildup on CPU-only machines.
        self.cfg.audio.live_preview_enabled = False
        self.cfg.audio.live_preview_final_grace_ms = 0
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
            paused=os.environ.get("REMOTEPLUS_START_PAUSED") == "1",
            tts_enabled=cfg.tts.enabled,
        )
        self._state_lock = threading.Lock()
        # Do not replace this with _state_lock: control() calls helpers that
        # need to take _state_lock themselves and may probe slow audio drivers.
        self._control_lock = threading.Lock()
        self._capture_lock = threading.Lock()
        self._latest_lock = threading.Lock()
        self._latest_started_by_mode: dict[str, int] = {"customer": 0, "staff": 0}
        self._live_lock = threading.Lock()
        self._live_decode_done: dict[int, threading.Event] = {}
        self._utterances: queue.Queue[Utterance] = queue.Queue(maxsize=1)
        self._recognitions: queue.Queue[RecognitionJob] = queue.Queue(maxsize=1)
        self._live_snapshots: queue.Queue[LiveSnapshot] = queue.Queue(maxsize=1)
        self._finalizing_ids: set[int] = set()
        self._finalized_ids: deque[int] = deque(maxlen=128)
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._live_ready = threading.Event()
        self._translator_ready = threading.Event()
        self._translator_failed = threading.Event()
        self._recognizing_active = threading.Event()
        self._translating_active = threading.Event()
        self._debug_logger: logging.Logger | None = None

        self.gate = PlaybackGate(cfg.audio.post_tts_mute_ms)
        self.recognizer = recognizer or WhisperRecognizer(cfg.stt, self._status, label="final")
        self.recognizer.set_enabled_languages(enabled) if hasattr(self.recognizer, "set_enabled_languages") else None
        self.recognizer.set_selected_language(customer) if hasattr(self.recognizer, "set_selected_language") else None
        self.live_recognizer: WhisperRecognizer | None = None
        self.translator = translator or create_translator(cfg.translation, self._status)
        self.speaker = LocalSpeaker(cfg.tts, cfg.audio, self.gate, self._status, metrics=self._log_perf)
        self.capture = self._make_capture()
        self._capture_started = False
        self._stt_worker = threading.Thread(target=self._run_stt, name="conversation-final-stt", daemon=True)
        self._live_worker = threading.Thread(target=self._run_live, name="conversation-live-stt", daemon=True)
        self._translation_worker = threading.Thread(target=self._run_translation, name="conversation-translation", daemon=True)
        self._translator_warmup: threading.Thread | None = None
        self._live_launcher: threading.Thread | None = None
        self._translator_warmup_lock = threading.Lock()

    @staticmethod
    def _initial_customer_language(cfg: AppConfig, enabled: list[str]) -> str:
        configured = str(cfg.conversation.language_lock).lower()
        if configured != "auto" and configured != "ja" and get_language(configured) is not None:
            return configured
        return next((str(code).lower() for code in enabled if str(code).lower() != "ja" and get_language(str(code).lower()) is not None), "en")

    def _make_capture(self) -> AudioCapture:
        with self._latest_lock:
            initial_id = max(self._latest_started_by_mode.values(), default=0)
        return AudioCapture(
            self.cfg.audio,
            self._utterances,
            self.gate,
            self._status,
            metrics=self._log_perf,
            context=self._capture_context,
            speech_started_sink=self._speech_started,
            live_snapshot_sink=(self._queue_live_snapshot if self.cfg.audio.live_preview_enabled else None),
            initial_utterance_id=initial_id,
        )

    def _capture_context(self) -> tuple[str, str, str, bool]:
        with self._state_lock:
            mode = self.state.speech_mode
            customer = self.state.input_language
            reply = self.state.reply_language
            target = reply if reply != "auto" else self.state.active_language or customer
            tts_enabled = self.state.tts_enabled
        if mode == "staff":
            return "staff", self.cfg.conversation.japanese_code, target, tts_enabled
        return "customer", customer, self.cfg.conversation.japanese_code, False

    def _speech_started(self, utterance_id: int, speech_mode: str, language: str) -> None:
        with self._latest_lock:
            self._latest_started_by_mode[speech_mode] = max(
                utterance_id, self._latest_started_by_mode.get(speech_mode, 0)
            )
        if hasattr(self.translator, "cancel_active_request"):
            try:
                if self.translator.cancel_active_request():
                    self._log_perf("translation_cancel_requested", replacement_utterance_id=utterance_id)
            except Exception:
                pass
        if speech_mode == "staff":
            self.speaker.interrupt(clear_queue=True, reason="staff_speech_started")
        self._log_perf("speech_started", utterance_id=utterance_id, speech_mode=speech_mode, forced_language=language)
        self.bus.publish("speech_started", utterance_id=utterance_id, speech_mode=speech_mode, language=language)

    def _start_capture_if_needed(self) -> None:
        with self._capture_lock:
            if self._capture_started and self.capture.is_alive():
                return
            if self._capture_started and not self.capture.is_alive():
                self.capture = self._make_capture()
            self.capture.start()
            self._capture_started = True

    def _is_stale(self, job: RecognitionJob) -> bool:
        with self._latest_lock:
            return job.utterance_id < max(self._latest_started_by_mode.values(), default=0)

    def start(self) -> None:
        if self._stt_worker.is_alive():
            return
        self._debug_logger = _create_debug_logger(self.cfg.data_root)
        self._log_perf(
            "run_started",
            pid=os.getpid(),
            customer_language=self.state.input_language,
            speech_mode=self.state.speech_mode,
            tts_enabled=self.state.tts_enabled,
            tts_backend="local",
            pipeline="final_only_latest_queue_no_live",
            live_preview=False,
            final_model=self.cfg.stt.model,
            speech_control="space_hold",
        )
        self.speaker.start()
        self._translation_worker.start()
        # The final model is authoritative. No live preview model is loaded in
        # this build, so there is no base-vs-small CPU competition.
        self._stt_worker.start()
        if self.cfg.audio.live_preview_enabled:
            self._live_launcher = threading.Thread(
                target=self._launch_live_after_final_ready,
                name="conversation-live-launcher",
                daemon=True,
            )
            self._live_launcher.start()

    def _ensure_translator_warmup_started(self) -> None:
        with self._translator_warmup_lock:
            if self._translator_warmup is not None:
                return
            self._translator_warmup = threading.Thread(
                target=self._warm_translator,
                name="translator-warmup",
                daemon=True,
            )
            self._translator_warmup.start()

    def stop(self) -> None:
        self._log_perf("run_stopping")
        self._stop.set()
        self.capture.stop()
        self.speaker.stop()
        # translate() owns the translator lock while waiting for SSE chunks.
        # Close its response first so close() does not wait for the full request
        # timeout when the operator exits during an active translation.
        if hasattr(self.translator, "cancel_active_request"):
            try:
                self.translator.cancel_active_request()
            except Exception:
                pass
        if hasattr(self.translator, "close"):
            self.translator.close()
        for thread in (self.capture, self.speaker, self._translator_warmup, self._live_launcher, self._stt_worker, self._live_worker, self._translation_worker):
            if thread is not None and thread.is_alive():
                thread.join(timeout=3)
        logger, self._debug_logger = self._debug_logger, None
        if logger is not None:
            for handler in tuple(logger.handlers):
                try:
                    handler.flush()
                    handler.close()
                except (OSError, ValueError):
                    pass
                finally:
                    logger.removeHandler(handler)

    def _status(self, phase: str, message: str = "") -> None:
        requested_phase = phase
        requested_message = message
        if self._recognizing_active.is_set() and phase in {"listening", "translating", "speaking", "warning"}:
            phase, message = "recognizing", "Recognizing"
        elif self._translating_active.is_set() and phase in {"listening", "speaking", "warning"}:
            phase, message = "translating", "Translating"
        with self._state_lock:
            self.state.phase = phase
            self.state.message = message
        self.bus.publish("status", phase=phase, message=message)
        if requested_phase in {"error", "warning"}:
            self.bus.publish(requested_phase, message=requested_message)

    def _log_perf(self, event: str, **fields: object) -> None:
        logger = self._debug_logger
        if logger is None:
            return
        escaped_newline = "\\n"
        details = " ".join(
            f"{key}={str(value).replace(chr(10), escaped_newline).replace(chr(13), '')}"
            for key, value in fields.items()
        )
        try:
            logger.info("%s %s", event, details)
            for handler in logger.handlers:
                handler.flush()
        except (OSError, ValueError):
            # Losing diagnostics is preferable to interrupting live audio.
            self._debug_logger = None

    @staticmethod
    def _take_latest(source: queue.Queue, first):
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

    def _is_finalizing(self, utterance_id: int) -> bool:
        with self._live_lock:
            return utterance_id in self._finalizing_ids or utterance_id in self._finalized_ids

    def _mark_finalizing(self, utterance_id: int) -> None:
        with self._live_lock:
            self._finalizing_ids.add(utterance_id)

    def _mark_finalized(self, utterance_id: int) -> None:
        with self._live_lock:
            self._finalizing_ids.discard(utterance_id)
            self._finalized_ids.append(utterance_id)

    def _live_decode_started(self, utterance_id: int) -> threading.Event:
        with self._live_lock:
            event = self._live_decode_done.get(utterance_id)
            if event is None:
                event = threading.Event()
                self._live_decode_done[utterance_id] = event
            return event

    def _live_decode_finished(self, utterance_id: int) -> None:
        with self._live_lock:
            event = self._live_decode_done.pop(utterance_id, None)
        if event is not None:
            event.set()

    def _wait_briefly_for_live_decode(self, utterance_id: int) -> float:
        grace_ms = max(0, int(self.cfg.audio.live_preview_final_grace_ms))
        if grace_ms <= 0:
            return 0.0
        with self._live_lock:
            event = self._live_decode_done.get(utterance_id)
        if event is None or event.is_set():
            return 0.0
        started = time.monotonic()
        event.wait(grace_ms / 1000)
        waited = time.monotonic() - started
        if waited:
            self._log_perf(
                "final_waited_for_live",
                utterance_id=utterance_id,
                wait_seconds=f"{waited:.3f}",
                live_finished=event.is_set(),
            )
        return waited

    def _queue_live_snapshot(self, snapshot: LiveSnapshot) -> None:
        if self._stop.is_set() or self._is_finalizing(snapshot.utterance_id):
            return
        with self._state_lock:
            paused = self.state.paused
        if paused or not self.cfg.audio.live_preview_enabled:
            return
        replaced: LiveSnapshot | None = None
        try:
            while True:
                replaced = self._live_snapshots.get_nowait()
        except queue.Empty:
            pass
        if replaced is not None:
            self._log_perf("live_snapshot_dropped", utterance_id=replaced.utterance_id, revision=replaced.revision, replacement_utterance_id=snapshot.utterance_id, replacement_revision=snapshot.revision, reason="newer_snapshot")
        try:
            self._live_snapshots.put_nowait(snapshot)
            self._log_perf("live_snapshot_queued", utterance_id=snapshot.utterance_id, revision=snapshot.revision, speech_seconds=f"{snapshot.speech_seconds:.3f}", audio_seconds=f"{len(snapshot.audio) / self.cfg.audio.sample_rate:.3f}")
        except queue.Full:
            pass

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
            with self._state_lock:
                self.state.dropped += 1
            self._log_perf("translation_job_dropped", utterance_id=job.utterance_id, reason="translation_queue_full")
            return
        self._log_perf("translation_job_queued", utterance_id=job.utterance_id, speech_mode=job.speech_mode, queue_depth=self._recognitions.qsize())

    def _launch_live_after_final_ready(self) -> None:
        """Start the live-caption model only when explicitly enabled."""
        if not self.cfg.audio.live_preview_enabled or self.live_recognizer is None:
            return
        self._log_perf("live_model_waiting_for_final")
        while not self._stop.is_set():
            if self._ready.wait(timeout=0.2):
                if not self._stop.is_set() and not self._live_worker.is_alive():
                    self._log_perf("live_model_starting_after_final_ready")
                    self._live_worker.start()
                return

    def _run_live(self) -> None:
        if not self.cfg.audio.live_preview_enabled or self.live_recognizer is None:
            return
        try:
            started = time.monotonic()
            self._log_perf("live_model_load_started", model=self.cfg.stt.live_model)
            self.live_recognizer.load()
            self._live_ready.set()
            self._log_perf("live_model_ready", seconds=f"{time.monotonic() - started:.3f}")
        except Exception as exc:
            self._log_perf("live_model_failed", error=repr(exc))
            self._status("warning", f"Live caption model unavailable: {exc}")
            return
        while not self._stop.is_set():
            try:
                snapshot = self._live_snapshots.get(timeout=0.2)
            except queue.Empty:
                continue
            snapshot, stale = self._take_latest(self._live_snapshots, snapshot)
            for old in stale:
                self._log_perf("live_snapshot_dropped", utterance_id=old.utterance_id, revision=old.revision, replacement_utterance_id=snapshot.utterance_id, replacement_revision=snapshot.revision, reason="superseded_before_decode")
            if self._is_finalizing(snapshot.utterance_id):
                self._log_perf("live_snapshot_skipped", utterance_id=snapshot.utterance_id, revision=snapshot.revision, reason="finalizing")
                continue
            started = time.monotonic()
            self._live_decode_started(snapshot.utterance_id)
            self._log_perf("live_stt_started", utterance_id=snapshot.utterance_id, revision=snapshot.revision, speech_mode=snapshot.speech_mode, forced_language=snapshot.recognition_language, audio_seconds=f"{len(snapshot.audio) / self.cfg.audio.sample_rate:.3f}")
            try:
                result = self.live_recognizer.transcribe(snapshot.audio, language=snapshot.recognition_language)
            except Exception as exc:
                self._log_perf("live_stt_failed", utterance_id=snapshot.utterance_id, revision=snapshot.revision, error=repr(exc))
                continue
            finally:
                self._live_decode_finished(snapshot.utterance_id)
            done = time.monotonic()
            if self._is_finalizing(snapshot.utterance_id):
                self._log_perf("live_stt_discarded", utterance_id=snapshot.utterance_id, revision=snapshot.revision, reason="final_started_before_publish")
                continue
            text = result.text.strip()
            self._log_perf("live_stt_done", utterance_id=snapshot.utterance_id, revision=snapshot.revision, stt_seconds=f"{done - started:.3f}", speech_start_to_preview_seconds=f"{max(0.0, done - snapshot.speech_started_at):.3f}", text_characters=len(text))
            if not text or _NOISE_TEXT.match(text):
                continue
            self.bus.publish(
                "preview",
                utterance_id=snapshot.utterance_id,
                revision=snapshot.revision,
                text=text,
                language=snapshot.recognition_language,
                speech_mode=snapshot.speech_mode,
                speech_seconds=round(snapshot.speech_seconds, 2),
            )

    def _run_stt(self) -> None:
        try:
            started = time.monotonic()
            self._status("loading", "Loading final speech model")
            self._log_perf("whisper_load_started", model=self.cfg.stt.model)
            self.recognizer.load()
            self._ready.set()
            self._log_perf("whisper_ready", seconds=f"{time.monotonic() - started:.3f}")
            if self._stop.is_set():
                return
            while not self._stop.is_set():
                with self._state_lock:
                    paused = self.state.paused
                if not paused:
                    break
                self._status("paused", "Models ready; paused")
                time.sleep(0.2)
            if self._stop.is_set():
                return
            self._ensure_translator_warmup_started()
            # Do not open the microphone until the final STT model AND the
            # translation engine are ready. This prevents input overflow/noise
            # warnings while models are still loading and avoids queued audio
            # being processed late.
            if not self._translator_ready.is_set() and not self._translator_failed.is_set():
                self._status("loading", "Loading translation model")
                while not self._stop.is_set() and not self._translator_ready.is_set() and not self._translator_failed.is_set():
                    time.sleep(0.05)
            if self._stop.is_set():
                return
            if self._translator_failed.is_set():
                self._status("warning", "Translation model failed")
                return
            with self._state_lock:
                paused = self.state.paused
            if paused:
                self._status("paused", "Models ready; paused")
            else:
                self._start_capture_if_needed()
                self._status("listening", "Models ready")
            while not self._stop.is_set():
                try:
                    item = self._utterances.get(timeout=0.2)
                except queue.Empty:
                    continue
                item, stale = self._take_latest(self._utterances, item)
                for old in stale:
                    self._mark_finalized(old.utterance_id)
                    with self._state_lock:
                        self.state.dropped += 1
                    self.bus.publish("preview_discard", utterance_id=old.utterance_id)
                    self._log_perf("utterance_dropped", utterance_id=old.utterance_id, replacement_utterance_id=item.utterance_id, reason="superseded_before_final_stt")
                with self._state_lock:
                    paused = self.state.paused
                if paused:
                    self._mark_finalized(item.utterance_id)
                    self.bus.publish("preview_discard", utterance_id=item.utterance_id)
                    self._log_perf("utterance_skipped", utterance_id=item.utterance_id, reason="paused")
                    continue
                self._mark_finalizing(item.utterance_id)
                forced = item.recognition_language
                if hasattr(self.recognizer, "set_selected_language"):
                    self.recognizer.set_selected_language(forced)
                if hasattr(self.recognizer, "set_context_language"):
                    self.recognizer.set_context_language(forced)
                stt_started = time.monotonic()
                queue_wait = max(0.0, stt_started - item.ready_at) if item.ready_at else 0.0
                self._log_perf("stt_started", utterance_id=item.utterance_id, speech_mode=item.speech_mode, forced_language=forced, audio_seconds=f"{item.duration:.3f}", speech_seconds=f"{item.speech_seconds:.3f}", vad_tail_seconds=f"{item.vad_tail_seconds:.3f}", queue_wait_seconds=f"{queue_wait:.3f}")
                self._recognizing_active.set()
                self._status("recognizing", "Recognizing")
                try:
                    result = self.recognizer.transcribe(item.audio, language=forced)
                except Exception as exc:
                    self._mark_finalized(item.utterance_id)
                    self.bus.publish("preview_discard", utterance_id=item.utterance_id)
                    self._log_perf("stt_failed", utterance_id=item.utterance_id, error=repr(exc))
                    self._status("error", f"Speech recognition failed: {exc}")
                    continue
                finally:
                    self._recognizing_active.clear()
                stt_seconds = time.monotonic() - stt_started
                self._mark_finalized(item.utterance_id)
                self._log_perf("stt_done", utterance_id=item.utterance_id, speech_mode=item.speech_mode, forced_language=forced, stt_seconds=f"{stt_seconds:.3f}", realtime_factor=f"{stt_seconds / item.duration:.3f}" if item.duration else "0.000", speech_end_to_stt_done_seconds=f"{max(0.0, time.monotonic()-item.speech_ended_at):.3f}" if item.speech_ended_at else "0.000", language=result.language, probability=f"{result.probability:.3f}", quality_retry=getattr(result, "quality_retry_used", False))
                text = result.text.strip()
                if self._is_stale(RecognitionJob(result, forced, item.speech_mode, item.duration, stt_started, stt_seconds, item.utterance_id, item.speech_ended_at, item.ready_at, item.speech_seconds, item.vad_tail_seconds, item.reply_language, item.tts_enabled)):
                    self.bus.publish("preview_discard", utterance_id=item.utterance_id)
                    self._log_perf("recognition_skipped", utterance_id=item.utterance_id, reason="newer_speech_started")
                    continue
                cleaned_text, filler_count = _clean_filler_text(text, forced)
                if filler_count:
                    self._log_perf(
                        "filler_removed",
                        utterance_id=item.utterance_id,
                        language=forced,
                        removed=filler_count,
                        original_characters=len(text),
                        cleaned_characters=len(cleaned_text),
                    )
                    text = cleaned_text
                    result = Recognition(text=text, language=forced, probability=result.probability)
                if not text or _NOISE_TEXT.match(text):
                    self.bus.publish("preview_discard", utterance_id=item.utterance_id)
                    self._log_perf("recognition_skipped", utterance_id=item.utterance_id, speech_mode=item.speech_mode, reason="empty_or_noise")
                    self._status("listening", "Listening")
                    continue
                self.bus.publish("transcript", utterance_id=item.utterance_id, text=text, language=forced, probability=round(result.probability, 3), final=True)
                self._put_latest_recognition(RecognitionJob(result, forced, item.speech_mode, item.duration, stt_started, stt_seconds, item.utterance_id, item.speech_ended_at, item.ready_at, item.speech_seconds, item.vad_tail_seconds, item.reply_language, item.tts_enabled))
                self._status("listening", "Listening")
        except Exception as exc:
            self._log_perf("stt_worker_failed", error=repr(exc))
            self._status("error", f"Speech recognition initialization failed: {exc}")

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
            with self._state_lock:
                preload_language = self.state.input_language
            if hasattr(self.speaker, "preload"):
                self.speaker.preload(preload_language)
            self.bus.publish("state", **self.snapshot())
        except Exception as exc:
            self._translator_failed.set()
            self._log_perf("translator_failed", error=repr(exc))
            self._status("warning", f"Translation engine unavailable: {exc}")
            self.bus.publish("state", **self.snapshot())

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
        if self._is_stale(job):
            self._log_perf("translation_job_dropped", utterance_id=job.utterance_id, reason="newer_speech_started")
            return
        text = job.result.text.strip()
        japanese = self.cfg.conversation.japanese_code
        if job.speech_mode == "staff":
            target = job.reply_language
            tts_enabled = job.tts_enabled
            source, target, direction = japanese, target, "reply"
        else:
            source, target, direction = job.language, japanese, "incoming"
            tts_enabled = False
        if get_language(source) is None or get_language(target) is None:
            self._log_perf("translation_skipped", utterance_id=job.utterance_id, reason="unsupported_language")
            return
        started = time.monotonic()
        self._translating_active.set()
        self._status("translating", "Translating")
        self._log_perf("translation_started", utterance_id=job.utterance_id, speech_mode=job.speech_mode, source_language=source, target_language=target, stt_to_translation_queue_seconds=f"{max(0.0, started - (job.stt_started_at + job.stt_seconds)):.3f}")
        try:
            translated = self.translator.translate(text, source, target)
        except Exception as exc:
            self._translating_active.clear()
            if self._is_stale(job):
                self._log_perf("translation_result_discarded", utterance_id=job.utterance_id, reason="cancelled_for_newer_speech")
                return
            self._log_perf("translation_failed", utterance_id=job.utterance_id, error=repr(exc))
            self._status("warning", f"Translation failed: {exc}")
            return
        finished = time.monotonic()
        if self._is_stale(job):
            self._translating_active.clear()
            self._log_perf("translation_result_discarded", utterance_id=job.utterance_id, reason="newer_speech_started")
            return
        self._translating_active.clear()
        translation_seconds = finished - started
        with self._state_lock:
            self.state.active_language = source if job.speech_mode == "customer" else self.state.input_language
            self.state.active_language_at = time.time()
            self.state.processed += 1
        tts_queued = False
        request_id = 0
        if direction == "reply" and tts_enabled:
            try:
                try:
                    request_id = self.speaker.speak(
                        translated,
                        target,
                        utterance_id=job.utterance_id,
                        speech_ended_at=job.speech_ended_at,
                        translation_ready_at=finished,
                    ) or 0
                except TypeError:
                    request_id = self.speaker.speak(translated, target) or 0
                tts_queued = bool(request_id)
            except Exception as exc:
                self._log_perf("tts_enqueue_failed", utterance_id=job.utterance_id, error=repr(exc))
        latency = max(0.0, finished - job.speech_ended_at) if job.speech_ended_at else translation_seconds
        self._log_perf("translation_done", utterance_id=job.utterance_id, speech_mode=job.speech_mode, direction=direction, source_language=source, target_language=target, stt_seconds=f"{job.stt_seconds:.3f}", translation_seconds=f"{translation_seconds:.3f}", speech_end_to_translation_seconds=f"{latency:.3f}", tts_queued=tts_queued, tts_request_id=request_id, text_characters=len(text))
        self.bus.publish("translation", utterance_id=job.utterance_id, final=True, direction=direction, source=text, translated=translated, source_language=source, target_language=target, speech_mode=job.speech_mode, audio_seconds=round(job.duration, 2), speech_seconds=round(job.speech_seconds, 2), vad_tail_seconds=round(job.vad_tail_seconds, 3), stt_seconds=round(job.stt_seconds, 2), translation_seconds=round(translation_seconds, 2), tts_queued=tts_queued, latency_seconds=round(latency, 2))
        self._status("listening", "Listening")

    def process_recognition(self, result: Recognition) -> None:
        """Exercise the same fixed-language routing as the production pipeline.

        This helper bypasses audio/STT timing only; it deliberately does not
        infer a mode or language from Recognition because production does not.
        """
        text = result.text.strip()
        if not text:
            return
        japanese = self.cfg.conversation.japanese_code
        with self._state_lock:
            selected = self.state.input_language
            active = self.state.active_language or selected
            reply = self.state.reply_language
            tts_enabled = self.state.tts_enabled
            selected_mode = self.state.speech_mode
        if selected_mode == "staff":
            language = japanese
            speech_mode = "staff"
        else:
            language = selected
            speech_mode = "customer"
        job = RecognitionJob(
            Recognition(text, language, result.probability),
            language,
            speech_mode,
            0.0,
            time.monotonic(),
            0.0,
            0,
            time.monotonic(),
            time.monotonic(),
            0.0,
            0.0,
            reply if reply != "auto" else active,
            tts_enabled,
        )
        self._translate_job(job)

    def snapshot(self) -> dict:
        with self._state_lock:
            if self.cfg.audio.output_device != self.state.output_device:
                self.state.output_device = self.cfg.audio.output_device
            result = asdict(self.state)
        result["dropped"] += self.capture.dropped_utterances
        result["dropped_frames"] = self.capture.dropped_frames
        result["ready"] = self._ready.is_set()
        result["live_ready"] = False
        translator_alive = True
        if hasattr(self.translator, "is_available"):
            try:
                translator_alive = bool(self.translator.is_available())
            except Exception:
                translator_alive = False
        result["translator_ready"] = self._translator_ready.is_set() and translator_alive
        result["translator_failed"] = self._translator_failed.is_set()
        if self._translator_ready.is_set() and not translator_alive:
            result["phase"] = "warning"
            result["message"] = "Translation engine stopped"
        elif result["ready"] and result["translator_ready"] and (
            result.get("phase") in {"starting", "loading"}
            or result.get("message") == "Translation engine stopped"
        ):
            result["phase"] = "listening"
            result["message"] = "Models ready"
        result["stt_queue_depth"] = self._utterances.qsize()
        result["live_queue_depth"] = 0
        result["translation_queue_depth"] = self._recognitions.qsize()
        result["tts_backend"] = self.cfg.tts.backend
        result["tts_online"] = False
        installed = self.speaker.installed_languages() if hasattr(self.speaker, "installed_languages") else set()
        result["tts_installed_languages"] = sorted(installed)
        reply_target = result.get("reply_language")
        if reply_target == "auto":
            reply_target = result.get("active_language") or result.get("input_language")
        result["tts_available"] = bool(not hasattr(self.speaker, "supports") or self.speaker.supports(str(reply_target or "")))
        result["pipeline"] = "final_only_latest_queue_no_live"
        return result

    def replay_tts(self, text: str, language: str) -> int:
        """Speak a completed reply again when automatic playback was interrupted."""
        clean = text.strip()
        target = language.strip().lower()
        if not clean or len(clean) > 1000:
            raise ValueError("Replay text must contain 1 to 1000 characters")
        with self._state_lock:
            enabled = self.state.tts_enabled
            allowed = set(self.state.enabled_languages or [])
        if not enabled:
            raise ValueError("Enable TTS before replaying a reply")
        if target not in allowed or get_language(target) is None:
            raise ValueError("Replay language is not enabled")
        if hasattr(self.speaker, "supports") and not self.speaker.supports(target):
            raise ValueError(f"No verified local voice pack is installed for '{target}'")
        try:
            request_id = self.speaker.speak(clean, target) or 0
        except TypeError:
            request_id = self.speaker.speak(clean, target) or 0
        self._log_perf(
            "tts_replay_queued",
            request_id=request_id,
            target_language=target,
            text_characters=len(clean),
        )
        return request_id

    @_serialized_control
    def control(self, *, paused: bool | None = None, tts_enabled: bool | None = None, active_language: str | None = None, reply_language: str | None = None, speech_mode: str | None = None, input_device: str | int | None = None, output_device: str | int | None = None, enabled_languages: list[str] | None = None) -> dict:
        if speech_mode is not None and speech_mode not in {"customer", "staff"}:
            raise ValueError("speech_mode must be 'customer' or 'staff'")
        previous_input_device: str | int | None = None
        if input_device is not None:
            with self._state_lock:
                previous_input_device = self.state.input_device
                input_changed = input_device != self.state.input_device
            if input_changed:
                # Device probing can block on COM/driver calls. Never hold the
                # state lock needed by the live audio context while probing.
                validate_input_device(input_device)
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
                if self.state.reply_language != "auto" and self.state.reply_language not in valid:
                    self.state.reply_language = "auto"
            if active_language is not None:
                language = active_language.lower().strip()
                if language == "auto" or language == "ja" or language not in (self.state.enabled_languages or []) or get_language(language) is None:
                    raise ValueError("Choose one enabled customer language; automatic recognition is disabled")
                self.state.input_language = language
                self.state.active_language = language
                self.state.active_language_at = time.time()
                self.cfg.conversation.language_lock = language
            if reply_language is not None:
                language = reply_language.lower().strip()
                if language != "auto" and (language == "ja" or language not in (self.state.enabled_languages or []) or get_language(language) is None):
                    raise ValueError("Reply language must be auto or an enabled customer language")
                self.state.reply_language = language
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
                if output_device != "default" and not str(output_device).startswith(
                    (LOCAL_OUTPUT_PREFIX, LEGACY_EDGE_OUTPUT_PREFIX)
                ):
                    raise ValueError("output_device must be 'default' or a local TTS output device")
                self.state.output_device = output_device
                self.cfg.audio.output_device = output_device
            forced = self.cfg.conversation.japanese_code if self.state.speech_mode == "staff" else self.state.input_language
            enabled_snapshot = list(self.state.enabled_languages or [])
            paused_snapshot = self.state.paused
            reply_target = (
                self.state.reply_language
                if self.state.reply_language != "auto"
                else self.state.active_language or self.state.input_language
            )
            tts_snapshot = self.state.tts_enabled
        if speech_mode == "staff" and previous_mode != "staff":
            self.capture.promote_active_to_staff(
                self.cfg.conversation.japanese_code,
                reply_target,
                tts_snapshot,
            )
        for recognizer in (self.recognizer, self.live_recognizer):
            if recognizer is None:
                continue
            if hasattr(recognizer, "set_enabled_languages"):
                recognizer.set_enabled_languages(enabled_snapshot)
            if hasattr(recognizer, "set_selected_language"):
                recognizer.set_selected_language(forced)
            if hasattr(recognizer, "set_context_language"):
                recognizer.set_context_language(forced)
        if speech_mode == "staff" and previous_mode != "staff":
            self.speaker.interrupt(clear_queue=True, reason="staff_mode_started")
            self._log_perf("tts_interrupted_for_staff_mode")
        if paused:
            self.speaker.interrupt(clear_queue=True, reason="paused")
        elif paused is False and self._ready.is_set() and self._translator_ready.is_set() and not self._stop.is_set():
            self._start_capture_if_needed()
            self._status("listening", "Listening")
        if restart_capture:
            with self._capture_lock:
                old = self.capture
                old.stop()
                if old.is_alive():
                    old.join(timeout=3)
                if old.is_alive():
                    # The request has already updated the shared config, but
                    # the old stream is still the only live stream. Roll the
                    # advertised device back so API/UI and reality agree.
                    with self._state_lock:
                        self.state.input_device = previous_input_device
                        self.cfg.audio.input_device = previous_input_device
                    raise ValueError("Previous audio stream did not stop; device was not changed")
                self.capture = self._make_capture()
                self._capture_started = False
            if self._ready.is_set() and self._translator_ready.is_set() and not self._stop.is_set() and not paused_snapshot:
                self._start_capture_if_needed()
        if active_language is not None and hasattr(self.speaker, "preload"):
            self.speaker.preload(active_language)
        state = self.snapshot()
        self.bus.publish("state", **state)
        return state
