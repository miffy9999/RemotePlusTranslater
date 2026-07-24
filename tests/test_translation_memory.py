from translator_app.translation_memory import (
    TranslationMemory,
    TranslationMemoryTranslator,
)


def test_approved_translation_is_persistent_and_normalized(tmp_path):
    memory = TranslationMemory(tmp_path)
    memory.remember(
        "  Could   you open the door? ",
        "EN",
        "JA",
        "ドアを開けていただけますか。",
    )

    reloaded = TranslationMemory(tmp_path)
    assert reloaded.lookup(
        "could you open the door?",
        "en",
        "ja",
    ) == "ドアを開けていただけますか。"
    assert reloaded.lookup(
        "could you open the door?",
        "en",
        "ko",
    ) is None


def test_translation_memory_skips_ai_for_regular_and_contextual_calls(tmp_path):
    class FailingBackend:
        def translate(self, *_args, **_kwargs):
            raise AssertionError("AI must not run for an approved translation")

        def translate_contextual(self, *_args, **_kwargs):
            raise AssertionError("context AI must not run for an approved translation")

    memory = TranslationMemory(tmp_path)
    memory.remember("That one, please.", "en", "ja", "そちらをお願いします。")
    translator = TranslationMemoryTranslator(FailingBackend(), memory)

    assert translator.translate("That one, please.", "en", "ja") == (
        "そちらをお願いします。"
    )
    assert translator.translate_contextual(
        "That one, please.",
        "en",
        "ja",
        previous_text="Which room would you like?",
    ) == "そちらをお願いします。"


def test_feedback_translation_correction_populates_memory(tmp_path):
    from translator_app.feedback import FeedbackStore

    memory = TranslationMemory(tmp_path)
    store = FeedbackStore(tmp_path, memory)
    store.append(
        {
            "direction": "incoming",
            "source_language": "en",
            "target_language": "ja",
            "source": "Please send my baggage.",
            "translation": "パンを送ってください。",
            "corrected_source": "",
            "corrected_translation": "荷物を送ってください。",
        }
    )

    assert memory.lookup(
        "Please send my baggage.",
        "en",
        "ja",
    ) == "荷物を送ってください。"
    assert store.clear() is True
    assert memory.lookup("Please send my baggage.", "en", "ja") is None
