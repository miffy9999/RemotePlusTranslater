from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from translator_app.config import load_config
from translator_app.hymt2 import create_translator

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "benchmarks" / "hotel_translation_extended.json"
REPORT = ROOT / "benchmarks" / "latest_translation_extended_report.json"


def score(text: str, groups: list[list[str]]) -> tuple[float, list[list[str]]]:
    folded = text.casefold()
    missed = [group for group in groups if not any(term.casefold() in folded for term in group)]
    return (len(groups) - len(missed)) / len(groups), missed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()
    cfg = load_config()
    os.chdir(cfg.data_root)
    translator = create_translator(cfg.translation, lambda phase, msg: print(phase, msg))
    translator.load()
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    rows = []
    for item in corpus:
        started = time.perf_counter()
        translated = translator.translate(item["text"], item["source"], item["target"])
        term_score, missed = score(translated, item["expected_any"])
        row = {
            **item,
            "translated": translated,
            "score": round(term_score, 3),
            "missed": missed,
            "seconds": round(time.perf_counter() - started, 3),
        }
        rows.append(row)
        print(f"{item['id']} {term_score:.3f} | {translated}")
    directions = {}
    for prefix in ("f", "r"):
        selected = [row for row in rows if row["id"].startswith(prefix + "-")]
        directions[prefix] = round(sum(row["score"] for row in selected) / len(selected), 3)
    summary = {
        "samples": len(rows),
        "forward_score": directions["f"],
        "reverse_score": directions["r"],
        "failed": [row["id"] for row in rows if row["score"] < 1],
    }
    args.report.write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("SUMMARY", json.dumps(summary, ensure_ascii=False))
    if hasattr(translator, "close"):
        translator.close()


if __name__ == "__main__":
    main()
