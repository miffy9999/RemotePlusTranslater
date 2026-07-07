from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class Language:
    code: str
    name: str
    native_name: str
    # Kept only so older extensions that read this attribute do not fail.
    sapi_lcids: tuple[str, ...] = ()


_LANGUAGES: tuple[Language, ...] = (
    Language("ja", "Japanese", "日本語"),
    Language("en", "English", "English"),
    Language("ko", "Korean", "한국어"),
    Language("zh", "Chinese", "中文"),
    Language("es", "Spanish", "Español"),
    Language("fr", "French", "Français"),
    Language("de", "German", "Deutsch"),
    Language("it", "Italian", "Italiano"),
    Language("pt", "Portuguese", "Português"),
    Language("ru", "Russian", "Русский"),
    Language("ar", "Arabic", "العربية"),
    Language("hi", "Hindi", "हिन्दी"),
    Language("vi", "Vietnamese", "Tiếng Việt"),
    Language("th", "Thai", "ไทย"),
    Language("id", "Indonesian", "Bahasa Indonesia"),
    Language("ms", "Malay", "Bahasa Melayu"),
    Language("tr", "Turkish", "Türkçe"),
    Language("nl", "Dutch", "Nederlands"),
    Language("pl", "Polish", "Polski"),
    Language("uk", "Ukrainian", "Українська"),
    Language("cs", "Czech", "Čeština"),
    Language("he", "Hebrew", "עברית"),
)

_BY_CODE = {language.code: language for language in _LANGUAGES}

# Japanese is reserved for the Space-held employee mode. Every item below is a
# selectable fixed customer language and has an Edge Neural voice mapping.
CUSTOMER_LANGUAGE_CODES: tuple[str, ...] = tuple(
    language.code for language in _LANGUAGES if language.code != "ja"
)


def get_language(code: str | None) -> Language | None:
    if not code:
        return None
    return _BY_CODE.get(str(code).strip().lower())


def public_languages(codes: Iterable[str] | None = None) -> list[dict[str, str]]:
    wanted = list(codes) if codes is not None else list(CUSTOMER_LANGUAGE_CODES)
    result: list[dict[str, str]] = []
    for code in wanted:
        language = get_language(code)
        if language is None:
            continue
        result.append({
            "code": language.code,
            "name": language.name,
            "native_name": language.native_name,
        })
    return result
