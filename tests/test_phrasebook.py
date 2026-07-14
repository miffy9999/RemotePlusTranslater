import pytest

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


def test_common_acknowledgement_uses_natural_service_language():
    assert translate_hotel_phrase("わかりました。", "en") == "Certainly."
    assert translate_hotel_phrase("わかりました。", "ko") == "네, 알겠습니다."


def test_common_service_phrases_are_not_translated_word_for_word():
    assert translate_hotel_phrase("お待たせしました。", "en") == "Thank you for waiting."
    assert translate_hotel_phrase("確認いたします。", "ko") == "확인해 보겠습니다."
    assert translate_hotel_phrase("もう一度お願いします。", "en") == "Could you please say that again?"


def test_short_phrase_rules_do_not_capture_longer_unrelated_sentences():
    assert translate_hotel_phrase("問題の原因がわかりました。", "en") is None


def test_common_hotel_call_center_phrases_use_natural_english_and_korean():
    examples = (
        ("お電話ありがとうございます。", "Thank you for calling.", "전화 주셔서 감사합니다."),
        ("本日はどのようなご用件でしょうか。", "How may I help you today?", "무엇을 도와드릴까요?"),
        ("ご予約を確認いたします。", "Let me check your reservation.", "예약 내용을 확인해 보겠습니다."),
        (
            "確認の間、少々保留にさせていただいてもよろしいでしょうか。",
            "May I place you on hold while I check?",
            "확인하는 동안 잠시 통화를 보류해도 될까요?",
        ),
        (
            "担当部署におつなぎします。",
            "I'll connect you with the appropriate department.",
            "담당 부서로 연결해 드리겠습니다.",
        ),
        (
            "他にお手伝いできることはございますか。",
            "Is there anything else I can help you with?",
            "그 밖에 도와드릴 사항이 있을까요?",
        ),
    )
    for source, expected_en, expected_ko in examples:
        assert translate_hotel_phrase(source, "en") == expected_en
        assert translate_hotel_phrase(source, "ko") == expected_ko


def test_call_center_rules_do_not_invent_details_for_unmatched_requests():
    assert translate_hotel_phrase("予約について友人と相談します。", "en") is None
    assert translate_hotel_phrase("担当者の名前を教えてください。", "ko") is None


@pytest.mark.parametrize(
    "source",
    (
        "タクシーは手配できません。",
        "緊急時でも救急車は手配できません。",
        "料金を確認できません。",
        "ピーナッツアレルギーは厨房に伝えられません。",
        "予約番号を教えていただきました。",
        "タクシーを手配します。料金は3,000円です。",
    ),
)
def test_fixed_phrases_never_turn_negation_or_extra_details_into_a_promise(source):
    assert translate_hotel_phrase(source, "en") is None
    assert translate_hotel_phrase(source, "ko") is None


def test_safe_exact_service_phrases_still_use_fast_natural_translations():
    assert translate_hotel_phrase("タクシーを手配します。", "en") == "We will arrange a taxi for you."
    assert translate_hotel_phrase("少々お待ちください。", "ko") == "잠시만 기다려 주세요."
    assert translate_hotel_phrase("料金を確認します。", "en") == "We will review the charge."


def test_contact_and_transfer_phrases_preserve_their_exact_channel_and_target():
    assert translate_hotel_phrase("お問い合わせありがとうございます。", "en") == (
        "Thank you for contacting us."
    )
    assert translate_hotel_phrase("担当者におつなぎします。", "ko") == (
        "담당자에게 연결해 드리겠습니다."
    )
    assert translate_hotel_phrase("担当部署におつなぎします。", "ko") == (
        "담당 부서로 연결해 드리겠습니다."
    )


def test_common_taxi_and_reservation_name_variants_use_fast_path():
    assert translate_hotel_phrase("タクシーを呼びます。", "en") == (
        "We will arrange a taxi for you."
    )
    assert translate_hotel_phrase(
        "ご予約のお名前をお伺いしてもよろしいでしょうか。", "en"
    ) == "May I have the name on the reservation, please?"
