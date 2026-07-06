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
        r"予約番号.*(?:教えて|お願い)",
        "Please give me your reservation number.",
        "예약 번호를 알려 주세요.",
        "请告诉我您的预订号码。",
        "Por favor, indíqueme su número de reserva.",
    ),
    _phrase(
        r"(?:お名前|名前).*(?:教えて|お願い)",
        "May I have your name, please?",
        "성함을 알려 주세요.",
        "请告诉我您的姓名。",
        "¿Podría indicarme su nombre, por favor?",
    ),
    _phrase(
        r"(?:部屋|客室).*番号.*(?:教えて|お願い)",
        "May I have your room number, please?",
        "객실 번호를 알려 주세요.",
        "请告诉我您的房间号码。",
        "¿Podría indicarme el número de su habitación?",
    ),
    _phrase(
        r"追加.*タオル.*(?:3|三)枚.*(?:届け|お持ち)",
        "We will deliver three additional towels to your room.",
        "추가 수건 세 장을 객실로 가져다드리겠습니다.",
        "我们会把三条额外的毛巾送到您的房间。",
        "Le llevaremos tres toallas adicionales a su habitación.",
    ),
    _phrase(
        r"空港.*シャトル.*午前?(?:8|八)時.*出発",
        "The airport shuttle leaves at 8:00 a.m.",
        "공항 셔틀은 오전 8시에 출발합니다.",
        "机场班车上午八点出发。",
        "El transporte al aeropuerto sale a las ocho de la mañana.",
    ),
    _phrase(
        r"ピーナッツ.*アレルギー.*(?:厨房|キッチン).*(?:伝え|確認)",
        "We will inform the kitchen about your peanut allergy.",
        "땅콩 알레르기가 있다고 주방에 전달하겠습니다.",
        "我们会将您的花生过敏情况告知厨房。",
        "Informaremos a la cocina de su alergia al cacahuete.",
    ),
    _phrase(
        r"レイトチェックアウト.*午後?(?:2|二)時.*可能",
        "Late check-out is available until 2:00 p.m.",
        "레이트 체크아웃은 오후 2시까지 가능합니다.",
        "延迟退房可以到下午两点。",
        "La salida tardía está disponible hasta las dos de la tarde.",
    ),
    _phrase(
        r"(?:少々|しばらく).*(?:お待ち|待って)",
        "Please wait a moment while I check.",
        "확인하는 동안 잠시만 기다려 주세요.",
        "请稍等片刻，我们正在确认。",
        "Espere un momento mientras lo comprobamos.",
    ),
    _phrase(
        r"(?:(?:申し訳|すみません).*(?:不便|迷惑)|(?:不便|迷惑).*(?:申し訳|すみません))",
        "We sincerely apologize for the inconvenience.",
        "불편을 드려 진심으로 죄송합니다.",
        "给您带来不便，我们深表歉意。",
        "Le pedimos sinceras disculpas por las molestias.",
    ),
    _phrase(
        r"(?:スタッフ|係員|技術者).*(?:部屋|客室).*(?:伺|行き)",
        "A staff member will come to your room shortly.",
        "직원이 곧 객실로 방문하겠습니다.",
        "工作人员很快会到您的房间。",
        "Un miembro del personal irá a su habitación en breve.",
    ),
    _phrase(
        r"タクシー.*(?:手配|呼び)",
        "We will arrange a taxi for you.",
        "택시를 불러 드리겠습니다.",
        "我们会为您安排出租车。",
        "Le pediremos un taxi.",
    ),
    _phrase(
        r"(?:請求|料金).*(?:訂正|修正|確認)",
        "We will check the charge and correct it if necessary.",
        "요금을 확인하고 필요한 경우 정정하겠습니다.",
        "我们会核对费用，并在需要时进行更正。",
        "Revisaremos el cargo y lo corregiremos si es necesario.",
    ),
    _phrase(
        r"朝食会場.*(?:2|二)階.*(?:6時30分|6時半|六時半).*(?:10|十)時",
        "The breakfast venue is on the second floor and is open from 6:30 to 10:00 a.m.",
        "조식 장소는 2층이며 오전 6시 30분부터 10시까지 운영합니다.",
        "早餐地点在二楼，开放时间为上午六点半到十点。",
        "El desayuno se sirve en la segunda planta de 6:30 a 10:00 de la mañana.",
    ),
    _phrase(
        r"パスポート.*見つか.*身分証明.*フロント",
        "We found your passport. Please bring identification to the front desk.",
        "여권을 찾았습니다. 신분증을 가지고 프런트 데스크로 와 주세요.",
        "我们找到了您的护照。请携带身份证件到前台领取。",
        "Hemos encontrado su pasaporte. Lleve un documento de identificación a recepción.",
    ),
    _phrase(
        r"緊急.*救急車.*手配",
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
