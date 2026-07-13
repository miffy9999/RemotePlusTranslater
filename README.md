# RemotePlus Translator 0.6.0 Commercial Local TTS

일본 호텔·콜센터용 로컬 양방향 음성 번역기입니다. 고객이 선택된 외국어로 말하면 로컬 Whisper가 받아쓰고 로컬 Hy-MT2가 일본어 텍스트로 번역합니다. 직원이 `Space`를 누른 채 일본어로 답하면 같은 대화의 고객 언어로 번역하고 검증된 로컬 ONNX TTS로 읽습니다.

Python이 없는 다른 Windows PC에서도 `dist\RemotePlusTranslator` 폴더 전체를 복사하면 실행할 수 있습니다. STT·번역·TTS와 검증된 음성팩이 모두 포함되며 사용량 과금이 없습니다. 인터넷은 앱 업데이트나 손상·누락된 팩 복구 때만 필요하고, 통화 중 고객 음성이나 직원 답변은 외부 TTS 서비스로 전송되지 않습니다.

## 현재 제품 범위

- Windows 10/11 x64, Intel CPU 기준
- 고객 언어 수동 선택: 영어, 한국어, 중국어, 스페인어, 프랑스어, 독일어, 이탈리아어, 포르투갈어, 러시아어, 아랍어, 힌디어, 베트남어, 태국어, 인도네시아어, 말레이어, 튀르키예어, 네덜란드어, 폴란드어, 우크라이나어, 체코어, 히브리어
- 고객 음성 → 일본어 텍스트
- 직원 일본어 음성 → 선택된 고객 언어 텍스트 + TTS
- 로컬 TTS: Supertonic 3의 31개 언어와 Apache-2.0 Kokoro Mandarin 팩. 태국어·말레이어·히브리어는 현재 텍스트 번역만 지원
- 마이크와 Windows WASAPI `PC playback` 입력 선택
- 로컬 TTS/pygame 출력 장치 선택 및 시스템 기본 장치 fallback
- 일본어 기본 UI, 한국어·영어·중국어·스페인어 화면 전환
- 번역 기록 지우기, 번역 교정 저장, 완료된 답변 다시 듣기

자동 언어 감지는 속도와 오감지 비용 때문에 제품 경로에서 제거했습니다. 일본어 고객 입력을 처리하는 제품도 아닙니다. 일본 직원 발화는 `Space`를 누른 동안만 일본어 모드로 고정됩니다.

## 가장 빠른 실행 방법

### 완성 EXE

1. `dist\RemotePlusTranslator` 폴더 전체를 대상 PC로 복사합니다. EXE 하나만 떼어 복사하면 모델과 DLL을 찾지 못합니다.
2. `RemotePlusTranslator.exe`를 실행합니다.
3. `입력 언어`, `입력 장치`, `출력 장치`를 고릅니다.
4. 검증된 Supertonic·중국어 Kokoro 음성팩이 배포 폴더에 내장되어 있어 별도 다운로드 없이
   바로 사용할 수 있습니다. 팩이 누락된 개발 빌드에서만 자동 다운로드가 복구 경로로 동작합니다.
5. 상단 상태가 `Models ready`/준비 완료인지 확인합니다.
6. 고객 음성을 들려주고 일본어 번역을 확인합니다.
7. 답변할 때 `Space`를 누른 채 일본어로 말하고, 발화를 끝낸 뒤 놓습니다.
8. TTS가 잘렸다면 해당 답변 카드의 소리/다시 듣기 버튼을 누릅니다.

새 고객 통화를 시작할 때 `기록 지우기`를 누르면 메모리 대화 기록이 초기화됩니다. 자동 답변에는
별도의 AI 안내 음성을 붙이지 않고 직원이 말한 답변의 번역문만 재생합니다. 필요한 고객 안내는
호텔의 실제 운영 정책과 통화 안내 절차에서 별도로 처리합니다.

첫 실행은 Whisper와 Hy-MT2를 메모리에 올리므로 일반 발화보다 오래 걸립니다. 준비 완료 전에 마이크 스트림은 열리지 않습니다.

### 소스 개발 실행

```bat
install.bat
run_debug.bat
```

`run_debug.bat`은 이번 실행의 타이밍 로그만 분석합니다. 일반 실행은 `run.bat`, 설치 점검은 `doctor.bat`을 사용합니다.

## 올바른 통화 테스트

