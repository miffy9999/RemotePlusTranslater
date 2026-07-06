from __future__ import annotations

import ctypes.util
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


def _load_soundcard():
    """Load SoundCard despite cffi's incomplete Windows DLL name lookup."""
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
    if data.ndim == 2:
        data = data.mean(axis=1)
    else:
        data = data.reshape(-1)
    if source_rate == target_rate or len(data) < 2:
        return data
    target_length = max(1, round(len(data) * target_rate / source_rate))
    old_positions = np.arange(len(data), dtype=np.float64)
    new_positions = np.linspace(0, len(data) - 1, target_length)
    return np.interp(new_positions, old_positions, data).astype(np.float32)


@dataclass(slots=True)
class Utterance:
    audio: np.ndarray
    captured_at: float
    duration: float


class PlaybackGate:
    """Prevents synthesized speech from being captured and translated again."""

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
    """Low-latency RMS VAD with hysteresis, adaptive noise floor, and pre-roll."""

    def __init__(self, cfg: AudioConfig):
        self.cfg = cfg
        self.block_samples = cfg.sample_rate * cfg.block_ms // 1000
        self.pre_blocks = max(1, cfg.pre_roll_ms // cfg.block_ms)
        self.end_blocks = max(1, cfg.end_silence_ms // cfg.block_ms)
        self.min_blocks = max(1, cfg.min_speech_ms // cfg.block_ms)
        self.max_blocks = max(1, cfg.max_utterance_ms // cfg.block_ms)
        self.pre_roll: deque[np.ndarray] = deque(maxlen=self.pre_blocks)
        self.frames: list[np.ndarray] = []
        self.speaking = False
        self.silent_blocks = 0
        self.voiced_blocks = 0
        self.noise_floor = 0.002

    def reset(self) -> None:
        self.pre_roll.clear()
        self.frames.clear()
        self.speaking = False
        self.silent_blocks = 0
        self.voiced_blocks = 0

    def process(self, frame: np.ndarray) -> np.ndarray | None:
        frame = np.asarray(frame, dtype=np.float32).reshape(-1)
        rms = float(np.sqrt(np.mean(np.square(frame), dtype=np.float64)))
        if not self.speaking:
            self.noise_floor = 0.995 * self.noise_floor + 0.005 * min(rms, 0.03)
        start_threshold = max(self.cfg.start_rms, self.noise_floor * 3.5)
        continue_threshold = max(self.cfg.continue_rms, self.noise_floor * 2.0)

        if not self.speaking:
            self.pre_roll.append(frame.copy())
            if rms >= start_threshold:
                self.speaking = True
                self.frames = list(self.pre_roll)
                self.voiced_blocks = 1
                self.silent_blocks = 0
            return None

        self.frames.append(frame.copy())
        if rms >= continue_threshold:
            self.voiced_blocks += 1
            self.silent_blocks = 0
        else:
            self.silent_blocks += 1

        reached_silence = self.silent_blocks >= self.end_blocks
        reached_limit = len(self.frames) >= self.max_blocks
        if not (reached_silence or reached_limit):
            return None

        valid = self.voiced_blocks >= self.min_blocks
        audio = np.concatenate(self.frames) if valid else None
        self.reset()
        return audio


class AudioCapture(threading.Thread):
    def __init__(
        self,
        cfg: AudioConfig,
        output: queue.Queue[Utterance],
        gate: PlaybackGate,
        status: Callable[[str, str], None],
    ):
        super().__init__(name="audio-capture", daemon=True)
        self.cfg = cfg
        self.output = output
        self.gate = gate
        self.status = status
        self.segmenter = SpeechSegmenter(cfg)
        self._frames: queue.Queue[np.ndarray] = queue.Queue(maxsize=100)
        self._stop_event = threading.Event()
        self.dropped_utterances = 0
        self._failure_count = 0
        self._capture_error = "Audio device unavailable"

    def _callback(self, indata, frames, time_info, callback_status) -> None:
        if callback_status:
            self.status("warning", f"Audio input warning: {callback_status}")
        try:
            self._frames.put_nowait(indata[:, 0].copy())
        except queue.Full:
            try:
                self._frames.get_nowait()
                self._frames.put_nowait(indata[:, 0].copy())
            except (queue.Empty, queue.Full):
                pass

    def run(self) -> None:
        while not self._stop_event.is_set():
            if isinstance(self.cfg.input_device, str) and self.cfg.input_device.startswith(
                LOOPBACK_PREFIX
            ):
                self._run_loopback(self.cfg.input_device[len(LOOPBACK_PREFIX) :])
            else:
                self._run_microphone()
            if not self._stop_event.is_set():
                self._failure_count += 1
                delay = min(30, 2 ** min(self._failure_count, 5))
                if self._failure_count == 1 or self._failure_count % 5 == 0:
                    self.status(
                        "warning",
                        f"{self._capture_error}; retrying in {delay} seconds",
                    )
                self._stop_event.wait(delay)

    def _run_microphone(self) -> None:
        try:
            import sounddevice as sd

            device = sounddevice_value(self.cfg.input_device)
            with sd.InputStream(
                samplerate=self.cfg.sample_rate,
                blocksize=self.segmenter.block_samples,
                channels=1,
                dtype="float32",
                device=device,
                callback=self._callback,
            ):
                self._failure_count = 0
                self.status("listening", "Listening")
                while not self._stop_event.is_set():
                    try:
                        frame = self._frames.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if self.gate.muted():
                        self.segmenter.reset()
                        continue
                    audio = self.segmenter.process(frame)
                    if audio is None:
                        continue
                    self._submit(audio)
        except Exception as exc:
            self._capture_error = f"Microphone failed: {exc}"

    def _run_loopback(self, device_id: str) -> None:
        """Capture the Windows speaker mix through WASAPI loopback."""
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
            # SoundCard's Windows backend is more reliable with two channels.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", sc.SoundcardRuntimeWarning)
                with microphone.recorder(
                    samplerate=source_rate,
                    channels=2,
                    blocksize=source_frames,
                ) as recorder:
                    self._failure_count = 0
                    self.status("listening", "Listening to PC playback")
                    while not self._stop_event.is_set():
                        frame = recorder.record(numframes=source_frames)
                        if self.gate.muted():
                            self.segmenter.reset()
                            continue
                        audio = self.segmenter.process(
                            _resample_mono(frame, source_rate, self.cfg.sample_rate)
                        )
                        if audio is not None:
                            self._submit(audio)
        except Exception as exc:
            self._capture_error = f"PC playback capture failed: {exc}"
        finally:
            if com_initialized:
                pythoncom.CoUninitialize()

    def _submit(self, audio: np.ndarray) -> None:
        item = Utterance(
            audio=audio,
            captured_at=time.time(),
            duration=len(audio) / self.cfg.sample_rate,
        )
        try:
            self.output.put_nowait(item)
        except queue.Full:
            self.dropped_utterances += 1
            self.status("warning", "Processing is behind; oldest utterance was dropped")
            try:
                self.output.get_nowait()
                self.output.put_nowait(item)
            except (queue.Empty, queue.Full):
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
        stable_outputs = [
            {"id": f"{OUTPUT_PREFIX}{speaker.id}", "name": speaker.name}
            for speaker in sc.all_speakers()
        ]
        if stable_outputs:
            outputs = stable_outputs
        known_ids = {str(item["id"]) for item in inputs}
        for microphone in sc.all_microphones(include_loopback=True):
            if not microphone.isloopback:
                continue
            device_id = f"{LOOPBACK_PREFIX}{microphone.id}"
            if device_id not in known_ids:
                inputs.append({"id": device_id, "name": f"PC playback · {microphone.name}"})
    except Exception as exc:
        # Ordinary microphones remain usable if WASAPI loopback is unavailable.
        warnings_list.append(f"WASAPI loopback unavailable: {type(exc).__name__}: {exc}")
    finally:
        if com_initialized:
            pythoncom.CoUninitialize()
    return {"inputs": inputs, "outputs": outputs, "warnings": warnings_list}
