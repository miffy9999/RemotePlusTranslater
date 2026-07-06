from translator_app.phrasebook import translate_hotel_phrase


def test_allergy_reply_is_safe_in_all_customer_languages():
    source = "ピーナッツアレルギーとして厨房に伝えます。"
    assert "peanut allergy" in translate_hotel_phrase(source, "en")
    assert "땅콩 알레르기" in translate_hotel_phrase(source, "ko")
    assert "花生过敏" in translate_hotel_phrase(source, "zh")
    assert "alergia al cacahuete" in translate_hotel_phrase(source, "es")


def test_phrasebook_does_not_guess_unmatched_free_speech():
    assert translate_hotel_phrase("今日は良い天気ですね。", "en") is None


def test_late_checkout_keeps_time_and_intent():
    actual = translate_hotel_phrase("レイトチェックアウトは午後2時まで可能です。", "en")
    assert actual == "Late check-out is available until 2:00 p.m."


def test_found_passport_reply_does_not_translate_front_as_body_part():
    source = "パスポートが見つかりました。身分証明書を持ってフロントへお越しください。"
    assert "front desk" in translate_hotel_phrase(source, "en")
    assert "프런트 데스크" in translate_hotel_phrase(source, "ko")
    assert "前台" in translate_hotel_phrase(source, "zh")
    assert "recepción" in translate_hotel_phrase(source, "es")
