from __future__ import annotations

import time

from transformers import MarianMTModel, MarianTokenizer


CASES = {
    "Helsinki-NLP/opus-mt-en-jap": [
        "Please arrange a wake-up call for six thirty.",
        "My passport is missing from the room safe.",
        "I have a severe peanut allergy.",
        "Is the airport shuttle wheelchair accessible?",
    ],
    "Helsinki-NLP/opus-mt-ja-en": [
        "追加のタオルを3枚お部屋へお届けします。",
        "ピーナッツアレルギーとして厨房に伝えます。",
        "レイトチェックアウトは午後2時まで可能です。",
        "空港シャトルは午前8時に出発します。",
    ],
}


def main() -> None:
    for name, texts in CASES.items():
        print("MODEL", name)
        tokenizer = MarianTokenizer.from_pretrained(name, cache_dir="models/huggingface")
        model = MarianMTModel.from_pretrained(name, cache_dir="models/huggingface")
        for text in texts:
            started = time.perf_counter()
            inputs = tokenizer(text, return_tensors="pt")
            output = model.generate(**inputs, max_new_tokens=128)
            translated = tokenizer.decode(output[0], skip_special_tokens=True)
            print(round(time.perf_counter() - started, 2), text, "=>", translated)


if __name__ == "__main__":
    main()
