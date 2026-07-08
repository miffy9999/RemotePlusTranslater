from types import SimpleNamespace

import numpy as np

from translator_app.config import SttConfig
from translator_app.stt import WhisperRecognizer, apply_corrections, contains_japanese_kana


def test_domain_corrections_are_deterministic():
    corrections = {"콜을 주세요": "콜라 주세요", "진저일": "진저에일"}
    assert apply_corrections("콜을 주세요. 진저일도 주세요.", corrections) == (
        "콜라 주세요. 진저에일도 주세요."
    )


def test_longer_correction_runs_first():
    corrections = {"진저": "생강", "진저일": "진저에일"}
    assert apply_corrections("진저일", corrections) == "진저에일"


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
