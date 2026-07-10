from __future__ import annotations

import json
import threading
import os
from pathlib import Path


class UserSettings:
    SCHEMA_VERSION = 1
    def __init__(self, data_root: Path):
        self.path = data_root / "user-settings.json"
        self._lock = threading.Lock()

    def load_languages(self, defaults: list[str]) -> tuple[list[str], bool]:
        with self._lock:
            if not self.path.exists():
                return list(defaults), True
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                languages = data.get("enabled_languages", defaults)
                if isinstance(languages, list) and languages:
                    return [str(code) for code in languages], False
            except (OSError, ValueError, TypeError):
                pass
            return list(defaults), True

    def save_languages(self, languages: list[str]) -> None:
        payload = json.dumps(
            {"enabled_languages": languages}, ensure_ascii=False, indent=2
        )
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(payload, encoding="utf-8")

    def load(self) -> dict:
        with self._lock:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                return {}
        if not isinstance(data, dict) or data.get("schema_version", 1) != self.SCHEMA_VERSION:
            return {}
        allowed = {"active_language", "reply_language", "tts_enabled", "input_device", "output_device"}
        return {key: value for key, value in data.items() if key in allowed}

    def save(self, state: dict) -> None:
        allowed = ("active_language", "reply_language", "tts_enabled", "input_device", "output_device")
        payload = {"schema_version": self.SCHEMA_VERSION}
        payload.update({key: state[key] for key in allowed if key in state})
        encoded = json.dumps(payload, ensure_ascii=False, indent=2)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(f".tmp-{os.getpid()}")
            try:
                temporary.write_text(encoded, encoding="utf-8")
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)
