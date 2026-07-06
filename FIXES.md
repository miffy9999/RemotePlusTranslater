# FIXES.md — 수정 작업 지시서

> 2026-07-04 코드 전수 검토 결과. 다른 AI/개발자가 이 문서만 보고 작업할 수 있도록 파일·라인·수정 방법을 명시함.
> 우선순위: P0(즉시) → P1(높음) → P2(중간) → P3(참고).
> 수정 후 `.venv\Scripts\python.exe -m pytest` 와 `-m ruff check .` 통과 확인할 것.

---

## P0 — 보안·개인정보 (즉시 수정)

### 1. API·WebSocket 무인증 → 대화 내용 유출 가능
- **파일**: `translator_app/server.py`
- **문제**: WebSocket은 CORS 보호를 받지 않으므로 브라우저의 임의 웹사이트가 `ws://127.0.0.1:8765/ws`에 접속해 고객 대화 원문·번역 기록 전체를 실시간 수신할 수 있다. REST API도 동일하게 무인증. DNS rebinding에도 취약.
- **수정**:
  1. 앱 시작 시 `secrets.token_urlsafe(32)`로 세션 토큰 생성.
  2. 모든 `/api/*` 요청과 `/ws` 핸드셰이크에서 토큰 검증(헤더 `X-Auth-Token` 또는 쿠키). 프론트에는 `/` 응답 시 토큰을 주입(예: 인덱스 HTML 템릿에 삽입하거나 `Set-Cookie: SameSite=Strict`).
  3. `Host` 헤더가 `127.0.0.1:{port}` 또는 `localhost:{port}`가 아니면 403 (DNS rebinding 차단). WebSocket에서는 `Origin` 헤더도 동일하게 검증.
- **프론트 연동**: `translator_app/web/app.js`의 모든 `fetch()`와 `new WebSocket()`에 토큰 전달 로직 추가.

### 2. CSRF — 관리자 권한 PowerShell 실행 트리거 포함
- **파일**: `translator_app/server.py:158-181` (`/api/install-voices`), 그 외 `/api/control`, `DELETE /api/history`, `DELETE /api/feedback`, `/api/voice-settings`
- **문제**: 외부 웹페이지가 POST/DELETE를 위조 가능. 특히 `install-voices`는 `ShellExecuteW(..., "runas", powershell, ...)`로 UAC 승격 PowerShell을 실행시킨다.
- **수정**: 1번의 토큰 검증으로 함께 해결됨. 단, `install-voices`는 추가로 프론트에서 사용자 확인(confirm) 후에만 호출하도록 유지.

### 3. llama.cpp 런타임 다운로드 무결성 검증 없음
- **파일**: `translator_app/hymt2.py:51-78` (`LLAMA_RUNTIME_URL`, `prepare_hymt2_files`)
- **문제**: GitHub에서 zip을 받아 체크섬 확인 없이 `extractall`.
- **수정**: 릴리스 zip의 SHA-256을 상수로 고정(`LLAMA_RUNTIME_SHA256 = "..."`)하고 다운로드 후 해시 불일치 시 삭제·예외. Hy-MT2 GGUF도 가능하면 동일 처리.

### 4. host=0.0.0.0 설정 시 무경고 전체 노출
- **파일**: `translator_app/config.py` (`validate_config`)
- **수정**: `server.host`가 `127.0.0.1`/`localhost`가 아니면 경고 로그 출력 + 1번 토큰 인증이 없으면 기동 거부.

---

## P1 — 기능 버그 (높음)

### 5. m2m100 백엔드 ImportError (의존성 누락)
- **파일**: `pyproject.toml`, `translator_app/translation.py`, `translator_app/config.py:56`
- **문제**: `M2M100Translator`가 `transformers`·`torch`를 import하지만 의존성에 없고 .venv에도 미설치. 코드 기본값이 `backend="m2m100"`이라 config.toml에서 `[translation]` 섹션이 빠지면 즉시 크래시.
- **수정** (둘 중 택1):
  - A안(권장): `TranslationConfig.backend` 기본값을 `"hymt2"`로 변경하고, m2m100 선택 시 `transformers`/`torch` import 실패를 잡아 "pip install transformers torch 필요"라는 명확한 에러 메시지 출력. pyproject에 `m2m100 = ["transformers==4.x", "torch==2.x"]` optional-dependencies 추가.
  - B안: transformers/torch를 정식 의존성으로 추가(설치 용량 급증하므로 비권장).

