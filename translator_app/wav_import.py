from __future__ import annotations

import copy
import re
import threading
import uuid
import wave
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Protocol

import numpy as np

from .audio import SpeechSegmenter, _resample_mono
from .config import AudioConfig
from .hymt2 import needs_conversation_context
from .languages import get_language
from .stt import Recognition, contains_japanese_kana

MAX_WAV_BYTES = 512 * 1024 * 1024
MAX_WAV_SECONDS = 60 * 60
MAX_RETAINED_JOBS = 5
MAX_SOURCE_SAMPLES = 120_000_000
RECORDED_END_SILENCE_MS = 600
RECORDED_MAX_UTTERANCE_MS = 15_000
RECORDED_MIN_SPEECH_MS = 240
RECORDED_PRE_ROLL_MS = 160
RECORDED_TAIL_KEEP_MS = 300
RECORDED_MIN_CONFIDENCE = -1.2
RECORDED_LOW_LANGUAGE_PROBABILITY = 0.45
RECORDED_LOW_LANGUAGE_MIN_CONFIDENCE = -0.8
_FILLER_ONLY = re.compile(
    r"(?iu)^\s*(?:i[\s,]+)?"
    r"(?:u+h+|u+m+|e+rm+|h+m+|a+h+|えー+と?|あー+|うー+)\s*[.,!?…ー-]*\s*$"
)


class RecognizerLike(Protocol):
    def load(self) -> None: ...

    def transcribe(
        self, audio: np.ndarray, *, language: str | None = None
    ) -> Recognition: ...


class TranslatorLike(Protocol):
    def load(self) -> None: ...

    def translate(self, text: str, source_code: str, target_code: str) -> str: ...


@dataclass(slots=True)
class WavAudio:
    samples: np.ndarray
    sample_rate: int
    source_channels: int
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class WavMetadata:
    channels: int
    sample_rate: int
    frames: int
    sample_width: int
    duration_seconds: float


@dataclass(slots=True)
class WavSegment:
    audio: np.ndarray
    start_seconds: float
    end_seconds: float


@dataclass(slots=True)
class WavEntry:
    index: int
    start_seconds: float
    end_seconds: float
    role: str
    source_language: str
    target_language: str
    source: str
    translated: str
    confidence: float | None


@dataclass(slots=True)
class RecognizedWavSegment:
    segment: WavSegment
    recognition: Recognition
    source_language: str
    target_language: str
    role: str
    text: str


@dataclass(slots=True)
class WavImportJob:
    id: str
    customer_language: str
    status: str = "queued"
    progress: float = 0.0
    processed_segments: int = 0
    total_segments: int = 0
    entries: list[WavEntry] = field(default_factory=list)
    error: str = ""

    def public_dict(self) -> dict:
        return asdict(self)


def _decode_pcm(raw: bytes, sample_width: int, channels: int) -> np.ndarray:
    if sample_width < 1 or len(raw) % (sample_width * channels):
        raise ValueError("WAV channel data is incomplete")
    if sample_width == 1:
        integers = np.frombuffer(raw, dtype=np.uint8)
        if channels > 1:
            values = integers.reshape(-1, channels).mean(axis=1, dtype=np.float32)
        else:
            values = integers.astype(np.float32)
        values = (values - 128.0) / 128.0
    elif sample_width == 2:
        integers = np.frombuffer(raw, dtype="<i2")
        if channels > 1:
            values = integers.reshape(-1, channels).mean(axis=1, dtype=np.float32)
        else:
            values = integers.astype(np.float32)
        values /= 32768.0
    elif sample_width == 3:
        packed = np.frombuffer(raw, dtype=np.uint8)
        if len(packed) % 3:
            raise ValueError("WAV contains an incomplete 24-bit sample")
        triples = packed.reshape(-1, 3).astype(np.int32)
        integers = triples[:, 0] | (triples[:, 1] << 8) | (triples[:, 2] << 16)
        integers = (integers ^ 0x800000) - 0x800000
        if channels > 1:
            values = integers.reshape(-1, channels).mean(axis=1, dtype=np.float32)
        else:
            values = integers.astype(np.float32)
        values /= 8388608.0
    elif sample_width == 4:
        integers = np.frombuffer(raw, dtype="<i4")
        if channels > 1:
            values = integers.reshape(-1, channels).mean(axis=1, dtype=np.float32)
        else:
            values = integers.astype(np.float32)
        values /= 2147483648.0
    else:
        raise ValueError("WAV sample width must be 8, 16, 24, or 32-bit PCM")
    return values


