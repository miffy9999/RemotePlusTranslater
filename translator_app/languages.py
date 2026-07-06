from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Language:
    whisper: str
    name: str
    native_name: str
    translation_code: str | None
    sapi_lcids: tuple[str, ...] | None


# SAPI LCIDs are hexadecimal Windows language identifiers. Actual availability depends on
# installed Windows language/voice packs.
_ROWS = [
    ("ja", "Japanese", "日本語", "ja", ("411",)),
    ("en", "English", "English", "en", ("409", "809", "c09", "1009")),
    ("ko", "Korean", "한국어", "ko", ("412",)),
    ("es", "Spanish", "Español", "es", ("c0a", "40a", "80a", "2c0a")),
    ("zh", "Chinese", "中文", "zh", ("804", "404")),
    ("fr", "French", "Français", "fr", ("40c", "c0c")),
    ("de", "German", "Deutsch", "de", ("407",)),
    ("it", "Italian", "Italiano", "it", ("410",)),
    ("pt", "Portuguese", "Português", "pt", ("416", "816")),
    ("ru", "Russian", "Русский", "ru", ("419",)),
    ("uk", "Ukrainian", "Українська", "uk", ("422",)),
    ("nl", "Dutch", "Nederlands", "nl", ("413",)),
    ("pl", "Polish", "Polski", "pl", ("415",)),
    ("tr", "Turkish", "Türkçe", "tr", ("41f",)),
    ("vi", "Vietnamese", "Tiếng Việt", "vi", ("42a",)),
    ("th", "Thai", "ไทย", "th", ("41e",)),
    ("id", "Indonesian", "Bahasa Indonesia", "id", ("421",)),
    ("ms", "Malay", "Bahasa Melayu", "ms", ("43e",)),
    ("hi", "Hindi", "हिन्दी", "hi", ("439",)),
    ("ar", "Arabic", "العربية", "ar", ("401", "c01")),
    ("cs", "Czech", "Čeština", "cs", ("405",)),
    ("da", "Danish", "Dansk", "da", ("406",)),
    ("fi", "Finnish", "Suomi", "fi", ("40b",)),
    ("sv", "Swedish", "Svenska", "sv", ("41d",)),
    ("no", "Norwegian", "Norsk", "no", ("414",)),
    ("el", "Greek", "Ελληνικά", "el", ("408",)),
    ("he", "Hebrew", "עברית", "he", ("40d",)),
    ("ro", "Romanian", "Română", "ro", ("418",)),
    ("hu", "Hungarian", "Magyar", "hu", ("40e",)),
]

LANGUAGES = {row[0]: Language(*row) for row in _ROWS}
HYMT2_CODES = frozenset(
    {"ja", "en", "ko", "zh", "es", "fr", "de", "it", "pt", "ru", "ar", "hi",
     "vi", "th", "id", "ms", "tr", "nl", "pl", "uk", "cs", "he"}
)


def get_language(code: str) -> Language | None:
    return LANGUAGES.get(code.lower().split("-")[0])


def public_languages(enabled: list[str] | None = None) -> list[dict[str, str | bool]]:
    allowed = set(enabled) if enabled is not None else HYMT2_CODES
    return [
        {
            "code": item.whisper,
            "name": item.name,
            "native_name": item.native_name,
            "tts": item.sapi_lcids is not None,
        }
        for item in LANGUAGES.values()
        if item.whisper != "ja"
        and item.translation_code is not None
        and item.whisper in HYMT2_CODES
        and item.whisper in allowed
    ]
