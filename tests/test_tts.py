import hashlib
import json
import threading
import time

from translator_app.audio import PlaybackGate
from translator_app.config import AudioConfig, TtsConfig
from translator_app.tts import (
    LOCAL_OUTPUT_PREFIX,
    LocalTtsEngine,
    LocalSpeaker,
    ProcessLocalTtsEngine,
    SpeechRequest,
)
from translator_app.tts_packs import PackSpec


def _speaker(audio: AudioConfig | None = None) -> LocalSpeaker:
    speaker = LocalSpeaker(
        TtsConfig(), audio or AudioConfig(), PlaybackGate(), lambda _phase, _message: None
    )
    speaker.engine.supports = lambda _language: True
    return speaker


def test_local_output_device_prefix_is_unwrapped():
    speaker = _speaker(AudioConfig(output_device=f"{LOCAL_OUTPUT_PREFIX}Speakers"))
    assert speaker._requested_output_name() == "Speakers"


def test_legacy_output_device_values_use_system_default():
    assert _speaker(AudioConfig(output_device=3))._requested_output_name() is None


def test_missing_voice_pack_does_not_queue_or_use_network():
    speaker = _speaker()
    speaker.engine.supports = lambda _language: False
    assert speaker.speak("hello", "en") is None
    assert speaker._requests.empty()


def test_automatic_reply_speaks_only_the_translated_text():
    speaker = _speaker()
    speaker.speak("Your room is ready.", "en", utterance_id=10)
    request = speaker._requests.get_nowait()
    assert request.text == "Your room is ready."


def test_interrupt_invalidates_inflight_local_synthesis():
    speaker = _speaker()
    speaker._latest_request_id = 1
    speaker.interrupt(clear_queue=False, reason="newer_tts_request")
    assert speaker._interrupt_event.is_set()


def test_concurrent_speak_calls_cannot_restore_an_older_request(monkeypatch):
    speaker = _speaker()
    first_inside_support = threading.Event()
    release_first = threading.Event()

    def delayed_support(_language):
        if threading.current_thread().name == "first-speak":
            first_inside_support.set()
            release_first.wait(1)
        return True

    monkeypatch.setattr(speaker.engine, "supports", delayed_support)
    first = threading.Thread(target=lambda: speaker.speak("old", "en"), name="first-speak")
    second = threading.Thread(target=lambda: speaker.speak("new", "en"), name="second-speak")
    first.start()
    assert first_inside_support.wait(1)
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
    monkeypatch.setattr(speaker, "_synthesize", lambda request: synthesized.append(request))
    speaker._play(SpeechRequest(1, "old", "en", 0.0), lambda: None)
    assert synthesized == []


def test_manual_interrupt_invalidates_an_already_dequeued_request(monkeypatch):
    speaker = _speaker()
    speaker._latest_request_id = 1
    request = SpeechRequest(1, "old", "en", 0.0)
    synthesized = []
    monkeypatch.setattr(speaker, "_synthesize", lambda item: synthesized.append(item))
    speaker.interrupt(clear_queue=True, reason="staff_speech_started")
    speaker._play(request, lambda: None)
    assert synthesized == []


def test_native_worker_is_terminated_when_busy_tts_is_interrupted():
    class FakeProcess:
        def __init__(self):
            self.return_code = None
            self.terminated = False

        def poll(self):
            return self.return_code

        def terminate(self):
            self.terminated = True
            self.return_code = 0

        def wait(self, timeout=None):
            return self.return_code

    engine = ProcessLocalTtsEngine(TtsConfig(), threading.Event())
    process = FakeProcess()
    engine._process = process
    engine._busy.set()

    engine.interrupt()

    assert process.terminated is True
    assert engine._process is None


def test_idle_worker_is_reused_instead_of_being_interrupted(monkeypatch):
    speaker = _speaker()
    interrupted = []
    monkeypatch.setattr(speaker.engine, "is_busy", lambda: False)
    monkeypatch.setattr(speaker.engine, "interrupt", lambda: interrupted.append(True))

    speaker.speak("first", "en")
    speaker.speak("second", "en")

    assert interrupted == []
    assert speaker._requests.get_nowait().text == "second"


def test_unicode_frontend_cache_is_rebuilt_after_tampering(tmp_path, monkeypatch):
    cfg = TtsConfig()
    cfg.data_root = tmp_path
    source = tmp_path / "한글" / "kokoro-model"
    assets = {
        "tokens.txt": b"tokens",
        "lexicon-us-en.txt": b"english",
        "lexicon-zh.txt": b"chinese",
        "espeak-ng-data/phontab": b"phonemes",
    }
    for relative, content in assets.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    inventory = {
        f"kokoro-model/{relative}": hashlib.sha256(content).hexdigest()
        for relative, content in assets.items()
    }
    (source.parent / "pack-receipt.json").write_text(
        json.dumps({"files": inventory}), encoding="utf-8"
    )
    spec = PackSpec(
        "kokoro-test", "kokoro", "1", ("zh",), "https://example.invalid/model",
        "a" * 64, "kokoro-model", "Apache-2.0",
    )
    monkeypatch.setenv("ProgramData", str(tmp_path / "ascii-cache"))
    engine = LocalTtsEngine(cfg, threading.Event())

    cache = engine._ascii_frontend_copy(spec, source)
    (cache / "tokens.txt").write_bytes(b"tampered")
    rebuilt = engine._ascii_frontend_copy(spec, source)

    assert rebuilt == cache
    assert (cache / "tokens.txt").read_bytes() == b"tokens"
    assert not (cache / "model.onnx").exists()
