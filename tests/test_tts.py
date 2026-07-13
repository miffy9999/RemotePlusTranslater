import threading
import time

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


def test_concurrent_speak_calls_cannot_restore_an_older_request(monkeypatch):
    speaker = _speaker()
    first_inside_interrupt = threading.Event()
    release_first = threading.Event()

    def delayed_interrupt(*, clear_queue=True, reason="manual"):
        if threading.current_thread().name == "first-speak":
            first_inside_interrupt.set()
            release_first.wait(1)
        if clear_queue:
            speaker._clear_requests(reason=reason)

    monkeypatch.setattr(speaker, "_interrupt_runtime", delayed_interrupt)
    first = threading.Thread(target=lambda: speaker.speak("old", "en"), name="first-speak")
    second = threading.Thread(target=lambda: speaker.speak("new", "en"), name="second-speak")
    first.start()
    assert first_inside_interrupt.wait(1)
    second.start()
    time.sleep(0.05)
    release_first.set()
    first.join(1)
    second.join(1)

    queued = speaker._requests.get_nowait()
    assert queued.text == "new"
    assert queued.request_id == 2


def test_dequeued_request_is_skipped_if_a_newer_request_exists(monkeypatch):
    speaker = _speaker()
    speaker._latest_request_id = 2
    synthesized = []
    monkeypatch.setattr(speaker, "_synthesize_with_retry", lambda request: synthesized.append(request))

    speaker._play(SpeechRequest(1, "old", "en", 0.0), lambda: None)

    assert synthesized == []


def test_manual_interrupt_invalidates_an_already_dequeued_request(monkeypatch):
    speaker = _speaker()
    speaker._latest_request_id = 1
    request = SpeechRequest(1, "old", "en", 0.0)
    synthesized = []
    monkeypatch.setattr(speaker, "_synthesize_with_retry", lambda item: synthesized.append(item))

    speaker.interrupt(clear_queue=True, reason="staff_speech_started")
    speaker._play(request, lambda: None)

    assert synthesized == []
