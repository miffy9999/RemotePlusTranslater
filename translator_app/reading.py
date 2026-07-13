from __future__ import annotations

import re
from functools import lru_cache


SUPPORTED_READING_LANGUAGES = frozenset({"en", "ko", "zh", "es"})

# Call-center phrases are deliberately authoritative. Dictionary/rule fallback
# handles novel text, while these entries keep the most frequent hotel replies
# natural and stable across releases.
PHRASES: dict[str, dict[str, str]] = {
    "en": {
        "thank you": "サンキュー",
        "thank you very much": "サンキュー ベリー マッチ",
        "please wait": "プリーズ ウェイト",
        "please wait a moment": "プリーズ ウェイト ア モーメント",
        "one moment please": "ワン モーメント プリーズ",
        "just a moment please": "ジャスト ア モーメント プリーズ",
        "i will check": "アイ ウィル チェック",
        "i will check your reservation": "アイ ウィル チェック ユア レザベーション",
        "please show me your passport": "プリーズ ショウ ミー ユア パスポート",
        "your room is ready": "ユア ルーム イズ レディ",
        "breakfast is included": "ブレックファスト イズ インクルーディッド",
        "you are welcome": "ユー アー ウェルカム",
    },
    "ko": {
        "감사합니다": "カムサハムニダ",
        "고맙습니다": "コマプスムニダ",
        "안녕하세요": "アンニョンハセヨ",
        "죄송합니다": "チェソンハムニダ",
        "잠시만 기다려 주세요": "チャムシマン キダリョ ジュセヨ",
        "기다려 주세요": "キダリョ ジュセヨ",
        "확인해 보겠습니다": "ファギネ ボゲッスムニダ",
        "확인해 주세요": "ファギネ ジュセヨ",
        "알겠습니다": "アルゲッスムニダ",
        "괜찮습니다": "クェンチャンスムニダ",
        "예약을 확인하겠습니다": "イェヤグル ファギナゲッスムニダ",
        "객실이 준비되었습니다": "ケクシリ ジュンビドェオッスムニダ",
    },
    "es": {
        "gracias": "グラシアス",
        "muchas gracias": "ムーチャス グラシアス",
        "por favor": "ポル ファボール",
        "un momento, por favor": "ウン モメント ポル ファボール",
        "espere un momento, por favor": "エスペレ ウン モメント ポル ファボール",
        "voy a comprobar su reserva": "ボイ ア コンプロバール ス レセルバ",
        "su habitación está lista": "ス アビタシオン エスタ リスタ",
        "el desayuno está incluido": "エル デサジュノ エスタ インクルイド",
    },
    "zh": {
        "谢谢": "シエシエ",
        "非常感谢": "フェイチャン ガンシエ",
        "请稍等": "チン シャオドン",
        "请稍等一下": "チン シャオドン イーシャー",
        "请出示您的护照": "チン チューシー ニンダ フージャオ",
        "我来确认您的预订": "ウォ ライ チュエレン ニンダ ユーディン",
        "您的房间已经准备好了": "ニンダ ファンジエン イージン ジュンベイ ハオラ",
        "早餐已包含在内": "ザオツァン イー バオハン ザイ ネイ",
    },
}

ENGLISH_WORDS = {
    "a": "ア", "an": "アン", "the": "ザ", "i": "アイ", "we": "ウィー",
    "you": "ユー", "your": "ユア", "our": "アワー", "my": "マイ", "me": "ミー",
    "is": "イズ", "are": "アー", "am": "アム", "be": "ビー", "will": "ウィル",
    "would": "ウッド", "can": "キャン", "could": "クッド", "please": "プリーズ",
    "wait": "ウェイト", "moment": "モーメント", "just": "ジャスト", "thank": "サンク",
    "thanks": "サンクス", "very": "ベリー", "much": "マッチ", "welcome": "ウェルカム",
    "sorry": "ソーリー", "excuse": "エクスキューズ", "yes": "イエス", "no": "ノー",
    "check": "チェック", "confirm": "コンファーム", "reservation": "レザベーション",
    "booking": "ブッキング", "passport": "パスポート", "name": "ネーム",
    "room": "ルーム", "ready": "レディ", "key": "キー", "card": "カード",
    "breakfast": "ブレックファスト", "included": "インクルーディッド", "lobby": "ロビー",
    "front": "フロント", "desk": "デスク", "elevator": "エレベーター",
    "towel": "タオル", "water": "ウォーター", "receipt": "レシート",
    "payment": "ペイメント", "cash": "キャッシュ", "credit": "クレジット",
    "checkout": "チェックアウト", "checkin": "チェックイン", "late": "レイト",
    "early": "アーリー", "night": "ナイト", "morning": "モーニング",
    "restaurant": "レストラン", "service": "サービス", "housekeeping": "ハウスキーピング",
    "available": "アベイラブル", "unavailable": "アンアベイラブル", "wifi": "ワイファイ",
    "password": "パスワード", "floor": "フロア", "number": "ナンバー",
    "single": "シングル", "double": "ダブル", "smoking": "スモーキング",
    "non-smoking": "ノンスモーキング", "airport": "エアポート", "taxi": "タクシー",
    "today": "トゥデイ", "tomorrow": "トゥモロー", "tonight": "トゥナイト",
}

