from __future__ import annotations

import json
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any


def normalize_memory_source(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text))
    return " ".join(normalized.split()).casefold()


class TranslationMemory:
    """Persistent, local operator-approved translations keyed by direction."""

    MAX_ENTRIES = 2000
    MAX_TEXT_LENGTH = 4000

    def __init__(self, data_root: Path):
        self.path = data_root / "feedback" / "translation-memory.json"
        self._lock = threading.RLock()
        self._entries: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._load()

    @staticmethod
    def _key(
        source: str,
        source_language: str,
        target_language: str,
    ) -> tuple[str, str, str]:
        return (
            source_language.strip().casefold(),
            target_language.strip().casefold(),
            normalize_memory_source(source),
        )

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            rows = payload.get("entries", [])
            if not isinstance(rows, list):
                return
            for row in rows[-self.MAX_ENTRIES :]:
                if not isinstance(row, dict):
                    continue
                source = str(row.get("source", "")).strip()
                source_language = str(row.get("source_language", "")).strip()
                target_language = str(row.get("target_language", "")).strip()
                corrected = str(row.get("corrected_translation", "")).strip()
                if not all((source, source_language, target_language, corrected)):
                    continue
                key = self._key(source, source_language, target_language)
                self._entries[key] = {
                    "source": source[: self.MAX_TEXT_LENGTH],
                    "source_language": source_language.casefold(),
                    "target_language": target_language.casefold(),
                    "corrected_translation": corrected[: self.MAX_TEXT_LENGTH],
                    "updated_at": float(row.get("updated_at", 0) or 0),
                }
        except (OSError, TypeError, ValueError):
            self._entries = {}

    def lookup(
        self,
        source: str,
        source_language: str,
        target_language: str,
    ) -> str | None:
        key = self._key(source, source_language, target_language)
        if not all(key):
            return None
        with self._lock:
            row = self._entries.get(key)
            return str(row["corrected_translation"]) if row is not None else None

    def remember(
        self,
        source: str,
        source_language: str,
        target_language: str,
        corrected_translation: str,
    ) -> None:
        source = source.strip()[: self.MAX_TEXT_LENGTH]
        source_language = source_language.strip().casefold()
        target_language = target_language.strip().casefold()
        corrected_translation = corrected_translation.strip()[: self.MAX_TEXT_LENGTH]
        if not all(
            (
                source,
                source_language,
                target_language,
                corrected_translation,
            )
        ):
            raise ValueError(
                "Source, language direction, and corrected translation are required"
            )
        key = self._key(source, source_language, target_language)
        with self._lock:
            self._entries.pop(key, None)
            self._entries[key] = {
                "source": source,
                "source_language": source_language,
                "target_language": target_language,
                "corrected_translation": corrected_translation,
                "updated_at": time.time(),
            }
            while len(self._entries) > self.MAX_ENTRIES:
                self._entries.pop(next(iter(self._entries)))
            self._save_locked()

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        payload = {
            "version": 1,
            "entries": list(self._entries.values()),
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def clear(self) -> bool:
        with self._lock:
            existed = bool(self._entries) or self.path.exists()
            self._entries.clear()
            self.path.unlink(missing_ok=True)
            return existed


class TranslationMemoryTranslator:
    """Return approved translations before invoking the local AI model."""

    def __init__(self, backend, memory: TranslationMemory):
        self.backend = backend
        self.memory = memory

    def __getattr__(self, name: str):
        return getattr(self.backend, name)

    def translate(
        self,
        text: str,
        source_code: str,
        target_code: str,
    ) -> str:
        remembered = self.memory.lookup(text, source_code, target_code)
        if remembered is not None:
            return remembered
        return self.backend.translate(text, source_code, target_code)

    def translate_contextual(
        self,
        text: str,
        source_code: str,
        target_code: str,
        *,
        previous_text: str = "",
        next_text: str = "",
    ) -> str:
        remembered = self.memory.lookup(text, source_code, target_code)
        if remembered is not None:
            return remembered
        return self.backend.translate_contextual(
            text,
            source_code,
            target_code,
            previous_text=previous_text,
            next_text=next_text,
        )

    def translate_preview(
        self,
        text: str,
        source_code: str,
        target_code: str,
    ) -> str:
        remembered = self.memory.lookup(text, source_code, target_code)
        if remembered is not None:
            return remembered
        return self.backend.translate_preview(text, source_code, target_code)
