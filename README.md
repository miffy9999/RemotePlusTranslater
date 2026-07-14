# RemotePlus Translator 0.7.0

일본 호텔 프런트·콜센터를 위한 로컬 번역 채팅 프로그램입니다.

- 고객: 선택한 외국어 음성 → STT → 일본어 번역문
- 직원: 일본어·영어 텍스트 입력 → 고객 언어 번역문
- 읽기 보조: 번역문 아래 일본어 가타카나와 로마자 표기
- TTS 없음: 직원이 화면의 읽기 보조를 보고 직접 말함
- 인터넷 사용료 없음: 모델을 준비한 뒤 음성 인식과 번역은 로컬 실행
- Windows portable EXE: Python이 없는 다른 PC에서도 폴더 단위로 배포

## 실제 화면 흐름

1. 고객 언어를 선택합니다. 자동 감지는 속도와 오감지 때문에 사용하지 않습니다.
2. 마이크 또는 PC 재생음 입력 장치를 선택합니다.
3. 고객이 말하면 원문과 일본어 번역이 왼쪽 고객 카드에 표시됩니다.
4. 직원은 하단 입력창에 일본어 또는 영어 답변을 입력합니다.
5. `Enter`를 누르면 고객 언어 번역이 먼저 즉시 표시됩니다.
6. 별도 경량 worker가 같은 카드에 가타카나·로마자 읽기를 추가합니다.
7. `Shift+Enter`는 줄바꿈입니다.

좌측 `자주 쓰는 문장`에는 최대 40개를 직접 등록할 수 있습니다. 일본어·영어 단어로
검색할 수 있고, 문장을 우클릭하면 카테고리를 지정할 수 있습니다. 카테고리 제목을 누르면
접거나 펼칠 수 있으며 이 상태는 앱을 다시 실행해도 유지됩니다. 등록 데이터는 로컬 사용자
데이터에 저장되고 Git 및 배포 원본에는 포함되지 않습니다.

예:

```text
직원 입력     入力します。
한국어 번역   입력하겠습니다.
일본어 읽기   イプリョクハゲッスムニダ.
로마자 읽기   ipryeokhagetseumnida.
```

가타카나는 영어·한국어·중국어·스페인어를 우선 지원합니다. 로마자 읽기는 모든 지원
언어에 제공하며, 한국어는 발음 규칙, 중국어는 병음, 다른 문자권은 AnyAscii fallback을
사용합니다. 읽기 보조는 발음을 돕는 표기이지 공식 인명 표기나 전문 통역 보증이 아닙니다.

## 성능 설계

파이프라인은 `customer audio → final Whisper → Hy-MT2 → WebSocket`입니다. TTS, 직원용
Whisper 경로, 음성팩, pygame, sherpa-onnx를 제거해 메모리와 CPU 경쟁을 줄였습니다.

- 최종 STT와 번역 queue는 크기 1이며 최신 발화를 우선합니다.
- 새 발화가 시작되면 이전 llama 요청을 가능한 시점에 취소합니다.
- 이미 실행 중인 Whisper 네이티브 디코드는 안전하게 중단할 API가 없어 계산이 끝난 뒤 결과를 버립니다.
- 번역 결과는 읽기 계산을 기다리지 않고 먼저 게시합니다.
- 읽기 worker는 별도 queue에서 동작하며 번역 추론을 차단하지 않습니다.
- EventBus, subscriber, UI 카드 복원 기록은 모두 상한이 있어 장시간 실행 중 무한 증가하지 않습니다.
- 모델이 모두 준비된 뒤에만 마이크 stream을 엽니다.

TTS를 제거하면 음성 합성·재생 지연은 완전히 없어지고 로컬 ONNX 음성 모델의 CPU·메모리
점유도 사라집니다. 순수 Hy-MT2 추론 시간 자체는 모델과 CPU에 의해 결정되므로, 번역 품질을
낮춰 억지로 빠르게 만들지는 않습니다.

## 개발 환경 실행

Windows PowerShell 또는 배치 파일에서:

```powershell
install.bat
prepare_models.bat
run_debug.bat
```

`prepare_models.bat`은 Whisper와 Hy-MT2/llama.cpp 파일을 준비합니다. TTS 모델 다운로드는
더 이상 없습니다. 디버그 로그는 `%LOCALAPPDATA%\RemotePlusTranslator\logs`에 기록됩니다.

## 다른 PC 배포

```powershell
.\build.ps1
```

빌드가 성공하면 `dist\RemotePlusTranslator` 폴더 전체를 USB나 사내 파일 공유로 옮깁니다.
대상 PC에서는 폴더 안 `RemotePlusTranslator.exe`만 실행하면 됩니다. EXE 하나만 따로 옮기면
DLL, 웹 UI, 모델이 빠지므로 동작하지 않습니다.

포함되는 주요 파일:

```text
RemotePlusTranslator/
  RemotePlusTranslator.exe
  _internal/
  config.toml
  models/
    whisper/
    hymt2/
```

