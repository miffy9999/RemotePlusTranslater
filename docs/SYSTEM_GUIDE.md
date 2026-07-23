# 시스템 가이드 — 0.8.4 네이티브 WAV 브랜치

## 데이터 흐름

```text
고객 음성
  → AudioCapture / VAD
  → queue(maxsize=1)
  → faster-whisper final STT
  → queue(maxsize=1)
  → Hy-MT2 llama-server
  → 일본어 채팅 카드

직원 일본어·영어 텍스트
  → POST /api/reply
  → target 언어 snapshot
  → 같은 번역 queue
  → 고객 언어 채팅 카드 즉시 게시
  → 별도 ReadingWorker
  → 가타카나 + 로마자 표기를 카드에 추가

기존 고객·직원 혼합 WAV
  → localhost 임시 파일(작업 종료 시 삭제)
  → PCM 검증 / 16kHz mono 변환 / VAD
  → 자동 언어 판별 + 필요 구간만 고객 언어·일본어 재시도
  → 고객(추정) / 직원(추정) / 화자 미확인 카드
  → 시간순 원문·번역 + 해당 구간 원음 재생
```

TTS, 출력 장치, 음성팩은 사용하지 않으며 직원은 번역문의 읽기 표기를 보고 직접 말한다.

## ID와 snapshot

AudioCapture의 고객 음성과 직원 텍스트가 하나의 증가 utterance ID를 공유한다. 직원 답변을 제출할 때
목표 언어를 RecognitionJob에 복사하므로 이후 UI 언어 변경이 진행 중 작업에 영향을 주지
않는다. 고객 음성은 VAD가 시작될 때 인식 언어와 목표 언어를 segment에 고정한다.

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

일반 실행은 pywebview의 Windows WebView2 창 하나만 표시하고 FastAPI와 llama-server는 콘솔 없는
백그라운드에서 동작한다. 창을 닫으면 FastAPI lifespan이 controller.stop을 호출한다.
비정상 창 종료는 오류로 기록하고 다음 실행에서 깨끗한 예비 WebView 프로필로 전환한다.
WAV worker 취소 → audio stream 중지 → 활성 llama 요청 취소 →
llama-server 종료 → STT/번역/읽기 worker join 순서다. Windows Job Object 정리는 비정상 종료 때
남은 자식 프로세스를 회수한다.
