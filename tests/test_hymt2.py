import hashlib
from types import SimpleNamespace

import pytest

from translator_app.hymt2 import (
    LANGUAGE_NAMES,
    HyMT2Translator,
    _verify_sha256,
    build_hymt2_prompt,
    needs_conversation_context,
    translation_output_is_valid,
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
    assert "natural, polite hotel-service language" in prompt
    assert "hotel call-center expressions" in prompt
    assert "social function" in prompt
    assert "Korean sentence order" in prompt
    assert "Never add or remove facts" in prompt
    assert prompt.endswith("Hello")


def test_translation_output_guard_rejects_wrong_script_and_lost_numbers():
    assert translation_output_is_valid("room 204", "204号室です。", "ja")
    assert translation_output_is_valid("046-1234-5678", "04612345678", "ja")
    assert not translation_output_is_valid("room 204", "This is room 204.", "ja")
    assert not translation_output_is_valid("room 204", "こちらのお部屋です。", "ja")
    assert not translation_output_is_valid("確認します", "確認します", "en")


def test_numeric_only_turn_is_returned_without_model_hallucination():
    cfg = SimpleNamespace(protected_terms=[], glossary={})
    translator = HyMT2Translator(cfg, lambda *_: None)
    translator._request = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("numeric-only text must skip the model")
    )
    assert translator.translate("204.", "fr", "ja") == "204."
    assert translator.translate("046-878-6433", "en", "ja") == "046-878-6433"


def test_invalid_model_output_gets_one_strict_retry():
    cfg = SimpleNamespace(protected_terms=[], glossary={})
    translator = HyMT2Translator(cfg, lambda *_: None)
    translator.ready = True
    translator.process = SimpleNamespace(poll=lambda: None)
    answers = iter(["This is room 204.", "204号室です。"])
    prompts = []

    def request(prompt):
        prompts.append(prompt)
        return next(answers)

    translator._request = request
    assert translator.translate("room 204", "en", "ja") == "204号室です。"
    assert len(prompts) == 2
    assert "CRITICAL OUTPUT CHECK" in prompts[1]


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


def test_shutdown_terminates_engine_immediately_and_prevents_restart():
    cfg = SimpleNamespace(protected_terms=[], glossary={})
    translator = HyMT2Translator(cfg, lambda *_: None)

    class Process:
        terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

    process = Process()
    translator.process = process
    translator.begin_shutdown()
    assert process.terminated is True
    assert translator._shutdown_requested.is_set() is True
    translator._load_locked()
    assert translator.ready is False


def test_shutdown_during_engine_start_does_not_spawn_a_replacement(tmp_path, monkeypatch):
    model = tmp_path / "model.gguf"
    runtime = tmp_path / "runtime"
    model.write_bytes(b"model")
    runtime.mkdir()
    (runtime / "llama-server.exe").write_bytes(b"runtime")
    cfg = SimpleNamespace(
        root=tmp_path,
        data_root=tmp_path / "data",
        hymt2_model=str(model.relative_to(tmp_path)),
        hymt2_runtime=str(runtime.relative_to(tmp_path)),
        hymt2_context=1024,
        hymt2_threads=2,
        hymt2_timeout_seconds=1,
        hymt2_startup_poll_ms=20,
    )
    translator = HyMT2Translator(cfg, lambda *_: None)
    processes = []

    class Process:
        stopped = False

        def poll(self):
            return 0 if self.stopped else None

        def terminate(self):
            self.stopped = True

        def wait(self, timeout):
            return 0

        def kill(self):
            self.stopped = True

    def popen(*_args, **_kwargs):
        process = Process()
        processes.append(process)
        return process

    monkeypatch.setattr("translator_app.hymt2.subprocess.Popen", popen)

    def health():
        translator.begin_shutdown()
        return False

    translator._health = health
    translator.load()
    assert len(processes) == 1
    assert processes[0].stopped is True
    assert translator.process is None


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
        def __iter__(self):
            return iter([b'data: {"choices": []}\n'])

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    with pytest.raises(TranslationResponseError, match="invalid completion chunk"):
        translator._request("prompt")


def test_streaming_request_assembles_chunks_and_enables_early_cancel(monkeypatch):
    cfg = SimpleNamespace(max_new_tokens=128, hymt2_request_timeout_seconds=1)
    translator = HyMT2Translator(cfg, lambda *_: None)
    translator.port = 9999
    seen = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def __iter__(self):
            return iter([
                b'data: {"choices":[{"delta":{"content":"\\u3053\\u3093"}}]}\n',
                b'data: {"choices":[{"delta":{"content":"\\u306b\\u3061\\u306f"}}]}\n',
                b'data: [DONE]\n',
            ])

    def fake_urlopen(request, **_kwargs):
        seen.update(__import__("json").loads(request.data))
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert translator._request("prompt") == "こんにちは"
    assert seen["stream"] is True


def test_cancelled_stream_does_not_poison_the_next_request(monkeypatch):
    cfg = SimpleNamespace(max_new_tokens=128, hymt2_request_timeout_seconds=1)
    translator = HyMT2Translator(cfg, lambda *_: None)
    translator.port = 9999
    responses = []

    class Response:
        def __init__(self, cancel=False):
            self.cancel = cancel
            self.closed = False
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def close(self): self.closed = True
        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"ok"}}]}\n'
            if self.cancel:
                assert translator.cancel_active_request() is True
            yield b'data: [DONE]\n'

    responses.extend([Response(cancel=True), Response()])
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: responses.pop(0))
    with pytest.raises(InterruptedError, match="cancelled"):
        translator._request("old")
    assert translator._request("new") == "ok"


def test_context_guard_rejects_pathological_cjk_input_before_model_call():
    cfg = SimpleNamespace(protected_terms=[], glossary={})
    translator = HyMT2Translator(cfg, lambda *_: None)
    with pytest.raises(ValueError, match="too long"):
        translator.translate("客" * 801, "zh", "ja")


def test_production_translation_path_treats_konbanwa_as_a_greeting():
    cfg = SimpleNamespace(protected_terms=[], glossary={})
    translator = HyMT2Translator(cfg, lambda *_: None)
    assert translator.translate("こんばんは", "ja", "ko") == "안녕하세요."


def test_context_prompt_translates_current_only_with_bounded_input_budget():
    regular = build_hymt2_prompt("それでお願いします。", "ja", "ko", [])
    contextual = build_hymt2_prompt(
        "それでお願いします。",
        "ja",
        "ko",
        [],
        previous_text="朝食は洋食と和食から選べます。" * 20,
        next_text="飲み物はコーヒーにします。" * 20,
    )
    assert "Translate only CURRENT" in contextual
    assert "PREVIOUS:" in contextual and "NEXT:" in contextual
    assert len(contextual) <= len(regular)
    assert needs_conversation_context("それでお願いします。", "ja") is True
    assert needs_conversation_context("もう一度お願いします。", "ja") is True
    assert needs_conversation_context("Yes, that is fine.", "en") is True
    assert needs_conversation_context("다시 말씀해 주세요.", "ko") is True
    assert needs_conversation_context("予約番号は1234です。", "ja") is False
