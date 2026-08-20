# RemotePlus Translator 0.8.5

일본 호텔 프런트와 콜센터를 위한 Windows용 로컬 번역 프로그램입니다. 고객의 음성을
Whisper로 문자화하고 Hy-MT2로 일본어로 번역합니다. 직원은 일본어 답변을 입력해 고객
언어로 번역할 수 있습니다.

음성 인식과 번역은 PC 안에서 처리됩니다. 외부 브라우저나 별도 콘솔을 띄우지 않고
WebView2 창 하나로 실행하며, 프로그램 창을 닫으면 FastAPI와 `llama-server.exe`도 함께
종료됩니다.

## 주요 기능

- 마이크 또는 Windows WASAPI Loopback으로 고객 음성 입력
- 고객 음성 → 원문 → 일본어 번역을 같은 대화 카드에 표시
- 직원의 일본어 답변 → 고객 언어 번역
- 번역문의 가타카나·로마자 읽기 표시
- WAV 드래그 앤 드롭 분석과 구간별 원음 재생
- 고객·직원·화자 미확인 구간을 시간순으로 표시
- 자주 쓰는 문장 검색·등록·카테고리 관리
- 번역문 수정과 번역 메모리 재사용
- 모든 사용자 설정과 교정 데이터를 PC에 저장

화면 언어는 일본어로 고정되어 있습니다. 고객 언어 선택은 화면 언어와 별개입니다.

## 실행 준비

개발 환경은 Windows 10/11 64비트와 Python 3.11~3.13을 지원합니다.

```powershell
install.bat
prepare_models.bat
run.bat
```

- `install.bat`: `.venv`를 만들고 고정된 의존성을 설치합니다.
- `prepare_models.bat`: Whisper, Hy-MT2 GGUF, llama.cpp 런타임을 준비합니다.
- `run.bat`: 콘솔 없이 프로그램을 실행합니다.
- `run_debug.bat`: 장애 분석용 로그와 함께 실행합니다.
- `doctor.bat`: 모델, 설정, 오디오 환경을 검사합니다.

모델 준비에는 인터넷 연결과 수 GB의 저장 공간이 필요합니다. 준비가 끝난 뒤 실시간 음성
인식과 번역은 로컬에서 처리됩니다.

## 사용 방법

1. 고객 언어를 선택합니다.
2. 실제 마이크 또는 `PC playback`이 붙은 PC 재생음 장치를 선택합니다.
3. 고객이 말하면 원문과 일본어 번역이 대화 화면에 표시됩니다.
4. 직원은 하단 입력창에 일본어 답변을 입력하고 `Enter`로 번역합니다.
5. 잘못된 번역은 카드의 `翻訳を修正`에서 고칩니다.

`PC playback`은 통화 프로그램의 상대방 소리를 직접 받는 WASAPI Loopback 입력입니다.
목록에 나타나지 않으면 Windows 출력 장치가 활성화되어 있고 실제 소리가 재생되는지 먼저
확인합니다.

### 녹음 WAV 번역

`通話ログビューアー`에서 번역할 통화의 `再生`을 누른 뒤 바탕화면의 `ログ` 폴더를 엽니다.
그 안의 WAV 파일 하나를 `録音WAVを翻訳` 영역에 끌어 놓고 분석을 시작합니다.

- 비압축 PCM WAV만 지원합니다.
- 최대 크기는 512MB, 최대 길이는 60분입니다.
- 한 번에 한 파일만 분석합니다.
- 분석 중에는 실시간 마이크가 일시 정지됩니다.
- WAV 원본과 분석 결과를 외부 서버로 전송하지 않습니다.

## 사용자 데이터와 개인정보

설치 폴더를 교체해도 다음 데이터는 유지됩니다.

```text
%LOCALAPPDATA%\RemotePlusTranslator\
  config.local.toml
  quick-phrases.json
  feedback\translation-memory.json
  feedback\corrections.jsonl
  logs\
```

번역 메모리에는 원문과 수정 번역문이 저장됩니다. 이름, 전화번호, 예약번호, 카드번호 등
개인정보가 포함된 문장은 등록하지 마세요. 고객 음성, 로그, 개인 설정, 인증서 개인키는 Git에
올리지 않습니다.

## 테스트와 QA

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\qa.ps1
```

실제 모델까지 검사하려면 다음을 실행합니다.

```powershell
.\qa.ps1 -Models
```

## Windows 배포본 만들기

### 포터블 폴더

```powershell
.\build.ps1
```

결과는 `dist\RemotePlusTranslator`에 생성됩니다. EXE만 따로 복사하지 말고 폴더 전체를
배포해야 합니다.

### 호텔 내부 배포용 설치 ZIP

```powershell
.\build_internal_release.ps1 -Publisher "RemotePlus"
```

현재 Windows 사용자용 내부 코드 서명 인증서를 만들고 EXE·DLL·PYD를 서명한 뒤 설치 ZIP을
생성합니다. 이 자체 서명 인증서는 RemotePlus를 신뢰하는 호텔 관리 PC용이며 공개 인증기관의
상업용 코드 서명을 대신하지 않습니다. 대상 PC에서는 ZIP을 모두 푼 뒤
`Install_RemotePlus.cmd`를 실행합니다.

Google Drive에서 큰 ZIP을 나눠 배포해야 할 때만 다음 명령을 사용합니다.

```powershell
.\prepare_google_drive_release.ps1 -ZipPath ".\dist\RemotePlusTranslator-0.8.5-INTERNAL-SIGNED-YYYYMMDD.zip"
```

제3자 대상 상업 배포본은 유효한 코드 서명 인증서와 배포자 정보를 준비한 뒤
`build.ps1 -CommercialRelease`를 사용합니다.

## 구조

| 경로 | 역할 |
|---|---|
| `translator_app/audio.py` | 마이크·WASAPI 입력, VAD, 발화 구간 생성 |
| `translator_app/stt.py` | faster-whisper 모델 로드와 음성 인식 |
| `translator_app/hymt2.py` | `llama-server.exe` 관리와 번역 요청 |
| `translator_app/conversation.py` | STT·번역·읽기 작업 큐와 종료 처리 |
| `translator_app/wav_import.py` | WAV 검증·구간 분할·분석 |
| `translator_app/translation_memory.py` | 사용자가 수정한 번역 우선 적용 |
| `translator_app/server.py` | localhost REST API와 WebSocket |
| `translator_app/web/` | 일본어 WebView2 화면 |

## 라이선스

프로그램 코드는 저장소의 `LICENSE`를 따릅니다. Whisper, faster-whisper, Hy-MT2,
llama.cpp와 기타 구성 요소에는 각각의 라이선스가 적용됩니다. 배포할 때
`THIRD_PARTY_NOTICES.md`, 생성된 SBOM과 라이선스 자료를 함께 확인하세요. 모델 준비 및 QA가
최종 법률 검토를 대신하지는 않습니다.
