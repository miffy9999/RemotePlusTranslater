# 시스템 내부 가이드 (0.5.2)

이 문서는 코드를 계속 수정할 개발자를 위한 구조 설명이다. 사용자 실행법과 운영 한계는 루트 `README.md`가 기준이다.

## 프로세스와 스레드

하나의 `RemotePlusTranslator.exe`가 FastAPI/uvicorn을 loopback 주소에 열고 Chrome 또는 Edge의 독립 `--app` 창을 실행한다. 외부 브라우저가 없으면 기본 브라우저로 fallback한다. pywebview와 WebView2 임베딩은 사용하지 않는다.

주요 실행 단위:

- launcher/main thread: config, single-instance mutex, desktop lifecycle
- uvicorn thread: REST, WebSocket, static UI
- `conversation-final-stt`: 최종 Whisper 디코드
- `conversation-translation`: Hy-MT2 요청 직렬화
- `translator-warmup`: llama-server 시작과 첫 warm-up
- `audio-capture`: sounddevice microphone 또는 SoundCard WASAPI loopback
- `edge-tts`: 온라인 합성, pygame 재생
- 별도 `llama-server.exe`: 로컬 GGUF 추론

Windows Job Object의 `KILL_ON_JOB_CLOSE`가 부모 비정상 종료 시 자식 프로세스를 정리한다. desktop 앱은 named mutex로 중복 backend 실행을 막는다.

## 시작 순서와 준비 상태

1. `config.toml`을 읽고 호환 가능한 `config.local.toml`을 overlay한다.
2. desktop launcher thread에서 Whisper를 한 번 로드한다.
3. FastAPI lifespan이 `ConversationController.start()`를 호출한다.
4. STT worker가 이미 로드된 recognizer를 확인한다.
5. translator warm-up이 llama-server를 임의 loopback port에 시작한다.
6. `/health`와 실제 child process 생존이 확인된 뒤 translator-ready가 된다.
7. 두 모델이 모두 준비된 뒤에만 audio capture를 시작한다.

`ConversationState.phase`는 화면 문구이고, 진짜 준비 여부는 `_ready`, `_translator_ready`, translator `process.poll()`을 조합한 `snapshot()`이 권위 소스다. WebSocket은 유휴 1초마다 state heartbeat를 보내므로 child crash 뒤 UI가 예전 준비 상태로 남지 않는다.

## 발화 스냅샷

VAD가 첫 speech frame을 잡는 순간 다음 값을 `SpeechSegmenter` 내부에 복사한다.

- 전역 monotonic utterance ID
- customer/staff mode
- recognition language
- reply target language
- TTS enabled

이후 Space를 놓거나 UI 언어를 바꿔도 진행 중 발화에는 영향을 주지 않는다. 단, 브라우저의 Space REST 요청보다 VAD가 아주 조금 먼저 열린 경우 `promote_active_to_staff()`가 segment lock 아래 0.75초 이내 customer segment만 staff로 승격한다. device stream 재시작도 마지막 utterance ID 다음 번호에서 계속하므로 WebSocket 카드 키가 충돌하지 않는다.

브라우저는 서버 응답 상태와 별도로 `desiredStaff`를 보존한다. 아주 짧은 Space tap에서
release가 press 응답보다 먼저 발생해도 직렬 request loop가 마지막 의도까지 따라잡으므로
staff mode가 고정되지 않는다. 입력 요소나 버튼에 focus가 있을 때 Space는 PTT로 쓰지 않는다.

고객 모드는 선택 언어를 Whisper에 강제하고 일본어로 번역한다. 직원 모드는 일본어를 Whisper에 강제하고 발화 시작 때 snapshot한 고객 언어로 번역한다.

화면의 고객 언어 표시는 고객 발화에서는 `source_language`, 직원 답변에서는
`target_language`를 사용한다. 직원 답변의 source는 항상 일본어이므로 이를 표시값으로
사용하면 고객 언어가 일본어처럼 보이는 오류가 생긴다. 첫 실행 UI 기본값과 초기 HTML은
일본어이며, 사용자가 화면 언어를 바꾸면 해당 브라우저 저장값을 우선한다.