- 노트북 마이크 테스트: `입력 장치 = System default input`
- PC에서 재생되는 통화/영상: `입력 장치 = PC playback · ...`
- 처음에는 영어처럼 확실한 한 언어를 선택하고 1~2초 문장으로 확인합니다.
- 직원 답변은 반드시 `Space`를 누른 상태에서 말하기 시작합니다. localhost 제어 요청 직전에 VAD가 먼저 열린 경우 0.75초 이내 segment를 직원 모드로 안전하게 승격하며, 이후 언어·모드·TTS snapshot은 고정됩니다.
- TTS 재생 중 캡처는 음성 되먹임을 막기 위해 잠깐 mute됩니다. 고객과 TTS가 겹치면 고객 음성이 잘릴 수 있으므로 실제 통화 연결 시 echo cancellation 또는 송수신 분리가 필요합니다.

## 처리 구조

```text
마이크/WASAPI loopback
  → 20 ms frame + RMS VAD
  → 최신 발화 1개 큐
  → faster-whisper small CPU INT8
  → 최신 번역 1개 큐
  → llama-server + Hy-MT2 Q4
  → UI 최종 텍스트
  → 직원 답변일 때 로컬 sherpa-onnx TTS → pygame 출력
```

큐, WebSocket subscriber, 이벤트 기록, UI 카드 수는 모두 상한이 있습니다. 새 발화가 시작되면 대기 중인 이전 작업을 버리고, 실행 중이던 이전 결과도 UI나 TTS에 게시하지 않습니다. llama 응답 스트림을 닫을 수 있는 시점에는 실행 중 생성도 취소합니다. Whisper의 네이티브 CPU 디코드는 안전한 중간 취소 API가 없으므로 이미 시작된 한 번의 디코드는 끝까지 계산하되 결과는 폐기합니다.

준비 상태는 `Whisper loaded`와 실제 `llama-server` 프로세스 생존을 함께 확인합니다. 서버가 죽으면 UI도 준비 완료로 남지 않으며, 다음 번역 요청에서 한 번 복구합니다. 포트 충돌 시 새 포트로 재시도하고 llama 출력은 로그에 남깁니다.

## 정확도와 지연 설정

기본값은 CPU 지연을 우선한 실사용 프로필입니다.

- Whisper `small`, INT8, beam 1
- 명백한 반복 루프와 낮은 log probability에서만 beam 2 재시도
- 언어별 호텔 hotword와 보수적 교정 사전
- Hy-MT2 Q4, context 1024, 8 threads
- live preview 비활성화
- Supertonic 2 threads, Mandarin Kokoro 4 threads

일반 발화는 추가 STT 패스를 실행하지 않습니다. 뭉개진 발음처럼 의심스러운 결과에만 정확도 재시도가 들어가며, 두 번째 결과의 log probability가 실제로 더 좋을 때만 채택합니다. 기본 최소 발화는 180ms입니다. `config.toml`의 threshold를 무작정 낮추면 조용한 방 잡음과 TTS 되먹임이 발화로 잡힙니다.

중국어 Kokoro는 이 QA 노트북의 워밍 상태에서 약 5초 음성을 4.46초에 합성했습니다.
Supertonic 언어보다 지연이 크므로 중국어는 짧은 응답을 권장하며, 대상 PC에서 실측해야
합니다. 더 작은 Kokoro INT8는 같은 PC에서 오히려 느려 채택하지 않았습니다.

호텔 용어는 `[stt.language_hotwords]`, `[stt.corrections]`, `[translation.glossary]`, `translation.protected_terms`에서 관리합니다. UI의 교정 저장은 `%LOCALAPPDATA%\RemotePlusTranslator\feedback\corrections.jsonl`에 원자료를 축적하지만 자동 재학습은 하지 않습니다. 충분한 권리 확보 실통화 자료와 정답 전사가 모이기 전에는 Colab fine-tuning보다 hotword·교정·회귀 샘플 관리가 비용 대비 안전합니다.

## 설정과 데이터 위치

우선순위는 다음과 같습니다.

1. 배포 폴더의 `config.toml`: 모델·성능·기본값
2. `%LOCALAPPDATA%\RemotePlusTranslator\config.local.toml`: 관리자가 선택적으로 덮어쓰는 고급 설정
3. `%LOCALAPPDATA%\RemotePlusTranslator\user-settings.json`: UI에서 선택한 언어·TTS·장치

손상·범위 오류·구버전 local/user 설정은 시작을 막지 않고 무시됩니다. 다른 PC에서 존재하지 않는 장치명도 자동으로 건너뛰며 기본 장치를 사용합니다. 사용자 설정은 임시 파일을 거친 atomic replace로 저장하고, 디스크 오류가 나도 이미 적용된 런타임 제어는 성공 응답과 UI 경고로 일관되게 유지합니다.

로그:

