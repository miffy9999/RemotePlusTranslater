from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = "http://127.0.0.1:8788/v1/chat/completions"
LANGUAGES = {
    "ja": "Japanese",
    "en": "English",
    "ko": "Korean",
    "zh": "Chinese",
    "es": "Spanish",
}
CORPORA = (
    ROOT / "benchmarks/hotel_translation_extended.json",
    ROOT / "benchmarks/hotel_translation_holdout.json",
    ROOT / "benchmarks/hotel_translation_validation.json",
)


def score(text: str, groups: list[list[str]]) -> tuple[float, list[list[str]]]:
    folded = text.casefold()
    missed = [group for group in groups if not any(term.casefold() in folded for term in group)]
    return (len(groups) - len(missed)) / len(groups), missed


def translate(text: str, target: str) -> str:
    prompt = (
        f"Translate the following text into {LANGUAGES[target]}. "
        "Note that you should only output the translated result without any "
        f"additional explanation:\n\n{text}"
    )
    body = json.dumps(
        {
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "top_p": 0.6,
            "top_k": 20,
            "repeat_penalty": 1.05,
            "max_tokens": 192,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        SERVER,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    return payload["choices"][0]["message"]["content"].strip()


def main() -> None:
    rows = []
    for corpus_path in CORPORA:
        corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
        for item in corpus:
            started = time.perf_counter()
            translated = translate(item["text"], item["target"])
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
            print(f"{item['id']} {term_score:.3f} {row['seconds']:.2f}s | {translated}", flush=True)
    groups = {}
    for corpus_path in CORPORA:
        name = corpus_path.stem
        selected = [row for row in rows if row["corpus"] == name]
        groups[name] = {
            "score": round(sum(row["score"] for row in selected) / len(selected), 3),
            "average_seconds": round(sum(row["seconds"] for row in selected) / len(selected), 3),
            "failed": [row["id"] for row in selected if row["score"] < 1],
        }
    summary = {
        "samples": len(rows),
        "score": round(sum(row["score"] for row in rows) / len(rows), 3),
        "average_seconds": round(sum(row["seconds"] for row in rows) / len(rows), 3),
        "corpora": groups,
    }
    output = ROOT / "benchmarks/latest_hymt2_report.json"
    output.write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("SUMMARY", json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
