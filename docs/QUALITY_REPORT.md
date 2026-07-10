# 품질 검증 현황 (0.5.0)

자동 검증:

- pytest 전체 통과가 release 조건
- Ruff 전체 통과가 release 조건
- en/ko/ja/zh/es 공개 음성 fixed-language 경로 benchmark
- Hy-MT2 hotel validation/holdout benchmark
- 실제 모델 반복 실행용 `scripts/stress_runtime.py`
- EXE build 후 `doctor` 실행

구조 회귀 항목:

- 발화 시작 시 language/mode/reply/TTS snapshot
- queue supersede와 실행 중 오래된 결과 폐기
- llama process death와 malformed/empty JSON
- EventBus/DOM bounded history
- WebSocket 인증·disconnect subscriber 정리
- user setting schema와 다른 PC 장치 fallback
- Edge synthesis cancel/retry

아직 자동 점수가 보증하지 않는 영역은 실제 30~60분 통화, 겹쳐 말하기, 저속/불안정 인터넷 Edge TTS, 호텔별 전화 코덱, 강한 억양과 뭉개진 발음이다. 공개 음원만으로 이 조건을 대표할 수 없으므로 상업 사용 권리가 확보된 현장 샘플을 익명화해 회귀 세트로 유지해야 한다.
