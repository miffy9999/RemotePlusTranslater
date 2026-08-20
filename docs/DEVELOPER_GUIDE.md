# 개발자 가이드

## 수정 전에 지켜야 할 불변조건

1. 고객 음성만 STT를 거친다. 직원 답변은 일본어 텍스트다.
2. 고객 언어는 자동 감지하지 않고 UI 선택값을 강제한다.
3. 직원 답변은 제출 순간 목표 언어를 snapshot한다.
4. 번역 카드는 읽기 표기보다 먼저 게시한다.
5. 읽기 보조 때문에 번역 모델을 한 번 더 호출하지 않는다.
6. 새 작업 이후 완료된 오래된 STT/번역 결과는 게시하지 않는다.
7. 사용자 설정은 `%LOCALAPPDATA%`에 schema와 함께 원자적으로 저장한다.

## 파일별 책임

| 파일 | 책임 |
|---|---|
| `audio.py` | 장치·VAD·frame gap·언어 snapshot·공용 ID 예약 |
| `stt.py` | Whisper 한 번 로드, 호텔 hotword와 선택적 품질 재시도 |
| `hymt2.py` | llama-server 포트·health·timeout·cancel·종료 |
| `conversation.py` | worker, queue, stale 검사, typed reply routing |
| `reading.py` | 네 언어 가타카나와 전 언어 로마자 fallback |
| `events.py` | 제한된 history/subscriber fan-out |
| `server.py` | localhost 인증 REST/WebSocket, 장치 probe |
| `web/` | 채팅 카드, 일본어 입력, 읽기 이벤트 병합 |

## 읽기 사전 수정

호텔 고정 문구는 `reading.py`의 `PHRASES`에 소문자·문장부호 제거 형태로 추가한다. 영어와
스페인어 새 단어는 언어별 word 사전에 추가한다. 규칙 fallback을 광범위하게 바꾸면 기존 단어가
퇴행할 수 있으므로 `tests/test_reading.py`에 먼저 회귀 예제를 추가한다.

## 검증

```powershell
qa.ps1
qa.ps1 -Models
```

새 API 필드는 Pydantic strict request와 UI를 함께 바꾼다. 제거된 필드를 조용히 무시하지 말고
422로 거부해 구버전 UI 혼용을 드러낸다.
