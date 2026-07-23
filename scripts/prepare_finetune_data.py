from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "finetune/hotel_en_ko_seed.json"
OUTPUT = ROOT / "cache/finetune"
ALLOWED_LANGUAGES = {"ja", "ko", "en"}
ALLOWED_SPLITS = {"train", "holdout"}
SENSITIVE_PATTERNS = (
    re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
    re.compile(r"\b\d{3}-\d{3,4}-\d{4}\b"),
    re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
)


def _prompt(item: dict[str, str]) -> str:
    source = item["source"]
    target = item["target"]
    language_names = {"ja": "Japanese", "ko": "Korean", "en": "English"}
    if item.get("previous") or item.get("next"):
        lines = [
            f"Translate only CURRENT from {language_names[source]} into natural "
            f"{language_names[target]} for a hotel conversation.",
        ]
        if item.get("previous"):
            lines.append(f"PREVIOUS: {item['previous']}")
        if item.get("next"):
            lines.append(f"NEXT: {item['next']}")
        lines.append(f"CURRENT: {item['current']}")
        return "\n".join(lines)
    return (
        f"Translate the following text into natural {language_names[target]} for a hotel "
        f"conversation. Output only the translation:\n\n{item['current']}"
    )


def validate(items: list[dict[str, str]]) -> Counter:
    if not items:
        raise ValueError("Fine-tuning seed is empty")
    ids: set[str] = set()
    prompts: dict[str, set[str]] = {split: set() for split in ALLOWED_SPLITS}
    counts: Counter = Counter()
    for index, item in enumerate(items, start=1):
        required = {"id", "split", "category", "source", "target", "current", "translation"}
        missing = required - item.keys()
        if missing:
            raise ValueError(f"Row {index} is missing: {sorted(missing)}")
        if item["id"] in ids:
            raise ValueError(f"Duplicate id: {item['id']}")
        ids.add(item["id"])
        if item["split"] not in ALLOWED_SPLITS:
            raise ValueError(f"Invalid split: {item['id']}")
        if {item["source"], item["target"]} - ALLOWED_LANGUAGES:
            raise ValueError(f"Unsupported language: {item['id']}")
        if item["source"] == item["target"]:
            raise ValueError(f"Source and target are identical: {item['id']}")
        fields = ("current", "translation", "previous", "next")
        combined = " ".join(item.get(field, "") for field in fields)
        if any(pattern.search(combined) for pattern in SENSITIVE_PATTERNS):
            raise ValueError(f"Possible personal data in: {item['id']}")
        normalized_text = re.sub(r"\s+", " ", item["current"].strip()).casefold()
        normalized = f"{item['source']}->{item['target']}:{normalized_text}"
        if normalized in prompts[item["split"]]:
            raise ValueError(f"Duplicate prompt inside {item['split']}: {item['id']}")
        prompts[item["split"]].add(normalized)
        counts[(item["split"], item["source"], item["target"])] += 1
        counts[item["split"]] += 1
    overlap = prompts["train"] & prompts["holdout"]
    if overlap:
        raise ValueError("Train/holdout prompt leakage detected")
    if counts["holdout"] < 8:
        raise ValueError("At least eight holdout rows are required")
    if counts[("train", "ko", "ja")] < 8 or counts[("train", "en", "ja")] < 8:
        raise ValueError("English and Korean forward training coverage is insufficient")
    if counts[("train", "ja", "ko")] < 8 or counts[("train", "ja", "en")] < 8:
        raise ValueError("English and Korean reverse training coverage is insufficient")
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and render Hy-MT2 hotel LoRA data")
    parser.add_argument("--seed", type=Path, default=SEED)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    items = json.loads(args.seed.read_text(encoding="utf-8"))
    counts = validate(items)
    args.output.mkdir(parents=True, exist_ok=True)
    for split in sorted(ALLOWED_SPLITS):
        output_path = args.output / f"hotel_{split}.jsonl"
        with output_path.open("w", encoding="utf-8", newline="\n") as handle:
            for item in items:
                if item["split"] != split:
                    continue
                record = {
                    "messages": [
                        {"role": "user", "content": _prompt(item)},
                        {"role": "assistant", "content": item["translation"]},
                    ],
                    "metadata": {
                        "id": item["id"],
                        "category": item["category"],
                        "source": item["source"],
                        "target": item["target"],
                    },
                }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    summary = {
        "train": counts["train"],
        "holdout": counts["holdout"],
        "train_ko_to_ja": counts[("train", "ko", "ja")],
        "train_en_to_ja": counts[("train", "en", "ja")],
        "train_ja_to_ko": counts[("train", "ja", "ko")],
        "train_ja_to_en": counts[("train", "ja", "en")],
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
