from __future__ import annotations

import json
import threading
from pathlib import Path


class UserSettings:
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
