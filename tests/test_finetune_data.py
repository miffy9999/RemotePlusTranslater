from __future__ import annotations

import json

import pytest

from scripts.prepare_finetune_data import SEED, _prompt, validate


def test_seed_is_private_data_safe_balanced_and_leak_free():
    items = json.loads(SEED.read_text(encoding="utf-8"))
    counts = validate(items)
    assert counts["train"] == 40
    assert counts["holdout"] == 8
    assert all(item["source"] in {"ja", "ko", "en"} for item in items)


def test_context_record_renders_current_and_adjacent_turns():
    prompt = _prompt(
        {
            "source": "ko",
            "target": "ja",
            "previous": "객실을 변경해 드릴까요?",
            "current": "그렇게 해 주세요.",
            "next": "변경하겠습니다.",
        }
    )
    assert "PREVIOUS:" in prompt
    assert "CURRENT: 그렇게 해 주세요." in prompt
    assert "NEXT:" in prompt


def test_validator_rejects_train_holdout_leakage():
    base = {
        "category": "test",
        "source": "ko",
        "target": "ja",
        "current": "같은 문장",
        "translation": "同じ文",
    }
    with pytest.raises(ValueError, match="leakage"):
        validate(
            [
                {**base, "id": "train", "split": "train"},
                {**base, "id": "holdout", "split": "holdout"},
            ]
        )
