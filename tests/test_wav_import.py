import threading
import time
import wave

import numpy as np
import pytest

from translator_app.config import AudioConfig
from translator_app.stt import Recognition
from translator_app.wav_import import (
    WavImportManager,
    WavImportProcessor,
    WavSegment,
    _recorded_audio_config,
    _usable_recorded_recognition,
    load_wav,
    segment_wav,
    segment_wav_file,
)


def test_load_wav_decodes_stereo_pcm_and_resamples(tmp_path):
    path = tmp_path / "conversation.wav"
    samples = np.column_stack(
        (
            np.linspace(-0.5, 0.5, 8000, dtype=np.float32),
            np.linspace(0.5, -0.5, 8000, dtype=np.float32),
        )
    )
    pcm = np.clip(samples * 32767, -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(pcm.tobytes())

    result = load_wav(path)
    assert result.source_channels == 2
    assert result.sample_rate == 16000
    assert result.duration_seconds == 1.0
    assert result.samples.shape == (16000,)


def test_segment_wav_returns_chronological_speech_regions():
    rate = 16000
    silence = np.zeros(rate // 5, dtype=np.float32)
    first = np.full(rate // 3, 0.05, dtype=np.float32)
    gap = np.zeros(rate // 3, dtype=np.float32)
    second = np.full(rate // 3, 0.06, dtype=np.float32)
    samples = np.concatenate((silence, first, gap, second, silence))
    config = AudioConfig(
        speech_start_confirm_ms=40,
        end_silence_ms=100,
        min_speech_ms=100,
    )

    segments = segment_wav(samples, config)
    assert len(segments) == 2
    assert segments[0].start_seconds < segments[1].start_seconds
    assert all(segment.end_seconds > segment.start_seconds for segment in segments)


def test_recorded_audio_config_keeps_natural_phone_pauses_in_one_turn():
    rate = 16000
    speech = np.full(rate // 2, 0.05, dtype=np.float32)
    natural_pause = np.zeros(rate // 2, dtype=np.float32)
    samples = np.concatenate((speech, natural_pause, speech, np.zeros(rate)))
    live = AudioConfig(
        speech_start_confirm_ms=40,
        end_silence_ms=360,
        min_speech_ms=100,
    )

    assert len(segment_wav(samples, live)) == 2
    assert len(segment_wav(samples, _recorded_audio_config(live))) == 1


@pytest.mark.parametrize(
    ("recognition", "expected"),
    [
        (Recognition("Please send my baggage.", "en", 0.9, confidence=-0.6), True),
        (Recognition("uh...", "en", 0.9, confidence=-0.2), False),
        (Recognition("and found", "en", 0.3, confidence=-2.0), False),
        (Recognition("hip-hop", "en", 0.2, confidence=-0.95), False),
        (Recognition("チューン", "ja", 0.8, confidence=-1.2), False),
        (Recognition("automática", "pt", 0.7, confidence=-1.21), False),
        (Recognition("I, uh...", "en", 0.8, confidence=-0.2), False),
        (Recognition("カード", "ja", 0.8, confidence=-0.5), True),
    ],
)
def test_recorded_recognition_rejects_noise_hallucinations(
    recognition, expected
):
    assert _usable_recorded_recognition(recognition) is expected


def test_processor_labels_customer_staff_and_translates_in_order(tmp_path, monkeypatch):
    segments = [
        WavSegment(np.array([1], dtype=np.float32), 1.0, 2.0),
        WavSegment(np.array([2], dtype=np.float32), 3.0, 4.0),
    ]
    monkeypatch.setattr(
        "translator_app.wav_import.segment_wav_file", lambda *_args, **_kwargs: segments
    )

    class FakeRecognizer:
        def load(self):
            return None

        def transcribe(self, audio, *, language=None):
            assert language == "auto"
            if int(audio[0]) == 1:
                return Recognition("예약 확인 부탁해요", "ko", 0.96, confidence=-0.1)
            return Recognition("かしこまりました", "ja", 0.98, confidence=-0.05)

    class FakeTranslator:
        def __init__(self):
            self.calls = []

        def load(self):
            return None

        def translate(self, text, source_code, target_code):
            self.calls.append((text, source_code, target_code))
            return f"{target_code}:{text}"

    translator = FakeTranslator()
    processor = WavImportProcessor(FakeRecognizer(), translator, AudioConfig())
    progress = []
    entries = processor.process(
        tmp_path / "ignored.wav",
        "ko",
        threading.Event(),
        lambda done, total: progress.append((done, total)),
    )

    assert [entry.role for entry in entries] == ["customer", "staff"]
    assert [entry.start_seconds for entry in entries] == [1.0, 3.0]
    assert translator.calls == [
        ("예약 확인 부탁해요", "ko", "ja"),
        ("かしこまりました", "ja", "ko"),
    ]
    assert progress[-1] == (4, 4)


def test_manager_runs_one_background_import_and_removes_temporary_file(tmp_path):
    class FakeProcessor:
        def process(self, path, customer_language, cancelled, progress):
            assert customer_language == "ko"
            progress(0, 1)
            progress(1, 1)
            return []

    path = tmp_path / "upload.wav"
    path.write_bytes(b"temporary")
    manager = WavImportManager(FakeProcessor())
    submitted = manager.submit(path, "ko")
    deadline = time.monotonic() + 2
    status = manager.status(submitted["id"])
    while status["status"] not in {"completed", "failed"} and time.monotonic() < deadline:
        time.sleep(0.01)
        status = manager.status(submitted["id"])

    assert status["status"] == "completed"
    assert status["progress"] == 1.0
    assert not path.exists()
    manager.close()


def test_streaming_wav_segmentation_can_be_cancelled_before_model_work(tmp_path):
    path = tmp_path / "long.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(np.zeros(16000, dtype="<i2").tobytes())
    cancelled = threading.Event()
    cancelled.set()

    with pytest.raises(InterruptedError, match="cancelled"):
        segment_wav_file(path, AudioConfig(), cancelled)


def test_load_wav_rejects_truncated_declared_audio(tmp_path):
    path = tmp_path / "truncated.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(np.zeros(16000, dtype="<i2").tobytes())
    content = path.read_bytes()
    path.write_bytes(content[:-100])

    with pytest.raises(ValueError, match="truncated|Invalid WAV"):
        load_wav(path)


def test_processor_reports_when_wav_has_no_speech(tmp_path, monkeypatch):
    class UnusedRecognizer:
        def load(self):
            raise AssertionError("recognizer must not load for an empty recording")

    class UnusedTranslator:
        def load(self):
            raise AssertionError("translator must not load for an empty recording")

    monkeypatch.setattr(
        "translator_app.wav_import.segment_wav_file", lambda *_args, **_kwargs: []
    )
    processor = WavImportProcessor(UnusedRecognizer(), UnusedTranslator(), AudioConfig())

    with pytest.raises(ValueError, match="No speech"):
        processor.process(
            tmp_path / "silent.wav", "en", threading.Event(), lambda *_: None
        )


def test_processor_falls_back_to_selected_language_for_unsupported_detection(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "translator_app.wav_import.segment_wav_file",
        lambda *_args, **_kwargs: [
            WavSegment(np.array([1], dtype=np.float32), 0.0, 1.0)
        ],
    )

    class UncertainRecognizer:
        def load(self):
            return None

        def transcribe(self, _audio, *, language=None):
            if language == "auto":
                return Recognition("hello", "xx", 0.9, confidence=-0.1)
            return Recognition("", language or "", 0.0, no_speech_probability=1.0)

    class RecordingTranslator:
        def __init__(self):
            self.call = None

        def load(self):
            return None

        def translate(self, text, source_code, target_code):
            self.call = (text, source_code, target_code)
            return "こんにちは"

    translator = RecordingTranslator()
    processor = WavImportProcessor(UncertainRecognizer(), translator, AudioConfig())
    entries = processor.process(
        tmp_path / "uncertain.wav", "en", threading.Event(), lambda *_: None
    )

    assert entries[0].role == "customer"
    assert entries[0].source_language == "en"
    assert translator.call == ("hello", "en", "ja")


def test_wav_auto_language_is_not_replaced_by_forced_hallucination(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "translator_app.wav_import.segment_wav_file",
        lambda *_args, **_kwargs: [
            WavSegment(np.array([1], dtype=np.float32), 0.0, 1.0)
        ],
    )

    class JapaneseRecognizer:
        def load(self):
            return None

        def transcribe(self, _audio, *, language=None):
            assert language == "auto"
            return Recognition(
                "少々お待ちください。",
                "ja",
                0.48,
                confidence=-0.4,
            )

    class RecordingTranslator:
        def load(self):
            return None

        def translate(self, text, source_code, target_code):
            assert (text, source_code, target_code) == (
                "少々お待ちください。",
                "ja",
                "en",
            )
            return "Please wait a moment."

    processor = WavImportProcessor(
        JapaneseRecognizer(),
        RecordingTranslator(),
        AudioConfig(),
    )
    entries = processor.process(
        tmp_path / "field-call.wav",
        "en",
        threading.Event(),
        lambda *_: None,
    )

    assert entries[0].role == "staff"
    assert entries[0].source_language == "ja"
    assert entries[0].translated == "Please wait a moment."


def test_wav_uses_visible_latin_script_for_short_english_hotel_terms(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "translator_app.wav_import.segment_wav_file",
        lambda *_args, **_kwargs: [
            WavSegment(np.array([1], dtype=np.float32), 0.0, 1.0)
        ],
    )

    class MisidentifiedRecognizer:
        def load(self):
            return None

        def transcribe(self, _audio, *, language=None):
            assert language == "auto"
            return Recognition("credit card", "ja", 0.51, confidence=-0.2)

    class RecordingTranslator:
        def load(self):
            return None

        def translate(self, text, source_code, target_code):
            assert (text, source_code, target_code) == ("credit card", "en", "ja")
            return "クレジットカード"

    entries = WavImportProcessor(
        MisidentifiedRecognizer(),
        RecordingTranslator(),
        AudioConfig(),
    ).process(tmp_path / "call.wav", "en", threading.Event(), lambda *_: None)

    assert entries[0].role == "customer"
    assert entries[0].source_language == "en"


def test_wav_ambiguous_turn_uses_previous_and_next_recognized_context(
    tmp_path, monkeypatch
):
    segments = [
        WavSegment(np.array([1], dtype=np.float32), 0.0, 1.0),
        WavSegment(np.array([2], dtype=np.float32), 1.0, 2.0),
        WavSegment(np.array([3], dtype=np.float32), 2.0, 3.0),
    ]
    monkeypatch.setattr(
        "translator_app.wav_import.segment_wav_file", lambda *_args, **_kwargs: segments
    )

    class SequenceRecognizer:
        def load(self):
            return None

        def transcribe(self, audio, *, language=None):
            texts = {
                1: "朝食は洋食と和食から選べます。",
                2: "それでお願いします。",
                3: "飲み物はコーヒーにします。",
            }
            return Recognition(texts[int(audio[0])], "ja", 0.99, confidence=-0.1)

    class ContextTranslator:
        def __init__(self):
            self.context = None

        def load(self):
            return None

        def translate(self, text, source_code, target_code):
            return f"{target_code}:{text}"

        def translate_contextual(
            self,
            text,
            source_code,
            target_code,
            *,
            previous_text="",
            next_text="",
        ):
            self.context = (text, previous_text, next_text)
            return "그것으로 부탁드립니다."

    translator = ContextTranslator()
    processor = WavImportProcessor(SequenceRecognizer(), translator, AudioConfig())
    entries = processor.process(
        tmp_path / "dialogue.wav", "ko", threading.Event(), lambda *_: None
    )

    assert len(entries) == 3
    assert translator.context == (
        "それでお願いします。",
        "朝食は洋食と和食から選べます。",
        "飲み物はコーヒーにします。",
    )