EN_CHUNKS = (
    ("tion", "ション"), ("sion", "ジョン"), ("ture", "チャー"), ("ough", "オー"),
    ("eigh", "エイ"), ("igh", "アイ"), ("air", "エア"), ("oo", "ウー"),
    ("ee", "イー"), ("ea", "イー"), ("ai", "エイ"), ("ay", "エイ"),
    ("oa", "オウ"), ("oi", "オイ"), ("oy", "オイ"), ("ch", "チ"),
    ("sh", "シ"), ("th", "ス"), ("ph", "フ"), ("wh", "ウ"),
    ("ck", "ック"), ("ng", "ング"), ("qu", "ク"), ("er", "アー"),
    ("or", "オー"), ("ar", "アー"), ("ir", "アー"), ("ur", "アー"),
)
EN_LETTERS = {
    "a": "ア", "b": "ブ", "c": "ク", "d": "ド", "e": "エ", "f": "フ",
    "g": "グ", "h": "ハ", "i": "イ", "j": "ジ", "k": "ク", "l": "ル",
    "m": "ム", "n": "ン", "o": "オ", "p": "プ", "q": "ク", "r": "ル",
    "s": "ス", "t": "ト", "u": "ウ", "v": "ヴ", "w": "ウ", "x": "クス",
    "y": "イ", "z": "ズ",
}


def _clean_phrase(text: str) -> str:
    return re.sub(r"[\s。．.!！?？,，、]+$", "", text.strip().casefold())


def _english_word(word: str) -> str:
    key = word.casefold().strip("'")
    if key in ENGLISH_WORDS:
        return ENGLISH_WORDS[key]
    out: list[str] = []
    pos = 0
    while pos < len(key):
        for spelling, kana in EN_CHUNKS:
            if key.startswith(spelling, pos):
                out.append(kana)
                pos += len(spelling)
                break
        else:
            out.append(EN_LETTERS.get(key[pos], key[pos].upper()))
            pos += 1
    return "".join(out)


def _english(text: str) -> str:
    parts = re.findall(r"[A-Za-z]+(?:-[A-Za-z]+)?|\d+|[^A-Za-z\d]+", text)
    rendered = [_english_word(part) if re.search(r"[A-Za-z]", part) else part for part in parts]
    return re.sub(r"\s+", " ", "".join(rendered)).strip()


# Compatibility-jamo order used by Unicode Hangul syllables.
KO_ONSETS = ("g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h")
KO_VOWELS = ("a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i")
KO_CODAS = ("", "k", "k", "ks", "n", "nj", "nh", "t", "l", "lk", "lm", "lp", "ls", "lt", "lp", "lh", "m", "p", "ps", "t", "t", "ng", "t", "t", "k", "t", "p", "h")
KO_CODA_ONSET = {"k": "g", "n": "n", "t": "d", "l": "r", "m": "m", "p": "b", "s": "s", "h": ""}
KO_SPLIT_CODA = {"ks": ("k", "s"), "nj": ("n", "j"), "nh": ("n", "h"), "lk": ("l", "g"), "lm": ("l", "m"), "lp": ("l", "b"), "ls": ("l", "s"), "lt": ("l", "t"), "lh": ("l", "h"), "ps": ("p", "s")}