사용자 설정과 로그는 설치 폴더가 아니라 `%LOCALAPPDATA%\RemotePlusTranslator`에 저장됩니다.
따라서 Program Files 또는 읽기 전용 배포 폴더에서도 설정 저장 권한 문제를 피합니다.

## QA

```powershell
.\qa.ps1
```

QA는 unit/integration 테스트, Ruff, compileall, 의존성 충돌, SBOM/라이선스 생성을 검사합니다.
실제 모델까지 확인하려면:

```powershell
.\qa.ps1 -Models
```

자동 테스트가 보증하지 못하는 것은 호텔별 전화 코덱, 실제 억양·뭉개진 발음, 장치 드라이버,
30~60분 실통화입니다. 권리가 확보된 익명화 현장 음성은 별도의 회귀 corpus로 유지해야 합니다.

## 주요 설정

`config.toml`의 우선 조정 항목:

- `[audio] input_device`: `default`, 마이크 index, 또는 `loopback:<id>`
- `[audio] start_rms`, `continue_rms`: VAD 민감도
- `[audio] end_silence_ms`, `tail_keep_ms`: 발화 종료와 끝음 보존
- `[stt] model`, `compute_type`, `cpu_threads`: STT 품질·CPU 균형
- `[translation] timeout_seconds`, `threads`, `context_size`: Hy-MT2 자원 한도
- `[conversation] language_lock`: 초기 고객 언어

UI에서 언어 또는 입력 장치를 바꾸면 발화 시작 시점 값이 snapshot으로 고정됩니다. 번역 중
언어를 바꿔도 이미 제출한 고객 발화나 직원 답변의 목적 언어는 바뀌지 않습니다.

## 문제 해결

### 가상환경이 손상되었거나 다른 컴퓨터에서 만들어졌다는 메시지

프로젝트 폴더와 함께 복사된 `.venv`는 생성 당시 Python의 절대 경로를 기억하므로 다른
컴퓨터나 사용자 폴더에서는 실행되지 않을 수 있습니다. `install.bat`을 다시 실행하면
손상 여부를 확인한 뒤 이 프로젝트의 가상환경을 자동으로 재생성합니다.

### 계속 “시스템 준비 중”

`doctor.bat`을 실행하고 Whisper 파일, Hy-MT2 GGUF, `llama-server.exe`를 확인합니다. 번역
서버가 죽으면 ready 표시를 유지하지 않고 경고 상태로 전환합니다.

### 고객 음성이 잘림

입력 장치를 확인하고 `run_debug.bat` 로그의 `audio_frame_gap` 또는 overflow를 찾습니다.
frame이 유실된 불완전 발화는 잘못 번역하지 않도록 폐기됩니다. CPU가 포화되면 다른 무거운
프로그램을 닫고 STT/번역 thread 값을 동시에 높이지 마세요.

### 읽기 표기가 부정확함

읽기 표기는 추가 AI 모델을 사용하지 않는 결정적 규칙 기반입니다. 자주 쓰는 호텔 문구는
`translator_app/reading.py`의 `PHRASES`와 언어별 사전에 추가하면 즉시 개선되며 번역 속도에
영향을 주지 않습니다. 고유명사는 직원이 번역 원문과 함께 반드시 확인해야 합니다.

### 장치 변경 후 소리가 안 들어옴

장치는 매 번역마다 검색하지 않습니다. 앱 시작/장치 목록 요청 때 검색하고 결과를 60초
캐시합니다. 선택을 바꿀 때 기존 stream을 닫은 뒤 하나만 다시 엽니다. 이전 stream이 종료되지
않으면 새 장치를 적용한 척하지 않고 설정을 롤백합니다.

## 구조

| 파일 | 책임 |
|---|---|
| `translator_app/audio.py` | 입력 장치, VAD, 발화 snapshot, frame 유실 처리 |
| `translator_app/stt.py` | faster-whisper 로드, 호텔 hotword, 품질 재시도 |
| `translator_app/hymt2.py` | llama-server 수명주기, 번역, timeout/cancel |
| `translator_app/conversation.py` | 최신 queue, 고객 음성/직원 텍스트 routing, worker 종료 |
| `translator_app/reading.py` | 가타카나와 전 언어 로마자 읽기 |
| `translator_app/quick_phrases.py` | 자주 쓰는 문장, 카테고리, 접힘 상태의 원자적 저장 |
| `translator_app/server.py` | localhost 인증 API, WebSocket, 장치 probe |
| `translator_app/web/` | 채팅 UI와 일본어 기본 다국어 화면 |
| `translator_app/settings.py` | schema가 있는 사용자 설정과 원자적 저장 |

## 상업 사용 메모

TTS/Edge Read Aloud는 이 브랜치에 포함되지 않습니다. 핵심 코드와 모델의 고지 사항은
`THIRD_PARTY_NOTICES.md`와 빌드 시 생성되는 `sbom.cdx.json`, `licenses` 폴더를 배포물에
포함해야 합니다. 자동 생성 자료는 최종 법률 검토를 대체하지 않습니다.
