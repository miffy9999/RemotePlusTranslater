# RemotePlus Translator 0.8.4

일본 호텔 프런트·콜센터를 위한 로컬 번역 채팅 프로그램입니다.

- 고객: 선택한 외국어 음성 → STT → 일본어 번역문
- 직원: 일본어·영어 텍스트 → 고객 언어 번역문
- 읽기 보조: 번역문 아래 일본어 가타카나와 로마자 표기
- TTS 없음: 직원이 화면의 읽기 보조를 보고 직접 말함
- 인터넷 사용료 없음: 모델을 준비한 뒤 음성 인식과 번역은 로컬 실행
- Windows 네이티브 창: 외부 브라우저를 열지 않고 WebView2 앱 창 하나로 실행
- 백그라운드 로컬 엔진: localhost API와 번역 서버는 별도 콘솔 없이 앱 내부에서 실행
- Windows portable EXE: Python이 없는 다른 PC에서도 폴더 단위로 배포

## 실제 화면 흐름

1. 고객 언어를 선택합니다. 자동 감지는 속도와 오감지 때문에 사용하지 않습니다.
2. 마이크 또는 PC 재생음 입력 장치를 선택합니다.
3. 고객이 말하면 확정 원문이 먼저 표시되고 같은 카드에 일본어 번역이 추가됩니다.
4. 직원은 하단 입력창에 일본어·영어 답변을 입력할 수 있습니다.
5. 별도 경량 worker가 같은 카드에 가타카나·로마자 읽기를 추가합니다.
6. `Enter`는 전송, `Shift+Enter`는 줄바꿈입니다.

좌측 `녹음 WAV 번역`에서 고객과 직원 음성이 함께 들어 있는 PCM WAV를 선택하면 라이브
마이크를 잠시 멈추고 로컬에서 음성 구간을 분석합니다. 선택한 고객 언어와 일본어를 우선해
`고객(추정)`, `직원(추정)`, `화자 미확인` 카드로 시간순 표시하며 각 구간의 원음을 다시 들을 수
있습니다. 판단이 애매한 문장도 가능한 경우 원문과 일본어 번역을 남깁니다. WAV 원본과 결과는
외부 서버로 전송하지 않습니다.

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

파이프라인은 `고객 audio → final Whisper → Hy-MT2 → WebSocket`입니다. 직원 답변 텍스트도
같은 번역 모델을 공유하므로 모델을 추가로 올리지 않습니다. TTS, 음성팩,
pygame, sherpa-onnx를 제거해 메모리와 CPU 경쟁을 줄였습니다.

- 최종 STT와 번역 queue는 크기 1이며 최신 발화를 우선합니다.
- 새 발화가 시작되면 이전 llama 요청을 가능한 시점에 취소합니다.
- 이미 실행 중인 Whisper 네이티브 디코드는 안전하게 중단할 API가 없어 계산이 끝난 뒤 결과를 버립니다.
- 번역 결과는 읽기 계산을 기다리지 않고 먼저 게시합니다.
- 확정 STT 원문은 번역을 기다리지 않고 먼저 같은 채팅 카드에 표시합니다.
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
일반 실행은 `run.bat` 또는 설치된 바로가기를 사용하며 콘솔 창을 남기지 않습니다.
터미널 로그가 필요한 개발·장애 분석에만 `run_debug.bat`을 사용합니다.

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

호텔 운영 PC에는 휴대용 개발본 대신 내부 서명된 설치 프로그램을 사용합니다.
`legal\distributor-info.local.json`, 호텔 IT가 관리하는 Code Signing 인증서, Microsoft가 서명한
WebView2 Evergreen x64 오프라인 설치 파일을 준비한 뒤 `build.ps1 -CommercialRelease`를 실행합니다.
WebView2 파일의 위치와 검증 규칙은 `build\redist\README_KO.md`에 있습니다. 완성된 설치 프로그램은
서명·해시를 확인한 뒤 호텔 파일 공유 또는 호텔/VPN IP만 허용한 VPS에서 배포합니다.

VPS 배포는 `deploy\vps\deployment-profile.example.json`을 실제 값으로 복사해
`scripts\prepare_vps_deployment.py`로 설정을 생성한 뒤 진행합니다. 상업용 설치본은
`publish_release.ps1`, SSH 업로드와 원자적 활성화는 `deploy_to_vps.ps1`, 실제 HTTPS·해시·서명
종단 검증은 `scripts\verify_vps_release.py`가 담당합니다. 정확한 순서는
`deploy\vps\README_KO.md`에 있습니다. 기존 채팅 서비스의 용량·프록시 검사를 통과하기 전에는
서버 설정을 변경하지 않습니다.

## QA

```powershell
.\qa.ps1
```

QA는 unit/integration 테스트, Ruff, compileall, 의존성 충돌, SBOM/라이선스 생성을 검사합니다.
실제 모델까지 확인하려면:

```powershell
.\qa.ps1 -Models
```

영어·한국어 호텔 회화 LoRA 데이터 준비와 후보 모델의 품질·속도 승격 절차는
`finetune/README_KO.md`를 따릅니다. 더 큰 모델이나 더 낮은 bit 양자화는 자동으로 더 좋은
운영 모델로 간주하지 않으며, 같은 PC에서 품질과 p50/p95 지연이 모두 후퇴하지 않을 때만
교체합니다.

2026년 7월 기준 최신 번역·STT 후보와 현재 구조를 비교한 결정 근거는
`docs/ARCHITECTURE_MODEL_REVIEW_KO.md`에 있습니다. 최신이라는 이유만으로 교체하지 않고 호텔
PC에서 품질과 속도를 동시에 통과한 모델만 운영본에 반영합니다.

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

### 실행 중 종료되었거나 다시 실행했을 때 화면이 뜨지 않음

0.8.1부터 비정상 종료 흔적이 있으면 다음 실행에서 WebView2 예비 프로필로 자동 전환합니다.
아이콘을 중복 실행하면 기존 창을 앞으로 가져옵니다. 장애 분석용 로그는 재실행해도 보존되며
`%LOCALAPPDATA%\RemotePlusTranslator\logs`에 있습니다.

릴리스 담당자는 Windows 배포본을 만든 뒤 `scripts\stress_portable.ps1`을 실행해 번역 서버
강제 종료 후 재기동과 번역 중 전체 종료를 반복 검증할 수 있습니다. 실행 전 기존 RemotePlus
창을 모두 닫아야 합니다.

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