KO_KANA = {
    "": {"a":"ア","ae":"エ","ya":"ヤ","yae":"イェ","eo":"オ","e":"エ","yeo":"ヨ","ye":"イェ","o":"オ","wa":"ワ","wae":"ウェ","oe":"ウェ","yo":"ヨ","u":"ウ","wo":"ウォ","we":"ウェ","wi":"ウィ","yu":"ユ","eu":"ウ","ui":"ウィ","i":"イ"},
    "g": {"a":"ガ","ae":"ゲ","ya":"ギャ","eo":"ゴ","e":"ゲ","yeo":"ギョ","o":"ゴ","wa":"グァ","oe":"グェ","yo":"ギョ","u":"グ","wo":"グォ","wi":"グィ","yu":"ギュ","eu":"グ","ui":"グィ","i":"ギ"},
    "kk": {"a":"カ","ae":"ケ","ya":"キャ","eo":"コ","e":"ケ","o":"コ","yo":"キョ","u":"ク","yu":"キュ","eu":"ク","i":"キ"},
    "n": {"a":"ナ","ae":"ネ","ya":"ニャ","eo":"ノ","e":"ネ","yeo":"ニョ","o":"ノ","yo":"ニョ","u":"ヌ","yu":"ニュ","eu":"ヌ","i":"ニ"},
    "d": {"a":"ダ","ae":"デ","ya":"デャ","eo":"ド","e":"デ","o":"ド","u":"ドゥ","eu":"ドゥ","i":"ディ"},
    "tt": {"a":"タ","ae":"テ","eo":"ト","e":"テ","o":"ト","u":"トゥ","eu":"トゥ","i":"ティ"},
    "r": {"a":"ラ","ae":"レ","ya":"リャ","eo":"ロ","e":"レ","yeo":"リョ","o":"ロ","yo":"リョ","u":"ル","yu":"リュ","eu":"ル","i":"リ"},
    "m": {"a":"マ","ae":"メ","ya":"ミャ","eo":"モ","e":"メ","yeo":"ミョ","o":"モ","yo":"ミョ","u":"ム","yu":"ミュ","eu":"ム","i":"ミ"},
    "b": {"a":"バ","ae":"ベ","ya":"ビャ","eo":"ボ","e":"ベ","o":"ボ","u":"ブ","yu":"ビュ","eu":"ブ","i":"ビ"},
    "pp": {"a":"パ","ae":"ペ","eo":"ポ","e":"ペ","o":"ポ","u":"プ","eu":"プ","i":"ピ"},
    "s": {"a":"サ","ae":"セ","ya":"シャ","eo":"ソ","e":"セ","yeo":"ショ","o":"ソ","yo":"ショ","u":"ス","yu":"シュ","eu":"ス","i":"シ"},
    "ss": {"a":"サ","ae":"セ","eo":"ソ","e":"セ","o":"ソ","u":"ス","eu":"ス","i":"シ"},
    "j": {"a":"ジャ","ae":"ジェ","ya":"ジャ","eo":"ジョ","e":"ジェ","yeo":"ジョ","o":"ジョ","yo":"ジョ","u":"ジュ","yu":"ジュ","eu":"ジュ","i":"ジ"},
    "jj": {"a":"チャ","ae":"チェ","eo":"チョ","e":"チェ","o":"チョ","u":"チュ","eu":"チュ","i":"チ"},
    "ch": {"a":"チャ","ae":"チェ","ya":"チャ","eo":"チョ","e":"チェ","o":"チョ","yo":"チョ","u":"チュ","yu":"チュ","eu":"チュ","i":"チ"},
    "k": {"a":"カ","ae":"ケ","ya":"キャ","eo":"コ","e":"ケ","o":"コ","yo":"キョ","u":"ク","yu":"キュ","eu":"ク","i":"キ"},
    "t": {"a":"タ","ae":"テ","eo":"ト","e":"テ","o":"ト","u":"トゥ","eu":"トゥ","i":"ティ"},
    "p": {"a":"パ","ae":"ペ","eo":"ポ","e":"ペ","o":"ポ","u":"プ","yu":"ピュ","eu":"プ","i":"ピ"},
    "h": {"a":"ハ","ae":"ヘ","ya":"ヒャ","eo":"ホ","e":"ヘ","yeo":"ヒョ","o":"ホ","yo":"ヒョ","u":"フ","yu":"ヒュ","eu":"フ","i":"ヒ"},
}
KO_END = {"k":"ク","n":"ン","t":"ッ","l":"ル","m":"ム","p":"プ","ng":"ン"}