def _validate_wav_source(source: wave.Wave_read, file_size: int) -> WavMetadata:
    if file_size > MAX_WAV_BYTES:
        raise ValueError("WAV file is larger than 512 MB")
    if source.getcomptype() != "NONE":
        raise ValueError("Only uncompressed PCM WAV files are supported")
    channels = source.getnchannels()
    sample_rate = source.getframerate()
    frames = source.getnframes()
    sample_width = source.getsampwidth()
    if channels not in (1, 2):
        raise ValueError("WAV must contain one or two channels")
    if sample_width not in (1, 2, 3, 4):
        raise ValueError("WAV sample width must be 8, 16, 24, or 32-bit PCM")
    if sample_rate < 8000 or sample_rate > 192000:
        raise ValueError("WAV sample rate must be between 8 kHz and 192 kHz")
    if frames * channels > MAX_SOURCE_SAMPLES:
        raise ValueError("WAV has too many source samples; convert it to 16 kHz mono PCM")
    duration = frames / sample_rate if sample_rate else 0.0
    if duration <= 0 or duration > MAX_WAV_SECONDS:
        raise ValueError("WAV duration must be between 0 and 60 minutes")
    return WavMetadata(channels, sample_rate, frames, sample_width, duration)


def load_wav(path: Path, target_rate: int = 16000) -> WavAudio:
    try:
        with wave.open(str(path), "rb") as source:
            metadata = _validate_wav_source(source, path.stat().st_size)
            raw = source.readframes(metadata.frames)
    except (EOFError, wave.Error) as exc:
        raise ValueError(f"Invalid WAV file: {exc}") from exc
    expected_bytes = metadata.frames * metadata.channels * metadata.sample_width
    if len(raw) != expected_bytes:
        raise ValueError("WAV audio data is truncated")
    decoded = _decode_pcm(raw, metadata.sample_width, metadata.channels)
    samples = _resample_mono(decoded, metadata.sample_rate, target_rate)
    return WavAudio(samples, target_rate, metadata.channels, metadata.duration_seconds)


def segment_wav(samples: np.ndarray, cfg: AudioConfig) -> list[WavSegment]:
    segmenter = SpeechSegmenter(cfg)
    block = segmenter.block_samples
    segments: list[WavSegment] = []
    total_blocks = (len(samples) + block - 1) // block
    for index in range(total_blocks):
        frame = samples[index * block : (index + 1) * block]
        if len(frame) < block:
            frame = np.pad(frame, (0, block - len(frame)))
        result = segmenter.process(frame, (index + 1) * segmenter.block_seconds)
        if result is not None:
            segments.append(
                WavSegment(result.audio, result.speech_started_at, result.speech_ended_at)
            )
    for offset in range(segmenter.end_blocks + 1):
        result = segmenter.process(
            np.zeros(block, dtype=np.float32),
            (total_blocks + offset + 1) * segmenter.block_seconds,
        )
        if result is not None:
            segments.append(
                WavSegment(result.audio, result.speech_started_at, result.speech_ended_at)
            )
            break
    return segments


def segment_wav_file(
    path: Path,
    cfg: AudioConfig,
    cancelled: threading.Event,
) -> list[WavSegment]:
    """Segment a WAV with bounded input memory and prompt cancellation checks."""
    segmenter = SpeechSegmenter(cfg)
    block = segmenter.block_samples
    segments: list[WavSegment] = []
    pending = np.empty(0, dtype=np.float32)
    block_index = 0

    def process_block(frame: np.ndarray) -> None:
        nonlocal block_index
        if cancelled.is_set():
            raise InterruptedError("WAV import was cancelled")
        block_index += 1
        result = segmenter.process(frame, block_index * segmenter.block_seconds)
        if result is not None:
            segments.append(
                WavSegment(result.audio, result.speech_started_at, result.speech_ended_at)
            )

    try:
        with wave.open(str(path), "rb") as source:
            metadata = _validate_wav_source(source, path.stat().st_size)
            source_frames_read = 0
            while source_frames_read < metadata.frames:
                if cancelled.is_set():
                    raise InterruptedError("WAV import was cancelled")
                requested = min(metadata.sample_rate, metadata.frames - source_frames_read)
                raw = source.readframes(requested)
                actual = len(raw) // (metadata.sample_width * metadata.channels)
                if actual <= 0:
                    raise ValueError("WAV audio data is truncated")
                source_frames_read += actual
                decoded = _decode_pcm(raw, metadata.sample_width, metadata.channels)
                converted = _resample_mono(decoded, metadata.sample_rate, cfg.sample_rate)
                pending = np.concatenate((pending, converted)) if len(pending) else converted
                complete_samples = len(pending) - (len(pending) % block)
                for offset in range(0, complete_samples, block):
                    process_block(pending[offset : offset + block])
                pending = pending[complete_samples:].copy()
            if source_frames_read != metadata.frames:
                raise ValueError("WAV audio data is truncated")
    except (EOFError, wave.Error) as exc:
        raise ValueError(f"Invalid WAV file: {exc}") from exc

    if len(pending):
        process_block(np.pad(pending, (0, block - len(pending))))
    silence = np.zeros(block, dtype=np.float32)
    for _ in range(segmenter.end_blocks + 1):
        before = len(segments)
        process_block(silence)
        if len(segments) > before:
            break
    return segments