## 오디오와 VAD

microphone은 16 kHz mono, 20 ms block이다. WASAPI loopback은 보통 48 kHz stereo로 읽고 mono 16 kHz로 선형 resample한다.

RMS VAD는 idle noise floor를 느리게 추정하고 `max(config threshold, noise multiplier)`를 사용한다. 최소 발화는 180ms다. customer/staff의 end silence, tail, max duration은 별도 값이며 staff 기본 최대 길이는 20초, customer는 12초다.

callback은 100-frame bounded queue에 넣는다. overflow/frame queue full은 실제 audio discontinuity이므로 진행 중 segment를 폐기한다. 중간이 잘린 오디오를 정상 문장처럼 STT에 넘기는 것보다 재발화를 요구하는 쪽이 안전하다. UI 경고는 10초 throttle한다.

출력 TTS 중에는 `PlaybackGate`가 입력 segmenter를 reset해 되먹임을 막고, 재생 종료 후 짧은 mute tail을 둔다.

## STT

`WhisperRecognizer.load()`는 module-level lock과 instance check로 중복 로드를 막는다. 기본 `small/cpu/int8`, beam 1, one worker다. GPU/compute fallback은 설정 조건이 CPU INT8이 아닐 때만 CPU INT8로 한 번 시도하므로 같은 실패 조건 반복이 없다.

일반 발화는 한 번만 decode한다. 3회 이상 반복 loop가 생기거나 segment avg log probability가 threshold 이하일 때만 beam 2로 다시 decode하며, 재시도 confidence가 첫 결과보다 높을 때만 교체한다. 후처리는 독립 filler만 제거하고, 3회 이상 인접 반복만 축약한다. 정상 호텔 표현인 `Thank you`는 noise 필터에서 제외한다. correction은 명시된 문자열만 longest-first로 치환한다.

Whisper native decode는 실행 중 안전한 취소 API가 없다. 새 발화가 와도 이미 시작한 decode는 계산을 끝내지만, utterance ID freshness 검사를 통과하지 못하면 transcript/translation으로 게시하지 않는다.

## 번역

`HyMT2Translator`가 private API key와 임의 loopback port로 llama-server를 시작한다. free-port 확인과 bind 사이 race 때문에 첫 시작이 실패하면 새 port로 한 번 다시 시작한다. stdout/stderr는 사용자 데이터의 `logs/llama-server.log`에 합치며 2 MB에서 이전 로그로 rotate한다.

응답은 OpenAI 호환 SSE stream의 각 `choices[0].delta.content` chunk와 최종 non-empty 결과를 검증한다. 4xx, 잘못된 JSON, empty choice, 일반 timeout에 같은 요청을 무조건 반복하지 않는다. process death/connection loss만 server를 한 번 재시작해 동일 요청을 복구한다. timeout이면 stuck CPU를 끝내기 위해 server를 중지하고 다음 작업에서 다시 로드한다.

새 발화가 실행 중 번역을 대체하면 streaming 초기에 확보한 HTTP response를 닫아 llama generation 취소를 요청한다. 연결 헤더를 받기 전의 짧은 구간에서는 즉시 취소할 수 없지만, 완료 결과는 freshness 검사로 버린다.

입력은 800 characters에서 거절해 CJK의 높은 token/character 비율에서도 1,024 context에 instruction과 출력을 남긴다. 실제 VAD 길이에서는 보통 이보다 훨씬 짧다.

## TTS

TTS는 `edge-tts`가 MP3를 임시 폴더에 만들고 pygame mixer가 선택된 SDL output으로 재생한다. 새 요청은 queue 1의 대기 요청, 실행 중 Edge asyncio task, 현재 playback을 중단한다. 네트워크 오류는 최신 요청이 없는 동안 한 번 재시도한다.

