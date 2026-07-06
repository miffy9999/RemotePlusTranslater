from __future__ import annotations

import os
import time

from translator_app.config import load_config
from translator_app.translation import M2M100Translator


SAMPLES = [
    ("en", "I would like to change the delivery address."),
    ("ko", "배송 주소를 변경하고 싶습니다."),
    ("es", "Quisiera cambiar la dirección de entrega."),
    ("zh", "我想更改送货地址。"),
]
JAPANESE_REPLY = "新しい住所を教えてください。"


def main() -> None:
    cfg = load_config()
    os.chdir(cfg.data_root)
    translator = M2M100Translator(cfg.translation, lambda p, m: print(f"[{p}] {m}"))
    started = time.perf_counter()
    translator.load()
    print(f"LOAD {time.perf_counter() - started:.2f}s")
    for language, text in SAMPLES:
        started = time.perf_counter()
        japanese = translator.translate(text, language, "ja")
        incoming_seconds = time.perf_counter() - started
        started = time.perf_counter()
        reply = translator.translate(JAPANESE_REPLY, "ja", language)
        reply_seconds = time.perf_counter() - started
        print(f"{language}>ja {incoming_seconds:.2f}s | {japanese}")
        print(f"ja>{language} {reply_seconds:.2f}s | {reply}")


if __name__ == "__main__":
    main()
