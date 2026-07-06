from __future__ import annotations

import tempfile
from pathlib import Path

from faster_whisper.audio import decode_audio

from scripts.benchmark_hotel import synthesize_wav
from translator_app.config import load_config
from translator_app.stt import WhisperRecognizer


CASES = (
    ("en", "en", "Could you send two extra towels to my room?"),
    ("en", "ja", "追加のタオルをお部屋までお届けします。"),
    ("ko", "ko", "객실로 수건 두 장 더 보내 주세요."),
    ("ko", "ja", "追加のタオルをお部屋までお届けします。"),
)


def main() -> None:
    cfg = load_config()
    recognizer = WhisperRecognizer(cfg.stt, lambda phase, message: print(phase, message))
    recognizer.load()
    failures = []
    with tempfile.TemporaryDirectory(prefix="remoteplus-modes-") as temp:
        for selected, spoken, text in CASES:
            path = Path(temp) / f"{selected}-{spoken}.wav"
            if not synthesize_wav(text, spoken, path):
                raise RuntimeError(f"No Windows voice for {spoken}")
            recognizer.set_selected_language(selected)
            result = recognizer.transcribe(decode_audio(str(path), sampling_rate=16000))
            ok = result.language == spoken
            print(selected, spoken, result.language, round(result.probability, 3), result.text, ok)
            if not ok:
                failures.append((selected, spoken, result.language))
    if failures:
        raise SystemExit(f"Language mode failures: {failures}")
    print("SUMMARY 4/4 language routes passed")


if __name__ == "__main__":
    main()
