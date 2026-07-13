from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent
TOKEN = re.compile(r"\{\{([a-z0-9_]+)\}\}")
REPLACEMENT_MARKERS = ("REPLACE_", "要記入", "要確認", "TBD", "TODO")
ALLOWED_SCOPES = {"internal_business_use", "third_party_distribution"}
REQUIRED_FIELDS = (
    "publisher_legal_name",
    "publisher_address",
    "publisher_responsible_person",
    "publisher_phone",
    "publisher_email",
    "operator_legal_name",
    "operator_address",
    "operator_responsible_person",
    "operator_phone",
    "operator_email",
    "product_version",
    "effective_date",
    "support_end_date",
    "governing_law",
    "exclusive_court",
    "refund_policy",
    "liability_cap",
)


class ReleaseComplianceError(ValueError):
    """Raised when a release would contain incomplete legal metadata."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolved_evidence_path(info_path: Path, raw: str) -> Path:
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    # Paths in the example are repository-relative. Also accept a path next to
    # the private metadata file so companies can keep both outside the repo.
    repository_candidate = ROOT / candidate
    if repository_candidate.exists():
        return repository_candidate
    return info_path.parent / candidate


def validate_info(info: dict, info_path: Path) -> list[str]:
    errors: list[str] = []
    if info.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    scope = str(info.get("distribution_scope", ""))
    if scope not in ALLOWED_SCOPES:
        errors.append(
            "distribution_scope must be internal_business_use or third_party_distribution"
        )
    for field in REQUIRED_FIELDS:
        value = str(info.get(field, "")).strip()
        if not value or any(marker.casefold() in value.casefold() for marker in REPLACEMENT_MARKERS):
            errors.append(f"{field} is missing or still contains a placeholder")

    for field in ("publisher_email", "operator_email"):
        email = str(info.get(field, ""))
        if email and ("@" not in email or email.startswith("@") or email.endswith("@")):
            errors.append(f"{field} is not a plausible email address")
    for field in ("support_url", "operator_privacy_url"):
        url = str(info.get(field, "")).strip()
        if not url:
            errors.append(f"{field} is required")
        elif url.casefold() != "none":
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.netloc:
                errors.append(f"{field} must be an https URL or the literal NONE")

    if scope == "third_party_distribution":
        if info.get("counsel_review_completed") is not True:
            errors.append("Japanese counsel review must be completed for third-party distribution")
        for field in ("counsel_name", "counsel_bar_registration", "counsel_review_date"):
            if not str(info.get(field, "")).strip():
                errors.append(f"{field} is required for third-party distribution")
        raw_document = str(info.get("counsel_review_document", "")).strip()
        expected_hash = str(info.get("counsel_review_document_sha256", "")).strip().lower()
        if not raw_document:
            errors.append("counsel_review_document is required for third-party distribution")
        else:
            evidence = _resolved_evidence_path(info_path, raw_document)
            if not evidence.is_file():
                errors.append(f"counsel review evidence does not exist: {evidence}")
            elif not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
                errors.append("counsel_review_document_sha256 must be a 64-character SHA-256")
            elif _sha256(evidence) != expected_hash:
                errors.append("counsel review evidence SHA-256 does not match")
    return errors


def render_template(template: str, info: dict) -> str:
    missing = sorted({key for key in TOKEN.findall(template) if not str(info.get(key, "")).strip()})
    if missing:
        raise ReleaseComplianceError("missing template values: " + ", ".join(missing))
    rendered = TOKEN.sub(lambda match: str(info[match.group(1)]).strip(), template)
    leftovers = TOKEN.findall(rendered)
    if leftovers:
        raise ReleaseComplianceError("unrendered tokens: " + ", ".join(sorted(set(leftovers))))
    return rendered


def prepare(info_path: Path, destination: Path) -> dict:
    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseComplianceError(f"cannot read distributor metadata: {exc}") from exc
    errors = validate_info(info, info_path)
    if errors:
        raise ReleaseComplianceError("\n- " + "\n- ".join(errors))

    templates = {
        "EULA_JA.md": ROOT / "EULA_JA.md",
        "PRIVACY_NOTICE_JA.md": ROOT / "PRIVACY_NOTICE_JA.md",
    }
    destination.mkdir(parents=True, exist_ok=True)
    for output_name, template_path in templates.items():
        rendered = render_template(template_path.read_text(encoding="utf-8"), info)
        (destination / output_name).write_text(rendered, encoding="utf-8", newline="\n")

    disclosure = (
        "# 配布者情報\n\n"
        f"- 正式名称: {info['publisher_legal_name']}\n"
        f"- 所在地: {info['publisher_address']}\n"
        f"- 代表者・責任者: {info['publisher_responsible_person']}\n"
        f"- 電話番号: {info['publisher_phone']}\n"
        f"- メール: {info['publisher_email']}\n"
        f"- サポート: {info['support_url']}\n"
        f"- 通話運営者: {info['operator_legal_name']}\n"
        f"- 個人情報窓口: {info['operator_email']}\n"
        f"- 製品バージョン: {info['product_version']}\n"
        f"- サポート終了日・方針: {info['support_end_date']}\n"
        f"- 配布範囲: {info['distribution_scope']}\n"
    )
    (destination / "DISTRIBUTOR_DISCLOSURE_JA.md").write_text(
        disclosure, encoding="utf-8", newline="\n"
    )
    return {
        "distribution_scope": info["distribution_scope"],
        "publisher_legal_name": info["publisher_legal_name"],
        "counsel_review_completed": bool(info.get("counsel_review_completed")),
        "documents": [*templates, "DISTRIBUTOR_DISCLOSURE_JA.md"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate private publisher data and render release-ready legal documents."
    )
    parser.add_argument("--info", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.info.resolve(), args.destination.resolve())
    except ReleaseComplianceError as exc:
        print(f"Commercial release compliance failed: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
