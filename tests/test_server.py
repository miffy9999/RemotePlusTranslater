import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from translator_app.config import load_config
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
            assert websocket.receive_json()["type"] == "snapshot"


def test_devices_endpoint_uses_edge_outputs_only(tmp_path, monkeypatch):
    monkeypatch.setenv("REMOTEPLUS_ENUMERATE_AUDIO_DEVICES", "1")
    monkeypatch.setattr(
        "translator_app.server.list_audio_devices",
        lambda: {
            "inputs": [{"id": 1, "name": "Mic"}],
            "outputs": [{"id": "output:legacy", "name": "Legacy output"}],
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "translator_app.server.EdgeSpeaker.output_devices",
        lambda: [{"id": "edge:Speakers", "name": "Speakers"}],
    )
    with make_client(tmp_path) as client:
        client.get("/")
        data = client.get("/api/devices").json()
    assert data["inputs"] == [{"id": 1, "name": "Mic"}]
    assert data["outputs"] == [{"id": "edge:Speakers", "name": "Speakers"}]


def test_devices_endpoint_falls_back_when_audio_enumeration_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("REMOTEPLUS_ENUMERATE_AUDIO_DEVICES", "1")
    monkeypatch.setattr(
        "translator_app.server.list_audio_devices",
        lambda: (_ for _ in ()).throw(RuntimeError("driver failed")),
    )
    monkeypatch.setattr("translator_app.server.EdgeSpeaker.output_devices", lambda: [])
    with make_client(tmp_path) as client:
        client.get("/")
        response = client.get("/api/devices")
    assert response.status_code == 200
    data = response.json()
    assert data["inputs"] == [{"id": "default", "name": "System default input"}]
    assert data["outputs"] == []
    assert "driver failed" in data["warnings"][0]
