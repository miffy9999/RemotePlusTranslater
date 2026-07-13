# 시스템 가이드 — 0.7.0 텍스트 답변 브랜치

## 데이터 흐름

```text
고객 음성
  → AudioCapture / VAD
  → queue(maxsize=1)
  → faster-whisper final STT
  → queue(maxsize=1)
  → Hy-MT2 llama-server
  → 일본어 채팅 카드

직원 일본어 텍스트
  → POST /api/reply
  → target 언어 snapshot
  → 같은 번역 queue
  → 고객 언어 채팅 카드 즉시 게시
  → 별도 ReadingWorker
  → 가타카나 + 로마자 표기를 카드에 추가
```

직원 음성 STT, Space PTT, TTS, 출력 장치, 음성팩은 사용하지 않는다. 이 구조는 직원
마이크가 전화기로 직접 나가는 문제를 프로그램에서 우회하려는 것이 아니라, 직원이 번역문의
읽기 표기를 보고 직접 말하는 운영 방식이다.

## ID와 snapshot

AudioCapture와 직원 텍스트가 하나의 증가 utterance ID를 공유한다. 직원 답변을 제출할 때
목표 언어를 RecognitionJob에 복사하므로 이후 UI 언어 변경이 진행 중 작업에 영향을 주지
않는다. 고객 음성도 VAD가 시작될 때 인식 언어를 segment에 고정한다.

## 최신 작업 정책

STT와 번역 대기 queue는 최신 항목 하나만 유지한다. 새 작업이 시작되면 진행 중 llama 요청을
취소하고, 완료된 결과도 ID가 오래됐으면 게시하지 않는다. faster-whisper 네이티브 디코드는
중간 취소 대신 완료 후 폐기한다.

읽기 queue는 번역 표시와 분리되어 있다. 따라서 pypinyin/AnyAscii 최초 import 또는 긴 읽기
표기가 번역 결과 표시를 막지 않는다. 앱 시작 직후 별도 worker에서 lazy import를 미리 데운다.

## 준비 상태

Whisper와 번역 엔진이 모두 준비된 뒤 AudioCapture를 시작한다. snapshot은 llama-server의 실제
생존 여부도 확인하므로 프로세스가 죽은 뒤 ready 상태를 계속 표시하지 않는다.

## 장치

입력 장치는 UI 요청 때 자식 프로세스에서 검색하고 60초 캐시한다. 변경 시 기존 stream을 닫은
뒤 새 stream 하나만 연다. 이전 stream 종료가 실패하면 상태와 config를 이전 값으로 롤백한다.

## 종료

FastAPI lifespan이 controller.stop을 호출한다. audio stream 중지 → 활성 llama 요청 취소 →
llama-server 종료 → STT/번역/읽기 worker join 순서다. Windows Job Object 정리는 비정상 종료 때
남은 자식 프로세스를 회수한다.
