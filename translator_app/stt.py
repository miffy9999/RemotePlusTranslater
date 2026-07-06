from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .config import SttConfig


@dataclass(slots=True)
class Recognition:
    text: str
    language: str
    probability: float


def apply_corrections(text: str, corrections: dict[str, str]) -> str:
    """Apply explicit domain corrections, longest phrase first."""
    if not corrections:
        return text
    phrases = sorted(corrections, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(phrase) for phrase in phrases))
    return pattern.sub(lambda match: corrections[match.group(0)], text)


def contains_japanese_kana(text: str) -> bool:
    return len(re.findall(r"[ぁ-ゖァ-ヺー]", text)) >= 2


class WhisperRecognizer:
    def __init__(self, cfg: SttConfig, status: Callable[[str, str], None]):
        self.cfg = cfg
        self.status = status
        self.model = None
        self.context_language: str | None = None
        self.selected_language: str = cfg.language
        self.enabled_languages: list[str] = []

    def set_context_language(self, language: str | None) -> None:
        self.context_language = language

    def set_selected_language(self, language: str) -> None:
        self.selected_language = language
        self.set_context_language(None if language == "auto" else language)

    def set_enabled_languages(self, languages: list[str]) -> None:
        self.enabled_languages = list(dict.fromkeys(languages))

    def _hotwords(self) -> str | None:
        words = list(self.cfg.hotwords)
        if self.context_language:
            words.extend(self.cfg.language_hotwords.get(self.context_language, []))
            if self.context_language != "ja":
                words.extend(self.cfg.language_hotwords.get("ja", []))
        else:
            for language_words in self.cfg.language_hotwords.values():
                words.extend(language_words)
        # Preserve order while removing duplicates.
        return ", ".join(dict.fromkeys(words)) or None

    def load(self) -> None:
        if self.model is not None:
            return
        self.status("loading", f"Loading speech model: {self.cfg.model}")
        from faster_whisper import WhisperModel

        try:
            self.model = WhisperModel(
                self.cfg.model,
                device=self.cfg.device,
                compute_type=self.cfg.compute_type,
                download_root=str(self.cfg.root / "models" / "whisper"),
            )
        except Exception:
            if self.cfg.device == "cpu" and self.cfg.compute_type == "int8":
                raise
            self.status("warning", "Configured STT device failed; retrying on CPU INT8")
            self.model = WhisperModel(
                self.cfg.model,
                device="cpu",
                compute_type="int8",
                download_root=str(self.cfg.root / "models" / "whisper"),
            )

    def transcribe(self, audio: np.ndarray) -> Recognition:
        self.load()
        forced = None
        detected_probability = None
        japanese_probability = 0.0
        if self.selected_language != "auto":
            detected, probability, probabilities = self.model.detect_language(audio=audio)
            japanese_probability = next(
                (score for code, score in probabilities if code == "ja"), 0.0
            )
            if detected == "ja" and probability >= self.cfg.japanese_reply_threshold:
                forced = "ja"
                detected_probability = probability
            else:
                forced = self.selected_language
                detected_probability = next(
                    (score for code, score in probabilities if code == self.selected_language),
                    probability if detected == self.selected_language else 0.0,
                )
        elif self.enabled_languages:
            _detected, _probability, probabilities = self.model.detect_language(audio=audio)
            allowed = {*self.enabled_languages, "ja"}
            candidates = [(code, score) for code, score in probabilities if code in allowed]
            if candidates:
                candidate, candidate_probability = max(candidates, key=lambda item: item[1])
                if candidate_probability >= self.cfg.enabled_language_min_probability:
                    forced, detected_probability = candidate, candidate_probability
                else:
                    self.status(
                        "warning",
                        "Speech language is outside the enabled set or too uncertain",
                    )
        segments, info = self.model.transcribe(
            audio,
            language=forced,
            beam_size=self.cfg.beam_size,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            hotwords=self._hotwords(),
            vad_filter=False,
            without_timestamps=True,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        text = apply_corrections(text, self.cfg.corrections)
        probability = float(
            detected_probability
            if detected_probability is not None
            else getattr(info, "language_probability", 1.0 if forced else 0.0)
        )
        language = info.language
        if (
            self.selected_language != "auto"
            and language != "ja"
            and contains_japanese_kana(text)
        ):
            language = "ja"
            probability = max(0.9, japanese_probability)
        return Recognition(text=text, language=language, probability=probability)
