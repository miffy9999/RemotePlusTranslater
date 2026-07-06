# RemotePlus Translator 시스템 이해 및 유지보수 안내서

이 문서는 개발자가 없어도 이 프로그램을 실행하고, 문제를 격리하고, 기능을 변경할 수 있도록 실제 코드 구조를 기준으로 설명한다.

## 1. 이 프로그램의 정확한 정체

이 프로그램은 하나의 거대한 AI가 아니라 다음 부품을 직렬로 연결한 로컬 파이프라인이다.

```text
마이크 또는 PC 재생음
  -> 20ms 오디오 블록
  -> RMS 기반 발화 구간 검출
  -> 16kHz mono 발화 배열
  -> faster-whisper STT
  -> 고객 언어/일본어 답변 판정
  -> Hy-MT2 번역
  -> 화면에 WebSocket 이벤트 전송
  -> 일본어 답변이면 Windows SAPI TTS
  -> 선택한 출력 장치
```

실행 화면은 웹 기술로 만들었지만 인터넷 웹서비스가 아니다. EXE가 PC 안에서 FastAPI 서버를 `127.0.0.1:8765`에 열고, pywebview가 그 주소를 Edge WebView2 창 안에 표시한다. 모델, 오디오, 번역 데이터는 모두 같은 PC 안에서 처리된다.

## 2. 프로세스와 스레드

EXE를 실행하면 최소 두 프로세스가 생긴다.

1. `RemotePlusTranslator.exe`: UI, 오디오, STT, 제어 서버, TTS를 담당한다.
2. `llama-server.exe`: Hy-MT2 GGUF 번역 모델만 담당한다.

메인 프로세스 내부에는 다음 실행 흐름이 병렬로 존재한다.

- pywebview 메인/UI 스레드
- Uvicorn 로컬 HTTP 서버 스레드
- `conversation` 스레드: STT와 번역을 순차 처리
- `audio-capture` 스레드: 마이크 또는 WASAPI loopback 캡처
- `tts` 스레드: SAPI 음성 출력
- WebSocket 연결별 이벤트 전달 작업

STT와 번역을 하나의 `conversation` 스레드에서 순차 실행하는 이유는 CPU와 메모리를 무제한으로 쓰지 않기 위해서다. 발화 대기열은 최대 3개다. 처리가 밀리면 가장 오래된 발화를 버리고 최신 발화를 보존한다. 콜센터에서는 30초 전 문장을 늦게 번역하는 것보다 현재 문장을 처리하는 편이 낫다는 정책이다.

## 3. 프로그램 시작 순서

기본 진입점은 `launcher.py -> translator_app.cli -> translator_app.desktop.run_desktop()`이다.

1. `config.toml`을 읽는다.
2. 개발 실행이면 프로젝트 폴더, EXE 실행이면 EXE 옆 폴더를 애플리케이션 루트로 정한다.
3. 사용자 데이터 폴더를 결정한다.
4. `ConversationController`와 로컬 FastAPI 앱을 만든다.
5. Uvicorn을 별도 스레드에서 시작한다.
6. 포트가 열릴 때까지 기다린다.
7. pywebview 창으로 로컬 페이지를 연다.
8. 백엔드는 Whisper를 메모리에 적재한다.
9. `llama-server.exe`를 임의의 빈 로컬 포트와 임의 API 키로 실행한다.
10. 번역 서버의 `/health`가 정상일 때 오디오 캡처를 시작한다.

모델 로딩이 끝나기 전에는 듣기를 시작하지 않는다. 따라서 첫 실행 직후 잠깐 조용한 것은 정상이다.

## 4. 파일별 책임

### 핵심 Python 코드

