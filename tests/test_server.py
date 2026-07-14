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


def test_quick_phrases_can_be_registered_listed_and_deleted(tmp_path):
    with make_client(tmp_path) as client:
        authenticate(client)
        created = client.post("/api/quick-phrases", json={"text": "少々お待ちください。"})
        assert created.status_code == 201
        phrase = created.json()["phrase"]
        assert phrase["text"] == "少々お待ちください。"
        listed = client.get("/api/quick-phrases").json()
        assert listed["phrases"] == [phrase]
        assert listed["max_items"] == 40
        assert client.delete(f"/api/quick-phrases/{phrase['id']}").status_code == 200
        assert client.get("/api/quick-phrases").json()["phrases"] == []


def test_quick_phrases_reject_duplicates_and_missing_ids(tmp_path):
    with make_client(tmp_path) as client:
        authenticate(client)
        assert client.post("/api/quick-phrases", json={"text": "確認します"}).status_code == 201
        assert client.post("/api/quick-phrases", json={"text": " 確認します "}).status_code == 400
        assert client.post("/api/quick-phrases", json={"text": "ＣＨＥＣＫ－ＩＮ"}).status_code == 201
        assert client.post("/api/quick-phrases", json={"text": "check-in"}).status_code == 400
        assert client.delete("/api/quick-phrases/missing").status_code == 404


def test_quick_phrase_category_can_be_saved_changed_and_removed(tmp_path):
    with make_client(tmp_path) as client:
        authenticate(client)
        phrase = client.post(
            "/api/quick-phrases", json={"text": "ご予約を確認いたします。"}
        ).json()["phrase"]
        assert phrase["category"] == ""

        category_url = f"/api/quick-phrases/{phrase['id']}/category"
        assigned = client.patch(category_url, json={"category": "予約"})
        assert assigned.status_code == 200
        assert assigned.json()["phrase"]["category"] == "予約"
        assert client.get("/api/quick-phrases").json()["phrases"][0]["category"] == "予約"

        removed = client.patch(category_url, json={"category": ""})
        assert removed.status_code == 200
        assert removed.json()["phrase"]["category"] == ""


def test_quick_phrase_category_rejects_invalid_or_missing_phrase(tmp_path):
    with make_client(tmp_path) as client:
        authenticate(client)
        phrase = client.post("/api/quick-phrases", json={"text": "Hello"}).json()["phrase"]
        category_url = f"/api/quick-phrases/{phrase['id']}/category"
        assert client.patch(category_url, json={"category": "x" * 41}).status_code == 400
        assert client.patch(category_url, json={"category": "予約\n確認"}).status_code == 400
        assert client.patch(
            "/api/quick-phrases/missing/category", json={"category": "予約"}
        ).status_code == 404


def test_equivalent_category_names_reuse_one_display_name(tmp_path):
    with make_client(tmp_path) as client:
        authenticate(client)
        first = client.post("/api/quick-phrases", json={"text": "First"}).json()["phrase"]
        second = client.post("/api/quick-phrases", json={"text": "Second"}).json()["phrase"]
        client.patch(
            f"/api/quick-phrases/{first['id']}/category", json={"category": "CHECK-IN"}
        )
        assigned = client.patch(
            f"/api/quick-phrases/{second['id']}/category", json={"category": "ｃｈｅｃｋ－ｉｎ"}
        )
        assert assigned.json()["phrase"]["category"] == "CHECK-IN"


def test_collapsed_categories_persist_with_quick_phrase_data(tmp_path):
    with make_client(tmp_path) as client:
        authenticate(client)
        categorized = client.post(
            "/api/quick-phrases", json={"text": "Reservation phrase"}
        ).json()["phrase"]
        client.patch(
            f"/api/quick-phrases/{categorized['id']}/category",
            json={"category": "予約"},
        )
        client.post("/api/quick-phrases", json={"text": "Uncategorized phrase"})
        saved = client.patch(
            "/api/quick-phrases/ui-state",
            json={"collapsed_categories": ["予約", "", "missing", "予約"]},
        )
        assert saved.status_code == 200
        assert saved.json()["collapsed_categories"] == ["予約", ""]

        client.post("/api/quick-phrases", json={"text": "Another phrase"})
        listed = client.get("/api/quick-phrases").json()
        assert listed["collapsed_categories"] == ["予約", ""]
        stored = (tmp_path / "quick-phrases.json").read_text(encoding="utf-8")
        assert '"schema_version": 3' in stored


def test_collapsed_category_state_rejects_invalid_input(tmp_path):
    with make_client(tmp_path) as client:
        authenticate(client)
        client.post("/api/quick-phrases", json={"text": "Phrase"})
        assert client.patch(
            "/api/quick-phrases/ui-state",
            json={"collapsed_categories": ["x"] * 41},
        ).status_code == 400
        assert client.patch(
            "/api/quick-phrases/ui-state",
            json={"collapsed_categories": ["bad\nname"]},
        ).status_code == 400


def test_quick_phrase_store_upgrades_legacy_items_without_losing_text(tmp_path):
    (tmp_path / "quick-phrases.json").write_text(
        '{"schema_version":1,"phrases":[{"id":"legacy","text":"少々お待ちください。"}]}',
        encoding="utf-8",
    )
    with make_client(tmp_path) as client:
        authenticate(client)
        assert client.get("/api/quick-phrases").json()["phrases"] == [
            {"id": "legacy", "text": "少々お待ちください。", "category": ""}
        ]


def test_corrupt_quick_phrase_file_is_preserved_before_new_data_is_saved(tmp_path):
    path = tmp_path / "quick-phrases.json"
    path.write_text('{"phrases":[', encoding="utf-8")
    with make_client(tmp_path) as client:
        authenticate(client)
        assert client.get("/api/quick-phrases").json()["phrases"] == []
        assert client.post("/api/quick-phrases", json={"text": "Recovered"}).status_code == 201

    backups = list(tmp_path.glob("quick-phrases.corrupt-*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == '{"phrases":['
    assert "Recovered" in path.read_text(encoding="utf-8")


def test_boolean_quick_phrase_schema_version_is_rejected_and_preserved(tmp_path):
    path = tmp_path / "quick-phrases.json"
    original = '{"schema_version":true,"phrases":[]}'
    path.write_text(original, encoding="utf-8")

    with make_client(tmp_path) as client:
        authenticate(client)
        assert client.get("/api/quick-phrases").json()["phrases"] == []

    backups = list(tmp_path.glob("quick-phrases.corrupt-*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == original


def test_quick_phrases_enforce_the_advertised_40_item_limit(tmp_path):
    with make_client(tmp_path) as client:
        authenticate(client)
        for index in range(40):
            response = client.post("/api/quick-phrases", json={"text": f"phrase {index}"})
            assert response.status_code == 201

        listed = client.get("/api/quick-phrases").json()
        assert listed["max_items"] == 40
        assert len(listed["phrases"]) == 40
        assert client.post("/api/quick-phrases", json={"text": "phrase 41"}).status_code == 400


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
