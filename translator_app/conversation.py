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
from pathlib import Path
from typing import Protocol

from .audio import AudioCapture, LiveSnapshot, PlaybackGate, Utterance
from .config import AppConfig, sounddevice_value
from .events import EventBus
from .hymt2 import create_translator
from .languages import get_language
from .stt import Recognition, WhisperRecognizer, contains_japanese_kana
from .tts import EdgeSpeaker


class RecognizerLike(Protocol):
    def load(self) -> None: ...
    def transcribe(self, audio, *, language: str | None = None) -> Recognition: ...


class TranslatorLike(Protocol):
    def load(self) -> None: ...
    def translate(self, text: str, source_code: str, target_code: str) -> str: ...


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


_NOISE_TEXT = re.compile(r"^(thank you|thanks for watching|subscribe|ご視聴ありがとうございました|字幕視聴ありがとうございました)$", re.IGNORECASE)

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
        self._debug_logger: logging.Logger | None = None

        self.gate = PlaybackGate(cfg.audio.post_tts_mute_ms)
        self.recognizer = recognizer or WhisperRecognizer(cfg.stt, self._status, label="final")
        self.recognizer.set_enabled_languages(enabled) if hasattr(self.recognizer, "set_enabled_languages") else None
        self.recognizer.set_selected_language(customer) if hasattr(self.recognizer, "set_selected_language") else None
        self.live_recognizer: WhisperRecognizer | None = None
        self.translator = translator or create_translator(cfg.translation, self._status)
        self.speaker = EdgeSpeaker(cfg.tts, cfg.audio, self.gate, self._status, metrics=self._log_perf)
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
        return AudioCapture(
            self.cfg.audio,
            self._utterances,
            self.gate,
            self._status,
            metrics=self._log_perf,
            context=self._capture_context,
            speech_started_sink=self._speech_started,
            live_snapshot_sink=(self._queue_live_snapshot if self.cfg.audio.live_preview_enabled else None),
        )

    def _capture_context(self) -> tuple[str, str]:
        with self._state_lock:
            mode = self.state.speech_mode
            customer = self.state.input_language
        return ("staff", self.cfg.conversation.japanese_code) if mode == "staff" else ("customer", customer)

    def _speech_started(self, utterance_id: int, speech_mode: str, language: str) -> None:
        self._log_perf("speech_started", utterance_id=utterance_id, speech_mode=speech_mode, forced_language=language)
        self.bus.publish("speech_started", utterance_id=utterance_id, speech_mode=speech_mode, language=language)

    def _start_capture_if_needed(self) -> None:
        if self._capture_started and self.capture.is_alive():
            return
        if self._capture_started and not self.capture.is_alive():
            self.capture = self._make_capture()
        self.capture.start()
        self._capture_started = True

    def start(self) -> None:
        if self._stt_worker.is_alive():
            return
        self._debug_logger = _create_debug_logger()
        self._log_perf(
            "run_started",
            pid=os.getpid(),
            customer_language=self.state.input_language,
            speech_mode=self.state.speech_mode,
            tts_enabled=self.state.tts_enabled,
            tts_backend="edge",
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
        if hasattr(self.translator, "close"):
            self.translator.close()
        for thread in (self.capture, self.speaker, self._translator_warmup, self._live_launcher, self._stt_worker, self._live_worker, self._translation_worker):
            if thread is not None and thread.is_alive():
                thread.join(timeout=3)

    def _status(self, phase: str, message: str = "") -> None:
        with self._state_lock:
            self.state.phase = phase
            self.state.message = message
        self.bus.publish("status", phase=phase, message=message)
        if phase in {"error", "warning"}:
            self.bus.publish(phase, message=message)

    def _log_perf(self, event: str, **fields: object) -> None:
        if self._debug_logger is None:
            return
        escaped_newline = "\\n"
        details = " ".join(
            f"{key}={str(value).replace(chr(10), escaped_newline).replace(chr(13), '')}"
            for key, value in fields.items()
        )
        self._debug_logger.info("%s %s", event, details)
        for handler in self._debug_logger.handlers:
            handler.flush()

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
                forced = item.recognition_language or (self.cfg.conversation.japanese_code if item.speech_mode == "staff" else self.state.input_language)
                if hasattr(self.recognizer, "set_selected_language"):
                    self.recognizer.set_selected_language(forced)
                if hasattr(self.recognizer, "set_context_language"):
                    self.recognizer.set_context_language(forced)
                stt_started = time.monotonic()
                queue_wait = max(0.0, stt_started - item.ready_at) if item.ready_at else 0.0
                self._log_perf("stt_started", utterance_id=item.utterance_id, speech_mode=item.speech_mode, forced_language=forced, audio_seconds=f"{item.duration:.3f}", speech_seconds=f"{item.speech_seconds:.3f}", vad_tail_seconds=f"{item.vad_tail_seconds:.3f}", queue_wait_seconds=f"{queue_wait:.3f}")
                self._status("recognizing", "Recognizing")
                try:
                    result = self.recognizer.transcribe(item.audio, language=forced)
                except Exception as exc:
                    self._mark_finalized(item.utterance_id)
                    self.bus.publish("preview_discard", utterance_id=item.utterance_id)
                    self._log_perf("stt_failed", utterance_id=item.utterance_id, error=repr(exc))
                    self._status("error", f"Speech recognition failed: {exc}")
                    continue
                stt_seconds = time.monotonic() - stt_started
                self._mark_finalized(item.utterance_id)
                self._log_perf("stt_done", utterance_id=item.utterance_id, speech_mode=item.speech_mode, forced_language=forced, stt_seconds=f"{stt_seconds:.3f}", realtime_factor=f"{stt_seconds / item.duration:.3f}" if item.duration else "0.000", speech_end_to_stt_done_seconds=f"{max(0.0, time.monotonic()-item.speech_ended_at):.3f}" if item.speech_ended_at else "0.000", language=result.language, probability=f"{result.probability:.3f}")
                text = result.text.strip()
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
                self._put_latest_recognition(RecognitionJob(result, forced, item.speech_mode, item.duration, stt_started, stt_seconds, item.utterance_id, item.speech_ended_at, item.ready_at, item.speech_seconds, item.vad_tail_seconds))
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
        except Exception as exc:
            self._translator_failed.set()
            self._log_perf("translator_failed", error=repr(exc))
            self._status("warning", f"Translation engine unavailable: {exc}")

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
                target = (
                    self.state.reply_language
                    if self.state.reply_language != "auto"
                    else self.state.active_language or self.state.input_language
                )
                tts_enabled = self.state.tts_enabled
            source, target, direction = japanese, target, "reply"
        else:
            source, target, direction = job.language, japanese, "incoming"
            tts_enabled = False
        if get_language(source) is None or get_language(target) is None:
            self._log_perf("translation_skipped", utterance_id=job.utterance_id, reason="unsupported_language")
            return
        started = time.monotonic()
        self._status("translating", "Translating")
        self._log_perf("translation_started", utterance_id=job.utterance_id, speech_mode=job.speech_mode, source_language=source, target_language=target, stt_to_translation_queue_seconds=f"{max(0.0, started - (job.stt_started_at + job.stt_seconds)):.3f}")
        try:
            translated = self.translator.translate(text, source, target)
        except Exception as exc:
            self._log_perf("translation_failed", utterance_id=job.utterance_id, error=repr(exc))
            self._status("warning", f"Translation failed: {exc}")
            return
        finished = time.monotonic()
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
        text = result.text.strip()
        if not text:
            return
        japanese = self.cfg.conversation.japanese_code
        with self._state_lock:
            selected = self.state.input_language
            active = self.state.active_language or selected
            enabled = set(self.state.enabled_languages or [])
        is_staff = result.language == japanese or contains_japanese_kana(text)
        if is_staff:
            language = japanese
            speech_mode = "staff"
        elif result.probability >= self.cfg.conversation.minimum_language_probability and result.language in enabled:
            language = result.language
            speech_mode = "customer"
        else:
            language = active or selected
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
        )
        self._translate_job(job)

    def snapshot(self) -> dict:
        with self._state_lock:
            result = asdict(self.state)
        result["dropped"] += self.capture.dropped_utterances
        result["ready"] = self._ready.is_set()
        result["live_ready"] = False
        result["translator_ready"] = self._translator_ready.is_set()
        result["translator_failed"] = self._translator_failed.is_set()
        if result["ready"] and result["translator_ready"] and result.get("phase") in {"starting", "loading"}:
            result["phase"] = "listening"
            result["message"] = "Models ready"
        result["stt_queue_depth"] = self._utterances.qsize()
        result["live_queue_depth"] = 0
        result["translation_queue_depth"] = self._recognitions.qsize()
        result["tts_backend"] = self.cfg.tts.backend
        result["tts_online"] = self.cfg.tts.backend == "edge"
        result["pipeline"] = "final_only_latest_queue_no_live"
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
                if isinstance(input_device, str) and input_device.startswith("loopback:"):
                    pass
                else:
                    sounddevice_value(input_device)
                self.state.input_device = input_device
                self.cfg.audio.input_device = input_device
                restart_capture = True
            if output_device is not None:
                self.state.output_device = output_device
                self.cfg.audio.output_device = output_device
            forced = self.cfg.conversation.japanese_code if self.state.speech_mode == "staff" else self.state.input_language
        for recognizer in (self.recognizer, self.live_recognizer):
            if recognizer is None:
                continue
            if hasattr(recognizer, "set_enabled_languages"):
                recognizer.set_enabled_languages(self.state.enabled_languages or [])
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
            old = self.capture
            old.stop()
            if old.is_alive():
                old.join(timeout=3)
            self.capture = self._make_capture()
            self._capture_started = False
            if self._ready.is_set() and not self._stop.is_set() and not self.state.paused:
                self._start_capture_if_needed()
        state = self.snapshot()
        self.bus.publish("state", **state)
        return state
