# 품질 검증 현황 (0.6.0)

자동 검증:

- pytest 전체 통과가 release 조건
- Ruff 전체 통과가 release 조건
- en/ko/ja/zh/es 공개 음성 fixed-language 실행 smoke test
- Hy-MT2 hotel validation/holdout benchmark
- 실제 모델 반복 실행용 `scripts/stress_runtime.py`
- EXE build 후 `doctor` 실행

## 0.6.0 상업용 로컬 TTS 브랜치 검증

2026-07-13 기준 unit/integration test 116개, Ruff, compileall, pip check를 통과했다.
SBOM은 Python dependency closure 69개와 라이선스 파일 87개를 생성하며 누락은 0개다.
새 PyInstaller 산출물에서 `doctor` exit 0, frozen TTS worker JSON protocol, 실제 Supertonic
WAV(247,136 bytes), sherpa/ONNX/CTranslate2 DLL, Edge TTS 파일 0개를 확인했다.

상업성·성능 화이트박스에서 추가로 수정한 항목:

- Edge Read Aloud/`edge-tts`를 완전히 제거하고 검증된 로컬 ONNX 팩만 허용
- `zh_CN-chaowen-medium`이 MIT 저장소 표시와 달리 non-commercial Xiao Ya/BZNSYP에서
  파인튜닝된 계보임을 찾아 상업 카탈로그에서 제거
- 공개 가중치가 non-commercial인 `wuxuedaifu/supertonic_cn`을 참고 후보로만 기록
- Apache-2.0 Kokoro v1.1-zh exact archive의 크기, SHA-256, 내장 LICENSE SHA-256 고정
- HTTPS 다운로드가 HTTP로 downgrade redirect되면 거부
- 네이티브 TTS를 별도 persistent worker에 격리해 오래된 긴 합성을 0.003초 수준에서 종료
- 중국어 FP32/INT8 및 1/2/4/8 threads 비교 후 FP32 4 threads 채택; 이 QA PC에서 warm
  4.99초 음성 합성 4.46초(RTF 0.893), INT8 4 threads는 RTF 2.368로 기각
- 한글 경로 때문에 필요한 중국어 frontend만 ASCII 캐시에 두고, 파일별 해시를 매 로드 전
  검증하며 변조된 캐시는 자동 재생성
- TTS worker stderr 1MB rotation log와 invalid protocol worker reset 추가
- commercial build가 desktop EXE와 TTS worker EXE 모두 Authenticode 서명하지 못하면 실패

현재 QA 산출물 두 EXE는 기능 검증용으로 `NotSigned`다. 인증서 없이 만든 portable build를
상업 최종 릴리스로 승인해서는 안 된다.

## 0.5.2 화이트박스 재검증 결과

2026-07-13 재검증에서 107개 unit/integration test, Ruff, compileall, pip check와
dependency audit를 통과했다. 실제 모델 경로에서는 호텔 번역 corpus 128건이
forward/reverse term score 1.0, fixed-language 공개 음성 execution smoke 5/5였다.
공개 음성 결과는 아래 설명처럼 정확도 점수가 아니다. 실제 로컬 TTS 다국어 WAV 생성,
스트리밍 번역 중 취소, 취소 직후 다음 번역도 확인했다.

이번 검증에서 재현하고 수정한 항목:

- 짧은 Space tap의 release 요청이 사라져 staff mode가 고정되는 UI 경쟁 상태
- 입력 stream 종료 실패 뒤 설정만 새 장치로 표시되는 비원자적 상태
- 잘못된 `user-settings.json` 타입이 시작을 중단하거나 문자열 TTS 값을 적용하는 문제
- 동시 replay/자동 TTS가 오래된 요청을 다시 queue에 넣는 경쟁 상태
- dequeue 직후 staff interrupt가 이전 TTS를 놓치는 짧은 경쟁 구간
- non-streaming llama 요청 때문에 실행 중 번역 취소가 사실상 늦게만 가능했던 문제
- 취소 플래그가 다음 정상 번역 예외를 오염시킬 가능성
- 빠른 업데이트 manifest에 없는 추가 파일을 검출하지 못한 문제
- `config.toml` 최상위 section 오타가 기본값으로 조용히 무시되는 문제
- 1,024-token context에 비해 2,000 CJK character 제한이 과도했던 문제
- 제거된 `llama_cpp`를 참조하던 오래된 평가 스크립트와 native exit-code 은폐
- 새 개발 환경에서 coverage QA를 재현할 `pytest-cov` 고정 의존성 누락
- `run_debug.bat`의 중첩 quote가 CMD에서 Python 경로 전체를 명령명으로 오해하는 문제
- BAT의 `pause`와 PowerShell의 native command 처리가 실제 실패 exit code를 가리는 문제
- 32-bit Python을 설치 후보로 받아 PyInstaller/native runtime이 뒤늦게 실패할 가능성
- 실행 중 번역을 취소하기 전에 translator lock을 기다려 앱 종료가 지연되는 문제
- 디버그 로그 파일 open/flush 실패가 실시간 파이프라인을 방해할 가능성
- 직원 답변 이벤트의 일본어 source를 고객 언어 표시로 사용해 UI가 일본어로 바뀌는 문제
- 첫 실행 HTML과 JavaScript의 기본 화면 언어가 한국어로 고정된 문제

`qa.ps1`은 빠른 회귀를, `qa.ps1 -Models`는 실제 Whisper/Hy-MT2까지 실행한다.
각 native command의 non-zero exit code에서 즉시 중단한다.

구조 회귀 항목:

- 발화 시작 시 language/mode/reply/TTS snapshot
- queue supersede와 실행 중 오래된 결과 폐기
- llama process death와 malformed/empty JSON
- EventBus/DOM bounded history
- WebSocket 인증·disconnect subscriber 정리
- user setting schema와 다른 PC 장치 fallback
- 로컬 synthesis cancel, 최신 요청 우선, 팩 무결성 검증

아직 자동 점수가 보증하지 않는 영역은 실제 30~60분 통화, 겹쳐 말하기, 저사양 CPU의 로컬 TTS 지연, 호텔별 전화 코덱, 강한 억양과 뭉개진 발음이다. 공개 음원만으로 이 조건을 대표할 수 없으므로 상업 사용 권리가 확보된 현장 샘플을 익명화해 회귀 세트로 유지해야 한다.

`benchmark_public_audio.py`의 공개 파일에는 권위 있는 정답 transcript가 없으므로 모델 실행·non-empty 결과만 검사한다. 이 결과를 WER/CER 또는 인식 정확도로 표현하면 안 된다. 실제 정확도 gate는 정답 transcript가 포함된 권리 확보 호텔 음성 corpus로 별도 구성해야 한다.