- `translator_app/config.py`: TOML 로딩, 기본값, 경로, 설정 유효성 검사
- `translator_app/audio.py`: 장치 검색, 마이크/PC 재생 캡처, 리샘플링, 발화 분할
- `translator_app/stt.py`: faster-whisper 로딩, 언어 감지, hotword, STT 교정
- `translator_app/conversation.py`: 전체 상태 머신과 번역 방향 결정
- `translator_app/hymt2.py`: llama-server 생명주기, 번역 프롬프트, 재시작
- `translator_app/translation.py`: 중요 용어 보존, 선택적 M2M100 개발 백엔드
- `translator_app/phrasebook.py`: 정확히 일치하는 호텔 정형문 응답
- `translator_app/tts.py`: Windows SAPI 음성/출력 장치 선택
- `translator_app/events.py`: 스레드 안전 이벤트 버스와 최근 기록
- `translator_app/server.py`: 로컬 REST API, WebSocket, 인증, UI 제공
- `translator_app/desktop.py`: 로컬 서버와 데스크톱 창 결합
- `translator_app/settings.py`: 선택 언어 저장
- `translator_app/feedback.py`: 사용자가 수정한 문장 JSONL 저장
- `translator_app/languages.py`: 언어 코드, 이름, SAPI LCID 매핑

### UI

- `translator_app/web/index.html`: 화면 구조
- `translator_app/web/app.css`, `device.css`: 디자인과 반응형 배치
- `translator_app/web/app.js`: REST 요청, WebSocket, 다국어 UI, 장치 재검색

### 운영 및 배포

- `config.toml`: 운영 동작을 바꾸는 중심 설정
- `build.ps1`: PyInstaller portable EXE 빌드
- `build/local_bridge.spec`: EXE에 포함할 패키지와 제외할 무거운 패키지
- `install_voice_packs.ps1`: Windows 선택적 음성 기능 설치
- `tests/`: 단위 및 통합 회귀 테스트
- `scripts/benchmark_*.py`: 번역 및 언어 감지 품질 평가
- `benchmarks/*.json`: 고정 평가 데이터와 결과

## 5. 오디오 처리

### 마이크 입력

`sounddevice.InputStream`을 연 뒤 20ms마다 mono float32 샘플을 받는다. 스트림은 번역마다 새로 열지 않고 선택 장치가 바뀌거나 오류가 날 때까지 계속 유지한다.

### PC 재생음 입력

`SoundCard`가 Windows WASAPI loopback 장치를 연다. 일반적으로 48kHz stereo로 읽고, 두 채널 평균을 낸 다음 16kHz mono로 리샘플링한다. 전화 프로그램의 소리를 번역하려면 마이크가 아니라 `PC playback · ...` 장치를 선택한다.

### 장치 재검색의 의미

UI가 `/api/devices`를 시작 시 한 번, 이후 10초마다 호출한다. 이는 목록만 재조회하는 작업이다. 매 번역마다 장치를 다시 여는 것이 아니다. 현재 장치가 두 번 연속 목록에서 사라졌을 때만 기본 장치로 되돌린다. 일시적인 USB 장치 열거 실패 때문에 스트림을 즉시 깨지 않기 위한 정책이다.

### 발화 분할

별도 신경망 VAD가 아니라 RMS 에너지 기반 상태 머신이다.

- `start_rms`: 말이 시작됐다고 보는 문턱
- `continue_rms`: 이미 말하는 중일 때 계속 말한다고 보는 문턱
- `pre_roll_ms`: 문턱을 넘기 직전 오디오도 포함해 첫 음절 손실 방지
- `end_silence_ms`: 이 시간만큼 조용하면 한 문장 종료
- `min_speech_ms`: 너무 짧은 소리 폐기
- `max_utterance_ms`: 한 발화 최대 길이

시작 문턱과 지속 문턱을 다르게 두는 것을 hysteresis라고 한다. 시작 후 작은 음량 변화 때문에 발화가 잘게 끊어지는 것을 줄인다. 주변 소음 바닥값도 천천히 추정하여 고정 문턱과 함께 사용한다.

이 시스템의 “실시간”은 음성 샘플이 들어오는 즉시 번역 토큰을 내는 스트리밍 방식이 아니다. 약 550ms의 문장 끝 침묵을 확인한 뒤 발화 단위로 STT와 번역을 실행하는 near-real-time 방식이다.

