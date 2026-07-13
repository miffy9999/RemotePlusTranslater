from __future__ import annotations

import argparse
import json
import threading
import time
import wave
from pathlib import Path

from translator_app.config import load_config
from translator_app.tts import LocalTtsEngine, SpeechRequest


SAMPLES = {
    "en": "Thank you for calling. Your room service order will arrive in about twenty minutes.",
    "ko": "전화해 주셔서 감사합니다. 룸서비스 주문은 약 이십 분 후에 도착합니다.",
    "es": "Gracias por llamar. Su pedido de servicio a la habitación llegará en unos veinte minutos.",
    "zh": "感谢您的来电。您的客房送餐服务将在大约二十分钟后送达。",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("cache/tts-smoke"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    engine = LocalTtsEngine(load_config().tts, threading.Event())
    results = []
    for request_id, (language, text) in enumerate(SAMPLES.items(), 1):
        target = args.output / f"{language}.wav"
        started = time.perf_counter()
        pack_id = engine.synthesize(SpeechRequest(request_id, text, language, 0.0), target)
        elapsed = time.perf_counter() - started
        with wave.open(str(target), "rb") as audio:
            duration = audio.getnframes() / audio.getframerate()
            sample_rate = audio.getframerate()
        result = {
            "language": language,
            "pack": pack_id,
            "synthesis_seconds": round(elapsed, 3),
            "audio_seconds": round(duration, 3),
            "real_time_factor": round(elapsed / duration, 3),
            "sample_rate": sample_rate,
            "bytes": target.stat().st_size,
        }
        if duration < 0.5 or elapsed / duration >= 1.0:
            raise RuntimeError(f"Local TTS smoke failed: {result}")
        results.append(result)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
