from __future__ import annotations

import json
import os
import re
import tempfile
import time
from difflib import SequenceMatcher
from pathlib import Path

from faster_whisper.audio import decode_audio

from translator_app.config import load_config
from translator_app.stt import WhisperRecognizer
from translator_app.translation import M2M100Translator
from translator_app.tts import SapiSpeaker

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "benchmarks" / "hotel_sentences.json"


def normalized(text: str) -> str:
    return re.sub(r"[^\w]+", "", text, flags=re.UNICODE).lower()


def similarity(expected: str, actual: str) -> float:
    return SequenceMatcher(None, normalized(expected), normalized(actual)).ratio()


def sapi_voice_for(language: str):
    import win32com.client

    from translator_app.languages import get_language

    item = get_language(language)
    wanted = {value.lower().lstrip("0") for value in (item.sapi_lcids or ())}
    speaker = win32com.client.Dispatch("SAPI.SpVoice")
    for voice in speaker.GetVoices():
        if str(voice.GetAttribute("Language")).lower().lstrip("0") in wanted:
            return speaker, voice
    return speaker, None


def synthesize_wav(text: str, language: str, path: Path) -> bool:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        speaker, voice = sapi_voice_for(language)
        if voice is None:
            return False
        stream = win32com.client.Dispatch("SAPI.SpFileStream")
        stream.Open(str(path), 3, False)
        speaker.Voice = voice
        speaker.AudioOutputStream = stream
        speaker.Speak(text)
        stream.Close()
        del stream, voice, speaker
        return True
    finally:
        pythoncom.CoUninitialize()


def run_stt(corpus: dict, cfg) -> list[dict]:
    recognizer = WhisperRecognizer(cfg.stt, lambda p, m: print(f"[STT:{p}] {m}"))
    recognizer.load()
    rows = []
    with tempfile.TemporaryDirectory(prefix="local-bridge-hotel-") as temp:
        for item in corpus["stt"]:
            wav = Path(temp) / f"{item['id']}.wav"
            if not synthesize_wav(item["text"], item["language"], wav):
                rows.append({**item, "status": "voice-not-installed"})
                continue
            recognizer.set_context_language(item["language"])
            audio = decode_audio(str(wav), sampling_rate=cfg.audio.sample_rate)
            started = time.perf_counter()
            result = recognizer.transcribe(audio)
            rows.append(
                {
                    **item,
                    "status": "ok",
                    "recognized": result.text,
                    "detected_language": result.language,
                    "language_probability": round(result.probability, 3),
                    "similarity": round(similarity(item["text"], result.text), 3),
                    "seconds": round(time.perf_counter() - started, 2),
                }
            )
            print(f"{item['id']} {rows[-1]['similarity']:.3f} | {result.text}")
    return rows


def run_translation(corpus: dict, cfg) -> list[dict]:
    translator = M2M100Translator(cfg.translation, lambda p, m: print(f"[MT:{p}] {m}"))
    translator.load()
    rows = []
    for item in corpus["translation"]:
        started = time.perf_counter()
        translated = translator.translate(item["text"], item["language"], "ja")
        hits = [term for term in item["expected_ja"] if term in translated]
        row = {
            **item,
            "translated": translated,
            "term_recall": round(len(hits) / len(item["expected_ja"]), 3),
            "matched_terms": hits,
            "seconds": round(time.perf_counter() - started, 2),
        }
        rows.append(row)
        print(f"{item['id']} terms={row['term_recall']:.3f} | {translated}")
    return rows


def main() -> None:
    cfg = load_config()
    os.chdir(cfg.data_root)
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    print("Installed voices:", [voice["name"] for voice in SapiSpeaker.installed_voices()])
    stt_rows = run_stt(corpus, cfg)
    translation_rows = run_translation(corpus, cfg)
    completed = [row for row in stt_rows if row["status"] == "ok"]
    summary = {
        "stt_samples": len(completed),
        "stt_average_similarity": round(
            sum(row["similarity"] for row in completed) / len(completed), 3
        ),
        "stt_below_090": [row["id"] for row in completed if row["similarity"] < 0.9],
        "translation_samples": len(translation_rows),
        "translation_term_recall": round(
            sum(row["term_recall"] for row in translation_rows) / len(translation_rows), 3
        ),
        "translation_failed_terms": [
            row["id"] for row in translation_rows if row["term_recall"] < 1
        ],
    }
    report = {"summary": summary, "stt": stt_rows, "translation": translation_rows}
    output = ROOT / "benchmarks" / "latest_hotel_report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("SUMMARY", json.dumps(summary, ensure_ascii=False))
    print("REPORT", output)


if __name__ == "__main__":
    main()