## 6. STT와 언어 감지

Whisper `small`, CPU `int8`, 16kHz 오디오가 기본이다. 번역 모델과 Whisper 모델은 서로 독립적이다.

자동 모드에서는 Whisper의 언어 확률 중 사용자가 설치 단계에서 선택한 언어와 일본어만 후보로 삼는다. 최고 후보 확률이 `enabled_language_min_probability` 이상일 때 그 언어를 강제한다. 확신이 부족하면 Whisper 자체 감지로 돌아가고 경고를 낸다.

수동 모드에서도 먼저 언어 감지를 한 번 한다. 일본어 확률이 충분히 높으면 직원 답변으로 인정하고, 그렇지 않으면 사용자가 지정한 고객 언어로 STT를 강제한다. 이 설계가 필요한 이유는 같은 마이크/재생 채널로 고객 음성과 직원 일본어 답변이 모두 들어오기 때문이다.

또한 결과 텍스트에 히라가나/가타카나가 두 글자 이상 있으면 낮은 감지 확률보다 실제 문자 증거를 우선하여 일본어로 처리한다.

### STT 품질 조절 수단

1. `stt.hotwords`: 모든 언어에 주는 도메인 힌트
2. `stt.language_hotwords`: 현재 언어에만 주는 호텔 용어
3. `stt.corrections`: 이미 인식된 문자열의 결정적 치환
4. `beam_size`: 후보 탐색 폭. 높이면 느려지고 항상 좋아지는 것은 아니다.
5. Whisper 모델 크기: `small -> medium`은 정확도와 메모리/지연의 교환이다.

`콜라주세요 -> 콜을 주세요` 같은 문제는 먼저 실제 소음 환경에서 같은 오인식이 반복되는지 확인한다. 반복되면 hotword를 추가하고, 오인식 형태가 안정적일 때만 corrections에 넣는다. 너무 일반적인 치환은 정상 문장을 망가뜨린다.

## 7. 대화 방향 상태 머신

핵심은 `ConversationController._resolve_language()`와 `process_recognition()`이다.

```text
외국어 인식
  -> 외국어에서 일본어로 번역
  -> active_language에 고객 언어 저장
  -> 일본어 텍스트 표시

일본어 인식
  -> 최근 active_language 확인
  -> 일본어에서 그 언어로 번역
  -> 번역문 표시
  -> TTS 큐에 넣기
```

`active_language`는 마지막 고객 언어다. 기본 90초 동안 유효하다. 90초가 지나거나 아직 고객 언어가 정해지지 않았는데 일본어가 들어오면, 어느 언어로 말해야 하는지 알 수 없으므로 TTS를 하지 않고 경고한다. 틀린 언어로 고객에게 음성을 내보내는 것보다 안전한 실패다.

`reply_language`는 밖으로 내보낼 답변 언어다. `auto`이면 위의 `active_language`를 사용하고, 영어·한국어·중국어·스페인어 중 하나를 수동으로 선택하면 최근 고객 언어와 관계없이 일본어 답변을 지정 언어로 번역해 TTS로 출력한다. 선택 언어팩에서 제외된 언어는 답변 출력 목록에서도 제거되며, 사용 중이던 출력 언어를 제거하면 자동으로 `auto`로 복귀한다.

수동 언어를 선택하면 그 언어가 입력 언어이면서 답변 TTS 대상 언어가 된다. 자동으로 돌리고 싶으면 다시 `자동 감지`를 선택한다.

## 8. 번역 엔진

기본 엔진은 Tencent Hy-MT2 1.8B의 Q4_K_M GGUF다. Python 프로세스가 직접 모델을 읽지 않고, 포함된 `llama-server.exe`를 숨김 프로세스로 실행한 뒤 OpenAI 호환 로컬 HTTP API로 요청한다.

중요 설정은 다음과 같다.

