# Commercial release gate

`feature/commercial-local-tts` is technically prepared for a commercial pilot only when every
item below is satisfied. The build must fail rather than silently using an online TTS fallback.

- [x] Edge Read Aloud / `edge-tts` removed from dependencies and runtime
- [x] Local TTS archives pinned by HTTPS URL and SHA-256
- [x] Safe archive extraction and model file integrity receipt
- [x] No TTS when a reviewed pack is absent
- [x] AI translation/synthetic voice disclosure in the UI
- [x] Loopback-only web server
- [x] Unauthenticated side-by-side updater disabled by default
- [x] Bounded in-memory conversation history and explicit clear action
- [ ] Distributor identity and support terms completed in `EULA_JA.md`
- [ ] Japanese counsel approves the final EULA/privacy notice and hotel call script
- [ ] Authenticode certificate signs the desktop EXE, TTS worker EXE, installer and any updater
- [ ] Release SBOM and all license texts generated and reviewed
- [ ] Hotel operator documents access control, retention, deletion and incident response
- [ ] Human reconfirmation procedure trained for emergency, allergy, payment and booking changes
- [ ] 30–60 minute real call-device soak test passes on every supported PC class

An unchecked organizational/signing item cannot be solved automatically by source code and must
remain visible in the release approval record.
