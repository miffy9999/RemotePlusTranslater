from __future__ import annotations

import time
from pathlib import Path

from llama_cpp import Llama


CASES = (
    ("Japanese", "I'd like two colas and one ginger ale."),
    ("Japanese", "I have a severe peanut allergy."),
    ("Japanese", "¿Puedo salir más tarde, a las dos de la tarde?"),
    ("Korean", "レイトチェックアウトは午後2時まで可能です。"),
    ("Chinese", "ピーナッツアレルギーとして厨房に伝えます。"),
    ("Spanish", "空港シャトルは午前8時に出発します。"),
)


def main() -> None:
    model_path = Path("models/hymt2/Hy-MT2-1.8B-Q4_K_M.gguf")
    llm = Llama(model_path=str(model_path), n_ctx=1024, n_threads=8, verbose=False)
    for language, text in CASES:
        prompt = (
            f"Translate the following text into {language}. "
            "Note that you should only output the translated result without any "
            f"additional explanation:\n\n{text}"
        )
        started = time.perf_counter()
        output = llm.create_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            top_p=0.6,
            top_k=20,
            repeat_penalty=1.05,
            max_tokens=160,
        )
        result = output["choices"][0]["message"]["content"]
        print(round(time.perf_counter() - started, 3), language, text, "=>", result)


if __name__ == "__main__":
    main()
