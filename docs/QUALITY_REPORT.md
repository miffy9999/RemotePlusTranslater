# 품질 검증 현황 — 0.7.0

## 자동 검증

- pytest 84개 통과
- Ruff 통과
- Python compileall 통과
- pip dependency check 통과
- SBOM 68개 구성요소 생성, license 파일 누락 0개
- 고객 언어 snapshot, 직원 목표 언어 snapshot, stale 결과 폐기 테스트
- 번역 즉시 게시 후 reading worker 비동기 병합 테스트
- 한국어/영어/중국어/스페인어 가타카나 및 전 언어 로마자 fallback 테스트
- localhost HTTP/WebSocket 인증과 Origin 제한 테스트
- 구버전 TTS 필드 422 거부와 설정 schema 1 마이그레이션 테스트

## 측정 결과

규칙 기반 읽기 생성은 warm 상태에서 일반 호텔 문장 기준 밀리초 미만이다. pypinyin과 AnyAscii
최초 import는 Windows에서 수십~약 150ms가 걸릴 수 있어 앱 시작 직후 별도 reading worker에서
미리 로드한다. 번역 이벤트는 읽기 생성 전에 게시되므로 이 비용은 번역 표시 지연에 포함되지 않는다.

## 남은 현장 검증

자동 테스트는 실제 전화 코덱, 호텔 장치 드라이버, 강한 억양, 뭉개진 발음, 30~60분 통화를
보증하지 않는다. 권리를 확보한 익명화 현장 corpus와 실제 배포 PC에서 별도 검증해야 한다.
