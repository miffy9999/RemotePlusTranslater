import numpy as np

from translator_app.audio import LOOPBACK_PREFIX, SpeechSegmenter, _resample_mono
import pytest

from translator_app.config import AudioConfig, sounddevice_value


def frame(level: float, samples: int = 320) -> np.ndarray:
    return np.full(samples, level, dtype=np.float32)


def test_segmenter_keeps_preroll_and_ends_after_silence():
    cfg = AudioConfig(
        pre_roll_ms=100,
        end_silence_ms=100,
        min_speech_ms=100,
        max_utterance_ms=2000,
    )
    vad = SpeechSegmenter(cfg)
    for _ in range(5):
        assert vad.process(frame(0.001)) is None
    for _ in range(8):
        assert vad.process(frame(0.04)) is None
    result = None
    for _ in range(5):
        result = vad.process(frame(0.001))
    assert result is not None
    # Four quiet blocks precede the trigger block inside the five-block pre-roll.
    assert len(result) >= (4 + 8 + 5) * 320


def test_segmenter_rejects_short_click():
    cfg = AudioConfig(end_silence_ms=60, min_speech_ms=200)
    vad = SpeechSegmenter(cfg)
    vad.process(frame(0.05))
    result = None
    for _ in range(4):
        result = vad.process(frame(0.0))
    assert result is None


def test_loopback_resampling_converts_stereo_48k_to_mono_16k():
    stereo = np.column_stack((np.arange(960), np.arange(960))).astype(np.float32)
    result = _resample_mono(stereo, 48000, 16000)
    assert result.shape == (320,)
    assert result[0] == 0
    assert result[-1] == 959


def test_loopback_device_prefix_is_stable():
    assert LOOPBACK_PREFIX == "loopback:"


def test_invalid_sounddevice_value_has_clear_error():
    with pytest.raises(ValueError, match="audio.input_device"):
        sounddevice_value("broken")


def test_segmenter_snapshots_reply_language_and_tts_at_speech_start():
    cfg = AudioConfig(end_silence_ms=60, staff_end_silence_ms=60, min_speech_ms=20)
    vad = SpeechSegmenter(cfg)
    vad.process(
        frame(0.05),
        candidate_utterance_id=7,
        speech_mode="staff",
        recognition_language="ja",
        reply_language="ko",
        tts_enabled=True,
    )
    result = None
    for _ in range(4):
        candidate = vad.process(
            frame(0.0),
            speech_mode="customer",
            recognition_language="en",
            reply_language="es",
            tts_enabled=False,
        )
        if candidate is not None:
            result = candidate
            break
    assert result is not None
    assert result.utterance_id == 7
    assert result.speech_mode == "staff"
    assert result.recognition_language == "ja"
    assert result.reply_language == "ko"
    assert result.tts_enabled is True