- `hymt2_threads`: CPU 추론 스레드 수
- `hymt2_context`: 프롬프트와 입력이 들어갈 문맥 크기
- `hymt2_timeout_seconds`: 서버 최초 시작 제한 시간
- `hymt2_request_timeout_seconds`: 한 번역 요청 제한 시간
- `max_new_tokens`: 번역 출력 최대 토큰

번역 요청은 임의 빈 포트와 실행마다 새로 만든 API 키를 사용한다. 서버가 죽거나 요청이 실패하면 한 번 종료·재시작 후 재시도한다. 번역 호출 전체는 `RLock`으로 보호하므로 동시에 두 스레드가 모델 생명주기를 망가뜨리지 않는다.

프롬프트는 원문 안의 명령을 명령으로 수행하지 말고 번역할 텍스트로 취급하도록 지시한다. 이는 고객이 “이전 지시를 무시하라” 같은 문장을 말해도 번역기가 그 문장을 실행 지시로 오해하지 않게 하는 최소 방어다.

### 번역 품질을 보강하는 3단계

1. `phrasebook.py`: 일본어 답변이 등록된 정형문과 정확히 맞으면 생성 모델을 건너뛰고 검증된 번역을 반환한다.
2. 프롬프트 reference: 원문에서 보호 용어를 찾으면 모델에 목표 언어 표준어를 알려준다.
3. 사후 검사: 모델 출력에 중요 용어가 빠지면 `（重要語: ...）`처럼 명시적으로 붙인다.

알레르기, 금연, 예약 취소, 셔틀 같은 단어가 자연스러운 문장보다 더 중요하기 때문이다. 다만 이 후처리는 문장의 전체 의미가 맞다는 보증이 아니라, 특정 핵심 용어의 누락을 눈에 보이게 막는 안전망이다.

M2M100 코드는 개발 비교용으로 남아 있지만 portable EXE에는 Torch/Transformers를 넣지 않는다. 기본 제품 경로는 Hy-MT2다.

## 9. TTS

TTS는 AI 음성 모델을 함께 배포하는 방식이 아니라 Windows SAPI를 사용한다. 그래서 Python이 없는 PC에서도 EXE가 작동하지만, 대상 언어의 Windows 음성 기능은 그 PC에 설치되어 있어야 한다.

`languages.py`의 SAPI LCID와 설치된 voice token의 Language 속성을 비교해 언어별 음성을 고른다. 출력 장치는 WASAPI GUID로 맞춘다. 선택 장치가 사라지면 시스템 기본 출력으로 안전하게 복귀한다.

온라인 번역기가 많은 언어의 TTS를 즉시 제공하는 이유는 서버에 대규모 음성 모델과 GPU를 운영하기 때문이다. 완전 로컬·무료·작은 EXE 조건에서는 Windows 기본 음성팩을 활용하는 것이 현실적인 기준선이다.

TTS가 재생되는 동안 `PlaybackGate`가 오디오 분할기를 막고, 재생 종료 후에도 기본 500ms 더 막는다. 이것이 번역된 음성이 다시 마이크/loopback에 들어가 무한 번역되는 피드백 루프를 막는다.

## 10. UI와 로컬 서버

UI는 REST와 WebSocket을 나눠 쓴다.

- REST: 장치 조회, 설정 변경, 언어팩 상태, 기록 삭제, 교정 저장
- WebSocket: 상태 변화, 번역 결과, 오류를 즉시 UI로 push

`EventBus`는 최근 translation/error/warning 최대 100개를 메모리에 둔다. UI는 번역 카드 최대 20개만 DOM에 남긴다. 기록 지우기는 이 메모리와 화면을 비운다. 그러나 수 GB 모델 메모리가 대부분이므로 기록을 지워 절약되는 RAM은 매우 작다. 장시간 실행 안정성에는 bounded queue와 bounded history가 더 중요하다.

사용자 교정은 일반 기록과 다르다. `%LOCALAPPDATA%\RemotePlusTranslator\feedback\corrections.jsonl`에 명시적으로 저장되며 10MB가 되면 회전한다. 이것은 자동으로 모델을 학습시키지 않는다. 향후 평가 데이터 또는 파인튜닝 데이터 후보일 뿐이다.

