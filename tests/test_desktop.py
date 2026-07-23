import threading
from types import SimpleNamespace

import pytest

from translator_app.desktop import _prepare_webview_profile, _show_native_window


def test_native_window_uses_embedded_webview_without_browser(tmp_path, monkeypatch):
    calls = {}

    def create_window(title, url, **kwargs):
        calls["window"] = (title, url, kwargs)

    def start(**kwargs):
        calls["start"] = kwargs

    monkeypatch.setitem(
        __import__("sys").modules,
        "webview",
        SimpleNamespace(create_window=create_window, start=start),
    )

    _show_native_window("http://127.0.0.1:8765", tmp_path)

    assert calls["window"][0] == "RemotePlus Translator"
    assert calls["window"][1] == "http://127.0.0.1:8765"
    assert calls["window"][2]["maximized"] is True
    assert calls["start"]["gui"] == "edgechromium"
    assert calls["start"]["private_mode"] is False
    assert calls["start"]["storage_path"] == str(tmp_path / "webview2")


def test_unclean_webview_session_switches_to_fresh_recovery_profile(tmp_path):
    first, state_path, first_name = _prepare_webview_profile(tmp_path)
    assert first_name == "a"
    assert first.is_dir()
    (first / "preserved.txt").write_text("unclean", encoding="utf-8")

    recovered, _, recovered_name = _prepare_webview_profile(tmp_path)
    assert recovered_name == "b"
    assert recovered != first
    assert not (recovered / "preserved.txt").exists()
    assert '"clean_exit": false' in state_path.read_text(encoding="utf-8")


def test_corrupt_webview_state_is_replaced_without_blocking_startup(tmp_path):
    state = tmp_path / "webview2-v2" / "state.json"
    state.parent.mkdir(parents=True)
    state.write_bytes(b'{"profile":')
    profile, state_path, profile_name = _prepare_webview_profile(tmp_path)
    assert profile_name == "a"
    assert profile.is_dir()
    assert '"clean_exit": false' in state_path.read_text(encoding="utf-8")


class FakeHook:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def emit(self):
        for handler in self.handlers:
            handler()


class FakeWindow:
    def __init__(self):
        self.events = SimpleNamespace(closing=FakeHook())
        self.reloads = []
        self.destroyed = False

    def load_url(self, url):
        self.reloads.append(url)

    def destroy(self):
        self.destroyed = True
        self.events.closing.emit()


def test_native_window_accepts_explicit_close_after_ui_ready(tmp_path, monkeypatch):
    window = FakeWindow()
    ready = threading.Event()
    ready.set()

    def start(**kwargs):
        kwargs["func"]()
        window.events.closing.emit()

    monkeypatch.setitem(
        __import__("sys").modules,
        "webview",
        SimpleNamespace(create_window=lambda *_args, **_kwargs: window, start=start),
    )
    _show_native_window("http://127.0.0.1:8765", tmp_path, ready)
    assert window.reloads == []


def test_native_window_rejects_renderer_exit_without_close_event(tmp_path, monkeypatch):
    window = FakeWindow()
    monkeypatch.setitem(
        __import__("sys").modules,
        "webview",
        SimpleNamespace(
            create_window=lambda *_args, **_kwargs: window,
            start=lambda **_kwargs: None,
        ),
    )
    with pytest.raises(RuntimeError, match="ended unexpectedly"):
        _show_native_window("http://127.0.0.1:8765", tmp_path)
