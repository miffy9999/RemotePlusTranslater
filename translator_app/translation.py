from __future__ import annotations

import re


JAPANESE_TERM_CORRECTIONS = {
    "カラス": "コーラ",
    "ココラ": "コーラ",
    "コラ": "コーラ",
    "ギンジャーアレ": "ジンジャーエール",
    "ガンジャー": "ジンジャーエール",
    "ジンジュース": "ジンジャーエール",
}


def contains_alias(text: str, alias: str) -> bool:
    if re.search(r"[A-Za-z]", alias):
        pattern = rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])"
        return re.search(pattern, text, re.IGNORECASE) is not None
    return alias.casefold() in text.casefold()


def protect_japanese_terms(
    source_text: str,
    translated: str,
    glossary: dict[str, list[str]],
) -> str:
    """Keep safety- and service-critical hotel terms visible to the operator."""
    result = translated
    folded_source = source_text.casefold()
    non_smoking_aliases = ("non-smoking", "금연", "无烟", "無煙", "no fumadores")
    if any(alias in folded_source for alias in non_smoking_aliases):
        result = result.replace("喫煙者向けの部屋", "禁煙の部屋")
    for wrong, correct in JAPANESE_TERM_CORRECTIONS.items():
        pattern = re.compile(rf"(?<![ァ-ヺー]){re.escape(wrong)}(?![ァ-ヺー])")
        result = pattern.sub(correct, result)

    missing = []
    for japanese, aliases in glossary.items():
        if any(contains_alias(source_text, alias) for alias in aliases) and japanese not in result:
            missing.append(japanese)
    if missing:
        result = f"{result}（重要語: {'・'.join(missing)}）"
    return result


TERM_LABELS = {
    "ja": "重要語",
    "en": "Important term",
    "ko": "중요 용어",
    "zh": "重要词语",
    "es": "Término importante",
}


def protect_multilingual_terms(
    source_text: str,
    translated: str,
    source_code: str,
    target_code: str,
    protected_terms: list[dict[str, list[str]]],
) -> str:
    """Preserve configured hotel terms across both translation directions."""
    missing = []
    for term in protected_terms:
        source_aliases = term.get(source_code, [])
        target_aliases = term.get(target_code, [])
        if not source_aliases or not target_aliases:
            continue
        source_has_term = any(contains_alias(source_text, alias) for alias in source_aliases)
        target_has_term = any(contains_alias(translated, alias) for alias in target_aliases)
        if source_has_term and not target_has_term:
            missing.append(target_aliases[0])
    if missing:
        label = TERM_LABELS.get(target_code, "Important term")
        translated = f"{translated}（{label}: {'・'.join(dict.fromkeys(missing))}）"
    return translated
