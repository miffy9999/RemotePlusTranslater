from __future__ import annotations

import re
import threading
from typing import Callable

from .config import TranslationConfig
from .languages import get_language
from .phrasebook import translate_hotel_phrase


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


class M2M100Translator:
    """MIT M2M100 running as CPU-optimized CTranslate2 INT8."""

    def __init__(self, cfg: TranslationConfig, status: Callable[[str, str], None]):
        self.cfg = cfg
        self.status = status
        self.model = None
        self.tokenizer = None
        self._lock = threading.Lock()
        self.model_dir = self.cfg.root / "models" / "m2m100-ct2-compat-int8"

    def _model_source(self) -> str:
        cache_name = "models--" + self.cfg.model.replace("/", "--")
        snapshots = self.cfg.root / "models" / "huggingface" / cache_name / "snapshots"
        if snapshots.exists():
            for candidate in snapshots.iterdir():
                if (candidate / "pytorch_model.bin").exists():
                    return str(candidate)
        return self.cfg.model

    def _ensure_converted(self) -> None:
        import ctranslate2

        if ctranslate2.contains_model(str(self.model_dir)):
            return
        self.status("loading", "Optimizing translation model for this PC (one time)")
        try:
            from ctranslate2.converters import TransformersConverter
            import torch  # noqa: F401
            import transformers  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "M2M100 is an optional development backend. Install with: "
                "pip install -e '.[m2m100]'"
            ) from exc

        class CompatibleTransformersConverter(TransformersConverter):
            def load_model(self, model_class, model_name_or_path, **kwargs):
                # CTranslate2 4.8 targets the new Transformers `dtype` API. The pinned
                # Transformers 4.x M2M100 implementation still calls it `torch_dtype`.
                if "dtype" in kwargs:
                    kwargs["torch_dtype"] = kwargs.pop("dtype")
                return model_class.from_pretrained(model_name_or_path, **kwargs)

        self.model_dir.parent.mkdir(parents=True, exist_ok=True)
        converter = CompatibleTransformersConverter(
            self._model_source(),
            low_cpu_mem_usage=True,
        )
        converter.convert(str(self.model_dir), quantization="int8", force=True)

    def load(self) -> None:
        if self.model is not None:
            return
        self._ensure_converted()
        self.status("loading", "Loading optimized translation model")
        import ctranslate2
        try:
            from transformers import M2M100Tokenizer
        except ImportError as exc:
            raise RuntimeError(
                "M2M100 is an optional development backend. Install with: "
                "pip install -e '.[m2m100]'"
            ) from exc

        tokenizer_source = self.cfg.root / "models" / "m2m100-tokenizer"
        self.tokenizer = M2M100Tokenizer.from_pretrained(
            str(tokenizer_source) if tokenizer_source.exists() else self._model_source(),
            cache_dir=str(self.cfg.root / "models" / "huggingface"),
        )
        self.model = ctranslate2.Translator(
            str(self.model_dir),
            device="cpu",
            compute_type="int8",
            inter_threads=1,
            intra_threads=0,
        )

    def translate(self, text: str, source_code: str, target_code: str) -> str:
        if source_code == target_code:
            return text.strip()
        if source_code == "ja":
            phrase = translate_hotel_phrase(text, target_code)
            if phrase is not None:
                return phrase
        source = get_language(source_code)
        target = get_language(target_code)
        if (
            source is None
            or target is None
            or source.translation_code is None
            or target.translation_code is None
        ):
            raise ValueError(f"Unsupported translation direction: {source_code} -> {target_code}")
        self.load()
        with self._lock:
            self.tokenizer.src_lang = source.translation_code
            source_tokens = self.tokenizer.convert_ids_to_tokens(
                self.tokenizer.encode(text.strip())
            )
            target_prefix = [self.tokenizer.lang_code_to_token[target.translation_code]]
            result = self.model.translate_batch(
                [source_tokens],
                target_prefix=[target_prefix],
                beam_size=1,
                max_decoding_length=self.cfg.max_new_tokens,
            )[0]
            target_tokens = result.hypotheses[0][1:]
            translated = self.tokenizer.decode(
                self.tokenizer.convert_tokens_to_ids(target_tokens),
                skip_special_tokens=True,
            ).strip()
            if target_code == "ja":
                translated = protect_japanese_terms(text, translated, self.cfg.glossary)
            translated = protect_multilingual_terms(
                text,
                translated,
                source_code,
                target_code,
                self.cfg.protected_terms,
            )
            return translated