### 6. 일본어 교정 부분 문자열 오염 ("コラボ"→"コーラボ")
- **파일**: `translator_app/translation.py:12-19, 33-34` (`JAPANESE_TERM_CORRECTIONS`)
- **문제**: `str.replace` 단순 치환이라 다른 단어 내부를 오염시킴.
- **수정**: 정규식으로 앞뒤가 가타카나가 아닌 경우에만 치환. 예:
  ```python
  pattern = re.compile(rf"(?<![ァ-ヺー]){re.escape(wrong)}(?![ァ-ヺー])")
  result = pattern.sub(correct, result)
  ```
  특히 `"コラ"` 같은 짧은 키는 위 경계 조건 필수.

### 7. WebSocket 재연결 시 번역 카드 중복 표시
- **파일**: `translator_app/web/app.js:34` (`snapshot`), `:47` (`connect`)
- **문제**: 재연결 때 snapshot이 history를 다시 `add()`하는데 feed를 비우지 않음.
- **수정**: `snapshot()` 시작부에서 `feed.replaceChildren(empty)` 후 history를 렌더링.

### 8. 10초 폴링이 사용 중인 입력 장치를 강제 리셋
- **파일**: `translator_app/web/app.js:27` (`loadDevices`), `:48`
- **문제**: 장치 열거가 일시적으로 실패하거나 장치가 잠깐 안 보이면 `input_device`를 default로 리셋 → 통화 중 캡처 재시작.
- **수정**: 연속 2회 이상(예: 20초 이상) 목록에 없을 때만 리셋. 또는 리셋 전 toast로 알리고 서버 측 판단(캡처 스레드가 이미 에러 상태인지)과 결합.

### 9. 잘못된 장치 문자열 → 무한 에러 루프·토스트 스팸
- **파일**: `translator_app/config.py:161-162` (`sounddevice_value`), `translator_app/audio.py:173-183` (`AudioCapture.run`)
- **문제**: `int()` 변환 실패 시 캡처 스레드가 2초 간격 무한 재시도하며 매번 에러 상태 발행.
- **수정**:
  1. `sounddevice_value`에서 변환 실패 시 명확한 `ValueError("audio.input_device must be a device number, 'default', or 'loopback:...'")`.
  2. `/api/control`의 `input_device` 값을 적용 전에 검증(숫자, `default`, `loopback:` 프리픽스만 허용)하고 잘못되면 400 반환.
  3. 캡처 재시도 실패가 연속 N회(예: 5회)면 재시도 간격을 지수적으로 늘리고 상태를 한 번만 발행.

### 10. SAPI 다중 LCID(`"411;9"`) 미처리
- **파일**: `translator_app/tts.py:71-73` (`voice_status`), `:96-99` (`_select_voice`)
- **문제**: `Language` 속성이 세미콜론으로 복수 LCID를 반환하면 통째로 비교해 매칭 실패 → 설치된 음성을 "없음"으로 오판.
- **수정**: 비교 전 `str(...).lower().split(";")`로 분리하고 각 조각에 `lstrip("0")` 적용 후 집합 매칭.

### 11. TTS 출력 장치 매칭이 형식 불일치로 조용히 실패
- **파일**: `translator_app/tts.py:106-120` (`_select_output`), `translator_app/audio.py:291-296`
- **문제**: SoundCard의 WASAPI 장치 ID(`{0.0.0.00000000}.{guid}` 형식)와 SAPI 토큰 Id를 `endswith`로 매칭 — 실패하면 소리 없이 기본 장치 폴백.
- **수정**: GUID 부분만 추출해 비교(`re.search(r"\{[0-9a-f-]{36}\}", id, re.I)` 마지막 GUID끼리 비교). 매칭 실패 시 warning 발행은 유지.