### 로컬 API 보안

- 서버 host는 loopback만 허용한다.
- 예상한 Host 헤더가 아니면 403을 반환한다.
- `/` 접속 시 임의 세션 값을 HttpOnly/SameSite 쿠키로 준다.
- `/api/*`와 `/ws`는 세션을 검증한다.
- WebSocket은 로컬 Origin도 검사한다.
- 내부 llama-server도 별도 임의 API 키를 사용한다.

따라서 같은 PC의 악성 웹페이지가 브라우저를 이용해 번역기 제어 API를 마음대로 호출하는 공격을 줄인다. 이것은 인터넷 공개용 인증 시스템은 아니며, 서버를 LAN에 공개하도록 바꾸면 안 된다.

## 11. 설정과 저장 위치

### 프로그램 옆에 있어야 하는 것

- `config.toml`
- `models/whisper/...`
- `models/hymt2/Hy-MT2-1.8B-Q4_K_M.gguf`
- `models/hymt2/llama/llama-server.exe`와 DLL

모델 경로는 현재 작업 디렉터리가 아니라 EXE 위치를 기준으로 계산한다. 따라서 USB로 폴더 전체를 복사해도 된다.

### 사용자별로 저장되는 것

EXE에서는 `%LOCALAPPDATA%\RemotePlusTranslator`를 사용한다.

- `user-settings.json`: 선택한 고객 언어
- `config.local.toml`: 있으면 기본 config 위에 덮어쓰는 로컬 설정
- `feedback/`: 사용자가 저장한 교정

환경 변수 `REMOTEPLUS_DATA_DIR`로 사용자 데이터 위치를 바꿀 수 있다.

## 12. 언어팩의 실제 의미

현재 영어/한국어/중국어/스페인어 선택은 언어별 번역 모델을 따로 설치하는 구조가 아니다.

- Whisper 하나가 여러 언어 STT를 처리한다.
- Hy-MT2 하나가 여러 언어 번역을 처리한다.
- Windows TTS 음성만 언어별 OS 기능으로 설치한다.
- 언어 선택은 자동 감지 후보, 수동 목록, TTS 설치 대상을 제한한다.

따라서 새 언어를 추가하려면 단순히 모델 파일 하나를 복사하는 것이 아니라 다음을 모두 확인해야 한다.

1. `languages.py`에 언어 코드/표시 이름/SAPI LCID 추가
2. `hymt2.py`의 언어 이름 지원 확인
3. 서버의 설치 가능 언어 목록 확장
4. UI 이름과 번역문 추가
5. Windows 음성 locale 매핑 추가
6. 해당 언어의 실제 STT·양방향 번역·TTS 회귀 테스트

## 13. “파인튜닝”을 정확히 구분하기

현재까지 한 호텔 특화는 대부분 inference-time adaptation이다.

- hotword: STT 디코딩 힌트
- correction: 결과 문자열 규칙 치환
- glossary/protected terms: 번역 프롬프트와 사후 안전망
- phrasebook: 정형문 결정적 번역

이것들은 모델 가중치를 바꾸지 않는다. 장점은 빠르고, 되돌리기 쉽고, Colab 없이 재현 가능하다는 것이다.

실제 STT 파인튜닝은 `오디오 + 정확한 전사 + 언어 + 환경 메타데이터`가 충분히 쌓인 뒤 고려한다. 텍스트 문장 목록만으로는 호텔 소음, 억양, 전화 대역폭에 대한 STT를 학습할 수 없다. 적어도 별도 보관한 실제/동의된 전화 음성, 익명화, train/dev/test 분리, 원본을 모르는 평가 세트가 필요하다.

실제 번역 파인튜닝은 `원문 + 검수된 목표문` 병렬 코퍼스가 필요하다. 현재 피드백 파일은 원료가 될 수 있지만, 운영자가 고친 문장을 자동으로 전부 학습시키면 오타와 잘못된 교정도 모델에 들어간다. 반드시 사람이 검수하고 중복 제거해야 한다.

