from __future__ import annotations

import logging
import os
import queue
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol
from datetime import datetime

from .audio import AudioCapture, PlaybackGate, Utterance
from .config import AppConfig
from .events import EventBus
from .hymt2 import create_translator
from .languages import get_language
from .stt import Recognition, WhisperRecognizer
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
class PendingRecognition:
    result: Recognition
    language: str
    speech_mode: str
    duration: float
    started: float | None
    stt_seconds: float
    utterance_id: int
    speech_ended_at: float
    ready_at: float
    speech_seconds: float
    vad_tail_seconds: float


_NOISE_TEXT = re.compile(
    r"^(thank you|thanks for watching|subscribe|ご視聴ありがとうございました|字幕視聴ありがとうございました)$",
    re.IGNORECASE,
)


def _create_debug_logger() -> logging.Logger | None:
    """
    Create one timing log only when a controller actually starts.

    The prior controller-created log could come from a preview/controller that
    never started. Opening the file in start() avoids empty misleading files.
    """
    if os.getenv("REMOTEPLUS_DEBUG") != "1":
        return None

    project_root = Path(__file__).resolve().parent.parent
    log_dir = project_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    log_file = log_dir / f"timing-{run_id}.log"
    logger_name = f"remoteplus.timing.{os.getpid()}.{run_id}"

    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    handler = logging.FileHandler(
        log_file,
        mode="w",
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s.%(msecs)03d %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    logger.info("timing_log_started path=%s pid=%s", log_file, os.getpid())

    return logger


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

        enabled_languages = list(cfg.conversation.enabled_languages)
        customer_language = self._initial_customer_language(
            cfg,
            enabled_languages,
        )

        self.state = ConversationState(
            active_language=customer_language,
            input_language=customer_language,
            reply_language=cfg.conversation.reply_language,
            speech_mode="customer",
            input_device=cfg.audio.input_device,
            output_device=cfg.audio.output_device,
            enabled_languages=enabled_languages,
            active_language_at=time.time(),
            tts_enabled=cfg.tts.enabled,
        )

        self._state_lock = threading.Lock()
        self._pending_lock = threading.Lock()

        # A small queue is retained as a safety buffer, but the worker uses
        # latest-wins processing so stale speech is not translated late.
        self._utterances: queue.Queue[Utterance] = queue.Queue(maxsize=3)
        self._pending_recognition: PendingRecognition | None = None

        self._stop = threading.Event()
        self._ready = threading.Event()
        self._translator_ready = threading.Event()
        self._translator_failed = threading.Event()

        self._debug_logger: logging.Logger | None = None

        self.gate = PlaybackGate(cfg.audio.post_tts_mute_ms)
        self.recognizer = recognizer or WhisperRecognizer(cfg.stt, self._status)

        if hasattr(self.recognizer, "set_enabled_languages"):
            self.recognizer.set_enabled_languages(enabled_languages)

        if hasattr(self.recognizer, "set_selected_language"):
            self.recognizer.set_selected_language(customer_language)

        self.translator = translator or create_translator(
            cfg.translation,
            self._status,
        )

        self.speaker = SapiSpeaker(
            cfg.tts,
            cfg.audio,
            self.gate,
            self._status,
            metrics=self._log_perf,
        )

        self.capture = AudioCapture(
            cfg.audio,
            self._utterances,
            self.gate,
            self._status,
            metrics=self._log_perf,
            context=self._capture_context,
        )

        self._worker = threading.Thread(
            target=self._run,
            name="conversation",
            daemon=True,
        )

        self._translator_warmup: threading.Thread | None = None

    @staticmethod
    def _initial_customer_language(
        cfg: AppConfig,
        enabled_languages: list[str],
    ) -> str:
        configured = str(cfg.conversation.language_lock).lower()
        if configured != "auto" and configured != "ja":
            if get_language(configured) is not None:
                return configured

        for code in enabled_languages:
            normalized = str(code).lower()
            if normalized != "ja" and get_language(normalized) is not None:
                return normalized

        # The language setup screen will replace this before real use when
        # necessary. It avoids calling Whisper with language=None.
        return "en"

    def _capture_context(self) -> tuple[str, str]:
        """
        Snapshot the mode at VAD speech start.

        AudioCapture stores this snapshot with the utterance, so changing the
        staff button while the previous sentence is waiting cannot make it be
        transcribed in the wrong language.
        """
        with self._state_lock:
            mode = self.state.speech_mode
            customer_language = self.state.input_language

        if mode == "staff":
            return "staff", self.cfg.conversation.japanese_code

        return "customer", customer_language

    def start(self) -> None:
        if self._worker.is_alive():
            return

        self._debug_logger = _create_debug_logger()

        with self._state_lock:
            customer_language = self.state.input_language
            speech_mode = self.state.speech_mode

        self._log_perf(
            "run_started",
            pid=os.getpid(),
            customer_language=customer_language,
            speech_mode=speech_mode,
            tts_enabled=self.state.tts_enabled,
            live_preview=False,
            speech_control="space_hold",
        )

        self.speaker.start()
        self._worker.start()

    def stop(self) -> None:
        self._log_perf("run_stopping")
        self._stop.set()
        self.capture.stop()
        self.speaker.stop()

        if hasattr(self.translator, "close"):
            self.translator.close()

        for thread in (
            self.capture,
            self.speaker,
            self._translator_warmup,
            self._worker,
        ):
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
        """Record timings only; never write recognized or translated text."""
        if self._debug_logger is None:
            return

        details = " ".join(
            f"{key}={str(value).replace(chr(10), r'\\n').replace(chr(13), '')}"
            for key, value in fields.items()
        )
        self._debug_logger.info("%s %s", event, details)
        for handler in self._debug_logger.handlers:
            handler.flush()

    def _run(self) -> None:
        try:
            # Start translation server first, in parallel with Whisper model load.
            # The worker still waits for Whisper before opening the microphone.
            self._translator_warmup = threading.Thread(
                target=self._warm_translator,
                name="translator-warmup",
                daemon=True,
            )
            self._translator_warmup.start()

            whisper_started = time.monotonic()
            self._status("loading", "음성·번역 모델을 동시에 준비 중")
            self._log_perf("whisper_load_started")
            self.recognizer.load()

            whisper_load_seconds = time.monotonic() - whisper_started
            self._ready.set()
            self._log_perf("whisper_ready", seconds=f"{whisper_load_seconds:.3f}")

            if self._stop.is_set():
                return

            if not self.capture.is_alive():
                self.capture.start()

            if self._translator_ready.is_set():
                self._status("listening", "듣는 중 · 고객 언어 고정 / Space 누르는 동안 일본어")
            else:
                self._status("listening", "듣는 중 · 번역 엔진 준비 중")

            while not self._stop.is_set():
                pending = self._take_pending_recognition()
                if pending is not None:
                    try:
                        self.process_recognition(
                            pending.result,
                            pending.duration,
                            pending.started,
                            stt_seconds=pending.stt_seconds,
                            resolved_language=pending.language,
                            speech_mode=pending.speech_mode,
                            publish_transcript=False,
                            utterance_id=pending.utterance_id,
                            speech_ended_at=pending.speech_ended_at,
                            ready_at=pending.ready_at,
                            speech_seconds=pending.speech_seconds,
                            vad_tail_seconds=pending.vad_tail_seconds,
                        )
                    except Exception as exc:
                        self._log_perf(
                            "pending_translation_failed",
                            utterance_id=pending.utterance_id,
                            error=repr(exc),
                        )
                        self._status(
                            "error",
                            f"대기 중 문장 처리 실패: {exc}",
                        )
                    continue

                try:
                    item = self._utterances.get(timeout=0.2)
                except queue.Empty:
                    continue

                # Real-time policy: do not spend CPU on speech that is already
                # behind the current conversation. Keep only the newest item
                # that has not entered Whisper yet.
                superseded: list[Utterance] = []
                while True:
                    try:
                        newer = self._utterances.get_nowait()
                    except queue.Empty:
                        break
                    superseded.append(item)
                    item = newer

                if superseded:
                    with self._state_lock:
                        self.state.dropped += len(superseded)

                    for dropped in superseded:
                        self._log_perf(
                            "utterance_dropped",
                            utterance_id=dropped.utterance_id,
                            reason="superseded_by_newer_utterance",
                            replacement_utterance_id=item.utterance_id,
                        )

                with self._state_lock:
                    paused = self.state.paused

                if paused or self._stop.is_set():
                    self._log_perf(
                        "utterance_skipped",
                        utterance_id=item.utterance_id,
                        reason="paused_or_stopping",
                    )
                    continue

                if item.speech_mode == "staff":
                    forced_language = (
                        item.recognition_language
                        or self.cfg.conversation.japanese_code
                    )
                else:
                    with self._state_lock:
                        fallback_customer_language = self.state.input_language
                    forced_language = (
                        item.recognition_language
                        or fallback_customer_language
                    )

                # The recognizer receives the language captured at speech
                # start. This is the only language passed to Whisper.
                if hasattr(self.recognizer, "set_selected_language"):
                    self.recognizer.set_selected_language(forced_language)

                if hasattr(self.recognizer, "set_context_language"):
                    self.recognizer.set_context_language(forced_language)

                stt_started = time.monotonic()
                queue_wait_seconds = max(
                    0.0,
                    stt_started - item.ready_at,
                ) if item.ready_at else 0.0
                speech_end_to_stt_seconds = max(
                    0.0,
                    stt_started - item.speech_ended_at,
                ) if item.speech_ended_at else 0.0

                self._log_perf(
                    "stt_started",
                    utterance_id=item.utterance_id,
                    speech_mode=item.speech_mode,
                    forced_language=forced_language,
                    audio_seconds=f"{item.duration:.3f}",
                    speech_seconds=f"{item.speech_seconds:.3f}",
                    vad_tail_seconds=f"{item.vad_tail_seconds:.3f}",
                    queue_wait_seconds=f"{queue_wait_seconds:.3f}",
                    speech_end_to_stt_seconds=f"{speech_end_to_stt_seconds:.3f}",
                )

                self._status("recognizing", "음성 인식 중")

                try:
                    result = self.recognizer.transcribe(item.audio)
                    stt_finished = time.monotonic()
                    stt_seconds = stt_finished - stt_started
                    rtf = (
                        stt_seconds / item.duration
                        if item.duration > 0
                        else 0.0
                    )

                    self._log_perf(
                        "stt_done",
                        utterance_id=item.utterance_id,
                        speech_mode=item.speech_mode,
                        forced_language=forced_language,
                        audio_seconds=f"{item.duration:.3f}",
                        speech_seconds=f"{item.speech_seconds:.3f}",
                        stt_seconds=f"{stt_seconds:.3f}",
                        realtime_factor=f"{rtf:.3f}",
                        speech_end_to_stt_done_seconds=(
                            f"{max(0.0, stt_finished - item.speech_ended_at):.3f}"
                            if item.speech_ended_at
                            else "0.000"
                        ),
                        language=result.language,
                        probability=f"{result.probability:.3f}",
                    )

                    self.process_recognition(
                        result,
                        item.duration,
                        stt_started,
                        stt_seconds=stt_seconds,
                        resolved_language=forced_language,
                        speech_mode=item.speech_mode,
                        utterance_id=item.utterance_id,
                        speech_ended_at=item.speech_ended_at,
                        ready_at=item.ready_at,
                        speech_seconds=item.speech_seconds,
                        vad_tail_seconds=item.vad_tail_seconds,
                    )

                except Exception as exc:
                    self._log_perf(
                        "stt_failed",
                        utterance_id=item.utterance_id,
                        speech_mode=item.speech_mode,
                        forced_language=forced_language,
                        error=repr(exc),
                    )
                    self._status("error", f"처리 실패: {exc}")

        except Exception as exc:
            self._status("error", f"모델 초기화 실패: {exc}")
            self._log_perf(
                "worker_failed",
                error=repr(exc),
            )

    def _warm_translator(self) -> None:
        translator_started = time.monotonic()
        try:
            self._log_perf("translator_load_started")
            self.translator.load()

            if self._stop.is_set():
                return

            if getattr(self.translator, "ready", True) is False:
                self._translator_failed.set()
                self._clear_pending_recognition()
                self._status("warning", "번역 엔진을 준비하지 못했습니다.")
                self._log_perf("translator_failed", reason="ready_false")
                return

            process_seconds = time.monotonic() - translator_started
            self._log_perf("translator_process_ready", seconds=f"{process_seconds:.3f}")

            warmup_started = time.monotonic()
            if hasattr(self.translator, "warmup"):
                self.translator.warmup()
            warmup_seconds = time.monotonic() - warmup_started

            self._translator_ready.set()
            total_seconds = time.monotonic() - translator_started
            self._log_perf(
                "translator_ready",
                seconds=f"{total_seconds:.3f}",
                warmup_seconds=f"{warmup_seconds:.3f}",
            )

            if self._ready.is_set():
                self._status("listening", "듣는 중 · 고객 언어 고정 / Space 누르는 동안 일본어")

        except Exception as exc:
            self._translator_failed.set()
            self._clear_pending_recognition()
            self._status("warning", f"번역 엔진 백그라운드 준비 실패: {exc}")
            self._log_perf("translator_failed", error=repr(exc))

    def _store_pending_recognition(
        self,
        result: Recognition,
        language: str,
        speech_mode: str,
        duration: float,
        started: float | None,
        stt_seconds: float,
        *,
        utterance_id: int,
        speech_ended_at: float,
        ready_at: float,
        speech_seconds: float,
        vad_tail_seconds: float,
    ) -> None:
        pending = PendingRecognition(
            result=result,
            language=language,
            speech_mode=speech_mode,
            duration=duration,
            started=started,
            stt_seconds=stt_seconds,
            utterance_id=utterance_id,
            speech_ended_at=speech_ended_at,
            ready_at=ready_at,
            speech_seconds=speech_seconds,
            vad_tail_seconds=vad_tail_seconds,
        )

        with self._pending_lock:
            if self._pending_recognition is not None:
                with self._state_lock:
                    self.state.dropped += 1

                self._log_perf(
                    "pending_recognition_replaced",
                    utterance_id=self._pending_recognition.utterance_id,
                    replacement_utterance_id=utterance_id,
                    reason="translator_not_ready",
                )

            self._pending_recognition = pending

        self._log_perf(
            "translation_waiting_for_model",
            utterance_id=utterance_id,
            speech_mode=speech_mode,
            forced_language=language,
        )

    def _take_pending_recognition(self) -> PendingRecognition | None:
        if not self._translator_ready.is_set():
            return None

        with self._pending_lock:
            pending = self._pending_recognition
            self._pending_recognition = None
            return pending

    def _clear_pending_recognition(self) -> None:
        with self._pending_lock:
            self._pending_recognition = None

    def _resolve_language(self, result: Recognition) -> str:
        """
        Recognition is already forced to customer language or Japanese.
        Do not reinterpret text or invoke automatic language heuristics.
        """
        return result.language.lower()

    def process_recognition(
        self,
        result: Recognition,
        duration: float = 0.0,
        started: float | None = None,
        *,
        stt_seconds: float = 0.0,
        resolved_language: str | None = None,
        speech_mode: str = "customer",
        publish_transcript: bool = True,
        utterance_id: int = 0,
        speech_ended_at: float = 0.0,
        ready_at: float = 0.0,
        speech_seconds: float = 0.0,
        vad_tail_seconds: float = 0.0,
    ) -> None:
        text = result.text.strip()
        speech_mode = "staff" if speech_mode == "staff" else "customer"
        language = (
            resolved_language or self._resolve_language(result)
        ).lower()

        if not text or _NOISE_TEXT.match(text):
            self._log_perf(
                "recognition_skipped",
                utterance_id=utterance_id,
                speech_mode=speech_mode,
                reason="empty_or_noise",
            )
            self._status("listening", "듣는 중")
            return

        if get_language(language) is None:
            self._log_perf(
                "translation_skipped",
                utterance_id=utterance_id,
                speech_mode=speech_mode,
                reason="unsupported_language",
                language=language,
            )
            self._status(
                "warning",
                f"지원하지 않는 언어가 설정되었습니다: {language}",
            )
            return

        if publish_transcript:
            self.bus.publish(
                "transcript",
                text=text,
                language=language,
                probability=round(result.probability, 3),
            )

        if self._translator_failed.is_set():
            self._log_perf(
                "translation_skipped",
                utterance_id=utterance_id,
                speech_mode=speech_mode,
                reason="translator_failed",
            )
            return

        if not self._translator_ready.is_set():
            self._store_pending_recognition(
                result,
                language,
                speech_mode,
                duration,
                started,
                stt_seconds,
                utterance_id=utterance_id,
                speech_ended_at=speech_ended_at,
                ready_at=ready_at,
                speech_seconds=speech_seconds,
                vad_tail_seconds=vad_tail_seconds,
            )
            self._status("listening", "듣는 중 · 번역 엔진 준비 중")
            return

        translation_started = time.monotonic()
        speech_end_to_translation_start_seconds = max(
            0.0,
            translation_started - speech_ended_at,
        ) if speech_ended_at else 0.0

        japanese = self.cfg.conversation.japanese_code
        tts_queued = False
        tts_request_id = 0
        tts_enqueue_seconds = 0.0

        # Direction is determined only by the manual speaking mode.
        if speech_mode == "customer":
            source_code, target_code = language, japanese
            direction = "incoming"

            self._log_perf(
                "translation_started",
                utterance_id=utterance_id,
                speech_mode=speech_mode,
                source_language=source_code,
                target_language=target_code,
                speech_end_to_translation_start_seconds=(
                    f"{speech_end_to_translation_start_seconds:.3f}"
                ),
            )

            translated = self.translator.translate(
                text,
                source_code,
                target_code,
            )

            with self._state_lock:
                self.state.active_language = source_code
                self.state.active_language_at = time.time()
                self.state.processed += 1

        else:
            with self._state_lock:
                customer_language = self.state.input_language
                tts_enabled = self.state.tts_enabled

            # Staff mode always returns Japanese to the currently selected
            # customer language. There is no automatic "recent language"
            # lookup in this fast path.
            target_code = customer_language
            source_code = japanese
            direction = "reply"

            if get_language(target_code) is None or target_code == japanese:
                self._log_perf(
                    "translation_skipped",
                    utterance_id=utterance_id,
                    speech_mode=speech_mode,
                    reason="invalid_customer_target",
                    target_language=target_code,
                )
                self._status(
                    "warning",
                    "고객 언어를 먼저 선택하세요.",
                )
                return

            self._log_perf(
                "translation_started",
                utterance_id=utterance_id,
                speech_mode=speech_mode,
                source_language=source_code,
                target_language=target_code,
                speech_end_to_translation_start_seconds=(
                    f"{speech_end_to_translation_start_seconds:.3f}"
                ),
            )

            translated = self.translator.translate(
                text,
                source_code,
                target_code,
            )

            with self._state_lock:
                self.state.processed += 1

        translation_finished = time.monotonic()
        translation_seconds = translation_finished - translation_started
        processing_seconds = (
            translation_finished - started
            if started is not None
            else translation_seconds
        )
        speech_end_to_translation_seconds = max(
            0.0,
            translation_finished - speech_ended_at,
        ) if speech_ended_at else processing_seconds
        ready_to_translation_seconds = max(
            0.0,
            translation_finished - ready_at,
        ) if ready_at else processing_seconds

        if direction == "reply" and tts_enabled:
            tts_enqueue_started = time.monotonic()
            try:
                request_id = self.speaker.speak(
                    translated,
                    target_code,
                    utterance_id=utterance_id,
                    speech_ended_at=speech_ended_at,
                    translation_ready_at=translation_finished,
                )
                tts_request_id = request_id or 0
                tts_queued = request_id is not None
                tts_enqueue_seconds = (
                    time.monotonic() - tts_enqueue_started
                )
            except Exception as exc:
                self._log_perf(
                    "tts_enqueue_failed",
                    utterance_id=utterance_id,
                    error=repr(exc),
                )
                self._status("warning", f"TTS 요청 실패: {exc}")

        self._log_perf(
            "translation_done",
            utterance_id=utterance_id,
            speech_mode=speech_mode,
            direction=direction,
            source_language=source_code,
            target_language=target_code,
            audio_seconds=f"{duration:.3f}",
            speech_seconds=f"{speech_seconds:.3f}",
            vad_tail_seconds=f"{vad_tail_seconds:.3f}",
            stt_seconds=f"{stt_seconds:.3f}",
            translation_seconds=f"{translation_seconds:.3f}",
            stt_to_translation_ready_seconds=f"{processing_seconds:.3f}",
            vad_ready_to_translation_seconds=(
                f"{ready_to_translation_seconds:.3f}"
            ),
            speech_end_to_translation_seconds=(
                f"{speech_end_to_translation_seconds:.3f}"
            ),
            tts_queued=tts_queued,
            tts_request_id=tts_request_id,
            tts_enqueue_seconds=f"{tts_enqueue_seconds:.3f}",
            text_characters=len(text),
        )

        self.bus.publish(
            "translation",
            direction=direction,
            source=text,
            translated=translated,
            source_language=source_code,
            target_language=target_code,
            speech_mode=speech_mode,
            audio_seconds=round(duration, 2),
            speech_seconds=round(speech_seconds, 2),
            vad_tail_seconds=round(vad_tail_seconds, 3),
            stt_seconds=round(stt_seconds, 2),
            translation_seconds=round(translation_seconds, 2),
            tts_queued=tts_queued,
            tts_queue_seconds=round(tts_enqueue_seconds, 3),
            latency_seconds=round(speech_end_to_translation_seconds, 2),
            processing_seconds=round(processing_seconds, 2),
        )

        self._status("listening", "듣는 중")

    def snapshot(self) -> dict:
        with self._state_lock:
            result = asdict(self.state)

        with self._pending_lock:
            has_pending_recognition = self._pending_recognition is not None

        result["dropped"] += self.capture.dropped_utterances
        result["ready"] = self._ready.is_set()
        result["translator_ready"] = self._translator_ready.is_set()
        result["translator_failed"] = self._translator_failed.is_set()
        result["pending_recognition"] = has_pending_recognition

        return result

    def control(
        self,
        *,
        paused: bool | None = None,
        tts_enabled: bool | None = None,
        active_language: str | None = None,
        reply_language: str | None = None,
        speech_mode: str | None = None,
        input_device: str | int | None = None,
        output_device: str | int | None = None,
        enabled_languages: list[str] | None = None,
    ) -> dict:
        restart_capture = False

        if speech_mode is not None and speech_mode not in {"customer", "staff"}:
            raise ValueError("speech_mode must be 'customer' or 'staff'")

        if input_device is not None:
            if isinstance(input_device, str):
                valid_input = (
                    input_device == "default"
                    or (
                        input_device.startswith("loopback:")
                        and len(input_device) > 9
                    )
                    or input_device.isdigit()
                )
                if not valid_input:
                    raise ValueError(
                        "input_device must be a number, 'default', or a loopback device"
                    )
            elif not isinstance(input_device, int):
                raise ValueError(
                    "input_device must be a number or device identifier"
                )

        if output_device is not None and not (
            output_device == "default"
            or (
                isinstance(output_device, str)
                and output_device.startswith("output:")
                and len(output_device) > 7
            )
        ):
            raise ValueError(
                "output_device must be 'default' or an output device identifier"
            )

        forced_language: str | None = None

        with self._state_lock:
            if enabled_languages is not None:
                valid = list(
                    dict.fromkeys(
                        code.lower().strip()
                        for code in enabled_languages
                        if code
                    )
                )
                if not valid or any(
                    get_language(code) is None or code == "ja"
                    for code in valid
                ):
                    raise ValueError(
                        "At least one supported foreign language is required"
                    )

                self.state.enabled_languages = valid
                self.cfg.conversation.enabled_languages = valid

                # Automatic recognition is removed. Restore a real customer
                # language whenever older settings still say "auto".
                if self.state.input_language not in valid:
                    self.state.input_language = valid[0]
                    self.state.active_language = valid[0]
                    self.state.active_language_at = time.time()

                if self.state.reply_language not in {"auto", *valid}:
                    self.state.reply_language = "auto"
                    self.cfg.conversation.reply_language = "auto"

                if hasattr(self.recognizer, "set_enabled_languages"):
                    self.recognizer.set_enabled_languages(valid)

            if active_language is not None:
                language = active_language.lower().strip()
                if (
                    language == "auto"
                    or language == "ja"
                    or get_language(language) is None
                ):
                    raise ValueError(
                        "Choose one enabled customer language; automatic recognition is disabled"
                    )

                if language not in (self.state.enabled_languages or []):
                    raise ValueError(
                        f"Language is not enabled: {language}"
                    )

                self.state.input_language = language
                self.state.active_language = language
                self.state.active_language_at = time.time()
                self.cfg.conversation.language_lock = language

            if reply_language is not None:
                language = reply_language.lower().strip()
                if language != "auto" and language not in (
                    self.state.enabled_languages or []
                ):
                    raise ValueError(
                        f"Reply language is not enabled: {language}"
                    )
                self.state.reply_language = language
                self.cfg.conversation.reply_language = language

            if speech_mode is not None:
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

            forced_language = (
                self.cfg.conversation.japanese_code
                if self.state.speech_mode == "staff"
                else self.state.input_language
            )

        if hasattr(self.recognizer, "set_selected_language"):
            self.recognizer.set_selected_language(forced_language)

        if hasattr(self.recognizer, "set_context_language"):
            self.recognizer.set_context_language(forced_language)

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
                metrics=self._log_perf,
                context=self._capture_context,
            )

            if self._ready.is_set() and not self._stop.is_set():
                self.capture.start()

        state = self.snapshot()
        self.bus.publish("state", **state)
        return state

