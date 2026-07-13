from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.prepare_commercial_release import ReleaseComplianceError, prepare, validate_info


def valid_info() -> dict:
    return {
        "schema_version": 1,
        "distribution_scope": "internal_business_use",
        "publisher_legal_name": "Example Hotel Co., Ltd.",
        "publisher_address": "1-2-3 Example, Tokyo, Japan",
        "publisher_responsible_person": "Taro Example",
        "publisher_phone": "+81-3-0000-0000",
        "publisher_email": "support@example.invalid",
        "support_url": "https://example.invalid/support",
        "operator_legal_name": "Example Hotel Co., Ltd.",
        "operator_address": "1-2-3 Example, Tokyo, Japan",
        "operator_responsible_person": "Hanako Example",
        "operator_phone": "+81-3-0000-0001",
        "operator_email": "privacy@example.invalid",
        "operator_privacy_url": "https://example.invalid/privacy",
        "product_version": "0.6.0",
        "effective_date": "2026-07-13",
        "support_end_date": "Internal IT lifecycle policy",
        "governing_law": "Laws of Japan",
        "exclusive_court": "Tokyo District Court",
        "refund_policy": "Internal deployment; no sale or refund",
        "liability_cap": "Defined by the internal service agreement",
        "counsel_review_completed": False,
        "counsel_name": "",
        "counsel_bar_registration": "",
        "counsel_review_date": "",
        "counsel_review_document": "",
        "counsel_review_document_sha256": "",
    }


def test_internal_release_does_not_claim_external_counsel_review(tmp_path: Path) -> None:
    info_path = tmp_path / "publisher.json"
    info_path.write_text(json.dumps(valid_info()), encoding="utf-8")
    destination = tmp_path / "release"

    result = prepare(info_path, destination)

    assert result["distribution_scope"] == "internal_business_use"
    assert result["counsel_review_completed"] is False
    assert "{{" not in (destination / "EULA_JA.md").read_text(encoding="utf-8")
    assert "Example Hotel Co., Ltd." in (
        destination / "DISTRIBUTOR_DISCLOSURE_JA.md"
    ).read_text(encoding="utf-8")


def test_placeholder_publisher_data_is_rejected(tmp_path: Path) -> None:
    info = valid_info()
    info["publisher_legal_name"] = "REPLACE_WITH_NAME"

    errors = validate_info(info, tmp_path / "publisher.json")

    assert any("publisher_legal_name" in error for error in errors)


def test_third_party_distribution_requires_verifiable_counsel_evidence(
    tmp_path: Path,
) -> None:
    info = valid_info()
    info["distribution_scope"] = "third_party_distribution"
    info_path = tmp_path / "publisher.json"

    errors = validate_info(info, info_path)

    assert any("counsel review must be completed" in error for error in errors)
    assert any("counsel_name" in error for error in errors)

    evidence = tmp_path / "review.pdf"
    evidence.write_bytes(b"signed legal review")
    info.update(
        {
            "counsel_review_completed": True,
            "counsel_name": "Licensed Counsel",
            "counsel_bar_registration": "Example Bar 12345",
            "counsel_review_date": "2026-07-13",
            "counsel_review_document": str(evidence),
            "counsel_review_document_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
        }
    )

    assert validate_info(info, info_path) == []


def test_missing_template_values_are_not_silently_emitted(tmp_path: Path) -> None:
    info = valid_info()
    del info["publisher_phone"]
    info_path = tmp_path / "publisher.json"
    info_path.write_text(json.dumps(info), encoding="utf-8")

    with pytest.raises(ReleaseComplianceError, match="publisher_phone"):
        prepare(info_path, tmp_path / "release")
