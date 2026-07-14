from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Phrase:
    pattern: re.Pattern[str]
    translations: dict[str, str]


def _phrase(pattern: str, en: str, ko: str, zh: str, es: str) -> Phrase:
    return Phrase(re.compile(pattern), {"en": en, "ko": ko, "zh": zh, "es": es})


PHRASES = (
    _phrase(
        r"^(?:わかりました|分かりました|承知しました|かしこまりました|了解しました)[。.!！]?$",
        "Certainly.",
        "네, 알겠습니다.",
        "好的，明白了。",
        "Por supuesto.",
    ),
    _phrase(
        r"^お待たせ(?:いた)?しました[。.!！]?$",
        "Thank you for waiting.",
        "기다려 주셔서 감사합니다.",
        "感谢您的耐心等待。",
        "Gracias por esperar.",
    ),
    _phrase(
        r"^(?:確認いたします|確認します)[。.!！]?$",
        "Let me check that for you.",
        "확인해 보겠습니다.",
        "我来为您确认一下。",
        "Permítame comprobarlo.",
    ),
    _phrase(
        r"^(?:申し訳ございません|大変申し訳ございません)[。.!！]?$",
        "I'm very sorry.",
        "정말 죄송합니다.",
        "真的非常抱歉。",
        "Lo siento mucho.",
    ),
    _phrase(
        r"^(?:もう一度|もう一回)(?:お願いします|おっしゃってください)[。.!！]?$",
        "Could you please say that again?",
        "다시 한번 말씀해 주시겠어요?",
        "可以请您再说一遍吗？",
        "¿Podría repetirlo, por favor?",
    ),
    _phrase(
        r"^(?:もう少し)?ゆっくり(?:話して|お話し)(?:ください|いただけますか)[。.!！]?$",
        "Could you speak a little more slowly, please?",
        "조금만 천천히 말씀해 주시겠어요?",
        "可以请您说慢一点吗？",
        "¿Podría hablar un poco más despacio, por favor?",
    ),
    _phrase(
        r"^(?:こちら|これ)でよろしいでしょうか[。.!！?？]?$",
        "Would this be all right?",
        "이렇게 해드리면 괜찮으실까요?",
        "这样可以吗？",
        "¿Le parece bien así?",
    ),
    _phrase(
        r"^(?:何か)?お手伝いできること(?:はございますか|がありますか)[。.!！?？]?$",
        "How may I assist you?",
        "무엇을 도와드릴까요?",
        "请问有什么可以帮您的吗？",
        "¿En qué puedo ayudarle?",
    ),
    _phrase(
        r"^お電話(?:をいただき|いただき)?ありがとうございます[。.!！]?$",
        "Thank you for calling.",
        "전화 주셔서 감사합니다.",
        "感谢您的来电。",
        "Gracias por llamar.",
    ),
    _phrase(
        r"^お問い合わせ(?:をいただき|いただき)?ありがとうございます[。.!！]?$",
        "Thank you for contacting us.",
        "문의해 주셔서 감사합니다.",
        "感谢您的咨询。",
        "Gracias por ponerse en contacto con nosotros.",
    ),
    _phrase(
        r"^(?:本日は)?(?:どのような|どんな)ご用件(?:でしょうか|でございますか|ですか)[。.!！?？]?$",
        "How may I help you today?",
        "무엇을 도와드릴까요?",
        "今天有什么可以帮您的吗？",
        "¿En qué puedo ayudarle hoy?",
    ),
    _phrase(
        r"^(?:ご予約|予約内容)(?:を|について)?確認(?:いた)?します[。.!！]?$",
        "Let me check your reservation.",
        "예약 내용을 확인해 보겠습니다.",
        "我来为您确认预订信息。",
        "Permítame comprobar su reserva.",
    ),
    _phrase(
        r"^(?:確認のため、?)?(?:ご予約|予約)(?:時|の際)?(?:の)?お名前を(?:(?:お伺いしても|伺っても)よろしいでしょうか)[。.!！?？]?$",
        "May I have the name on the reservation, please?",
        "예약자 성함을 확인해도 될까요?",
        "请问预订时使用的姓名是什么？",
        "¿Podría indicarme el nombre de la reserva, por favor?",
    ),
    _phrase(
        r"^(?:確認の間、?)?(?:少々)?保留(?:にさせていただいても|にしても|で)(?:よろしいでしょうか|よろしいですか)[。.!！?？]?$",
        "May I place you on hold while I check?",
        "확인하는 동안 잠시 통화를 보류해도 될까요?",
        "请问可以请您稍等一下，让我为您确认吗？",
        "¿Puedo ponerle en espera mientras lo compruebo?",
    ),
    _phrase(
        r"^担当部署(?:へ|に)(?:おつなぎ|お繋ぎ|転送)(?:いた)?します[。.!！]?$",
        "I'll connect you with the appropriate department.",
        "담당 부서로 연결해 드리겠습니다.",
        "我为您转接相关部门。",
        "Le comunicaré con el departamento correspondiente.",
    ),
    _phrase(
        r"^(?:担当者|担当の者)(?:へ|に)(?:おつなぎ|お繋ぎ|転送)(?:いた)?します[。.!！]?$",
        "I'll connect you with the appropriate staff member.",
        "담당자에게 연결해 드리겠습니다.",
        "我为您转接相关工作人员。",
        "Le comunicaré con la persona responsable.",
    ),
    _phrase(
        r"^(?:担当者|担当の者)(?:から)?折り返し(?:お電話|ご連絡)(?:いた)?します[。.!！]?$",
        "The appropriate staff member will call you back.",
        "담당자가 다시 연락드리겠습니다.",
        "相关工作人员会给您回电。",
        "La persona responsable le devolverá la llamada.",
    ),
    _phrase(
        r"^(?:ご希望|希望)(?:の)?(?:日程|お日にち|日付)(?:を|について)?(?:お伺い|教えて)(?:いただけますか|ください)[。.!！?？]?$",
        "What dates would you like to stay?",
        "희망하시는 숙박 날짜를 알려 주시겠어요?",
        "请问您希望入住哪些日期？",
        "¿En qué fechas desea alojarse?",
    ),
    _phrase(
        r"^(?:ご宿泊|宿泊)(?:の)?人数(?:を|について)?(?:お伺い|教えて)(?:いただけますか|ください)[。.!！?？]?$",
        "How many guests will be staying?",
        "숙박 인원을 알려 주시겠어요?",
        "请问有几位客人入住？",
        "¿Cuántos huéspedes se alojarán?",
    ),
    _phrase(
        r"^(?:ご希望|希望)(?:の)?(?:日程|お日にち|日付)(?:の)?空室(?:を|状況を)?確認(?:いた)?します[。.!！]?$",
        "Let me check availability for those dates.",
        "해당 날짜의 객실 가능 여부를 확인해 보겠습니다.",
        "我来确认这些日期是否有空房。",
        "Permítame comprobar la disponibilidad para esas fechas.",
    ),
    _phrase(
        r"^(?:あいにく、?)?(?:ご希望|希望)(?:の)?(?:日程|お日にち|日付)(?:は|が)?(?:満室|空室がございません)(?:でございます|です)?[。.!！]?$",
        "I'm sorry, but we're fully booked for those dates.",
        "죄송하지만 해당 날짜에는 예약 가능한 객실이 없습니다.",
        "很抱歉，这些日期的客房已订满。",
        "Lo siento, pero no tenemos disponibilidad para esas fechas.",
    ),
    _phrase(
        r"^(?:ご希望|ご要望)に添えず(?:、)?申し訳ございません[。.!！]?$",
        "I'm sorry we couldn't accommodate your request.",
        "요청하신 내용을 도와드리지 못해 죄송합니다.",
        "很抱歉未能满足您的要求。",
        "Lamento que no hayamos podido atender su solicitud.",
    ),
    _phrase(
        r"^(?:ほか|他)に(?:ご質問|ご不明な点|お手伝いできること)(?:はございますか|がありますか)[。.!！?？]?$",
        "Is there anything else I can help you with?",
        "그 밖에 도와드릴 사항이 있을까요?",
        "请问还有什么可以帮您的吗？",
        "¿Hay algo más en lo que pueda ayudarle?",
    ),
    _phrase(
        r"^お電話(?:をいただき|いただき)?ありがとうございました[。.!！]?$",
        "Thank you for calling. Have a nice day.",
        "전화 주셔서 감사합니다. 좋은 하루 보내세요.",
        "感谢您的来电，祝您愉快。",
        "Gracias por llamar. Que tenga un buen día.",
    ),
    _phrase(
        r"^お問い合わせ(?:をいただき|いただき)?ありがとうございました[。.!！]?$",
        "Thank you for contacting us.",
        "문의해 주셔서 감사합니다.",
        "感谢您的咨询。",
        "Gracias por ponerse en contacto con nosotros.",
    ),
    _phrase(
        r"^(?:ご予約|予約)(?:の)?番号(?:を)?(?:教えて(?:いただけますか|ください)|お願いいたします|お願いします)[。.!！?？]?$",
        "Please give me your reservation number.",
        "예약 번호를 알려 주세요.",
        "请告诉我您的预订号码。",
        "Por favor, indíqueme su número de reserva.",
    ),
    _phrase(
        r"^(?:(?:ご予約|予約)(?:時|の際)?(?:の)?)?お名前(?:を)?(?:教えて(?:いただけますか|ください)|お願いいたします|お願いします)[。.!！?？]?$",
        "May I have your name, please?",
        "성함을 알려 주세요.",
        "请告诉我您的姓名。",
        "¿Podría indicarme su nombre, por favor?",
    ),
    _phrase(
        r"^(?:お部屋|部屋|客室)(?:の)?番号(?:を)?(?:教えて(?:いただけますか|ください)|お願いいたします|お願いします)[。.!！?？]?$",
        "May I have your room number, please?",
        "객실 번호를 알려 주세요.",
        "请告诉我您的房间号码。",
        "¿Podría indicarme el número de su habitación?",
    ),
    _phrase(
        r"^追加(?:の)?タオル(?:を)?(?:3|三)枚(?:、)?(?:(?:お部屋|部屋|客室)(?:に|へ))?(?:お届け|お持ち)(?:いた)?します[。.!！]?$",
        "We will deliver three additional towels to your room.",
        "추가 수건 세 장을 객실로 가져다드리겠습니다.",
        "我们会把三条额外的毛巾送到您的房间。",
        "Le llevaremos tres toallas adicionales a su habitación.",
    ),
    _phrase(
        r"^空港(?:行き)?(?:の)?シャトル(?:は|が)?午前?(?:8|八)時(?:に)?出発(?:いた)?します[。.!！]?$",
        "The airport shuttle leaves at 8:00 a.m.",
        "공항 셔틀은 오전 8시에 출발합니다.",
        "机场班车上午八点出发。",
        "El transporte al aeropuerto sale a las ocho de la mañana.",
    ),
    _phrase(
        r"^ピーナッツ(?:の)?アレルギー(?:があること|について|として)?(?:を)?(?:厨房|キッチン)(?:に|へ)(?:(?:お伝え)(?:いた)?します|伝えます)[。.!！]?$",
        "We will inform the kitchen about your peanut allergy.",
        "땅콩 알레르기가 있다고 주방에 전달하겠습니다.",
        "我们会将您的花生过敏情况告知厨房。",
        "Informaremos a la cocina de su alergia al cacahuete.",
    ),
    _phrase(
        r"^レイトチェックアウト(?:は|が)?午後?(?:2|二)時まで可能(?:でございます|です)?[。.!！]?$",
        "Late check-out is available until 2:00 p.m.",
        "레이트 체크아웃은 오후 2시까지 가능합니다.",
        "延迟退房可以到下午两点。",
        "La salida tardía está disponible hasta las dos de la tarde.",
    ),
    _phrase(
        r"^(?:少々|しばらく)(?:、)?(?:お待ちください|待ってください)[。.!！]?$",
        "Please wait a moment.",
        "잠시만 기다려 주세요.",
        "请稍等片刻。",
        "Espere un momento, por favor.",
    ),
    _phrase(
        r"^(?:(?:ご)?(?:不便|迷惑)をおかけし(?:て)?(?:、)?(?:大変)?申し訳ございません|(?:大変)?申し訳ございません(?:、)?(?:ご)?(?:不便|迷惑)をおかけしました)[。.!！]?$",
        "We sincerely apologize for the inconvenience.",
        "불편을 드려 진심으로 죄송합니다.",
        "给您带来不便，我们深表歉意。",
        "Le pedimos sinceras disculpas por las molestias.",
    ),
    _phrase(
        r"^(?:スタッフ|係員|技術者)(?:が)?(?:すぐ|まもなく)?(?:お部屋|部屋|客室)(?:に|へ)(?:伺います|行きます)[。.!！]?$",
        "A staff member will come to your room shortly.",
        "직원이 곧 객실로 방문하겠습니다.",
        "工作人员很快会到您的房间。",
        "Un miembro del personal irá a su habitación en breve.",
    ),
    _phrase(
        r"^タクシー(?:を)?(?:(?:手配|お呼び)(?:いた)?します|呼びます)[。.!！]?$",
        "We will arrange a taxi for you.",
        "택시를 불러 드리겠습니다.",
        "我们会为您安排出租车。",
        "Le pediremos un taxi.",
    ),
    _phrase(
        r"^(?:ご)?(?:請求|料金|請求内容)(?:を)?確認(?:いた)?します[。.!！]?$",
        "We will review the charge.",
        "요금을 확인해 보겠습니다.",
        "我们会核对费用。",
        "Revisaremos el cargo.",
    ),
    _phrase(
        r"^(?:ご)?(?:請求|料金|請求内容)(?:を)?(?:訂正|修正)(?:いた)?します[。.!！]?$",
        "We will correct the charge.",
        "요금을 정정하겠습니다.",
        "我们会更正费用。",
        "Corregiremos el cargo.",
    ),
    _phrase(
        r"^朝食会場(?:は|が)?(?:2|二)階(?:で|にあり、?|にございます、?)(?:営業時間は)?(?:午前)?(?:6時30分|6時半|六時半)(?:から|～|〜)(?:午前)?(?:10|十)時(?:まで)?(?:です|でございます)?[。.!！]?$",
        "The breakfast venue is on the second floor and is open from 6:30 to 10:00 a.m.",
        "조식 장소는 2층이며 오전 6시 30분부터 10시까지 운영합니다.",
        "早餐地点在二楼，开放时间为上午六点半到十点。",
        "El desayuno se sirve en la segunda planta de 6:30 a 10:00 de la mañana.",
    ),
    _phrase(
        r"^パスポートが見つかりました[。.!！](?:身分証明書|身分証)(?:を)?持ってフロント(?:デスク)?(?:へ|に)お越しください[。.!！]?$",
        "We found your passport. Please bring identification to the front desk.",
        "여권을 찾았습니다. 신분증을 가지고 프런트 데스크로 와 주세요.",
        "我们找到了您的护照。请携带身份证件到前台领取。",
        "Hemos encontrado su pasaporte. Lleve un documento de identificación a recepción.",
    ),
    _phrase(
        r"^緊急(?:の場合|時)(?:は|、)?救急車を手配(?:いた)?します[。.!！]?$",
        "In an emergency, we will arrange an ambulance.",
        "응급 상황에는 구급차를 불러 드리겠습니다.",
        "紧急情况下，我们会为您安排救护车。",
        "En caso de emergencia, solicitaremos una ambulancia.",
    ),
)


def translate_hotel_phrase(text: str, target_code: str) -> str | None:
    compact = re.sub(r"\s+", "", text.strip())
    for phrase in PHRASES:
        if phrase.pattern.search(compact):
            return phrase.translations.get(target_code)
    return None
