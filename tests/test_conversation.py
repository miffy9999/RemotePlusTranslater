import threading
import time

import pytest

from translator_app.config import load_config
from translator_app.conversation import ConversationController, RecognitionJob, _NOISE_TEXT
from translator_app.events import EventBus
from translator_app.stt import Recognition


class FakeRecognizer:
    def __init__(self):
        self.selected_language = "en"

    def load(self):
        pass

    def transcribe(self, _audio, *, language=None):
        return Recognition("", language or "en", 1.0)

    def set_selected_language(self, language):
        self.selected_language = language


class FakeTranslator:
    def __init__(self):
        self.calls = []

    def load(self):
        pass

    def translate(self, text, source_code, target_code):
        self.calls.append((text, source_code, target_code))
        return {"ko": "입력하겠습니다.", "zh": "请稍等一下。"}.get(
            target_code, f"{target_code}:{text}"
        )


def make_controller():
    translator = FakeTranslator()
    bus = EventBus()
    controller = ConversationController(load_config(), bus, FakeRecognizer(), translator)
    return controller, translator, bus


def test_customer_recognition_uses_selected_language_and_translates_to_japanese():
    controller, translator, bus = make_controller()
    controller.process_recognition(Recognition("Hello", "fr", 0.2))
    assert translator.calls == [("Hello", "en", "ja")]
    assert bus.history()[-1]["data"]["direction"] == "incoming"


def test_typed_japanese_reply_uses_target_snapshot():
    controller, translator, bus = make_controller()
    controller._translator_ready.set()
    controller.control(reply_language="ko")
    utterance_id = controller.submit_staff_text("入力します")
    controller.control(reply_language="es")
    job = controller._recognitions.get_nowait()
    controller._translate_job(job)
    assert job.utterance_id == utterance_id
    assert translator.calls[-1] == ("入力します", "ja", "ko")
    assert bus.history()[-1]["data"]["target_language"] == "ko"


def test_typed_english_quick_phrase_is_not_mislabeled_as_japanese():
    controller, translator, _ = make_controller()
    controller._translator_ready.set()
    controller.control(reply_language="ko")
    controller.submit_staff_text("Please wait a moment.")
    job = controller._recognitions.get_nowait()
    assert job.language == "en"
    controller._translate_job(job)
    assert translator.calls[-1] == ("Please wait a moment.", "en", "ko")


def test_fullwidth_english_quick_phrase_is_detected_as_english():
    controller, _, _ = make_controller()
    controller.control(reply_language="ko")
    controller.submit_staff_text("ＰＬＥＡＳＥ ＷＡＩＴ")
    assert controller._recognitions.get_nowait().language == "en"


def test_reading_worker_adds_katakana_and_romanization_without_blocking_translation():
    controller, _, bus = make_controller()
    controller._translator_ready.set()
    controller.control(reply_language="ko")
    controller._reading_worker.start()
    controller.submit_staff_text("入力します")
    controller._translate_job(controller._recognitions.get_nowait())
    translations = [x for x in bus.history() if x["type"] == "translation"]
    assert translations[-1]["data"]["reading"] == ""
    deadline = time.monotonic() + 1
    while not any(x["type"] == "reading" for x in bus.history()) and time.monotonic() < deadline:
        time.sleep(0.01)
    controller._stop.set()
    controller._reading_worker.join(1)
    reading = [x for x in bus.history() if x["type"] == "reading"][-1]["data"]
    assert reading["reading"].startswith("イ")
    assert reading["romanized_reading"].startswith("ip")


def test_invalid_or_oversized_staff_reply_is_rejected():
    controller, _, _ = make_controller()
    with pytest.raises(ValueError, match="1 to 800"):
        controller.submit_staff_text("   ")
    with pytest.raises(ValueError, match="1 to 800"):
        controller.submit_staff_text("あ" * 801)


def test_shutdown_continues_when_audio_and_translator_cleanup_fail():
    controller, _, _ = make_controller()

    def fail():
        raise RuntimeError("cleanup failed")

    controller.capture.stop = fail
    controller.translator.close = fail
    controller.stop()
    assert controller._stop.is_set()


def test_running_old_result_cannot_overwrite_newer_work():
    controller, translator, bus = make_controller()
    with controller._latest_lock:
        controller._latest_started_by_mode["staff"] = 12
    old = RecognitionJob(
        Recognition("old", "en"), "en", "customer", 1, 0, 0, 11, 0, 0, 1, 0, "en"
    )
    controller._translate_job(old)
    assert translator.calls == []
    assert bus.history() == []


def test_manual_language_control_updates_recognizer_and_is_serialized():
    controller, _, _ = make_controller()
    entered = threading.Event()
    release = threading.Event()
    original = controller.recognizer.set_selected_language

    def delayed(language):
        if language == "ko":
            entered.set()
            release.wait(1)
        original(language)

    controller.recognizer.set_selected_language = delayed
    first = threading.Thread(target=lambda: controller.control(active_language="ko"))
    second = threading.Thread(target=lambda: controller.control(active_language="es"))
    first.start()
    assert entered.wait(1)
    second.start()
    time.sleep(0.03)
    assert second.is_alive()
    release.set()
    first.join(1)
    second.join(1)
    assert controller.recognizer.selected_language == "es"


def test_snapshot_does_not_claim_dead_translation_engine_is_ready():
    controller, _, _ = make_controller()
    controller.translator.is_available = lambda: False
    controller._ready.set()
    controller._translator_ready.set()
    state = controller.snapshot()
    assert state["ready"] is True
    assert state["translator_ready"] is False
    assert state["phase"] == "warning"


def test_normal_thank_you_is_not_noise():
    assert _NOISE_TEXT.fullmatch("Thank you") is None