Colab 파인튜닝은 지금 당장 필수가 아니다. 현재 병목이 언어 감지인지, STT인지, 번역인지, TTS인지 먼저 단계별로 측정한 뒤 학습 여부를 결정해야 한다.

## 14. 문제를 단계별로 격리하는 법

한 문장이 잘못됐을 때 “번역이 이상하다”라고만 보면 수정할 수 없다. UI 카드의 원문과 번역문을 보고 다음처럼 분류한다.

### A. 원문부터 틀림

STT 문제다.

- 입력 장치가 실제 통화 음원인지 확인
- 음량/잡음/클리핑 확인
- 언어를 수동 지정해 비교
- `start_rms`, `end_silence_ms`로 잘림 여부 확인
- 반복 오인식이면 hotword/correction 후보
- 모델 크기 비교 benchmark

### B. 원문은 맞고 일본어가 틀림

번역 문제다.

- 언어 코드가 맞는지 확인
- 중요 용어만 빠졌으면 protected term 추가
- 정형 답변이면 phrasebook 후보
- 자유문 전체 의미가 반복해서 틀리면 평가 세트에 추가
- 특정 예시 하나만 보고 프롬프트를 과적합하지 않기

### C. 일본어 답변의 외국어 텍스트는 맞는데 소리가 안 남

TTS/장치 문제다.

- TTS 토글 확인
- 고객 언어가 최근 90초 안에 설정됐는지 확인
- 해당 Windows voice 설치 여부 확인
- 출력 장치 확인
- `doctor` 명령과 오류 메시지 확인

### D. 아무 반응이 없음

- 상태가 `loading`인지 `listening`인지 확인
- 발화가 RMS 문턱을 넘는지 확인
- 선택 입력이 마이크인지 PC playback인지 확인
- `llama-server.exe`가 실행 중인지 확인
- 포트 8765 충돌 확인

## 15. 개발 및 테스트 명령

