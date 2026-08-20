from translator_app.reading import reading_guide, romanized_guide


def test_korean_has_both_japanese_and_latin_readings():
    text = "입력하겠습니다."
    assert reading_guide(text, "ko").startswith("イプ")
    assert romanized_guide(text, "ko") == "ipryeokhagetseumnida."


def test_chinese_has_katakana_and_pinyin():
    text = "请稍等一下。"
    assert reading_guide(text, "zh").startswith("チン")
    assert romanized_guide(text, "zh") == "qing shao deng yi xia."


def test_english_and_spanish_keep_latin_companion():
    assert reading_guide("Please wait a moment.", "en").startswith("プリーズ")
    assert romanized_guide("Please wait a moment.", "en") == "Please wait a moment."
    assert reading_guide("Gracias", "es") == "グラシアス"
    assert romanized_guide("Gracias", "es") == "Gracias"


def test_other_scripts_get_lightweight_ascii_fallback():
    assert romanized_guide("Подождите", "ru") == "Podozhdite"
    assert romanized_guide("يرجى الانتظار", "ar").isascii()


def test_empty_and_oversized_guides_are_rejected():
    assert reading_guide("", "ko") == ""
    assert romanized_guide("a" * 501, "en") == ""
