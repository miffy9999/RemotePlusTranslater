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


def authenticate(client):
    assert client.get("/").status_code == 200


def test_api_requires_session_cookie(tmp_path):
    with make_client(tmp_path) as client:
        assert client.get("/api/state").status_code == 401
        authenticate(client)
        assert client.get("/api/state").status_code == 200


def test_state_exposes_languages_and_reading_capabilities(tmp_path):
    with make_client(tmp_path) as client:
        authenticate(client)
        data = client.get("/api/state").json()
        assert {"en", "ko", "zh", "es"} <= {x["code"] for x in data["languages"]}
        assert data["reading"]["romanization"] == "all"
        assert "ko" in data["reading"]["katakana_languages"]


def test_staff_reply_endpoint_accepts_text_and_rejects_stale_tts_fields(tmp_path):
    with make_client(tmp_path) as client:
        authenticate(client)
        response = client.post("/api/reply", json={"text": "少々お待ちください"})
        assert response.status_code == 202
        assert response.json()["utterance_id"] > 0
        assert client.post("/api/control", json={"tts_enabled": False}).status_code == 422
        assert client.post("/api/reply", json={"text": ""}).status_code == 400


def test_language_and_device_settings_are_persisted(tmp_path, monkeypatch):
    monkeypatch.setattr("translator_app.conversation.validate_input_device", lambda _x: None)
    with make_client(tmp_path) as client:
        authenticate(client)
        response = client.post(
            "/api/control", json={"active_language": "ko", "input_device": 3}
        )
        assert response.status_code == 200
        saved = (tmp_path / "user-settings.json").read_text(encoding="utf-8")
        assert '"active_language": "ko"' in saved
        assert "tts_enabled" not in saved


def test_assets_are_allowlisted_and_path_traversal_is_rejected(tmp_path):
    with make_client(tmp_path) as client:
        authenticate(client)
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/assets/unknown.js").status_code == 404


def test_websocket_rejects_invalid_origin(tmp_path):
    with make_client(tmp_path) as client:
        authenticate(client)
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/ws", headers={"origin": "https://evil.example"}
            ):
                pass


def test_websocket_snapshot_has_one_consistent_state(tmp_path):
    with make_client(tmp_path) as client:
        authenticate(client)
        origin = str(client.base_url)
        with client.websocket_connect(
            "/ws",
            headers={
                "origin": origin,
                "host": client.base_url.netloc,
                "x-auth-token": client.app.state.auth_token,
            },
        ) as socket:
            message = socket.receive_json()
        assert message["type"] == "snapshot"
        assert "state" in message["data"]
