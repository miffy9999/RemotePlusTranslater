from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from .translation_memory import TranslationMemory


class FeedbackStore:
    """Append-only local correction log; no customer audio is retained."""

    MAX_BYTES = 10 * 1024 * 1024
    RETENTION_SECONDS = 30 * 24 * 60 * 60

    def __init__(
        self,
        data_root: Path,
        translation_memory: TranslationMemory | None = None,
    ):
        self.path = data_root / "feedback" / "corrections.jsonl"
        self._lock = threading.Lock()
        self.translation_memory = translation_memory or TranslationMemory(data_root)

    def append(self, record: dict[str, str]) -> Path:
        cleaned = {key: value.strip()[:4000] for key, value in record.items()}
        if not cleaned.get("corrected_source") and not cleaned.get("corrected_translation"):
            raise ValueError("At least one correction is required")
        corrected_translation = cleaned.get("corrected_translation", "")
        if corrected_translation and not all(
            cleaned.get(key)
            for key in ("source", "source_language", "target_language")
        ):
            raise ValueError(
                "Source, language direction, and corrected translation are required"
            )
        payload = {"timestamp": time.time(), **cleaned}
        encoded = json.dumps(payload, ensure_ascii=False) + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._prune_expired_locked(time.time() - self.RETENTION_SECONDS)
            if self.path.exists() and self.path.stat().st_size + len(
                encoded.encode("utf-8")
            ) > self.MAX_BYTES:
                backup = self.path.with_name("corrections.1.jsonl")
                backup.unlink(missing_ok=True)
                self.path.replace(backup)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(encoded)
            if corrected_translation:
                self.translation_memory.remember(
                    cleaned.get("source", ""),
                    cleaned.get("source_language", ""),
                    cleaned.get("target_language", ""),
                    corrected_translation,
                )
        return self.path

    def _prune_expired_locked(self, cutoff: float) -> None:
        if not self.path.exists():
            return
        retained: list[str] = []
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    payload = json.loads(line)
                    if float(payload.get("timestamp", 0)) >= cutoff:
                        retained.append(json.dumps(payload, ensure_ascii=False))
                except (ValueError, TypeError):
                    continue
            temporary = self.path.with_suffix(".prune.tmp")
            temporary.write_text(("\n".join(retained) + "\n") if retained else "", encoding="utf-8")
            temporary.replace(self.path)
        except OSError:
            # Retention maintenance must not corrupt or block a valid explicit
            # correction save. The size cap still bounds growth.
            return

    def clear(self) -> bool:
        with self._lock:
            log_existed = self.path.exists()
            self.path.unlink(missing_ok=True)
            return self.translation_memory.clear() or log_existed
