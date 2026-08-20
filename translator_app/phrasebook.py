from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Phrase:
    pattern: re.Pattern[str]
    translations: dict[str, str]


def _phrase(pattern: str, en: str, ko: str, zh: str, es: str) -> Phrase:
    return Phrase(re.compile(pattern), {"en": en, "ko": ko, "zh": zh, "es": es})


PHRASES = (
    _phrase(
        r"^(?:はい、?)?フロント(?:デスク)?でございます[。.!！]?$",
        "Front desk speaking.",
        "프런트 데스크입니다.",
        "这里是前台。",
        "Le atiende recepción.",
    ),
    _phrase(
        r"^(?:お電話ありがとうございます[。.!！]?)?ホテルフェスタ葉山でございます[。.!！]?$",
        "Thank you for calling. Hotel Festa Hayama speaking.",
        "전화 주셔서 감사합니다. 호텔 페스타 하야마입니다.",
        "感谢您的来电。这里是叶山费斯塔酒店。",
        "Gracias por llamar. Le atiende el Hotel Festa Hayama.",
    ),
    _phrase(
        r"^おはよう(?:ございます)?[。.!！]?$",
        "Good morning.",
        "안녕하세요.",
        "早上好。",
        "Buenos días.",
    ),
    _phrase(
        r"^こんにちは[。.!！]?$",
        "Hello.",
        "안녕하세요.",
        "您好。",
        "Hola.",
    ),
    _phrase(
        r"^こんばんは[。.!！]?$",
        "Good evening.",
        "안녕하세요.",
        "晚上好。",
        "Buenas tardes.",
    ),
    _phrase(
        r"^おやすみなさい[。.!！]?$",
        "Good night.",
        "안녕히 주무세요.",
        "晚安。",
        "Buenas noches.",
    ),
    _phrase(
        r"^はじめまして[。.!！]?$",
        "It's a pleasure to meet you.",
        "처음 뵙겠습니다.",
        "很高兴认识您。",
        "Mucho gusto.",
    ),
    _phrase(
        r"^(?:どうも)?ありがとうございます[。.!！]?$",
        "Thank you very much.",
        "감사합니다.",
        "非常感谢。",
        "Muchas gracias.",
    ),
    _phrase(
        r"^どういたしまして[。.!！]?$",
        "You're welcome.",
        "천만에요.",
        "不客气。",
        "De nada.",
    ),
    _phrase(
        r"^(?:ごめんなさい|申し訳ありません)[。.!！]?$",
        "I'm sorry.",
        "죄송합니다.",
        "对不起。",
        "Lo siento.",
    ),
    _phrase(
        r"^大丈夫ですか[。.!！?？]?$",
        "Are you all right?",
        "괜찮으세요?",
        "您没事吧？",
        "¿Se encuentra bien?",
    ),
    _phrase(
        r"^(?:大丈夫|問題ありません)です?[。.!！]?$",
        "It's all right.",
        "괜찮습니다.",
        "没问题。",
        "No hay problema.",
    ),
    _phrase(
        r"^はい、?そうです[。.!！]?$",
        "Yes, that's right.",
        "네, 맞습니다.",
        "是的，没错。",
        "Sí, así es.",
    ),
    _phrase(
        r"^いいえ、?違います[。.!！]?$",
        "No, that's not correct.",
        "아니요, 그렇지 않습니다.",
        "不，不是这样。",
        "No, no es así.",
    ),
    _phrase(
        r"^(?:よく)?わかりません[。.!！]?$",
        "I'm not sure.",
        "잘 모르겠습니다.",
        "我不太清楚。",
        "No estoy seguro.",
    ),
    _phrase(
        r"^お願いします[。.!！]?$",
        "Yes, please.",
        "부탁드립니다.",
        "拜托了。",
        "Sí, por favor.",
    ),
    _phrase(
        r"^(?:それ|そちら|これ|こちら)でお願いします[。.!！]?$",
        "That one, please.",
        "그걸로 부탁드립니다.",
        "请按那个办理。",
        "Ese, por favor.",
    ),
    _phrase(
        r"^それなら大丈夫です[。.!！]?$",
        "That will be fine.",
        "그렇다면 괜찮습니다.",
        "那样就可以。",
        "En ese caso, está bien.",
    ),
    _phrase(
        r"^それは含まれていますか[。.!！?？]?$",
        "Is that included?",
        "그것도 포함되어 있나요?",
        "那个包含在内吗？",
        "¿Eso está incluido?",
    ),
    _phrase(
        r"^もちろんです[。.!！]?$",
        "Certainly.",
        "물론입니다.",
        "当然可以。",
        "Por supuesto.",
    ),
    _phrase(
        r"^失礼いたします[。.!！]?$",
        "Excuse me.",
        "실례하겠습니다.",
        "失陪了。",
        "Disculpe.",
    ),
    _phrase(
        r"^さようなら[。.!！]?$",
        "Goodbye.",
        "안녕히 가세요.",
        "再见。",
        "Adiós.",
    ),
    _phrase(
        r"^また明日[。.!！]?$",
        "See you tomorrow.",
        "내일 뵙겠습니다.",
        "明天见。",
        "Hasta mañana.",
    ),
    _phrase(
        r"^お気をつけて(?:お帰り)?ください[。.!！]?$",
        "Have a safe journey.",
        "조심히 돌아가세요.",
        "请慢走。",
        "Que tenga buen viaje.",
    ),
    _phrase(
        r"^またお越しください[。.!！]?$",
        "We look forward to welcoming you again.",
        "다음에 또 방문해 주세요.",
        "欢迎您再次光临。",
        "Esperamos volver a recibirle.",
    ),
    _phrase(
        r"^よかったです[。.!！]?$",
        "I'm glad to hear that.",
        "다행입니다.",
        "那太好了。",
        "Me alegro.",
    ),
    _phrase(
        r"^聞こえません[。.!！]?$",
        "I can't hear you.",
        "잘 들리지 않습니다.",
        "我听不清。",
        "No le oigo bien.",
    ),
    _phrase(
        r"^もう少し大きな声でお願いします[。.!！]?$",
        "Could you speak a little louder, please?",
        "조금 더 큰 목소리로 말씀해 주세요.",
        "请说大声一点。",
        "¿Podría hablar un poco más alto, por favor?",
    ),
    _phrase(
        r"^どういう意味ですか[。.!！?？]?$",
        "What do you mean?",
        "무슨 뜻인가요?",
        "您是什么意思？",
        "¿Qué quiere decir?",
    ),
    _phrase(
        r"^お名前は何ですか[。.!！?？]?$",
        "May I have your name?",
        "성함이 어떻게 되시나요?",
        "请问您叫什么名字？",
        "¿Podría indicarme su nombre?",
    ),
    _phrase(
        r"^どこですか[。.!！?？]?$",
        "Where is it?",
        "어디에 있나요?",
        "在哪里？",
        "¿Dónde está?",
    ),
    _phrase(
        r"^何時ですか[。.!！?？]?$",
        "What time is it?",
        "몇 시인가요?",
        "几点？",
        "¿A qué hora?",
    ),
    _phrase(
        r"^いくらですか[。.!！?？]?$",
        "How much is it?",
        "얼마인가요?",
        "多少钱？",
        "¿Cuánto cuesta?",
    ),
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
        r"^(?:少々|しばらく|ちょっと)(?:、)?(?:お待ちください|待ってください)[。.!！]?$",
        "Please wait a moment.",
        "잠시만 기다려 주세요.",
        "请稍等片刻。",
        "Espere un momento, por favor.",
    ),
    _phrase(
        r"^(?:確認いたします|確認します)ので、?(?:少々)?お待ちください[。.!！]?$",
        "Please wait a moment while I check.",
        "확인하는 동안 잠시만 기다려 주세요.",
        "请稍等片刻，我来为您确认。",
        "Espere un momento mientras lo compruebo.",
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
        r"^(?:ご)?(?:請求|料金|請求内容)(?:を)?確認して(?:訂正|修正)(?:いた)?します[。.!！]?$",
        "We will review the charge and correct it.",
        "청구 내용을 확인하고 정정하겠습니다.",
        "我们会核对费用并予以更正。",
        "Revisaremos el cargo y lo corregiremos.",
    ),
    _phrase(
        r"^朝食会場(?:は|が)?(?:2|二)階(?:で、?|にあり、?|にございます、?)(?:営業時間は)?(?:午前)?(?:6時30分|6時半|六時半)(?:から|～|〜)(?:午前)?(?:10|十)時(?:まで)?(?:です|でございます)?[。.!！]?$",
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


CUSTOMER_NO_CLEANING = {
    "en": re.compile(r"^Pleasedonotcleantheroomtoday[.!]?$", re.IGNORECASE),
    "ko": re.compile(r"^오늘은객실청소를하지말아주세요[。.!！]?$"),
    "zh": re.compile(r"^今天请不要打扫房间[。.!！]?$"),
    "es": re.compile(
        r"^Porfavor,nolimpielahabitaciónhoy[.!]?$", re.IGNORECASE
    ),
}

CUSTOMER_EXCLUSION = {
    "en": re.compile(r"^(?:Please)?(?:leavethatout|donotaddthat)[.!]?$", re.IGNORECASE),
    "ko": re.compile(r"^(?:그건|그것은|그거는)(?:빼|제외해|추가하지말아)주세요[。.!！]?$"),
}

CURATED_CUSTOMER_TRANSLATIONS = {
    ("en", "good evening"): "こんばんは。",
    ("en", "what time can i check in"): "チェックインは何時からできますか。",
    ("en", "the room next door is too noisy"): "隣の部屋がうるさすぎます。",
    ("en", "where and when is breakfast served"): "朝食会場はどこで、何時からですか。",
    (
        "en",
        "i was charged for a minibar item i did not use",
    ): "利用していないミニバーの商品が請求されています。",
    (
        "en",
        "my child has a fever. could you call a doctor",
    ): "子どもが熱を出しています。医師を呼んでいただけますか。",
    ("en", "could you hold on a moment please"): "少々お待ちいただけますか。",
    ("en", "what's the phone number"): "電話番号を教えていただけますか。",
    (
        "en",
        "wait, i have a question. if i need send my baggage",
    ): "すみません、質問があります。荷物を送りたいのですが。",
    (
        "en",
        "i have a reservation. i'll be arriving past 23:30",
    ): "予約しています。23時30分を過ぎて到着する予定です。",
    (
        "en",
        "one more time, i didn't get it",
    ): "もう一度お願いします。聞き取れませんでした。",
    ("ko", "안녕하세요"): "こんにちは。",
    ("ko", "체크인은 몇 시부터 가능한가요"): "チェックインは何時からできますか。",
    ("ko", "옆방 소음이 너무 심합니다"): "隣の部屋の騒音がひどいです。",
    (
        "ko",
        "조식은 어디에서 몇 시부터 먹을 수 있나요",
    ): "朝食はどこで何時から食べられますか。",
    (
        "ko",
        "사용하지 않은 미니바 요금이 청구되었습니다",
    ): "利用していないミニバーの料金が請求されています。",
    (
        "ko",
        "아이가 열이 나는데 의사를 불러 주실 수 있나요",
    ): "子どもが熱を出しています。医師を呼んでいただけますか。",
}


def _normalized_customer_phrase(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = re.sub(r"\s+", " ", normalized.strip()).casefold()
    return re.sub(r"[。.!！?？]+$", "", normalized).strip()


def translate_hotel_phrase(text: str, target_code: str) -> str | None:
    compact = re.sub(r"\s+", "", text.strip())
    repeat = re.fullmatch(
        r"もう一度よろしい(?:ですか|でしょうか)[?？]?(\d{1,4})?[。.!！]?",
        compact,
    )
    if repeat:
        room = repeat.group(1)
        base = {
            "en": "Could you please say that again?",
            "ko": "다시 한번 말씀해 주시겠어요?",
            "zh": "可以请您再说一遍吗？",
            "es": "¿Podría repetirlo, por favor?",
        }.get(target_code)
        if not base or not room:
            return base
        room_followup = {
            "en": f" Is that room {room}?",
            "ko": f" {room}호실이 맞으신가요?",
            "zh": f" 是{room}号房吗？",
            "es": f" ¿Es la habitación {room}?",
        }
        return base + room_followup[target_code]
    for phrase in PHRASES:
        if phrase.pattern.search(compact):
            return phrase.translations.get(target_code)
    return None


def translate_customer_hotel_phrase(text: str, source_code: str) -> str | None:
    """Protect a small set of exact, high-risk customer requests into Japanese."""
    clean = re.sub(r"\s+", " ", text.strip())
    curated = CURATED_CUSTOMER_TRANSLATIONS.get(
        (source_code, _normalized_customer_phrase(clean))
    )
    if curated is not None:
        return curated
    if source_code == "en":
        room_door = re.fullmatch(
            r"(?:good morning,\s*)?this is room\s+(\d{1,4})[,.]?\s*"
            r"could you please open the door\??",
            clean,
            re.IGNORECASE,
        )
        if room_door:
            return (
                f"おはようございます。{room_door.group(1)}号室です。"
                "ドアを開けていただけますか？"
            )
        if re.fullmatch(
            r"we have a dedicated phone number,\s*"
            r"so could you please call us back\??",
            clean,
            re.IGNORECASE,
        ):
            return "専用の電話番号がありますので、折り返しお電話いただけますか？"
    pattern = CUSTOMER_NO_CLEANING.get(source_code)
    compact = re.sub(r"\s+", "", clean)
    if pattern is not None and pattern.fullmatch(compact):
        return "今日は客室を清掃しないでください。"
    exclusion = CUSTOMER_EXCLUSION.get(source_code)
    if exclusion is not None and exclusion.fullmatch(compact):
        return "それは追加しないでください。"
    return None