def _hangul_units(text: str) -> list[tuple[str, str, str] | str]:
    units: list[tuple[str, str, str] | str] = []
    for char in text:
        code = ord(char) - 0xAC00
        if 0 <= code < 11172:
            units.append((KO_ONSETS[code // 588], KO_VOWELS[(code % 588) // 28], KO_CODAS[code % 28]))
        else:
            units.append(char)
    return units


def _korean(text: str) -> str:
    units = _hangul_units(text)
    mutable = [list(unit) if isinstance(unit, tuple) else unit for unit in units]
    for index in range(len(mutable) - 1):
        current, following = mutable[index], mutable[index + 1]
        if not isinstance(current, list) or not isinstance(following, list):
            continue
        coda, onset = current[2], following[0]
        if onset == "" and coda:
            remain, moved = KO_SPLIT_CODA.get(coda, ("", coda))
            current[2] = remain
            following[0] = KO_CODA_ONSET.get(moved, moved)
        elif onset in {"n", "m"}:
            if coda in {"k", "ks", "lk"}:
                current[2] = "ng"
            elif coda in {"t", "s", "h"}:
                current[2] = "n"
            elif coda in {"p", "ps", "lp"}:
                current[2] = "m"
        if (current[2], following[0]) in {("n", "r"), ("l", "n")}:
            current[2], following[0] = "l", "r"
    rendered: list[str] = []
    for unit in mutable:
        if isinstance(unit, str):
            rendered.append(unit)
            continue
        onset, vowel, coda = unit
        row = KO_KANA.get(onset, KO_KANA[""])
        rendered.append(row.get(vowel, row.get("a", "")) + KO_END.get(coda, ""))
    return re.sub(r"\s+", " ", "".join(rendered)).strip()


def _korean_romanized(text: str) -> str:
    """Return a compact pronunciation-oriented Hangul romanization.

    This intentionally follows the same liaison adjustments as the katakana
    guide. It is a reading aid, not a legal-name romanization service.
    """
    units = _hangul_units(text)
    mutable = [list(unit) if isinstance(unit, tuple) else unit for unit in units]
    for index in range(len(mutable) - 1):
        current, following = mutable[index], mutable[index + 1]
        if not isinstance(current, list) or not isinstance(following, list):
            continue
        coda, onset = current[2], following[0]
        if onset == "" and coda:
            remain, moved = KO_SPLIT_CODA.get(coda, ("", coda))
            current[2] = remain
            following[0] = KO_CODA_ONSET.get(moved, moved)
        elif onset in {"n", "m"}:
            if coda in {"k", "ks", "lk"}:
                current[2] = "ng"
            elif coda in {"t", "s", "h"}:
                current[2] = "n"
            elif coda in {"p", "ps", "lp"}:
                current[2] = "m"
        if (current[2], following[0]) in {("n", "r"), ("l", "n")}:
            current[2], following[0] = "l", "r"
    return "".join(
        unit if isinstance(unit, str) else "".join(unit)
        for unit in mutable
    ).strip()


ES_WORDS = {
    "gracias":"グラシアス", "muchas":"ムーチャス", "por":"ポル", "favor":"ファボール",
    "momento":"モメント", "espere":"エスペレ", "reserva":"レセルバ", "habitación":"アビタシオン",
    "hotel":"オテル", "pasaporte":"パサポルテ", "desayuno":"デサジュノ", "incluido":"インクルイド",
    "lista":"リスタ", "confirmar":"コンフィルマール", "pago":"パゴ",
    "efectivo":"エフェクティボ", "tarjeta":"タルヘタ", "ascensor":"アセンソール", "recepción":"レセプシオン",
}


def _spanish_word(word: str) -> str:
    key = word.casefold()
    if key in ES_WORDS:
        return ES_WORDS[key]
    replacements = (("gue","ゲ"),("gui","ギ"),("que","ケ"),("qui","キ"),("ch","チ"),("ll","ヤ"),("rr","ル"),("ñ","ニャ"),("j","ハ"),("ge","ヘ"),("gi","ヒ"),("ce","セ"),("ci","シ"))
    out: list[str] = []
    pos = 0
    basic = {"a":"ア","e":"エ","i":"イ","o":"オ","u":"ウ","b":"ブ","v":"ブ","c":"ク","d":"ド","f":"フ","g":"グ","h":"","k":"ク","l":"ル","m":"ム","n":"ン","p":"プ","r":"ル","s":"ス","t":"ト","x":"クス","y":"イ","z":"ス"}
    while pos < len(key):
        for spelling, kana in replacements:
            if key.startswith(spelling, pos):
                out.append(kana)
                pos += len(spelling)
                break
        else:
            out.append(basic.get(key[pos], key[pos]))
            pos += 1
    return "".join(out)


def _spanish(text: str) -> str:
    parts = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+|\d+|[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ\d]+", text)
    return re.sub(r"\s+", " ", "".join(_spanish_word(p) if re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", p) else p for p in parts)).strip()


PINYIN_EXACT = {
    "xie":"シエ", "qing":"チン", "shao":"シャオ", "deng":"ドン", "yi":"イー", "xia":"シャー",
    "wo":"ウォ", "nin":"ニン", "de":"ダ", "fang":"ファン", "jian":"ジエン", "yu":"ユー",
    "ding":"ディン", "hao":"ハオ", "le":"ラ", "zao":"ザオ", "can":"ツァン", "bao":"バオ",
    "han":"ハン", "zai":"ザイ", "nei":"ネイ", "fei":"フェイ", "chang":"チャン", "gan":"ガン",
    "chu":"チュー", "shi":"シー", "hu":"フー", "zhao":"ジャオ", "lai":"ライ", "que":"チュエ",
    "ren":"レン", "zhun":"ジュン", "bei":"ベイ", "jing":"ジン", "ma":"マー", "mafan":"マーファン",
}


def _pinyin_kana(syllable: str) -> str:
    key = re.sub(r"[^a-züv]", "", syllable.casefold()).replace("ü", "v")
    if key in PINYIN_EXACT:
        return PINYIN_EXACT[key]
    initials = (("zh","ジ"),("ch","チ"),("sh","シ"),("j","ジ"),("q","チ"),("x","シ"),("b","ブ"),("p","プ"),("m","ム"),("f","フ"),("d","ド"),("t","ト"),("n","ヌ"),("l","ル"),("g","グ"),("k","ク"),("h","フ"),("z","ズ"),("c","ツ"),("s","ス"),("r","ル"))
    finals = (("iang","ヤン"),("iong","ヨン"),("uang","ワン"),("ang","アン"),("eng","オン"),("ong","オン"),("iao","ヤオ"),("ian","イエン"),("uan","ワン"),("uai","ワイ"),("ing","イン"),("in","イン"),("ai","アイ"),("ei","エイ"),("ao","アオ"),("ou","オウ"),("an","アン"),("en","エン"),("er","アル"),("ia","ヤ"),("ie","イエ"),("ua","ワ"),("uo","ウォ"),("ui","ウェイ"),("un","ウェン"),("ve","ユエ"),("v","ユー"),("a","ア"),("o","オ"),("e","オ"),("i","イ"),("u","ウ"))
    onset = ""
    for roman, kana in initials:
        if key.startswith(roman):
            onset, key = kana, key[len(roman):]
            break
    ending = next((kana for roman, kana in finals if key == roman), key.upper())
    return onset + ending


def _chinese(text: str) -> str:
    try:
        from pypinyin import Style, lazy_pinyin
    except ImportError:
        return ""
    syllables = lazy_pinyin(text, style=Style.NORMAL, neutral_tone_with_five=False, errors=lambda value: list(value))
    rendered = [_pinyin_kana(item) if re.fullmatch(r"[A-Za-züÜvV]+", item) else item for item in syllables]
    return re.sub(r"\s+", " ", " ".join(rendered)).replace(" 。", "。").replace(" ，", "，").strip()


def _chinese_romanized(text: str) -> str:
    try:
        from pypinyin import Style, lazy_pinyin
    except ImportError:
        return ""
    parts = lazy_pinyin(
        text,
        style=Style.NORMAL,
        neutral_tone_with_five=False,
        errors=lambda value: list(value),
    )
    return " ".join(parts).replace(" 。", ".").replace(" ，", ",").strip()


@lru_cache(maxsize=512)
def reading_guide(text: str, language: str) -> str:
    """Return fast Japanese katakana guidance without another model call."""
    clean = text.strip()
    code = language.strip().lower()
    if not clean or code not in SUPPORTED_READING_LANGUAGES or len(clean) > 500:
        return ""
    exact = PHRASES.get(code, {}).get(_clean_phrase(clean))
    if exact:
        return exact
    if code == "en":
        return _english(clean)
    if code == "ko":
        return _korean(clean)
    if code == "es":
        return _spanish(clean)
    return _chinese(clean)


@lru_cache(maxsize=512)
def romanized_guide(text: str, language: str) -> str:
    """Return a Latin-script companion for every translated language."""
    clean = text.strip()
    code = language.strip().lower()
    if not clean or len(clean) > 500:
        return ""
    if code == "ko":
        return _korean_romanized(clean)
    if code == "zh":
        return _chinese_romanized(clean)
    if code in {"en", "es"}:
        # These languages already use Latin script. Normalizing whitespace is
        # still useful when the translation model inserts line breaks.
        return re.sub(r"\s+", " ", clean).strip()
    try:
        from anyascii import anyascii
    except ImportError:
        return ""
    return re.sub(r"\s+", " ", anyascii(clean)).strip()