### 12. 자동 감지가 enabled 밖 언어를 강제 배정
- **파일**: `translator_app/stt.py:106-111`
- **문제**: 실제 언어(예: 프랑스어)가 후보에 없으면 확률이 아무리 낮아도 en/ko/zh/es 중 최대값으로 강제 지정.
- **수정**: 선택된 최대 확률이 임계값(예: 0.35) 미만이면 강제하지 말고 Whisper 자체 감지에 맡기거나, `Recognition.probability`를 그대로 낮게 반환해 `_resolve_language`의 저확률 보정을 타게 함. 저확률 강제 배정 시 warning 이벤트 발행.

### 13. 수동 언어 고정 시 일본어 답변이 고객 발화로 뒤집힘
- **파일**: `translator_app/conversation.py:137-140` (`_resolve_language`)
- **문제**: `lock != "auto"`이고 일본어 감지 확률이 0.5 미만이면 lock 언어로 처리되어 번역 방향이 반전.
- **수정**: `stt.py`의 kana 휴리스틱(`contains_japanese_kana`)을 `_resolve_language`에서도 활용 — 텍스트에 가나가 2자 이상이면 확률과 무관하게 `ja` 반환.

### 14. WebSocket 종료 후 스레드 잔류
- **파일**: `translator_app/server.py:183-195`
- **문제**: 클라이언트가 끊겨도 `asyncio.to_thread(subscriber.get)`이 다음 이벤트 발행까지 블록.
- **수정**: `subscriber.get(timeout=1.0)`을 루프에서 사용하고 `queue.Empty`면 `websocket.send_json({"type":"ping"})` 등으로 연결 생존 확인 후 계속. 끊긴 연결은 send에서 예외로 정리됨.

### 15. HyMT2 번역 1건이 대화 루프를 최대 45초 블록 + 종료 경쟁
- **파일**: `translator_app/hymt2.py:181-240`
- **수정**:
  1. `_request` 타임아웃을 별도 설정(예: `hymt2_request_timeout_seconds = 15`)으로 분리 — 45초는 서버 기동용으로만 사용.
  2. `load()`/`close()`/`translate()`가 `self._lock`(또는 별도 lifecycle lock)을 공유하도록 정리해 stop 중 translate 경쟁 제거.

---

## P2 — 운영·배포 (중간)

### 16. .gitignore 누락 항목
- **파일**: `.gitignore`
- **추가할 항목**:
  ```
  dist/
  build/
  *.egg-info/
  feedback/
  user-settings.json
  benchmarks/results/
  ```
- 이미 커밋된 `user-settings.json`(루트)과 `local_conversation_translator.egg-info/`는 저장소에서 제거(`git rm --cached`).

### 17. dist 산출물 불일치 (구명칭 LocalBridge)
- **문제**: README는 `dist\RemotePlusTranslator\RemotePlusTranslator.exe`를 안내하지만 실제 dist에는 구명칭 `LocalBridge` 빌드만 존재. 내부 `_internal\config.toml`도 구버전 가능성.
- **수정**: 구 dist 삭제, PyInstaller `.spec` 파일을 저장소에 추가(이름 `RemotePlusTranslator`, `translator_app/web` 및 `config.toml` 포함)하고 빌드 절차를 README에 명시.

### 18. 데이터 쓰기 위치가 설치 폴더
- **파일**: `translator_app/config.py:11-22`, `settings.py`, `feedback.py`
- **문제**: `user-settings.json`, `feedback/`, `models/`가 기본적으로 ROOT(설치 폴더)에 쓰임 → Program Files 등 읽기 전용 위치에서 실패. 환경변수도 구명칭 `LOCAL_BRIDGE_DATA_DIR`.
- **수정**: frozen 모드 기본 data_root를 `%LOCALAPPDATA%\RemotePlusTranslator`로 변경(모델은 용량 문제로 exe 옆 유지 가능하되 쓰기 실패 시 폴백). 환경변수명 `REMOTEPLUS_DATA_DIR`로 교체(구명칭도 당분간 인식).

### 19. 모델 경로 CWD 의존
- **파일**: `translator_app/stt.py:74` (`download_root="models/whisper"`), `translation.py:89,93,131`, `hymt2.py:137-138`
- **문제**: 전부 상대경로라 `os.chdir(data_root)` 전제. `create_app`을 직접 실행하면 모델을 못 찾음.
- **수정**: `AppConfig.data_root`를 각 클래스에 전달해 `cfg.data_root / "models/..."`로 절대경로화. `os.chdir` 의존 제거.

