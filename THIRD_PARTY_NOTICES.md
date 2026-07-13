# Third-party notices — RemotePlus Translator 0.6.0

RemotePlus Translator source code is distributed under the MIT License. Commercial use is
permitted, but every distributor must ship this notice, the generated `licenses` directory,
the model receipts, and `sbom.cdx.json` with the application.

## Core software and runtime

| Component | Pinned version/artifact | License |
|---|---|---|
| faster-whisper | 1.2.1 | MIT |
| CTranslate2 | dependency of faster-whisper | MIT |
| Whisper small model | `openai/whisper-small` compatible artifact | Apache-2.0 model card |
| Tencent Hy-MT2 GGUF | `Hy-MT2-1.8B-Q4_K_M.gguf` | Apache-2.0 |
| llama.cpp | bundled `llama-server` runtime | MIT |
| sherpa-onnx / sherpa-onnx-core | 1.13.4 | Apache-2.0 |
| pygame | 2.6.1 | LGPL-2.1-or-later |
| FastAPI / Starlette / Uvicorn | pinned in `pyproject.toml` | MIT/BSD-family; see generated licenses |
| NumPy, SoundDevice, SoundCard, PyWin32 | pinned in `pyproject.toml` | see generated licenses |

`edge-tts` and the Microsoft Edge Read Aloud service are not part of the commercial profile.
No call text is sent to Microsoft for speech synthesis.

## Local TTS model packs

| Pack | Languages | Model/data terms |
|---|---|---|
| Supertonic 3 INT8 | 31 languages including en/ko/ja/es | Model: BigScience OpenRAIL-M; sample/runtime code: MIT |
| Kokoro `v1.1-zh` | Mandarin Chinese | Apache-2.0; Chinese data described by the publisher as permissively granted |

The installer pins each reviewed archive URL and SHA-256 in `translator_app/tts_packs.py`.
Each installed pack contains a receipt, file hash inventory, model card, and applicable license.
Supertonic OpenRAIL-M restrictions must remain enforceable in the distributor's EULA. In
particular, the app must disclose machine-generated output, prohibit impersonation and harmful
uses, and must not make adverse legally binding decisions without human review.

Primary references:

- https://github.com/SYSTRAN/faster-whisper
- https://github.com/OpenNMT/CTranslate2
- https://huggingface.co/openai/whisper-small
- https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF
- https://github.com/ggml-org/llama.cpp
- https://github.com/k2-fsa/sherpa-onnx
- https://huggingface.co/Supertone/supertonic-3
- https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh
- https://k2-fsa.github.io/sherpa/onnx/tts/all/Chinese-English/kokoro-multi-lang-v1_1.html

The generated machine-readable inventory is a build aid, not a substitute for final legal review.
