from __future__ import annotations

import json
import time
from pathlib import Path

from translator_app.config import load_config
from translator_app.hymt2 import create_translator

ROOT = Path(__file__).resolve().parent.parent
CORPORA = (
    ROOT / "benchmarks/hotel_translation_extended.json",
    ROOT / "benchmarks/hotel_translation_holdout.json",
    ROOT / "benchmarks/hotel_translation_validation.json",
)
REPORT = ROOT / "benchmarks/latest_product_validation_report.json"


def score(text: str, groups: list[list[str]]) -> tuple[float, list[list[str]]]:
    folded = text.casefold()
    missed = [group for group in groups if not any(term.casefold() in folded for term in group)]
    return (len(groups) - len(missed)) / len(groups), missed


def main() -> int:
    """Run every hotel corpus through the same translator used by the app."""
    cfg = load_config()
    translator = create_translator(
        cfg.translation,
        lambda phase, message: print(phase, message, flush=True),
    )
    rows = []
    try:
        translator.load()
        translator.warmup()
        for corpus_path in CORPORA:
            corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
            for item in corpus:
                started = time.perf_counter()
                translated = translator.translate(
                    item["text"], item["source"], item["target"]
                )
                term_score, missed = score(translated, item["expected_any"])
                row = {
                    **item,
                    "corpus": corpus_path.stem,
                    "translated": translated,
                    "score": round(term_score, 3),
                    "missed": missed,
                    "seconds": round(time.perf_counter() - started, 3),
                }
                rows.append(row)
                print(
                    f"{item['id']} {term_score:.3f} {row['seconds']:.2f}s | {translated}",
                    flush=True,
                )
    finally:
        translator.close()

    forward = [row for row in rows if row["source"] != "ja"]
    reverse = [row for row in rows if row["source"] == "ja"]
    summary = {
        "samples": len(rows),
        "forward_score": round(sum(row["score"] for row in forward) / len(forward), 3),
        "reverse_score": round(sum(row["score"] for row in reverse) / len(reverse), 3),
        "failed": [row["id"] for row in rows if row["score"] < 1],
    }
    REPORT.write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("SUMMARY", json.dumps(summary, ensure_ascii=False), flush=True)
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
