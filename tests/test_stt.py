from types import SimpleNamespace

import numpy as np
import pytest

from translator_app.config import SttConfig
from translator_app.stt import (
    WhisperRecognizer,
    apply_corrections,
    collapse_repetitions,
    contains_japanese_kana,
)


def test_domain_corrections_are_deterministic():
    corrections = {"콜을 주세요": "콜라 주세요", "진저일": "진저에일"}
    assert apply_corrections("콜을 주세요. 진저일도 주세요.", corrections) == (
        "콜라 주세요. 진저에일도 주세요."
    )


def test_longer_correction_runs_first():
    corrections = {"진저": "생강", "진저일": "진저에일"}
    assert apply_corrections("진저일", corrections) == "진저에일"


def test_field_call_corrections_keep_the_intended_hotel_terms():
    corrections = {
        "uh, taus": "towels",
        "frontでございます": "フロントでございます",
    }
    assert apply_corrections("uh, taus", corrections) == "towels"
    assert (
        apply_corrections("frontでございます", corrections)
        == "フロントでございます"
    )


def test_obvious_stt_repetition_is_collapsed_without_removing_normal_emphasis():
    assert collapse_repetitions("check check check check") == "check"
    assert collapse_repetitions("please check in please check in please check in") == "please check in"
    assert collapse_repetitions("very very good") == "very very good"


def test_context_language_selects_hotel_hotwords():
    cfg = SttConfig(
        hotwords=["hotel"],
        language_hotwords={"en": ["room service"], "ja": ["ルームサービス"], "ko": ["룸서비스"]},
    )
    recognizer = WhisperRecognizer(cfg, lambda *_: None)
    recognizer.set_context_language("en")
    words = recognizer._hotwords()
    assert "room service" in words
    assert "ルームサービス" not in words
    assert "룸서비스" not in words


def test_selected_language_changes_context_hotwords():
    cfg = SttConfig(language_hotwords={"ko": ["진저에일"], "ja": ["ジンジャーエール"]})
    recognizer = WhisperRecognizer(cfg, lambda *_: None)
    recognizer.set_selected_language("ko")
    assert recognizer.selected_language == "ko"
    assert "진저에일" in recognizer._hotwords()


def test_japanese_kana_signal_requires_multiple_characters():
    assert contains_japanese_kana("追加のタオルを届けます")
    assert contains_japanese_kana("レイトチェックアウト")
    assert not contains_japanese_kana("客室123")
    assert not contains_japanese_kana("Aの")


def test_enabled_languages_are_deduplicated():
    recognizer = WhisperRecognizer(SttConfig(), lambda *_: None)
    recognizer.set_enabled_languages(["en", "ko", "en"])
    assert recognizer.enabled_languages == ["en", "ko"]


def test_low_probability_enabled_language_is_not_forced():
    class FakeModel:
        def detect_language(self, audio):
            return "fr", 0.9, [("fr", 0.9), ("en", 0.2), ("ko", 0.1)]

        def transcribe(self, audio, **kwargs):
            assert kwargs["language"] is None
            return [SimpleNamespace(text="Bonjour")], SimpleNamespace(
                language="fr", language_probability=0.9
            )

    recognizer = WhisperRecognizer(SttConfig(), lambda *_: None)
    recognizer.model = FakeModel()
    recognizer.set_enabled_languages(["en", "ko"])
    result = recognizer.transcribe(np.zeros(16000, dtype=np.float32))
    assert result.language == "fr"


def test_repetition_controls_are_sent_to_whisper():
    class FakeModel:
        def transcribe(self, audio, **kwargs):
            assert kwargs["repetition_penalty"] == 1.08
            assert kwargs["no_repeat_ngram_size"] == 2
            return [SimpleNamespace(text="check check check")], SimpleNamespace(
                language="en", language_probability=1.0
            )

    recognizer = WhisperRecognizer(SttConfig(), lambda *_: None)
    recognizer.model = FakeModel()
    result = recognizer.transcribe(np.zeros(16000, dtype=np.float32), language="en")
    assert result.text == "check"


def test_low_confidence_result_gets_a_quality_retry_only_when_needed():
    class FakeModel:
        def __init__(self):
            self.calls = 0

        def transcribe(self, audio, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return [SimpleNamespace(text="unclear", avg_logprob=-1.2)], SimpleNamespace(
                    language="en", language_probability=0.4
                )
            assert kwargs["beam_size"] == 2
            return [SimpleNamespace(text="clear answer", avg_logprob=-0.1)], SimpleNamespace(
                language="en", language_probability=0.9
            )

    recognizer = WhisperRecognizer(SttConfig(), lambda *_: None)
    recognizer.model = FakeModel()
    result = recognizer.transcribe(np.zeros(16000, dtype=np.float32), language="en")
    assert result.text == "clear answer"
    assert result.quality_retry_used is True


def test_lower_confidence_quality_retry_does_not_replace_better_first_pass():
    class FakeModel:
        def __init__(self):
            self.calls = 0

        def transcribe(self, audio, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return [SimpleNamespace(text="correct answer", avg_logprob=-1.0)], SimpleNamespace(
                    language="en", language_probability=1.0
                )
            return [SimpleNamespace(text="wrong answer", avg_logprob=-2.0)], SimpleNamespace(
                language="en", language_probability=1.0
            )

    recognizer = WhisperRecognizer(SttConfig(), lambda *_: None)
    recognizer.model = FakeModel()
    result = recognizer.transcribe(np.zeros(16000, dtype=np.float32), language="en")
    assert result.text == "correct answer"
    assert result.quality_retry_used is False


def test_high_no_speech_probability_rejects_background_noise_text():
    class FakeModel:
        def transcribe(self, audio, **kwargs):
            return [
                SimpleNamespace(
                    text="Thank you for watching",
                    avg_logprob=-0.3,
                    no_speech_prob=0.97,
                )
            ], SimpleNamespace(language="en", language_probability=0.8)

    recognizer = WhisperRecognizer(SttConfig(), lambda *_: None)
    recognizer.model = FakeModel()
    result = recognizer.transcribe(np.zeros(16000, dtype=np.float32), language="en")
    assert result.text == ""
    assert result.no_speech_probability == pytest.approx(0.97)


def test_explicit_auto_language_overrides_selected_customer_language():
    class FakeModel:
        def transcribe(self, audio, **kwargs):
            assert kwargs["language"] is None
            return [SimpleNamespace(text="いらっしゃいませ")], SimpleNamespace(
                language="ja", language_probability=0.95
            )

    recognizer = WhisperRecognizer(SttConfig(), lambda *_: None)
    recognizer.model = FakeModel()
    recognizer.set_selected_language("ko")
    result = recognizer.transcribe(np.zeros(16000, dtype=np.float32), language="auto")
    assert result.language == "ja"
