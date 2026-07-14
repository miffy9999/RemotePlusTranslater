from __future__ import annotations

import json
import os
import threading
import unicodedata
import uuid
from pathlib import Path


class QuickPhraseStore:
    SCHEMA_VERSION = 3
    MAX_ITEMS = 40
    MAX_LENGTH = 800
    MAX_CATEGORY_LENGTH = 40

    def __init__(self, data_root: Path):
        self.path = data_root / "quick-phrases.json"
        self._lock = threading.Lock()

    @staticmethod
    def _normalized_key(value: str) -> str:
        return unicodedata.normalize("NFKC", value).casefold()

    @staticmethod
    def _has_control_characters(value: str) -> bool:
        return any(unicodedata.category(character).startswith("C") for character in value)

    def _preserve_corrupt_file_unlocked(self) -> None:
        backup = self.path.with_name(f"quick-phrases.corrupt-{uuid.uuid4().hex}.json")
        try:
            self.path.replace(backup)
        except OSError as exc:
            raise OSError("Quick phrase data is invalid and could not be preserved") from exc

    def _load_unlocked(self) -> list[dict[str, str]]:
        try:
            raw = self.path.read_text(encoding="utf-8")
            payload = json.loads(raw)
        except FileNotFoundError:
            return []
        except (UnicodeError, json.JSONDecodeError):
            self._preserve_corrupt_file_unlocked()
            return []
        except OSError:
            return []
        if not isinstance(payload, dict) or not isinstance(payload.get("phrases"), list):
            self._preserve_corrupt_file_unlocked()
            return []
        schema_version = payload.get("schema_version", 1)
        if (
            not isinstance(schema_version, int)
            or isinstance(schema_version, bool)
            or schema_version not in {1, 2, self.SCHEMA_VERSION}
        ):
            self._preserve_corrupt_file_unlocked()
            return []
        items = payload["phrases"]
        result: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        seen_texts: set[str] = set()
        category_names: dict[str, str] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            phrase_id = item.get("id")
            text = item.get("text")
            category = item.get("category", "")
            if (
                not isinstance(phrase_id, str)
                or not isinstance(text, str)
                or not isinstance(category, str)
                or not phrase_id
                or phrase_id in seen_ids
            ):
                continue
            clean = text.strip()
            clean_category = category.strip()
            text_key = self._normalized_key(clean)
            if not clean or len(clean) > self.MAX_LENGTH or text_key in seen_texts:
                continue
            if (
                len(clean_category) > self.MAX_CATEGORY_LENGTH
                or self._has_control_characters(clean_category)
            ):
                clean_category = ""
            if clean_category:
                category_key = self._normalized_key(clean_category)
                clean_category = category_names.setdefault(category_key, clean_category)
            seen_ids.add(phrase_id)
            seen_texts.add(text_key)
            result.append({"id": phrase_id, "text": clean, "category": clean_category})
            if len(result) >= self.MAX_ITEMS:
                break
        return result

    def _load_collapsed_unlocked(self, phrases: list[dict[str, str]]) -> list[str]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return []
        stored = payload.get("collapsed_categories", []) if isinstance(payload, dict) else []
        if not isinstance(stored, list):
            return []
        available = {
            self._normalized_key(item["category"]): item["category"]
            for item in phrases
        }
        result: list[str] = []
        seen: set[str] = set()
        for category in stored:
            if not isinstance(category, str):
                continue
            key = self._normalized_key(category.strip())
            if key not in available or key in seen:
                continue
            seen.add(key)
            result.append(available[key])
        return result

    def _save_unlocked(
        self,
        phrases: list[dict[str, str]],
        collapsed_categories: list[str] | None = None,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if collapsed_categories is None:
            collapsed_categories = self._load_collapsed_unlocked(phrases)
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        try:
            temporary.write_text(
                json.dumps(
                    {
                        "schema_version": self.SCHEMA_VERSION,
                        "phrases": phrases,
                        "collapsed_categories": collapsed_categories,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def list(self) -> list[dict[str, str]]:
        with self._lock:
            return self._load_unlocked()

    def list_state(self) -> tuple[list[dict[str, str]], list[str]]:
        with self._lock:
            phrases = self._load_unlocked()
            return phrases, self._load_collapsed_unlocked(phrases)

    def set_collapsed_categories(self, categories: list[str]) -> list[str]:
        if len(categories) > self.MAX_ITEMS:
            raise ValueError(f"At most {self.MAX_ITEMS} categories can be collapsed")
        with self._lock:
            phrases = self._load_unlocked()
            available = {
                self._normalized_key(item["category"]): item["category"]
                for item in phrases
            }
            result: list[str] = []
            seen: set[str] = set()
            for category in categories:
                clean = category.strip()
                if (
                    len(clean) > self.MAX_CATEGORY_LENGTH
                    or self._has_control_characters(clean)
                ):
                    raise ValueError("Collapsed category contains an invalid name")
                key = self._normalized_key(clean)
                if key not in available or key in seen:
                    continue
                seen.add(key)
                result.append(available[key])
            current = self._load_collapsed_unlocked(phrases)
            if current != result:
                self._save_unlocked(phrases, result)
            return result

    def add(self, text: str) -> dict[str, str]:
        clean = text.strip()
        if not clean or len(clean) > self.MAX_LENGTH:
            raise ValueError(f"Quick phrase must contain 1 to {self.MAX_LENGTH} characters")
        with self._lock:
            phrases = self._load_unlocked()
            if len(phrases) >= self.MAX_ITEMS:
                raise ValueError(f"Up to {self.MAX_ITEMS} quick phrases can be registered")
            clean_key = self._normalized_key(clean)
            if any(self._normalized_key(item["text"]) == clean_key for item in phrases):
                raise ValueError("This quick phrase is already registered")
            phrase = {"id": uuid.uuid4().hex, "text": clean, "category": ""}
            phrases.append(phrase)
            self._save_unlocked(phrases)
            return dict(phrase)

    def set_category(self, phrase_id: str, category: str) -> dict[str, str] | None:
        clean = category.strip()
        if len(clean) > self.MAX_CATEGORY_LENGTH or self._has_control_characters(clean):
            raise ValueError(
                "Quick phrase category must be a single line containing at most "
                f"{self.MAX_CATEGORY_LENGTH} characters"
            )
        with self._lock:
            phrases = self._load_unlocked()
            phrase = next((item for item in phrases if item["id"] == phrase_id), None)
            if phrase is None:
                return None
            if clean:
                clean_key = self._normalized_key(clean)
                clean = next(
                    (
                        item["category"]
                        for item in phrases
                        if item["category"]
                        and self._normalized_key(item["category"]) == clean_key
                    ),
                    clean,
                )
            if phrase["category"] == clean:
                return dict(phrase)
            phrase["category"] = clean
            self._save_unlocked(phrases)
            return dict(phrase)

    def delete(self, phrase_id: str) -> bool:
        with self._lock:
            phrases = self._load_unlocked()
            remaining = [item for item in phrases if item["id"] != phrase_id]
            if len(remaining) == len(phrases):
                return False
            self._save_unlocked(remaining)
            return True