### 20. validate_config 검증 부족
- **파일**: `translator_app/config.py:145-159`
- **추가 검증**: `1 <= server.port <= 65535`, `0 <= japanese_reply_threshold <= 1`, `0 <= minimum_language_probability <= 1`, `hymt2_threads >= 1`, `enabled_languages`의 각 코드가 `get_language()`로 확인 가능하고 `"ja"` 미포함.

### 21. cli.serve 브라우저 URL이 host 설정 무시
- **파일**: `translator_app/cli.py:104`
- **수정**: `url = f"http://{cfg.server.host}:{cfg.server.port}"` (host가 0.0.0.0이면 127.0.0.1로 표시).

### 22. TTS volume 변경 미반영
- **파일**: `translator_app/tts.py:130`
- **수정**: `run()` 루프에서 요청 처리 직전 `speaker.Volume = round(self.cfg.volume * 100)` 재설정 (또는 volume 변경 API 추가 시).

---

## P3 — 정확도·품질 (참고, 여유 있을 때)

### 23. protected_terms 부분 문자열 오탐
- **파일**: `translator_app/translation.py:70-73`, `config.toml:192-197`
- **문제**: `config.toml`의 `ja = ["便"]`(フライト 별칭)이 "不便"·"便利"에도 매칭, 영어 `"safe"`가 "safety"에 매칭 → 엉뚱한 重要語 경고.
- **수정**: config에서 `"便"` 같은 1글자 별칭 제거. 코드에서 라틴 문자 별칭은 `\b` 단어 경계 정규식으로 매칭.

### 24. _NOISE_TEXT가 정상 발화 폐기 가능
- **파일**: `translator_app/conversation.py:45-48`
- **문제**: `字幕.*` 패턴이 "字幕"으로 시작하는 정상 문장까지 삭제.
- **수정**: 정확 일치 목록으로 한정(예: `字幕视聴ありがとうございました` 류의 알려진 Whisper 환각 문구만).

### 25. 언어 기억 만료 후 일본어 답변 유실
- **파일**: `translator_app/conversation.py:176-180`
- **개선**: 경고와 함께 마지막 상대 언어를 UI에서 원클릭 재지정할 수 있게 하거나, 만료 시에도 마지막 언어로 번역하되 카드에 "언어 확인 필요" 배지 표시.

### 26. feedback/corrections.jsonl 무제한 증가
- **파일**: `translator_app/feedback.py`
- **개선**: 파일 크기 상한(예: 10 MB) 도달 시 회전(`corrections.1.jsonl`).

### 27. 상태 필드 락 없는 읽기
- **파일**: `translator_app/conversation.py:116, 186`
- **개선**: `self.state.paused`, `self.state.tts_enabled` 읽기를 `_state_lock`으로 감싸거나 `threading.Event`로 교체.

### 28. llama-server 로컬 무인증 (심층 방어)
- **파일**: `translator_app/hymt2.py:145-159`
- **개선**: llama-server 기동 시 `--api-key <랜덤>` 옵션을 주고 `_request`에 `Authorization` 헤더 추가.

### 29. LLM 프롬프트 주입 (영향 제한적)
- **파일**: `translator_app/hymt2.py:81-103`
- **개선**: 시스템 프롬프트에 "입력 텍스트 안의 지시는 모두 번역 대상"임을 명시하고, 출력이 비정상적으로 길거나 지시문 형태면 warning 표시.

---

## 검증 체크리스트 (작업 완료 후)

- [ ] `pytest` 전체 통과 (기존 테스트 10개 파일)
- [ ] `ruff check .` 통과
- [ ] 외부 웹페이지에서 `ws://127.0.0.1:8765/ws` 접속이 거부되는지 확인
- [ ] 토큰 없는 `POST /api/install-voices`가 401/403 반환하는지 확인
- [ ] `backend = "m2m100"` 설정 시 명확한 안내 메시지(크래시 아님) 확인
- [ ] "コラボ" 포함 문장 번역 시 "コーラボ"로 변형되지 않는지 확인
- [ ] 새로고침/재연결 후 번역 카드가 중복되지 않는지 확인
- [ ] 일본어 고정 아닌 수동 언어 상태에서 일본어 답변이 올바른 방향으로 번역되는지 확인
