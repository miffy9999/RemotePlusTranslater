import threading

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from translator_app.config import load_config
from translator_app.desktop import _desktop_client_idle_seconds, _desktop_client_seen, _wait_for_http
from translator_app.server import create_app
from translator_app.tts_packs import PACK_CATALOG


def make_client(tmp_path):
    cfg = load_config()
    cfg.data_root = tmp_path
    return TestClient(
        create_app(cfg, start_backend=False),
        base_url=f"http://127.0.0.1:{cfg.server.port}",
    )


def test_api_requires_session_cookie(tmp_path):
    with make_client(tmp_path) as client:
        assert client.get("/api/state").status_code == 401
        assert (
            client.post("/api/install-voices", json={"languages": ["en"]}).status_code
            == 401
        )
        assert client.get("/").status_code == 200
        assert client.get("/api/state").status_code == 200


def test_voice_pack_install_accepts_only_reviewed_catalog_languages(tmp_path, monkeypatch):
    completed = threading.Event()

    def fake_install(_self, languages, _progress=None):
        assert languages == ["en"]
        completed.set()
        return []

    monkeypatch.setattr("translator_app.server.TtsPackManager.install_for_languages", fake_install)
    with make_client(tmp_path) as client:
        client.get("/")
        response = client.post("/api/install-voices", json={"languages": ["en"]})
        assert response.status_code == 202
        assert response.json()["accepted"] is True
        assert completed.wait(1)
        unavailable = client.post("/api/install-voices", json={"languages": ["th"]})
        assert unavailable.status_code == 400
        assert "commercially reviewed" in unavailable.json()["detail"]


def test_real_app_start_automatically_installs_every_reviewed_voice_pack(
    tmp_path, monkeypatch
):
    completed = threading.Event()
    calls = []

    monkeypatch.setattr("translator_app.server.ConversationController.start", lambda _self: None)
    monkeypatch.setattr("translator_app.server.ConversationController.stop", lambda _self: None)

    def fake_install(_self, languages, _progress=None):
        calls.append(set(languages))
        completed.set()
        return []

    monkeypatch.setattr(
        "translator_app.server.TtsPackManager.install_for_languages", fake_install
    )
    cfg = load_config()
    cfg.data_root = tmp_path
    expected = {code for spec in PACK_CATALOG.values() for code in spec.languages}

    with TestClient(
        create_app(cfg, start_backend=True),
        base_url=f"http://127.0.0.1:{cfg.server.port}",
    ):
        assert completed.wait(1)

    assert calls == [expected]


def test_voice_pack_selection_is_queued_during_an_active_download(tmp_path, monkeypatch):
    first_started = threading.Event()
    release_first = threading.Event()
    second_completed = threading.Event()
    calls = []

    def fake_install(_self, languages, _progress=None):
        calls.append(list(languages))
        if len(calls) == 1:
            first_started.set()
            assert release_first.wait(1)
        else:
            second_completed.set()
        return []

    monkeypatch.setattr(
        "translator_app.server.TtsPackManager.install_for_languages", fake_install
    )
    with make_client(tmp_path) as client:
        client.get("/")
        first = client.post("/api/install-voices", json={"languages": ["en"]})
        assert first.status_code == 202
        assert first_started.wait(1)
        second = client.post("/api/install-voices", json={"languages": ["zh"]})
        assert second.status_code == 202
        release_first.set()
        assert second_completed.wait(1)

    assert calls == [["en"], ["zh"]]


def test_reply_replay_refuses_uninstalled_voice_pack(tmp_path):
    with make_client(tmp_path) as client:
        client.get("/")
        response = client.post(
            "/api/replay",
            json={"text": "Please wait a moment.", "language": "en"},
        )
        assert response.status_code == 400
        assert "voice pack" in response.json()["detail"]
        invalid = client.post("/api/replay", json={"text": "test", "language": "ja"})
        assert invalid.status_code == 400


def test_dns_rebinding_host_is_rejected(tmp_path):
    with make_client(tmp_path) as client:
        assert client.get("/", headers={"host": "evil.example"}).status_code == 403


def test_websocket_requires_local_origin_and_cookie(tmp_path):
    with make_client(tmp_path) as client:
        client.get("/")
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws", headers={"origin": "http://evil.example"}):
                pass
        cookie = client.cookies.get("remoteplus_session")
        with client.websocket_connect(
            "/ws",
            headers={
                "origin": "http://127.0.0.1:8765",
                "cookie": f"remoteplus_session={cookie}",
                "host": "127.0.0.1:8765",
            },
        ) as websocket:
            assert client.app.state.desktop_client_count == 1
            assert client.app.state.desktop_client_seen is True
            assert websocket.receive_json()["type"] == "snapshot"
        assert client.app.state.desktop_client_count == 0
        assert client.app.state.desktop_last_disconnect > 0


