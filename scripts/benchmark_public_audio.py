from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from faster_whisper.audio import decode_audio

from translator_app.config import load_config
from translator_app.stt import WhisperRecognizer

ROOT = Path(__file__).resolve().parent.parent
WAV_ROOT = ROOT / "benchmarks/public_audio/spoken-language-identification-test-wavs"
FILES = {
    "en": "en-english.wav",
    "ko": "ko-korean.wav",
    "zh": "zh-chinese.wav",
    "es": "es-spanish.wav",
}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config()
    os.chdir(cfg.data_root)
    recognizer = WhisperRecognizer(cfg.stt, lambda phase, message: print(phase, message))
    recognizer.load()
    rows = []
    for expected, filename in FILES.items():
        # Production uses one fixed customer language per call. Staff replies
        # are typed and therefore do not consume the STT model.
        mode = "customer"
        selected = expected
        recognizer.set_selected_language(selected)
        audio = decode_audio(str(WAV_ROOT / filename), sampling_rate=cfg.audio.sample_rate)
        result = recognizer.transcribe(audio, language=selected)
        text_present = bool(result.text.strip())
        row = {
            "mode": mode,
            "selected": selected,
            "expected": expected,
            "detected": result.language,
            "probability": round(result.probability, 3),
            "text": result.text,
            # This public corpus has language labels but no authoritative
            # transcripts. Treat it only as a packaged-model execution smoke
            # test; it must never be reported as STT accuracy/WER.
            "text_present": text_present,
            "smoke_passed": result.language == expected and text_present,
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    summary = {
        "test_type": "fixed_language_execution_smoke",
        "transcript_accuracy_evaluated": False,
        "samples": len(rows),
        "passed": sum(row["smoke_passed"] for row in rows),
        "failed": [
            f"{row['mode']}:{row['expected']}->{row['detected']}"
            for row in rows
            if not row["smoke_passed"]
        ],
    }
    output = ROOT / "benchmarks/latest_public_audio_report.json"
    output.write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("SUMMARY", json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