request ID 발급·이전 요청 중단·queue 삽입은 하나의 lock transaction이다. staff 발화나
pause처럼 새 TTS를 만들지 않는 interrupt도 현재 유효 ID를 무효화한다. 따라서 dequeue와
`_playing` 설정 사이의 짧은 구간에서도 이전 음성이 다시 살아나지 않는다.

선택 출력이 사라지면 system default로 재초기화하고 `audio_cfg.output_device`를 바꾼다. controller snapshot이 이 값을 UI state로 동기화한다. MP3는 finally에서 삭제되고 비정상 종료 orphan은 다음 시작 때 1시간 기준으로 청소한다. thread finally에서 mixer를 quit한다.

## 최신 작업 정책

audio utterance queue, recognition/translation queue, TTS request queue는 각각 크기 1이다. queue에서 꺼낼 때도 남은 항목을 drain해 가장 최신 것만 사용한다. 이것만으로는 이미 실행 중인 결과를 막지 못하므로 controller가 `latest_started_by_mode`와 전역 최대 utterance ID를 검사한다.

검사 지점은 STT 완료 뒤, 번역 시작 전, 번역 완료 뒤다. 오래된 번역은 UI history, processed count, TTS 어디에도 들어가지 않는다.

## WebSocket과 기록

EventBus history는 translation/error/warning만 최대 100개 보존한다. subscriber queue도 100이며 느린 client에서는 oldest event를 버린다. WebSocket disconnect의 finally에서 subscriber를 제거하고 desktop client count/disconnect time을 갱신한다.

연결 시 snapshot이 화면/history를 다시 구성한다. translation card는 utterance ID Map으로 upsert하므로 snapshot과 직후 queued event가 겹쳐도 카드가 중복되지 않는다. history clear와 `history_cleared` fan-out은 같은 EventBus lock에서 순서화하고, REST 응답 쪽은 화면을 다시 지우지 않는다. UI DOM은 20개 카드만 남긴다. 전체 페이지는 fixed viewport/hidden overflow이고 feed만 scroll한다.

## 설정

- `config.toml`: 배포 기본/모델 성능
- `config.local.toml`: 사용자 데이터 폴더의 관리자 overlay
- `user-settings.json`: schema-versioned UI 선택

local overlay가 syntax/unknown field뿐 아니라 값 범위 검증에 실패해도 기본 config로 계속 시작한다. primary config의 알 수 없는 최상위 section은 오타로 취급해 즉시 실패한다. 모든 control 요청은 state 변경, recognizer context, 장치 재시작까지 하나의 control lock으로 직렬화하되 느린 장치 검증은 audio context용 state lock 밖에서 수행한다. stream 종료 실패 시 device state/config를 이전 값으로 rollback한다. user settings는 허용 키와 타입만 읽고 atomic replace로 쓴다. 장치/언어가 다른 PC에서 invalid면 해당 키만 적용하지 않는다.

## 종료

UI WebSocket이 끊기면 desktop launcher가 idle grace를 센다. browser parent process가 먼저 종료돼도 active WebSocket이 있으면 server를 죽이지 않는다. 종료 시 uvicorn lifespan이 controller.stop을 호출하며 capture, TTS cancel, translator close 후 worker join을 수행한다. launcher는 server thread에 최대 12초를 주고 app browser process를 정리한다.

## 테스트 원칙

unit test는 segment snapshot/Space 승격, concurrent control 직렬화, latest/stale 판정, invalid llama JSON, settings schema, WebSocket auth/lifecycle를 포함한다. 실제 운영 성능은 `benchmark_public_audio.py`, `stress_runtime.py`, `run_debug.bat` 로그로 별도 확인한다. 공개 음성은 정답 transcript가 없어 실행 smoke test일 뿐 정확도 점수가 아니며, 권리 확보한 실통화 회귀 corpus가 최종 기준이어야 한다.
