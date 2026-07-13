import queue
import time

import numpy as np
import pytest

from translator_app.audio import AudioCapture, LOOPBACK_PREFIX, SpeechSegmenter, _resample_mono
from translator_app.config import AudioConfig, sounddevice_value


def frame(level: float, samples: int = 320) -> np.ndarray:
    return np.full(samples, level, dtype=np.float32)


def test_segmenter_keeps_preroll_and_ends_after_silence():
    cfg = AudioConfig(pre_roll_ms=100, end_silence_ms=100, min_speech_ms=100)
    vad = SpeechSegmenter(cfg)
    for _ in range(5):
        assert vad.process(frame(0.001)) is None
    for _ in range(8):
        assert vad.process(frame(0.04)) is None
    result = None
    for _ in range(5):
        result = vad.process(frame(0.001))
    assert result is not None
    assert len(result) >= (4 + 8 + 5) * 320


def test_segmenter_snapshots_languages_at_speech_start():
    vad = SpeechSegmenter(AudioConfig(end_silence_ms=60, min_speech_ms=20))
    vad.process(
        frame(0.05),
        candidate_utterance_id=7,
        recognition_language="ko",
        reply_language="ko",
    )
    result = None
    for _ in range(4):
        result = vad.process(
            frame(0), recognition_language="en", reply_language="es"
        ) or result
    assert result is not None
    assert result.utterance_id == 7
    assert result.speech_mode == "customer"
    assert result.recognition_language == "ko"
    assert result.reply_language == "ko"


def test_typed_reply_and_audio_ids_never_collide():
    output = queue.Queue(maxsize=1)
    capture = AudioCapture(
        AudioConfig(end_silence_ms=60, min_speech_ms=20),
        output,
        lambda *_: None,
        context=lambda: ("en", "en"),
    )
    assert capture.reserve_utterance_id() == 1
    now = time.monotonic()
    capture._process_frame(frame(0.05), now)
    for index in range(1, 5):
        capture._process_frame(frame(0), now + index * 0.02)
    assert output.get_nowait().utterance_id == 2


def test_segmenter_rejects_short_click():
    vad = SpeechSegmenter(AudioConfig(end_silence_ms=60, min_speech_ms=200))
    vad.process(frame(0.05))
    assert all(vad.process(frame(0)) is None for _ in range(4))


def test_loopback_resampling_converts_stereo_48k_to_mono_16k():
    stereo = np.column_stack((np.arange(960), np.arange(960))).astype(np.float32)
    result = _resample_mono(stereo, 48000, 16000)
    assert result.shape == (320,)
    assert result[0] == 0
    assert result[-1] == 959


def test_device_helpers_are_stable_and_reject_unknown_values():
    assert LOOPBACK_PREFIX == "loopback:"
    with pytest.raises(ValueError, match="audio.input_device"):
        sounddevice_value("broken")