def _recorded_audio_config(cfg: AudioConfig) -> AudioConfig:
    """Use sentence-sized turns for call recordings without changing live capture."""
    end_silence_ms = max(cfg.end_silence_ms, RECORDED_END_SILENCE_MS)
    return replace(
        cfg,
        pre_roll_ms=max(cfg.pre_roll_ms, RECORDED_PRE_ROLL_MS),
        end_silence_ms=end_silence_ms,
        tail_keep_ms=min(
            end_silence_ms,
            max(cfg.tail_keep_ms, RECORDED_TAIL_KEEP_MS),
        ),
        min_speech_ms=max(cfg.min_speech_ms, RECORDED_MIN_SPEECH_MS),
        max_utterance_ms=max(
            cfg.max_utterance_ms,
            RECORDED_MAX_UTTERANCE_MS,
        ),
    )


def _usable_recorded_recognition(result: Recognition) -> bool:
    text = result.text.strip()
    if not text or _FILLER_ONLY.fullmatch(text):
        return False
    confidence = result.confidence
    if confidence is None:
        return True
    if confidence < RECORDED_MIN_CONFIDENCE:
        return False
    compact = re.sub(r"[\W_]+", "", text, flags=re.UNICODE)
    if len(compact) <= 4 and confidence < -1.0:
        return False
    return not (
        result.probability < RECORDED_LOW_LANGUAGE_PROBABILITY
        and confidence < RECORDED_LOW_LANGUAGE_MIN_CONFIDENCE
    )


class WavImportProcessor:
    def __init__(
        self,
        recognizer: RecognizerLike,
        translator: TranslatorLike,
        audio_config: AudioConfig,
        recognizer_lock: threading.Lock | None = None,
        translator_lock: threading.Lock | None = None,
    ):
        self.recognizer = recognizer
        self.translator = translator
        self.audio_config = audio_config
        self.recognizer_lock = recognizer_lock or threading.Lock()
        self.translator_lock = translator_lock or threading.Lock()

    def _recognize(self, audio: np.ndarray, language: str) -> Recognition:
        with self.recognizer_lock:
            self.recognizer.load()
            return self.recognizer.transcribe(audio, language=language)

    def _choose_recognition(
        self, audio: np.ndarray, customer_language: str
    ) -> tuple[Recognition, str]:
        automatic = self._recognize(audio, "auto")
        detected = automatic.language.casefold()
        text = automatic.text
        has_latin = bool(re.search(r"[A-Za-z]", text))
        has_japanese = contains_japanese_kana(text) or bool(
            re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", text)
        )
        # Auto language ID can label short English hotel terms as Japanese
        # (for example "check-out" and "credit card"). Trust the visible
        # script for these turns without running a second, slower decode.
        if detected == "ja" and has_latin and not has_japanese:
            return automatic, customer_language
        if detected != "ja" and contains_japanese_kana(text):
            return automatic, "ja"
        if get_language(detected) is not None:
            return automatic, detected
        if contains_japanese_kana(text):
            return automatic, "ja"
        # Whisper occasionally returns an unknown language code for a short
        # telephone turn while still producing usable Latin-script text.
        return automatic, customer_language

    def process(
        self,
        path: Path,
        customer_language: str,
        cancelled: threading.Event,
        progress: Callable[[int, int], None],
    ) -> list[WavEntry]:
        segments = segment_wav_file(
            path,
            _recorded_audio_config(self.audio_config),
            cancelled,
        )
        if not segments:
            raise ValueError(
                "No speech was found in the WAV file. Check the recording level or noise threshold."
            )
        total_steps = len(segments) * 2
        progress(0, total_steps)
        recognized: list[RecognizedWavSegment] = []
        for segment_index, segment in enumerate(segments, start=1):
            if cancelled.is_set():
                raise InterruptedError("WAV import was cancelled")
            recognition, source_language = self._choose_recognition(
                segment.audio, customer_language
            )
            text = recognition.text.strip()
            if not _usable_recorded_recognition(recognition):
                progress(segment_index, total_steps)
                continue
            if source_language == "ja":
                role = "staff"
                target_language = customer_language
            elif source_language == customer_language:
                role = "customer"
                target_language = "ja"
            else:
                role = "unknown"
                target_language = "ja"
            recognized.append(
                RecognizedWavSegment(
                    segment,
                    recognition,
                    source_language,
                    target_language,
                    role,
                    text,
                )
            )
            progress(segment_index, total_steps)
        if not recognized:
            raise ValueError(
                "Speech was detected, but no recognizable dialogue was found in the WAV file."
            )
        with self.translator_lock:
            self.translator.load()
        entries: list[WavEntry] = []
        for recognized_index, item in enumerate(recognized):
            if cancelled.is_set():
                raise InterruptedError("WAV import was cancelled")
            previous_text = recognized[recognized_index - 1].text if recognized_index else ""
            next_text = (
                recognized[recognized_index + 1].text
                if recognized_index + 1 < len(recognized)
                else ""
            )
            with self.translator_lock:
                if (
                    (previous_text or next_text)
                    and needs_conversation_context(item.text, item.source_language)
                    and hasattr(self.translator, "translate_contextual")
                ):
                    translated = self.translator.translate_contextual(
                        item.text,
                        item.source_language,
                        item.target_language,
                        previous_text=previous_text,
                        next_text=next_text,
                    )
                else:
                    translated = self.translator.translate(
                        item.text, item.source_language, item.target_language
                    )
            entries.append(
                WavEntry(
                    index=len(entries) + 1,
                    start_seconds=round(item.segment.start_seconds, 3),
                    end_seconds=round(item.segment.end_seconds, 3),
                    role=item.role,
                    source_language=item.source_language,
                    target_language=item.target_language,
                    source=item.text,
                    translated=translated,
                    confidence=(
                        round(item.recognition.confidence, 3)
                        if item.recognition.confidence is not None
                        else None
                    ),
                )
            )
            progress(len(segments) + recognized_index + 1, total_steps)
        progress(total_steps, total_steps)
        return entries


