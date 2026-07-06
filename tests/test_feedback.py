import json

import pytest

from translator_app.feedback import FeedbackStore


def test_feedback_is_appended_as_utf8_jsonl(tmp_path):
    store = FeedbackStore(tmp_path)
    path = store.append(
        {
            "direction": "incoming",
            "source_language": "ko",
            "source": "진저일 주세요",
            "translation": "ジンジャーをください",
            "corrected_source": "진저에일 주세요",
            "corrected_translation": "",
        }
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["corrected_source"] == "진저에일 주세요"


def test_feedback_requires_an_actual_correction(tmp_path):
    with pytest.raises(ValueError):
        FeedbackStore(tmp_path).append({"corrected_source": "", "corrected_translation": ""})


def test_feedback_file_can_be_deleted(tmp_path):
    store = FeedbackStore(tmp_path)
    store.append({"corrected_source": "fixed", "corrected_translation": ""})
    assert store.clear() is True
    assert store.clear() is False
