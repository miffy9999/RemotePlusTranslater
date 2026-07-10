from types import SimpleNamespace

import pytest

from translator_app.config import load_config
from translator_app.conversation import ConversationController
from translator_app.events import EventBus
from translator_app.stt import Recognition


class FakeRecognizer:
    def __init__(self): self.selected_language = "auto"
    def load(self): pass
    def transcribe(self, audio): return Recognition("", "en", 1.0)
    def set_selected_language(self, language): self.selected_language = language


class FakeTranslator:
    def __init__(self): self.calls = []
    def load(self): pass
    def translate(self, text, source_code, target_code):
        self.calls.append((text, source_code, target_code))
        return f"{target_code}:{text}"


class FakeSpeaker:
    def __init__(self):
        self.calls = []
        self.cfg = SimpleNamespace(enabled=True)
    def speak(self, text, language): self.calls.append((text, language))
    def stop(self): pass


def make_controller():
    translator = FakeTranslator()
    bus = EventBus()
    controller = ConversationController(load_config(), bus, FakeRecognizer(), translator)
    controller.speaker = FakeSpeaker()
    return controller, translator, bus


def test_incoming_sets_partner_language_and_translates_to_japanese():
    controller, translator, bus = make_controller()
    controller.process_recognition(Recognition("Hello", "en", 0.98))
    assert controller.state.active_language == "en"
    assert translator.calls == [("Hello", "en", "ja")]
    assert bus.history()[-1]["data"]["direction"] == "incoming"


def test_japanese_reply_returns_to_last_partner_and_speaks():
    controller, translator, bus = make_controller()
    controller.process_recognition(Recognition("Hola", "es", 0.99))
    controller.process_recognition(Recognition("こんにちは", "ja", 0.99))
    assert translator.calls[-1] == ("こんにちは", "ja", "es")
    assert controller.speaker.calls == [("es:こんにちは", "es")]
    assert bus.history()[-1]["data"]["direction"] == "reply"


def test_completed_reply_can_be_replayed_after_interruption():
    controller, _, _ = make_controller()
    controller.control(enabled_languages=["en", "ko", "es"])

    request_id = controller.replay_tts("Please wait a moment.", "en")

    assert request_id == 0
    assert controller.speaker.calls == [("Please wait a moment.", "en")]


def test_manual_reply_language_overrides_recent_partner():
    controller, translator, bus = make_controller()
    controller.process_recognition(Recognition("Hello", "en", 0.99))
    state = controller.control(reply_language="es")
    controller.process_recognition(Recognition("確認します", "ja", 0.99))
    assert state["reply_language"] == "es"
    assert translator.calls[-1] == ("確認します", "ja", "es")
    assert controller.speaker.calls == [("es:確認します", "es")]
    assert bus.history()[-1]["data"]["target_language"] == "es"


def test_manual_reply_language_works_without_recent_partner():
    controller, translator, _ = make_controller()
    controller.control(reply_language="ko")
    controller.process_recognition(Recognition("少々お待ちください", "ja", 0.99))
    assert translator.calls[-1] == ("少々お待ちください", "ja", "ko")


def test_disabled_reply_language_is_rejected_and_removed_language_resets_auto():
    controller, _, _ = make_controller()
    controller.control(enabled_languages=["en", "ko", "es"])
    with pytest.raises(ValueError, match="Reply language"):
        controller.control(reply_language="fr")
    controller.control(reply_language="es")
    state = controller.control(enabled_languages=["en", "ko"])
    assert state["reply_language"] == "auto"


def test_low_confidence_language_uses_recent_partner():
    controller, translator, _ = make_controller()
    controller.process_recognition(Recognition("Hello", "en", 0.99))
    controller.process_recognition(Recognition("More", "fr", 0.2))
    assert translator.calls[-1][1] == "en"


def test_manual_input_language_controls_recognizer_and_routing():
    controller, translator, _ = make_controller()
    controller.control(active_language="ko")
    assert controller.state.input_language == "ko"
    assert controller.recognizer.selected_language == "ko"
    controller.process_recognition(Recognition("룸서비스 부탁합니다", "en", 0.2))
    assert translator.calls[-1][1] == "ko"


def test_input_device_can_change_before_audio_starts(monkeypatch):
    controller, _, _ = make_controller()
    monkeypatch.setattr("translator_app.conversation.validate_input_device", lambda _device: None)
    old_capture = controller.capture
    state = controller.control(input_device=3)
    assert state["input_device"] == 3
    assert controller.cfg.audio.input_device == 3
    assert controller.capture is not old_capture


def test_output_device_can_change_without_restarting_capture():
    controller, _, _ = make_controller()
    old_capture = controller.capture
    device = "edge:Speakers"
    state = controller.control(output_device=device)
    assert state["output_device"] == device
    assert controller.cfg.audio.output_device == device
    assert controller.capture is old_capture


def test_legacy_output_device_is_rejected():
    controller, _, _ = make_controller()
    with pytest.raises(ValueError, match="output_device"):
        controller.control(output_device="output:{speaker-guid}")


def test_kana_reply_overrides_low_confidence_manual_language():
    controller, translator, _ = make_controller()
    controller.control(active_language="en")
    controller.process_recognition(Recognition("確認します", "en", 0.1))
    assert translator.calls[-1] == ("確認します", "ja", "en")


def test_invalid_input_device_is_rejected_before_capture_restart():
    controller, _, _ = make_controller()
    with pytest.raises(ValueError, match="input_device"):
        controller.control(input_device="not-a-device")
