from __future__ import annotations

import json
import os
import time
from pathlib import Path

from transformers import MarianMTModel, MarianTokenizer

from translator_app.config import load_config
from translator_app.translation import M2M100Translator, protect_multilingual_terms

ROOT = Path(__file__).resolve().parent.parent


def score(text: str, groups: list[list[str]]) -> tuple[float, list[list[str]]]:
    folded = text.casefold()
    missed = [group for group in groups if not any(term.casefold() in folded for term in group)]
    return (len(groups) - len(missed)) / len(groups), missed


def main() -> None:
    cfg = load_config()
    os.chdir(cfg.data_root)
    opus_name = "Helsinki-NLP/opus-mt-ja-en"
    tokenizer = MarianTokenizer.from_pretrained(opus_name, cache_dir="models/huggingface")
    opus = MarianMTModel.from_pretrained(opus_name, cache_dir="models/huggingface")
    m2m = M2M100Translator(cfg.translation, lambda phase, message: print(phase, message))
    m2m.load()
    corpus = json.loads(
        (ROOT / "benchmarks/hotel_translation_extended.json").read_text(encoding="utf-8")
    )
    rows = []
    total_started = time.perf_counter()
    for item in (row for row in corpus if row["id"].startswith("r-")):
        inputs = tokenizer(item["text"], return_tensors="pt")
        english = tokenizer.decode(
            opus.generate(**inputs, max_new_tokens=128)[0], skip_special_tokens=True
        )
        if item["target"] == "en":
            translated = english
        else:
            translated = m2m.translate(english, "en", item["target"])
        translated = protect_multilingual_terms(
            item["text"],
            translated,
            "ja",
            item["target"],
            cfg.translation.protected_terms,
        )
        term_score, missed = score(translated, item["expected_any"])
        rows.append({**item, "english": english, "translated": translated, "score": term_score})
        print(item["id"], round(term_score, 3), "|", english, "=>", translated, missed)
    summary = {
        "score": round(sum(row["score"] for row in rows) / len(rows), 3),
        "average_seconds": round((time.perf_counter() - total_started) / len(rows), 3),
    }
    output = ROOT / "benchmarks/latest_hybrid_reverse_report.json"
    output.write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("SUMMARY", summary)


if __name__ == "__main__":
    main()