프로젝트 폴더 PowerShell에서 실행한다.

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m translator_app.cli doctor
.\.venv\Scripts\python.exe -m translator_app.cli desktop
```

번역 품질은 고정 benchmark로 재현해야 한다. 테스트 문장을 수정하면서 정답도 동시에 유리하게 바꾸면 평가가 아니다. 개발 세트와 한 번도 보지 않은 holdout 세트를 분리한다.

코드 수정 후 최소 검증 순서는 다음과 같다.

1. 관련 단위 테스트 추가 또는 수정
2. 전체 pytest
3. Ruff
4. 번역 benchmark
5. 실제 마이크와 loopback 각각 확인
6. 언어 수동/자동 각각 확인
7. EXE 빌드
8. 프로젝트 폴더가 아닌 위치에서 EXE 실행
9. 다른 Windows PC에서 음성팩/장치/CPU 확인

## 16. 빌드와 배포

`build.ps1`은 PyInstaller onedir 빌드를 만든 뒤 설정, 문서, Whisper, Hy-MT2, llama.cpp를 복사한다. 결과는 단일 파일 EXE가 아니라 EXE와 DLL/모델이 함께 있는 portable 폴더다. 모델이 크므로 진짜 single-file 압축은 시작 속도, 임시 디스크 사용, 백신 오탐에 불리하다.

배포할 때는 `dist\RemotePlusTranslator` 폴더 전체를 ZIP으로 묶는다. EXE만 복사하면 동작하지 않는다. 대상 PC에는 Python이 필요 없지만 다음은 필요하다.

- 64-bit Windows
- Intel/AMD x64 CPU
- 충분한 RAM과 디스크
- Microsoft Edge WebView2 Runtime
- 사용할 언어의 Windows TTS voice
- 전화 음원에 접근 가능한 입력/loopback 장치

`build.ps1`은 Inno Setup 6이 있으면 설치 프로그램도 만들도록 되어 있다.

## 17. 성능과 메모리

RAM의 대부분은 번역 모델, Whisper 모델, 네이티브 런타임이 사용한다. 화면 카드나 텍스트 기록은 상대적으로 미미하다.

성능을 바꿀 때 가장 영향이 큰 순서는 대체로 다음과 같다.

1. Whisper 모델 크기와 compute type
2. Hy-MT2 양자화 크기
3. `hymt2_threads`
4. 발화 길이
5. beam size

스레드를 CPU 논리 코어 수까지 무조건 올리면 UI와 STT가 굶을 수 있다. 일반적으로 물리 코어 수 근처부터 측정하고, 실제 latency와 CPU 사용률을 보고 정한다.

`code=3221225786`은 Windows에서 `0xC000013A`로, 프로세스가 Ctrl+C/종료 신호로 중단됐다는 뜻이다. 함께 보였던 `Exit code: 137`은 Linux 계열 실행 환경에서 SIGKILL을 의미하며 메모리 제한 또는 외부 강제 종료일 수 있다. 둘 다 그 문자열만으로 제품 번역 로직의 예외라고 단정하면 안 된다. 어느 프로세스가, 어떤 작업 중, 얼마의 RAM을 쓰다가 종료됐는지가 필요하다.

## 18. 현재 구조의 한계

이 시스템은 완성된 토대지만 다음을 정직하게 알고 운영해야 한다.

- 전화 통신 프로그램과 직접 SIP/RTP 통합된 상태는 아니다.
- 발화 종료 후 처리하므로 완전 동시통역이 아니다.
- RMS VAD는 TV 소리, 키보드, 배경 음악을 음성으로 오인할 수 있다.
- 고객과 직원이 겹쳐 말하면 단일 채널 Whisper가 두 화자를 안정적으로 분리하지 못한다.
- 90초 언어 메모리는 통화 ID와 연결된 세션이 아니다.
- 생성 번역은 중요 상황에서 100% 정확성을 보장하지 않는다.
- Windows SAPI 음질과 언어 지원은 OS 버전/설치팩에 의존한다.
- UI의 언어 선택은 모델 다운로드 크기를 줄이지 않는다. 현재 모델은 공용 다국어 모델이다.

실제 콜센터 통합 단계에서는 통화별 세션, 고객/직원 채널 분리, 푸시투토크 또는 에코 제거, 개인정보 보존 정책, 실패 시 원문 표시와 재확인 절차가 필요하다.

## 19. 안전하게 기능을 확장하는 원칙

- 현상을 STT/언어 판정/번역/TTS 중 하나로 먼저 분류한다.
- 규칙 하나를 추가할 때 그 규칙이 망가뜨릴 반례 테스트도 추가한다.
- 운영 데이터와 모델/프로그램 파일을 분리한다.
- 큐, 기록, 파일은 항상 상한을 둔다.
- 음성 출력은 확신이 없을 때 침묵하도록 한다.
- 모델 파일과 런타임 다운로드는 SHA-256을 검증한다.
- 로컬 서버를 `0.0.0.0`으로 바꾸지 않는다.
- 모델/프롬프트 변경 전후에는 같은 holdout으로 비교한다.
- `feedback`을 곧바로 학습 데이터로 사용하지 않는다.

## 20. 가장 먼저 읽을 코드 순서

처음부터 모든 파일을 동시에 읽지 말고 다음 순서가 가장 이해하기 쉽다.

1. `config.toml`
2. `translator_app/conversation.py`
3. `translator_app/stt.py`
4. `translator_app/audio.py`
5. `translator_app/hymt2.py`
6. `translator_app/translation.py`
7. `translator_app/tts.py`
8. `translator_app/events.py`
9. `translator_app/server.py`
10. `translator_app/web/app.js`
11. 관련 `tests/test_*.py`

이 순서로 읽으면 “설정 -> 상태 머신 -> 각 AI/장치 부품 -> UI 전달”의 인과관계가 유지된다.
