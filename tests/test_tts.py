from translator_app.audio import PlaybackGate
from translator_app.config import AudioConfig, TtsConfig
from translator_app.tts import EDGE_OUTPUT_PREFIX, EdgeSpeaker, SpeechRequest


def _speaker(audio: AudioConfig | None = None) -> EdgeSpeaker:
    return EdgeSpeaker(
        TtsConfig(),
        audio or AudioConfig(),
        PlaybackGate(),
        lambda _phase, _message: None,
    )


def test_edge_voice_uses_language_mapping():
    assert _speaker()._voice("ja") == "ja-JP-NanamiNeural"


def test_edge_voice_falls_back_to_english():
    assert _speaker()._voice("unknown") == "en-US-JennyNeural"


def test_edge_output_device_prefix_is_unwrapped():
    speaker = _speaker(AudioConfig(output_device=f"{EDGE_OUTPUT_PREFIX}Speakers"))

    assert speaker._requested_output_name() == "Speakers"


def test_legacy_output_device_values_use_system_default():
    assert _speaker(AudioConfig(output_device=3))._requested_output_name() is None


def test_interrupt_cancels_inflight_edge_synthesis():
    class FakeTask:
        def __init__(self):
            self.cancelled = False

        def done(self):
            return False

        def cancel(self):
            self.cancelled = True

    class FakeLoop:
        def call_soon_threadsafe(self, callback):
            callback()

    speaker = _speaker()
    task = FakeTask()
    speaker._synthesis_loop = FakeLoop()
    speaker._synthesis_task = task
    speaker.interrupt(clear_queue=False, reason="newer_tts_request")

    assert task.cancelled is True


def test_edge_synthesis_retries_one_transient_failure(monkeypatch):
    speaker = _speaker()
    outcomes = [RuntimeError("temporary Edge failure"), "audio-path"]

    def fake_synthesize(_request):
        result = outcomes.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(speaker, "_synthesize", fake_synthesize)
    request = SpeechRequest(1, "test", "en", 0.0)

    assert speaker._synthesize_with_retry(request) == "audio-path"
    assert outcomes == []
