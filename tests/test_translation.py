from translator_app.translation import protect_japanese_terms, protect_multilingual_terms


GLOSSARY = {
    "コーラ": ["cola", "콜라"],
    "ジンジャーエール": ["ginger ale", "진저에일"],
    "ピーナッツ": ["peanut", "땅콩"],
}


def test_corrects_known_model_term_errors():
    actual = protect_japanese_terms(
        "I'd like two colas and a ginger ale.",
        "2カラスと1ギンジャーアレが好きです。",
        GLOSSARY,
    )
    assert "コーラ" in actual
    assert "ジンジャーエール" in actual
    assert "重要語" not in actual


def test_appends_missing_safety_critical_term():
    actual = protect_japanese_terms(
        "I have a severe peanut allergy.",
        "真剣なアレルギーがあります。",
        GLOSSARY,
    )
    assert actual.endswith("（重要語: ピーナッツ）")


def test_protects_terms_in_reverse_translation():
    terms = [{"ja": ["ピーナッツ"], "en": ["peanut"]}]
    actual = protect_multilingual_terms(
        "ピーナッツアレルギーとして厨房に伝えます。",
        "I am allergic to the kitchen.",
        "ja",
        "en",
        terms,
    )
    assert actual.endswith("（Important term: peanut）")


def test_short_katakana_correction_does_not_corrupt_larger_word():
    assert protect_japanese_terms("collaboration", "コラボ企画です。", {}) == "コラボ企画です。"


def test_latin_term_uses_word_boundaries():
    terms = [{"en": ["safe"], "ja": ["金庫"]}]
    actual = protect_multilingual_terms("Safety is important", "安全が重要です", "en", "ja", terms)
    assert "重要語" not in actual
