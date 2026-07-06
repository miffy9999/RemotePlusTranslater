from __future__ import annotations

import json
import threading
import time
from pathlib import Path


class FeedbackStore:
    """Append-only local correction log; no customer audio is retained."""

    MAX_BYTES = 10 * 1024 * 1024

    def __init__(self, data_root: Path):
        self.path = data_root / "feedback" / "corrections.jsonl"
        self._lock = threading.Lock()

    def append(self, record: dict[str, str]) -> Path:
        cleaned = {key: value.strip() for key, value in record.items()}
        if not cleaned.get("corrected_source") and not cleaned.get("corrected_translation"):
            raise ValueError("At least one correction is required")
        payload = {"timestamp": time.time(), **cleaned}
        encoded = json.dumps(payload, ensure_ascii=False) + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size + len(
                encoded.encode("utf-8")
            ) > self.MAX_BYTES:
                backup = self.path.with_name("corrections.1.jsonl")
                backup.unlink(missing_ok=True)
                self.path.replace(backup)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(encoded)
        return self.path

    def clear(self) -> bool:
        with self._lock:
            if not self.path.exists():
                return False
            self.path.unlink()
            return True
