import pytest

from translator_app.phrasebook import (
    translate_customer_hotel_phrase,
    translate_hotel_phrase,
)


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


def test_front_desk_phone_greeting_is_functional_not_literal():
    assert translate_hotel_phrase("フロントでございます", "en") == "Front desk speaking."
    assert translate_hotel_phrase("はい、フロントでございます。", "ko") == "프런트 데스크입니다."
    assert (
        translate_hotel_phrase(
            "お電話ありがとうございます。ホテルフェスタ葉山でございます",
            "en",
        )
        == "Thank you for calling. Hotel Festa Hayama speaking."
    )


def test_repeat_request_keeps_optional_room_number_and_intent():
    assert (
        translate_hotel_phrase("もう一度よろしいですか?", "en")
        == "Could you please say that again?"
    )


def test_field_call_room_and_callback_requests_keep_operational_intent():
    assert (
        translate_customer_hotel_phrase(
            "good morning, this is room 204 could you please open the door?",
            "en",
        )
        == "おはようございます。204号室です。ドアを開けていただけますか？"
    )
    assert (
        translate_customer_hotel_phrase(
            "we have a dedicated phone number, so could you please call us back?",
            "en",
        )
        == "専用の電話番号がありますので、折り返しお電話いただけますか？"
    )


@pytest.mark.parametrize(
    ("source", "language", "expected"),
    (
        ("What time can I check in?", "en", "チェックインは何時からできますか。"),
        ("The room next door is too noisy.", "en", "隣の部屋がうるさすぎます。"),
        (
            "사용하지 않은 미니바 요금이 청구되었습니다.",
            "ko",
            "利用していないミニバーの料金が請求されています。",
        ),
        (
            "아이가 열이 나는데 의사를 불러 주실 수 있나요?",
            "ko",
            "子どもが熱を出しています。医師を呼んでいただけますか。",
        ),
    ),
)
def test_curated_english_and_korean_customer_phrases_skip_model_errors(
    source, language, expected
):
    assert translate_customer_hotel_phrase(source, language) == expected


def test_field_fragments_use_contextually_complete_japanese():
    assert (
        translate_customer_hotel_phrase(
            "Wait, I have a question. If I need send my baggage",
            "en",
        )
        == "すみません、質問があります。荷物を送りたいのですが。"
    )
    assert (
        translate_customer_hotel_phrase(
            "I have a reservation. I'll be arriving past 23:30.",
            "en",
        )
        == "予約しています。23時30分を過ぎて到着する予定です。"
    )
    assert (
        translate_customer_hotel_phrase(
            "one more time, I didn't get it",
            "en",
        )
        == "もう一度お願いします。聞き取れませんでした。"
    )
    assert (
        translate_hotel_phrase("もう一度よろしいでしょうか?401", "ko")
        == "다시 한번 말씀해 주시겠어요? 401호실이 맞으신가요?"
    )


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


def test_combined_check_wait_charge_and_breakfast_phrases_preserve_all_facts():
    assert translate_hotel_phrase(
        "確認いたしますので、少々お待ちください。", "es"
    ) == "Espere un momento mientras lo compruebo."
    assert translate_hotel_phrase(
        "請求内容を確認して訂正いたします。", "ko"
    ) == "청구 내용을 확인하고 정정하겠습니다."
    assert translate_hotel_phrase(
        "朝食会場は2階で、午前6時30分から10時までです。", "en"
    ) == "The breakfast venue is on the second floor and is open from 6:30 to 10:00 a.m."


@pytest.mark.parametrize(
    ("source_code", "source"),
    (
        ("en", "Please do not clean the room today."),
        ("ko", "오늘은 객실 청소를 하지 말아 주세요."),
        ("zh", "今天请不要打扫房间。"),
        ("es", "Por favor, no limpie la habitación hoy."),
    ),
)
def test_no_cleaning_request_never_loses_negation(source_code, source):
    assert translate_customer_hotel_phrase(source, source_code) == (
        "今日は客室を清掃しないでください。"
    )


@pytest.mark.parametrize(
    ("source", "expected_ko"),
    (
        ("おはようございます。", "안녕하세요."),
        ("こんにちは。", "안녕하세요."),
        ("こんばんは。", "안녕하세요."),
        ("おやすみなさい。", "안녕히 주무세요."),
        ("はじめまして。", "처음 뵙겠습니다."),
        ("ありがとうございます。", "감사합니다."),
        ("どういたしまして。", "천만에요."),
        ("申し訳ありません。", "죄송합니다."),
        ("大丈夫ですか。", "괜찮으세요?"),
        ("大丈夫です。", "괜찮습니다."),
        ("はい、そうです。", "네, 맞습니다."),
        ("いいえ、違います。", "아니요, 그렇지 않습니다."),
        ("よくわかりません。", "잘 모르겠습니다."),
        ("もちろんです。", "물론입니다."),
        ("失礼いたします。", "실례하겠습니다."),
        ("さようなら。", "안녕히 가세요."),
        ("また明日。", "내일 뵙겠습니다."),
        ("お気をつけてお帰りください。", "조심히 돌아가세요."),
        ("よかったです。", "다행입니다."),
        ("聞こえません。", "잘 들리지 않습니다."),
        ("どういう意味ですか。", "무슨 뜻인가요?"),
        ("お名前は何ですか。", "성함이 어떻게 되시나요?"),
        ("どこですか。", "어디에 있나요?"),
        ("何時ですか。", "몇 시인가요?"),
        ("いくらですか。", "얼마인가요?"),
    ),
)
def test_daily_conversation_uses_natural_korean_not_literal_fragments(
    source, expected_ko
):
    assert translate_hotel_phrase(source, "ko") == expected_ko


@pytest.mark.parametrize(
    ("target", "expected"),
    (
        ("en", "Good evening."),
        ("ko", "안녕하세요."),
        ("zh", "晚上好。"),
        ("es", "Buenas tardes."),
    ),
)
def test_konbanwa_is_a_greeting_in_primary_languages(target, expected):
    assert translate_hotel_phrase("こんばんは。", target) == expected


@pytest.mark.parametrize(
    ("source", "target", "expected"),
    [
        ("それでお願いします。", "ko", "그걸로 부탁드립니다."),
        ("そちらでお願いします。", "en", "That one, please."),
        ("それなら大丈夫です。", "ko", "그렇다면 괜찮습니다."),
        ("それは含まれていますか。", "en", "Is that included?"),
    ],
)
def test_referential_service_formulas_preserve_speaker_intent(source, target, expected):
    assert translate_hotel_phrase(source, target) == expected


@pytest.mark.parametrize(
    ("source", "language"),
    [("그건 빼 주세요.", "ko"), ("Please leave that out.", "en")],
)
def test_customer_exclusion_request_never_repeats_the_previous_offer(source, language):
    assert translate_customer_hotel_phrase(source, language) == "それは追加しないでください。"