- 일반 시작 오류: `%LOCALAPPDATA%\RemotePlusTranslator\logs\startup-error.log`
- llama-server: `%LOCALAPPDATA%\RemotePlusTranslator\logs\llama-server.log`
- 로컬 TTS worker: `%LOCALAPPDATA%\RemotePlusTranslator\logs\local-tts-worker.log`
- 디버그 타이밍: `%LOCALAPPDATA%\RemotePlusTranslator\logs\timing-*.log`
- EXE doctor 결과: `%LOCALAPPDATA%\RemotePlusTranslator\doctor-report.txt`

## 장시간 운영과 종료

- 앱은 Windows named mutex로 중복 실행을 막습니다.
- 앱 창 WebSocket이 끊긴 뒤 설정된 유예 시간이 지나면 FastAPI가 종료됩니다.
- 정상 종료 시 audio, STT/translation/TTS worker, pygame mixer, uvicorn, llama-server를 차례로 닫습니다.
- Windows Job Object가 부모 프로세스 비정상 종료 때 llama-server 같은 자식 프로세스를 함께 정리합니다.
- 로컬 임시 WAV는 재생 직후 삭제하고, 비정상 종료로 남은 1시간 이상 파일은 다음 실행 때 청소합니다.
- 이벤트 기록은 100개, 화면 카드는 20개로 제한됩니다. 기록 지우기는 개인정보 정리에 유용하지만 수 GB 모델 메모리에는 거의 영향을 주지 않습니다.

## 문제 해결

### 계속 준비 중

`llama-server.log`를 확인합니다. 모델 GGUF와 `models\hymt2\llama\llama-server.exe` 및 같은 폴더 DLL이 모두 있어야 합니다. 준비 상태는 매 WebSocket heartbeat마다 실제 프로세스 생존과 다시 맞춰집니다.

### 음성이 중간에 잘림

입력 overflow나 내부 frame queue drop이 나면 잘린 발화를 억지로 번역하지 않고 폐기하며 UI 경고와 디버그 metric을 남깁니다. 다른 CPU 작업을 줄이고 올바른 장치를 선택하세요. 직원 모드는 최대 20초, 고객 모드는 최대 12초입니다.

### TTS가 안 나옴

배포 폴더의 `models\tts`에 두 검증된 팩과 `pack-receipt.json`이 있는지, TTS 토글과 출력 장치를 확인합니다. `/api/tts`의 `installed_languages`에 언어가 없으면 자동 복구 다운로드를 시도하며, 그동안 번역 텍스트만 표시하고 외부 서비스로 우회하지 않습니다. 새 답변이 들어오면 이전 로컬 합성과 재생을 중단하고, 실패한 답변은 카드의 다시 듣기로 다시 생성할 수 있습니다.

### `check check check` 같은 반복

Whisper가 잡음·끊긴 음절을 반복 토큰으로 확장할 때 생깁니다. 3회 이상 연속되는 명백한 단어/구문 루프만 축약하고, 의심 결과는 작은 beam 재시도를 합니다. 정상적인 두 번 강조는 유지합니다.

### 다른 PC에서 장치가 안 보임

장치는 번역마다 찾지 않습니다. 앱 화면 시작 시 조회하고 60초 캐시/주기로 갱신합니다. 선택 변경 때 기존 stream을 먼저 닫고, 3초 안에 닫히지 않으면 새 stream을 중복으로 열지 않습니다.

