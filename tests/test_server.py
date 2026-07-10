import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from translator_app.config import load_config
from translator_app.desktop import _desktop_client_idle_seconds, _desktop_client_seen, _wait_for_http
from translator_app.server import create_app


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


def test_reply_replay_requires_enabled_language_and_queues_audio(tmp_path):
    with make_client(tmp_path) as client:
        client.get("/")
        response = client.post(
            "/api/replay",
            json={"text": "Please wait a moment.", "language": "en"},
        )
        assert response.status_code == 200
        assert response.json()["queued"] is True
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
    assert response.json() == {"app": "remoteplus-translator", "ok": True}


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
