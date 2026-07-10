import hashlib
from types import SimpleNamespace

import pytest

from translator_app.hymt2 import (
    LANGUAGE_NAMES,
    HyMT2Translator,
    _verify_sha256,
    build_hymt2_prompt,
    TranslationResponseError,
)
from translator_app.languages import public_languages


def test_prompt_includes_matching_hotel_terminology_only():
    terms = [
        {"en": ["ginger ale"], "ja": ["ジンジャーエール"]},
        {"en": ["passport"], "ja": ["パスポート"]},
    ]
    prompt = build_hymt2_prompt(
        "Please bring one ginger ale.", "en", "ja", terms
    )
    assert "ginger ale translates to ジンジャーエール" in prompt
    assert "passport" not in prompt
    assert "into Japanese" in prompt


def test_prompt_without_terms_is_still_strict():
    prompt = build_hymt2_prompt("Hello", "en", "ja", [])
    assert "ONLY output the translated result" in prompt
    assert prompt.endswith("Hello")


def test_engine_request_failure_restarts_once():
    cfg = SimpleNamespace(protected_terms=[], glossary={})
    translator = HyMT2Translator(cfg, lambda *_: None)
    translator.ready = True
    attempts = 0

    def request(_prompt):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("server stopped")
        return "こんにちは"

    translator._request = request
    translator._close_locked = lambda: setattr(translator, "ready", False)
    translator._load_locked = lambda: setattr(translator, "ready", True)
    assert translator.translate("Hello", "en", "ja") == "こんにちは"
    assert attempts == 2


def test_ui_only_exposes_languages_supported_by_hymt2():
    assert {item["code"] for item in public_languages()} <= set(LANGUAGE_NAMES)


def test_checksum_failure_removes_download(tmp_path):
    path = tmp_path / "download.zip"
    path.write_bytes(b"valid bytes")
    with pytest.raises(RuntimeError, match="SHA-256"):
        _verify_sha256(path, "0" * 64)
    assert not path.exists()


def test_checksum_accepts_matching_file(tmp_path):
    path = tmp_path / "download.zip"
    path.write_bytes(b"valid bytes")
    _verify_sha256(path, hashlib.sha256(b"valid bytes").hexdigest())
    assert path.exists()


def test_invalid_completion_shape_has_clear_error(monkeypatch):
    cfg = SimpleNamespace(max_new_tokens=128, hymt2_request_timeout_seconds=1)
    translator = HyMT2Translator(cfg, lambda *_: None)
    translator.port = 9999

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def read(self, *_args): return b'{"choices": []}'

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    with pytest.raises(TranslationResponseError, match="no completion"):
        translator._request("prompt")