## 개발 검증과 빌드

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check translator_app tests scripts launcher.py
.\.venv\Scripts\python.exe scripts\benchmark_public_audio.py
.\.venv\Scripts\python.exe scripts\stress_runtime.py --help
.\build.ps1
```

`build.ps1`은 개발용 portable 폴더만 만들며, 설치 프로그램을 상업 배포본처럼 만들지 않는다.
호텔 관리 PC에 넣을 운영본은 먼저 `legal\distributor-info.example.json`을
`legal\distributor-info.local.json`으로 복사한 뒤 실제 호텔/운영 법인의 법적 이름, 주소,
책임자, 연락처와 내부 계약 정책을 채운다. 프로그램 제공자와 실제 통화를 처리하는 호텔 운영자가
다르면 `publisher_*`와 `operator_*`에 각 법인의 정보를 구분해 적고, 같을 때만 같은 정보를 반복한다.
그 뒤 다음처럼 만든다.

```powershell
$env:REMOTEPLUS_SIGN_CERT_SHA1 = "호텔 IT가 발급·배포한 코드 서명 인증서 지문"
.\build.ps1 -CommercialRelease
```

운영 빌드는 미기입 문구, 잘못된 연락처, 누락된 EULA/개인정보 문서, 부적합·만료 임박 인증서,
서명 실패 또는 Inno Setup 누락이 하나라도 있으면 중단된다. 내부 사용 범위를 넘어 별도 법인에
판매·배포하려면 `distribution_scope`를 `third_party_distribution`으로 바꾸고 일본 변호사의
검토 증빙과 SHA-256까지 등록해야 통과한다. 개인 정보와 법률 의견서는 `.gitignore` 대상이며
저장소에 커밋하지 않는다. 운영 기준은 `docs\INTERNAL_COMMERCIAL_USE_SAFETY_KO.md`, 내부
서명 절차는 `docs\AUTHENTICODE_INTERNAL_KO.md`를 따른다.

반복 QA는 `qa.ps1`, 실제 로컬 모델까지 포함한 release QA는 `qa.ps1 -Models`를 사용한다.
이 스크립트는 각 native command의 종료 코드를 즉시 확인하므로 중간 실패가 다음 명령의
성공 코드에 가려지지 않는다.

### EXE를 매번 다시 묶지 않는 빠른 업데이트

`build.ps1` 전체 빌드는 Python 런타임, 네이티브 DLL, 모델까지 조립하는 최종 배포용이다.
앱 코드·UI·프롬프트·설정만 고친 경우에는 전체 빌드 대신 아래 명령을 사용한다.

```powershell
.\update_app.ps1
```

이 명령은 `dist\RemotePlusTranslator\app_update`만 원자적으로 교체하며 모델과 기본 EXE는
건드리지 않는다. 앱을 재시작하면 체크섬 검증을 통과한 업데이트가 우선 로드된다.
복사가 불완전하거나 파일이 우발적으로 손상된 경우에는 업데이트를 무시하고 EXE 내장 버전으로
자동 복귀하며 `%LOCALAPPDATA%\RemotePlusTranslator\logs\update-error.log`에 원인을 남긴다.
SHA-256 manifest는 손상 검사용이며 코드 서명은 아니다. 신뢰할 수 없는 사람이 배포 파일과
manifest를 함께 바꾸는 공격까지 막으려면 별도의 Authenticode/전자서명 배포 절차가 필요하다.
라이브러리 버전, PyInstaller hidden import, C/C++ DLL 또는 `launcher.py`가 바뀐 경우에만
`build.ps1`로 전체 빌드해야 한다.

`build.ps1`은 web/config, faster-whisper/ctranslate2, sounddevice/SoundCard, sherpa-onnx/pygame와 DLL을 수집하고 Whisper·Hy-MT2·llama runtime을 복사한 뒤 완성 EXE로 doctor를 실행합니다. TTS 모델팩은 `%LOCALAPPDATA%\RemotePlusTranslator\models\tts`에 설치되어 앱 업데이트와 분리됩니다. 중국어 텍스트 프런트엔드의 비ASCII Windows 경로 결함을 피하기 위해 검증된 모델을 `%ProgramData%\RemotePlusTranslator\model-cache`에 한 번 복사합니다.

## 웹 배포와 라이선스

Vercel 같은 정적 호스팅만으로는 로컬 마이크/WASAPI, 1GB 이상 모델, 네이티브 llama/ctranslate2 DLL을 실행할 수 없습니다. 웹 UI를 원격 호스팅하면 고객 음성과 텍스트를 외부로 보내게 되어 현재의 로컬 우선·무사용량 과금 구조와 개인정보 경계가 달라집니다. 현재 구조에서는 portable EXE가 맞습니다.

프로젝트 코드는 MIT 라이선스입니다. 모델과 런타임에는 각 공급자의 별도 조건이 적용됩니다. Supertonic 3 모델은 OpenRAIL-M이므로 배포본의 EULA에 사용 제한을 포함하고, 고객에게 AI 번역·합성음성 사용 사실을 알려야 합니다. 운영자는 `THIRD_PARTY_NOTICES.md`, `EULA_JA.md`, `PRIVACY_NOTICE_JA.md`와 개인정보·통화녹음 관련 현지 법률을 확인해야 합니다.

## 현실적인 한계

이 시스템은 단일 혼합 음원에서 겹쳐 말하는 두 사람을 완벽히 분리하지 못하고, 강한 잡음·심한 발음 장애·전화 코덱 손실에서는 오인식할 수 있습니다. 따라서 긴급·의료·안전·알레르기·결제 핵심 내용은 직원이 원문과 번역을 함께 확인하고 재질문하는 운영 절차가 필요합니다. 완전 자동 의사결정이나 직원 확인 없는 계약·결제 확정 용도로 사용해서는 안 됩니다.
