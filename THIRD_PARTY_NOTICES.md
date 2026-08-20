# Third-party notices — RemotePlus Translator 0.8.5

RemotePlus Translator source code is distributed under the MIT License. Commercial use is
permitted subject to each bundled component and model license. Distributors must ship this
notice, the generated `licenses` directory, model receipts, and `sbom.cdx.json`.

## Core software and models

| Component | Pinned version/artifact | License |
|---|---|---|
| faster-whisper | 1.2.1 | MIT |
| CTranslate2 | 4.8.1 | MIT |
| Whisper small model | `openai/whisper-small` compatible artifact | Apache-2.0 model card |
| Tencent Hy-MT2 GGUF | `Hy-MT2-1.8B-Q4_K_M.gguf` | Apache-2.0 |
| llama.cpp | bundled `llama-server` runtime | MIT |
| pypinyin | 0.55.0 | MIT |
| AnyAscii | 0.3.3 | ISC |
| pywebview | 6.2.1 | BSD-3-Clause |
| Microsoft Edge WebView2 Runtime | Evergreen system runtime | Microsoft software terms |
| FastAPI / Starlette / Uvicorn | pinned in `pyproject.toml` | MIT/BSD-family |
| NumPy, SoundDevice, SoundCard, PyWin32 | pinned in `pyproject.toml` | generated licenses |

TTS runtimes, voice models, `edge-tts`, and Microsoft Edge Read Aloud are not included. Staff
reply text and customer call audio are processed locally by the normal application pipeline.

Primary references:

- https://github.com/SYSTRAN/faster-whisper
- https://huggingface.co/openai/whisper-small
- https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF
- https://github.com/ggml-org/llama.cpp
- https://pypi.org/project/pypinyin/
- https://pypi.org/project/anyascii/
- https://github.com/r0x0r/pywebview
- https://developer.microsoft.com/microsoft-edge/webview2/

The generated machine-readable inventory is a build aid, not a substitute for final legal review.
