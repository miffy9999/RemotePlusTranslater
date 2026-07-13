# 개발자 수정 가이드 (0.5.2)

이 문서는 코드를 처음 넘겨받은 사람이 수정 지점을 빠르게 찾기 위한 지도다. 주석은
구현 자체보다 동시성·최신성·폴백처럼 실수하기 쉬운 결정의 이유를 설명한다.

## 파일별 역할

| 파일 | 책임 | 수정할 때 주의할 점 |
|---|---|---|
| `launcher.py` | EXE 시작, 빠른 업데이트 검증, 치명 오류 기록 | 변경하면 전체 EXE 빌드 필요 |
| `config.py` | TOML 로드, 경로 확정, 설정 검증 | 문법뿐 아니라 값의 의미도 검증할 것 |
| `audio.py` | 장치 stream, frame queue, VAD 발화 구간 | callback에서 느린 작업·네트워크 호출 금지 |
| `stt.py` | faster-whisper 로드와 디코딩 | 재시도 결과가 항상 더 좋다고 가정하지 말 것 |
| `conversation.py` | 전체 worker와 최신 작업 정책 | 발화 시작 시 언어·모드·TTS snapshot 유지 |
| `hymt2.py` | llama-server 생명주기와 번역 요청 | 모든 HTTP 오류를 서버 사망으로 취급하지 말 것 |
| `tts.py` | Edge 합성, 재시도, 재생·중단 | 오래된 request id를 재생하지 말 것 |
| `events.py` | WebSocket fan-out과 제한된 history | 상태 변경과 대응 이벤트의 순서를 원자적으로 유지 |
| `server.py` | REST/WebSocket API와 정적 UI | 사용자 경로를 파일 시스템 경로로 직접 넘기지 말 것 |
| `web/app.js` | 화면 상태와 Space PTT 입력 | 서버 이벤트 순서를 로컬 추측으로 다시 뒤집지 말 것 |

## 한 발화의 데이터 흐름

1. `AudioCapture`가 프레임을 받고 `SpeechSegmenter`가 발화 시작을 판정한다.
2. 시작 순간의 `speech_mode`, 인식 언어, 응답 언어, TTS 여부를 발화에 고정한다.
3. 완성된 `RecognitionJob`이 STT worker로 이동한다.
4. 고객 발화는 일본어 텍스트로, 직원 발화는 고정된 고객 언어로 번역한다.
5. 직원 번역만 TTS queue로 이동한다. 새 직원 발화가 시작되면 이전 재생은 중단한다.
6. 각 단계는 request/utterance id를 검사해 늦게 끝난 오래된 결과가 UI를 덮지 못하게 한다.

Space 키 요청은 브라우저에서 localhost REST로 오므로 음성이 먼저 VAD에 잡힐 수 있다.
이때 `promote_active_to_staff()`는 0.75초 이내의 진행 중 고객 구간만 직원 구간으로
승격한다. Space를 놓는 요청은 이미 시작된 발화를 고객 모드로 되돌리지 않는다.

## 잠금 규칙

- `_state_lock`: 짧은 상태 읽기·쓰기만 한다. 장치 탐색이나 모델 호출을 안에서 하지 않는다.
- `_control_lock`: 하나의 설정 변경 전체를 직렬화한다.
- `_segment_lock`: 캡처 thread와 PTT HTTP thread가 같은 VAD 구간을 동시에 바꾸지 못하게 한다.
- EventBus lock: history 변경과 그 사실을 알리는 이벤트 순서를 함께 보호한다.

잠금을 두 개 이상 잡아야 한다면 기존 코드와 같은 순서를 지킨다. 새 코드에서 lock 안에
네트워크, 디스크, 장치 드라이버, worker join을 넣으면 통화 중 멈춤이 생길 수 있다.

## 빌드 선택

- Python 코드·HTML/CSS/JS·프롬프트·설정 수정: `update_app.ps1`
- pip 의존성·DLL·PyInstaller spec·`launcher.py` 수정: `build.ps1`
- 소스에서 즉시 시험: `run_debug.bat` (EXE 업데이트 불필요)

BAT는 개발 보조 경로이고 고객 배포 기준은 `dist\RemotePlusTranslator` EXE 패키지다.
`run_debug.bat`에는 앱을 열지 않고 CMD quote/timestamp parsing만 검사하는
`REMOTEPLUS_BATCH_SELFTEST=1` 경로가 있으며 unit test가 이를 실행한다.

빠른 업데이트는 `app_update/manifest.json`의 모든 파일 SHA-256을 시작 시 확인한다.
manifest의 파일 목록과 실제 파일 집합도 정확히 일치해야 하며, 누락·추가·손상 시 내장
코드를 사용한다. 이 checksum은 전자서명이 아니라 복사 손상 감지 장치다. 문제 분리는 환경 변수
`REMOTEPLUS_DISABLE_APP_UPDATE=1`로 업데이트를 임시 비활성화해 실행하면 된다.

## 변경 후 최소 검증

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check translator_app tests scripts launcher.py
```

전체 명령을 순서대로 실행할 때는 `qa.ps1`, 실제 Whisper·Hy-MT2까지 포함하려면
`qa.ps1 -Models`를 사용한다. 스크립트가 각 프로세스의 non-zero exit code에서 즉시 중단한다.

오디오 변경은 짧은 발화, frame gap, 장치 전환을 추가로 확인한다. worker 변경은 오래된
작업이 늦게 끝나는 테스트를 넣는다. 배포 전에는 실제 모델 smoke, Edge TTS, 새 EXE의
준비 완료와 창 종료 후 잔류 프로세스 검사를 수행한다.
