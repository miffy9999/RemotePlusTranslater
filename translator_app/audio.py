from __future__ import annotations

import ctypes.util
import math
import queue
import threading
import time
import warnings
from collections import deque
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .config import AudioConfig, sounddevice_value

LOOPBACK_PREFIX = "loopback:"
OUTPUT_PREFIX = "output:"
MetricsCallback = Callable[..., None]
SpeechContext = Callable[[], tuple[str, str]]
SpeechStartedSink = Callable[[int, str, str], None]
LiveSnapshotSink = Callable[["LiveSnapshot"], None]


def _load_soundcard():
    original = ctypes.util.find_library

    def windows_library(name: str) -> str | None:
        if name.lower() in {"ole32", "avrt"}:
            return f"{name}.dll"
        return original(name)

    ctypes.util.find_library = windows_library
    try:
        import soundcard
        return soundcard
    finally:
        ctypes.util.find_library = original


def _resample_mono(frame: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    data = np.asarray(frame, dtype=np.float32)
    data = data.mean(axis=1) if data.ndim == 2 else data.reshape(-1)
    if source_rate == target_rate or len(data) < 2:
        return data
    target_length = max(1, round(len(data) * target_rate / source_rate))
    return np.interp(
        np.linspace(0, len(data) - 1, target_length),
        np.arange(len(data), dtype=np.float64),
        data,
    ).astype(np.float32)


@dataclass(slots=True)
class Utterance:
    audio: np.ndarray
    captured_at: float
    duration: float
    speech_started_at: float = 0.0
    speech_ended_at: float = 0.0
    ready_at: float = 0.0
    speech_seconds: float = 0.0
    vad_tail_seconds: float = 0.0
    utterance_id: int = 0
    speech_mode: str = "customer"
    recognition_language: str = "en"


@dataclass(slots=True)
class LiveSnapshot:
    audio: np.ndarray
    utterance_id: int
    revision: int
    speech_started_at: float
    captured_at: float
    speech_seconds: float
    speech_mode: str
    recognition_language: str


@dataclass(slots=True)
class _SegmentResult:
    audio: np.ndarray
    utterance_id: int
    speech_started_at: float
    speech_ended_at: float
    ready_at: float
    speech_mode: str
    recognition_language: str


class PlaybackGate:
    def __init__(self, post_mute_ms: int):
        self._playing = threading.Event()
        self._muted_until = 0.0
        self._post_seconds = post_mute_ms / 1000
        self._lock = threading.Lock()

    def begin(self) -> None:
        self._playing.set()

    def end(self) -> None:
        with self._lock:
            self._muted_until = time.monotonic() + self._post_seconds
        self._playing.clear()

    def muted(self) -> bool:
        if self._playing.is_set():
            return True
        with self._lock:
            return time.monotonic() < self._muted_until


class SpeechSegmenter:
    """VAD with short-tail final chunks and periodic live snapshots."""

    def __init__(self, cfg: AudioConfig):
        self.cfg = cfg
        self.block_samples = cfg.sample_rate * cfg.block_ms // 1000
        self.block_seconds = self.block_samples / cfg.sample_rate
        self.pre_blocks = max(1, math.ceil(cfg.pre_roll_ms / cfg.block_ms))
        self.end_blocks = max(1, math.ceil(cfg.end_silence_ms / cfg.block_ms))
        self.keep_tail_blocks = max(0, math.ceil(cfg.tail_keep_ms / cfg.block_ms))
        self.min_blocks = max(1, math.ceil(cfg.min_speech_ms / cfg.block_ms))
        self.max_blocks = max(1, math.ceil(cfg.max_utterance_ms / cfg.block_ms))
        self.pre_roll: deque[np.ndarray] = deque(maxlen=self.pre_blocks)
        self.frames: list[np.ndarray] = []
        self.speaking = False
        self.silent_blocks = 0
        self.voiced_blocks = 0
        self.noise_floor = 0.002
        self.utterance_id = 0
        self.speech_started_at = 0.0
        self.speech_ended_at = 0.0
        self.speech_mode = "customer"
        self.recognition_language = "en"
        self.live_revision = 0
        self.last_live_emit_at = 0.0

    def reset(self) -> None:
        self.pre_roll.clear()
        self.frames.clear()
        self.speaking = False
        self.silent_blocks = 0
        self.voiced_blocks = 0
        self.utterance_id = 0
        self.speech_started_at = 0.0
        self.speech_ended_at = 0.0
        self.speech_mode = "customer"
        self.recognition_language = "en"
        self.live_revision = 0
        self.last_live_emit_at = 0.0

    def process(
        self,
        frame: np.ndarray,
        frame_ended_at: float,
        *,
        candidate_utterance_id: int,
        speech_mode: str,
        recognition_language: str,
    ) -> _SegmentResult | None:
        frame = np.asarray(frame, dtype=np.float32).reshape(-1)
        rms = float(np.sqrt(np.mean(np.square(frame), dtype=np.float64)))
        if not self.speaking:
            self.noise_floor = 0.995 * self.noise_floor + 0.005 * min(rms, 0.03)
        # Original sensitivity: no extra speech-start confirmation or final noise gate.
        # Keep the app responsive and let Whisper decide speech content.
        start_threshold = max(self.cfg.start_rms, self.noise_floor * 3.5)
        continue_threshold = max(self.cfg.continue_rms, self.noise_floor * 2.0)

        if not self.speaking:
            self.pre_roll.append(frame.copy())
            if rms >= start_threshold:
                self.speaking = True
                self.frames = list(self.pre_roll)
                self.voiced_blocks = 1
                self.silent_blocks = 0
                self.utterance_id = candidate_utterance_id
                self.speech_started_at = max(0.0, frame_ended_at - self.block_seconds)
                self.speech_ended_at = frame_ended_at
                self.speech_mode = "staff" if speech_mode == "staff" else "customer"
                self.recognition_language = recognition_language
            return None

        self.frames.append(frame.copy())
        if rms >= continue_threshold:
            self.voiced_blocks += 1
            self.silent_blocks = 0
            self.speech_ended_at = frame_ended_at
        else:
            self.silent_blocks += 1

        if self.silent_blocks < self.end_blocks and len(self.frames) < self.max_blocks:
            return None

        result = None
        if self.voiced_blocks >= self.min_blocks:
            frames = self.frames
            # Keep only a small tail after the last voiced block. It avoids
            # sending VAD padding into the final model without clipping words.
            if self.silent_blocks and len(frames) > self.silent_blocks:
                drop = max(0, self.silent_blocks - self.keep_tail_blocks)
                if drop:
                    frames = frames[:-drop]
            result = _SegmentResult(
                audio=np.concatenate(frames),
                utterance_id=self.utterance_id,
                speech_started_at=self.speech_started_at,
                speech_ended_at=self.speech_ended_at or frame_ended_at,
                ready_at=frame_ended_at,
                speech_mode=self.speech_mode,
                recognition_language=self.recognition_language,
            )
        self.reset()
        return result

    def live_snapshot(self, captured_at: float) -> LiveSnapshot | None:
        if not self.cfg.live_preview_enabled or not self.speaking:
            return None
        speech_seconds = max(0.0, captured_at - self.speech_started_at)
        if speech_seconds * 1000 < self.cfg.live_preview_min_speech_ms:
            return None
        if self.live_revision >= self.cfg.live_preview_max_revisions:
            return None
        if captured_at - self.last_live_emit_at < self.cfg.live_preview_interval_ms / 1000:
            return None
        if not self.frames:
            return None
        self.last_live_emit_at = captured_at
        self.live_revision += 1
        max_samples = max(1, self.cfg.sample_rate * self.cfg.live_preview_max_audio_ms // 1000)
        audio = np.concatenate(self.frames)
        if len(audio) > max_samples:
            audio = audio[-max_samples:]
        return LiveSnapshot(
            audio=audio,
            utterance_id=self.utterance_id,
            revision=self.live_revision,
            speech_started_at=self.speech_started_at,
            captured_at=captured_at,
            speech_seconds=speech_seconds,
            speech_mode=self.speech_mode,
            recognition_language=self.recognition_language,
        )


class AudioCapture(threading.Thread):
    def __init__(
        self,
        cfg: AudioConfig,
        output: queue.Queue[Utterance],
        gate: PlaybackGate,
        status: Callable[[str, str], None],
        metrics: MetricsCallback | None = None,
        context: SpeechContext | None = None,
        speech_started_sink: SpeechStartedSink | None = None,
        live_snapshot_sink: LiveSnapshotSink | None = None,
    ):
        super().__init__(name="audio-capture", daemon=True)
        self.cfg = cfg
        self.output = output
        self.gate = gate
        self.status = status
        self.metrics = metrics
        self.context = context
        self.speech_started_sink = speech_started_sink
        self.live_snapshot_sink = live_snapshot_sink
        self.segmenter = SpeechSegmenter(cfg)
        self._frames: queue.Queue[tuple[np.ndarray, float]] = queue.Queue(maxsize=100)
        self._stop_event = threading.Event()
        self.dropped_utterances = 0
        self._failure_count = 0
        self._capture_error = "Audio device unavailable"
        self._next_utterance_id = 0
        self._next_overflow_log_at = 0.0

    def _metric(self, event: str, **fields: object) -> None:
        if self.metrics is None:
            return
        try:
            self.metrics(event, **fields)
        except Exception:
            pass

    def _speech_context(self) -> tuple[str, str]:
        if self.context is None:
            return "customer", "en"
        try:
            mode, language = self.context()
            mode = "staff" if mode == "staff" else "customer"
            language = str(language or "en").strip().lower()
            return mode, language or "en"
        except Exception:
            return "customer", "en"

    def _callback(self, indata, frames, time_info, callback_status) -> None:
        if callback_status:
            warning = str(callback_status)
            # Input overflow is noisy during CPU spikes and does not require a UI warning.
            # Drop the oldest pending frame and keep listening; throttle debug logging.
            if "overflow" in warning.lower():
                now = time.monotonic()
                if now >= self._next_overflow_log_at:
                    self._metric("audio_input_overflow_ignored", warning=warning)
                    self._next_overflow_log_at = now + 5.0
            else:
                self.status("warning", f"Audio input warning: {callback_status}")
        item = (indata[:, 0].copy(), time.monotonic())
        try:
            self._frames.put_nowait(item)
        except queue.Full:
            try:
                self._frames.get_nowait()
                self._frames.put_nowait(item)
            except (queue.Empty, queue.Full):
                pass

    def _process_frame(self, frame: np.ndarray, ended_at: float) -> None:
        if self.gate.muted():
            self.segmenter.reset()
            return
        mode, language = self._speech_context()
        was_speaking = self.segmenter.speaking
        result = self.segmenter.process(
            frame,
            ended_at,
            candidate_utterance_id=self._next_utterance_id + 1,
            speech_mode=mode,
            recognition_language=language,
        )
        if self.segmenter.speaking and self.segmenter.utterance_id > self._next_utterance_id:
            self._next_utterance_id = self.segmenter.utterance_id
        if not was_speaking and self.segmenter.speaking and self.speech_started_sink is not None:
            try:
                self.speech_started_sink(
                    self.segmenter.utterance_id,
                    self.segmenter.speech_mode,
                    self.segmenter.recognition_language,
                )
            except Exception:
                pass
        if result is not None:
            self._submit(result)
            return
        if self.live_snapshot_sink is not None:
            snapshot = self.segmenter.live_snapshot(ended_at)
            if snapshot is not None:
                try:
                    self.live_snapshot_sink(snapshot)
                except Exception:
                    pass

    def run(self) -> None:
        while not self._stop_event.is_set():
            if isinstance(self.cfg.input_device, str) and self.cfg.input_device.startswith(LOOPBACK_PREFIX):
                self._run_loopback(self.cfg.input_device[len(LOOPBACK_PREFIX):])
            else:
                self._run_microphone()
            if not self._stop_event.is_set():
                self._failure_count += 1
                delay = min(30, 2 ** min(self._failure_count, 5))
                if self._failure_count == 1 or self._failure_count % 5 == 0:
                    self.status("warning", f"{self._capture_error}; retrying in {delay} seconds")
                self._stop_event.wait(delay)

    def _run_microphone(self) -> None:
        try:
            import sounddevice as sd
            with sd.InputStream(
                samplerate=self.cfg.sample_rate,
                blocksize=self.segmenter.block_samples,
                channels=1,
                dtype="float32",
                device=sounddevice_value(self.cfg.input_device),
                callback=self._callback,
            ):
                self._failure_count = 0
                self.status("listening", "Listening")
                while not self._stop_event.is_set():
                    try:
                        frame, ended_at = self._frames.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    self._process_frame(frame, ended_at)
        except Exception as exc:
            self._capture_error = f"Microphone failed: {exc}"

    def _run_loopback(self, device_id: str) -> None:
        source_rate = 48000
        source_frames = source_rate * self.cfg.block_ms // 1000
        com_initialized = False
        try:
            import pythoncom
            pythoncom.CoInitialize()
            com_initialized = True
            sc = _load_soundcard()
            microphone = sc.get_microphone(device_id, include_loopback=True)
            if microphone is None or not microphone.isloopback:
                raise RuntimeError("Selected PC playback device is unavailable")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", sc.SoundcardRuntimeWarning)
                with microphone.recorder(samplerate=source_rate, channels=2, blocksize=source_frames) as recorder:
                    self._failure_count = 0
                    self.status("listening", "Listening to PC playback")
                    while not self._stop_event.is_set():
                        frame = recorder.record(numframes=source_frames)
                        self._process_frame(_resample_mono(frame, source_rate, self.cfg.sample_rate), time.monotonic())
        except Exception as exc:
            self._capture_error = f"PC playback capture failed: {exc}"
        finally:
            if com_initialized:
                pythoncom.CoUninitialize()

    def _submit(self, result: _SegmentResult) -> None:
        audio_seconds = len(result.audio) / self.cfg.sample_rate
        speech_seconds = max(0.0, result.speech_ended_at - result.speech_started_at)
        vad_tail_seconds = max(0.0, result.ready_at - result.speech_ended_at)
        item = Utterance(
            audio=result.audio,
            captured_at=result.ready_at,
            duration=audio_seconds,
            speech_started_at=result.speech_started_at,
            speech_ended_at=result.speech_ended_at,
            ready_at=result.ready_at,
            speech_seconds=speech_seconds,
            vad_tail_seconds=vad_tail_seconds,
            utterance_id=result.utterance_id,
            speech_mode=result.speech_mode,
            recognition_language=result.recognition_language,
        )
        before = self.output.qsize()
        self._metric(
            "audio_utterance_ready",
            utterance_id=item.utterance_id,
            audio_seconds=f"{audio_seconds:.3f}",
            speech_seconds=f"{speech_seconds:.3f}",
            vad_tail_seconds=f"{vad_tail_seconds:.3f}",
            speech_mode=item.speech_mode,
            forced_language=item.recognition_language,
            queue_depth_before=before,
        )
        try:
            self.output.put_nowait(item)
            self._metric(
                "audio_utterance_queued",
                utterance_id=item.utterance_id,
                speech_mode=item.speech_mode,
                forced_language=item.recognition_language,
                queue_depth_after=self.output.qsize(),
            )
        except queue.Full:
            self.dropped_utterances += 1
            try:
                dropped = self.output.get_nowait()
            except queue.Empty:
                dropped = None
            self._metric(
                "audio_utterance_dropped",
                utterance_id=(dropped.utterance_id if dropped else 0),
                replacement_utterance_id=item.utterance_id,
                reason="capture_queue_full",
            )
            try:
                self.output.put_nowait(item)
                self._metric("audio_utterance_queued_after_drop", utterance_id=item.utterance_id, queue_depth_after=self.output.qsize())
            except queue.Full:
                pass

    def stop(self) -> None:
        self._stop_event.set()


def list_audio_devices() -> dict[str, list]:
    import sounddevice as sd
    inputs, outputs, warnings_list = [], [], []
    for index, item in enumerate(sd.query_devices()):
        public = {"id": index, "name": str(item["name"])}
        if item["max_input_channels"] > 0:
            inputs.append(public)
        if item["max_output_channels"] > 0:
            outputs.append(public)
    com_initialized = False
    try:
        import pythoncom
        pythoncom.CoInitialize()
        com_initialized = True
        sc = _load_soundcard()
        stable_outputs = [{"id": f"{OUTPUT_PREFIX}{speaker.id}", "name": speaker.name} for speaker in sc.all_speakers()]
        if stable_outputs:
            outputs = stable_outputs
        known_ids = {str(item["id"]) for item in inputs}
        for microphone in sc.all_microphones(include_loopback=True):
            if microphone.isloopback:
                device_id = f"{LOOPBACK_PREFIX}{microphone.id}"
                if device_id not in known_ids:
                    inputs.append({"id": device_id, "name": f"PC playback · {microphone.name}"})
    except Exception as exc:
        warnings_list.append(f"WASAPI loopback unavailable: {type(exc).__name__}: {exc}")
    finally:
        if com_initialized:
            pythoncom.CoUninitialize()
    return {"inputs": inputs, "outputs": outputs, "warnings": warnings_list}
