from __future__ import annotations

import json
import threading
import os
from pathlib import Path


class UserSettings:
    SCHEMA_VERSION = 4

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
        if not isinstance(data, dict) or data.get("schema_version", 1) not in {1, 2, 3, 4}:
            return {}
        # Treat this file as untrusted input. It can come from an older build,
        # a partial manual edit, or another PC with different device values.
        result = {}
        for key in ("active_language", "reply_language"):
            if isinstance(data.get(key), str):
                result[key] = data[key]
        input_device = data.get("input_device")
        if isinstance(input_device, str) or (
            isinstance(input_device, int) and not isinstance(input_device, bool)
        ):
            result["input_device"] = input_device
        return result

    def save(self, state: dict) -> None:
        allowed = ("active_language", "reply_language", "input_device")
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