def test_desktop_client_idle_seconds_uses_websocket_state(tmp_path, monkeypatch):
    with make_client(tmp_path) as client:
        assert _desktop_client_seen(client.app) is False
        client.app.state.desktop_client_seen = True
        client.app.state.desktop_client_count = 0
        client.app.state.desktop_last_disconnect = 10.0
        monkeypatch.setattr("translator_app.desktop.time.monotonic", lambda: 16.5)

        assert _desktop_client_seen(client.app) is True
        assert _desktop_client_idle_seconds(client.app) == 6.5


def test_devices_endpoint_uses_edge_outputs_only(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "translator_app.server._enumerate_devices",
        lambda _root: {
            "inputs": [{"id": 1, "name": "Mic"}],
            "outputs": [{"id": "edge:Speakers", "name": "Speakers"}],
            "warnings": [],
        },
    )
    with make_client(tmp_path) as client:
        client.get("/")
        data = client.get("/api/devices").json()
    assert data["inputs"] == [{"id": 1, "name": "Mic"}]
    assert data["outputs"] == [{"id": "edge:Speakers", "name": "Speakers"}]


def test_devices_endpoint_falls_back_when_audio_enumeration_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "translator_app.server._enumerate_devices",
        lambda _root: {
            "inputs": [{"id": "default", "name": "System default input"}],
            "outputs": [],
            "warnings": ["Audio device enumeration failed; system default remains available: driver failed"],
        },
    )
    with make_client(tmp_path) as client:
        client.get("/")
        response = client.get("/api/devices")
    assert response.status_code == 200
    data = response.json()
    assert data["inputs"] == [{"id": "default", "name": "System default input"}]
    assert data["outputs"] == []
    assert "driver failed" in data["warnings"][0]


def test_health_endpoint_identifies_remoteplus(tmp_path):
    with make_client(tmp_path) as client:
        response = client.get("/remoteplus-health")
    assert response.status_code == 200
    assert response.json() == {
        "app": "remoteplus-translator",
        "version": "0.6.0",
        "update_layer": False,
        "ok": True,
    }


def test_wait_for_http_waits_until_server_answers(monkeypatch):
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    calls = iter([OSError("not yet"), FakeResponse()])

    def fake_urlopen(*_args, **_kwargs):
        result = next(calls)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("translator_app.desktop.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("translator_app.desktop.time.sleep", lambda _seconds: None)

    assert _wait_for_http("http://127.0.0.1:8765", timeout_seconds=1)


def test_static_assets_are_explicitly_allowlisted(tmp_path):
    with make_client(tmp_path) as client:
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/assets/not-packaged.css").status_code == 404


def test_settings_write_failure_does_not_turn_applied_control_into_http_500(
    tmp_path, monkeypatch
):
    def fail_save(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("translator_app.settings.UserSettings.save", fail_save)
    with make_client(tmp_path) as client:
        client.get("/")
        response = client.post("/api/control", json={"tts_enabled": False})
        assert response.status_code == 200
        assert response.json()["tts_enabled"] is False
        assert response.json()["settings_persisted"] is False
        state = client.get("/api/state").json()
        assert state["state"]["tts_enabled"] is False
        assert any(event["type"] == "warning" for event in state["history"])


def test_momentary_staff_mode_does_not_write_user_settings(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "translator_app.settings.UserSettings.save",
        lambda *_args, **_kwargs: calls.append(True),
    )
    with make_client(tmp_path) as client:
        client.get("/")
        assert client.post("/api/control", json={"speech_mode": "staff"}).status_code == 200
        assert client.post("/api/control", json={"speech_mode": "customer"}).status_code == 200
    assert calls == []


def test_unknown_api_fields_are_rejected_instead_of_silently_ignored(tmp_path):
    with make_client(tmp_path) as client:
        client.get("/")
        response = client.post("/api/control", json={"speech_modes": "staff"})
    assert response.status_code == 422


def test_malformed_persisted_settings_do_not_prevent_startup(tmp_path):
    (tmp_path / "user-settings.json").write_text(
        '{"active_language": 123, "tts_enabled": "false", "input_device": {}}',
        encoding="utf-8",
    )
    with make_client(tmp_path) as client:
        client.get("/")
        state = client.get("/api/state").json()["state"]
    assert state["input_language"] == "en"
    assert state["tts_enabled"] is True
