# Local TTS packs (0.6.0)

The commercial profile does not use Microsoft Edge Read Aloud, Azure Speech, Windows SAPI,
or installed Windows language voices. `prepare_models.bat` installs reviewed ONNX model packs
under `%LOCALAPPDATA%\RemotePlusTranslator\models\tts` for a frozen build. Source runs use the
repository `models\tts` directory.

## Reviewed catalog

### `supertonic-3-int8`

- Engine: sherpa-onnx Supertonic
- Languages: en, ko, ja, es and 27 additional languages
- Model: BigScience OpenRAIL-M
- Runtime/sample code: MIT
- One shared INT8 pack, approximately 129 MB compressed
- Default: 2 CPU threads, 5 generation steps, speaker 0

The model license requires downstream use restrictions and intelligible disclosure of generated
output. Keep `MODEL-LICENSE.txt`, `pack-receipt.json`, `EULA_JA.md`, and the UI disclosure.

### `kokoro-v1.1-zh`

- Engine: sherpa-onnx Kokoro
- Language: Mandarin Chinese (`zh`)
- Model: `hexgrad/Kokoro-82M-v1.1-zh`, Apache-2.0
- The model card states that its Chinese speech data was permissively granted by LongMaoData
- 103 bundled speakers; the default is Mandarin female speaker ID 3
- FP32 ONNX build, approximately 365 MB compressed. The smaller INT8 build was rejected because
  it was substantially slower on the Intel i5-12450H QA machine (RTF 2.37 at four threads versus
  0.89 for FP32 in a cold comparative run).

The upstream Windows text frontend cannot reliably open every non-ASCII path. The application
validates the installed pack and stages the Chinese assets once under the ASCII ProgramData cache
before loading.

## Supply-chain controls

`translator_app/tts_packs.py` is the only catalog authority. A pack is accepted only when:

1. its ID exists in the compiled catalog;
2. the download uses the catalog HTTPS URL;
3. the full archive SHA-256 matches;
4. the downloaded byte count exactly matches the reviewed artifact size and cannot grow without bound;
5. the tar archive contains no absolute path, `..`, symlink, hardlink, or device entry;
6. the expected model root exists;
7. the separately downloaded model license hash matches where applicable;
8. a receipt containing every extracted model-file hash is written.

No arbitrary model URL is accepted from the browser, user settings, or `config.local.toml`.
At runtime a missing pack results in text-only translation. It never falls back to an online TTS.

## Adding a language/model

Before adding a catalog entry, retain evidence for the exact model revision, training-data terms,
commercial redistribution permission, model card, archive SHA-256, and upstream URL. Reject
non-commercial, research-only, unknown-license, impersonation-focused, or unclear voice-clone
artifacts. Add multilingual hotel sentences and a real WAV smoke test before release.

## Reviewed but rejected

- `wuxuedaifu/supertonic_cn` (`v0.1.0-preview`, reviewed 2026-07-13): code is MIT,
  but the public/gated weights are evaluation-only and non-commercial because the training data
  includes Baker/CSMSC. Its author offers a separate Baker-free commercial build, so the public
  artifact must not be downloaded or redistributed by this application. It may be used only as a
  quality/normalization benchmark reference unless a separate written commercial license and exact
  artifact hash are obtained.
- Piper `zh_CN-chaowen-medium` (reviewed 2026-07-13): rejected even though the repository is
  labeled MIT and its immediate dataset is CC0. Its model card says it was fine-tuned from the
  Xiao Ya voice, whose BZNSYP/DataBaker model card permits non-commercial use only. A downstream
  fine-tune does not erase that restriction.