class WavImportManager:
    def __init__(self, processor: WavImportProcessor):
        self.processor = processor
        self._lock = threading.Lock()
        self._jobs: dict[str, WavImportJob] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}

    def _active_unlocked(self) -> bool:
        return any(
            job.status in {"queued", "processing", "cancelling"}
            for job in self._jobs.values()
        )

    def active(self) -> bool:
        with self._lock:
            return self._active_unlocked()

    def _prune_unlocked(self) -> None:
        completed = [
            job_id
            for job_id, job in self._jobs.items()
            if job.status in {"completed", "failed", "cancelled"}
        ]
        for job_id in completed[:-MAX_RETAINED_JOBS]:
            self._jobs.pop(job_id, None)
            self._cancel.pop(job_id, None)
            self._threads.pop(job_id, None)

    def submit(self, path: Path, customer_language: str) -> dict:
        customer_language = customer_language.casefold().strip()
        if customer_language == "ja" or get_language(customer_language) is None:
            raise ValueError("Select a supported non-Japanese customer language")
        with self._lock:
            if self._active_unlocked():
                raise RuntimeError("Another WAV import is already running")
            self._prune_unlocked()
            job = WavImportJob(uuid.uuid4().hex, customer_language)
            cancel = threading.Event()
            self._jobs[job.id] = job
            self._cancel[job.id] = cancel
            thread = threading.Thread(
                target=self._run,
                args=(job.id, path),
                name=f"wav-import-{job.id[:8]}",
                daemon=True,
            )
            self._threads[job.id] = thread
            try:
                thread.start()
            except Exception:
                self._jobs.pop(job.id, None)
                self._cancel.pop(job.id, None)
                self._threads.pop(job.id, None)
                path.unlink(missing_ok=True)
                raise
            return job.public_dict()

    def _run(self, job_id: str, path: Path) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "processing"
            cancel = self._cancel[job_id]

        def update(processed: int, total: int) -> None:
            with self._lock:
                current = self._jobs[job_id]
                current.processed_segments = processed
                current.total_segments = total
                current.progress = processed / total if total else 1.0

        try:
            entries = self.processor.process(
                path, job.customer_language, cancel, update
            )
            with self._lock:
                job.entries = entries
                job.progress = 1.0
                job.status = "cancelled" if cancel.is_set() else "completed"
        except InterruptedError:
            with self._lock:
                job.status = "cancelled"
        except Exception as exc:
            with self._lock:
                job.status = "failed"
                job.error = str(exc)
        finally:
            path.unlink(missing_ok=True)

    def status(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return copy.deepcopy(job.public_dict()) if job is not None else None

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status not in {"queued", "processing", "cancelling"}:
                return False
            job.status = "cancelling"
            self._cancel[job_id].set()
            return True

    def close(self) -> None:
        with self._lock:
            events = list(self._cancel.values())
            threads = list(self._threads.values())
        for event in events:
            event.set()
        for thread in threads:
            if thread.is_alive():
                thread.join(timeout=3.0)
