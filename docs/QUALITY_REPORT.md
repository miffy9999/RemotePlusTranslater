# 품질 검증 현황 (0.5.2)

자동 검증:

- pytest 전체 통과가 release 조건
- Ruff 전체 통과가 release 조건
- en/ko/ja/zh/es 공개 음성 fixed-language 실행 smoke test
- Hy-MT2 hotel validation/holdout benchmark
- 실제 모델 반복 실행용 `scripts/stress_runtime.py`
- EXE build 후 `doctor` 실행

## 0.5.2 화이트박스 재검증 결과

2026-07-12 재검증에서 102개 unit/integration test, Ruff, compileall, pip check와
dependency audit를 통과했다. 실제 모델 경로에서는 호텔 번역 corpus 128건이
forward/reverse term score 1.0, fixed-language 공개 음성 execution smoke 5/5였다.
공개 음성 결과는 아래 설명처럼 정확도 점수가 아니다. 실제 Edge TTS 일본어 MP3 생성,
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

`qa.ps1`은 빠른 회귀를, `qa.ps1 -Models`는 실제 Whisper/Hy-MT2까지 실행한다.
각 native command의 non-zero exit code에서 즉시 중단한다.

구조 회귀 항목:

- 발화 시작 시 language/mode/reply/TTS snapshot
- queue supersede와 실행 중 오래된 결과 폐기
- llama process death와 malformed/empty JSON
- EventBus/DOM bounded history
- WebSocket 인증·disconnect subscriber 정리
- user setting schema와 다른 PC 장치 fallback
- Edge synthesis cancel/retry

아직 자동 점수가 보증하지 않는 영역은 실제 30~60분 통화, 겹쳐 말하기, 저속/불안정 인터넷 Edge TTS, 호텔별 전화 코덱, 강한 억양과 뭉개진 발음이다. 공개 음원만으로 이 조건을 대표할 수 없으므로 상업 사용 권리가 확보된 현장 샘플을 익명화해 회귀 세트로 유지해야 한다.

`benchmark_public_audio.py`의 공개 파일에는 권위 있는 정답 transcript가 없으므로 모델 실행·non-empty 결과만 검사한다. 이 결과를 WER/CER 또는 인식 정확도로 표현하면 안 된다. 실제 정확도 gate는 정답 transcript가 포함된 권리 확보 호텔 음성 corpus로 별도 구성해야 한다.
