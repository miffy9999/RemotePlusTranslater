# FIXES.md 검토 결과

검토일: 2026-07-05

Claude의 정적 분석을 현재 코드와 실제 실행 결과에 대조했다. 아래는 무조건 수용하지 않고 재현 가능성·제품 목표를 기준으로 결정한 결과다.

## 수용하여 수정

- P0-1/2: HttpOnly SameSite 세션 쿠키, API 인증, Host 검사, WebSocket Origin·쿠키 검사, 음성팩 설치 전 사용자 확인
- P0-3: Hy-MT2 GGUF와 고정 llama.cpp zip의 SHA-256 검증, zip 경로 이탈 검사
- P0-4: loopback 이외 서버 host 설정은 기동 거부
- P1-5: 기본 번역기를 Hy-MT2로 변경, M2M100은 명시적 optional dependency와 안내 오류로 격리
- P1-6/23: 가타카나 경계 치환, 라틴어 용어 단어 경계, 일본어 1글자 `便` 별칭 제거
- P1-7: WebSocket snapshot 재수신 전 화면 기록 초기화
- P1-8: 장치가 연속 두 번 누락될 때만 기본 장치로 복구
- P1-9: 입력 장치 API 검증, 명확한 오류, 재시도 지수 backoff와 경고 억제
- P1-10/11/22: 복수 LCID 분리, 출력 GUID 정규화 비교, 요청 직전 TTS 볼륨 적용
- P1-12/13: 활성 언어 최소 확률과 일본어 가나 우선 분기
- P1-14: WebSocket queue 1초 timeout·ping으로 끊긴 구독자 정리
- P1-15: 모델 기동 45초/요청 15초 분리, load·translate·close 생명주기 잠금 공유
- P2-16: 생성물·개인 설정·피드백 gitignore 보강
- P2-17: 구 `dist/LocalBridge` 제거, 기존 PyInstaller spec 유지, 최종 빌드에서 검증
- P2-18/19: frozen 사용자 데이터는 `%LOCALAPPDATA%\RemotePlusTranslator`, 모델은 EXE 옆 절대경로 사용, CWD 의존 제거
- P2-20/21: 포트·확률·스레드·언어·loopback host 검증과 브라우저 URL 보정
- P3-24/26/27/28/29: 과도한 자막 환각 패턴 제거, 피드백 10MB 회전, 주요 상태 읽기 잠금, llama API 키, 입력 지시를 번역 대상으로 고정

## 보류

- P3-25 언어 기억 만료 후 일본어를 자동 전송: 잘못된 고객 언어 TTS가 나가는 것이 유실보다 위험하다. 현재처럼 경고 후 직원이 고객 언어를 다시 선택하는 정책을 유지한다.

## 검증 근거

- 단위·보안 회귀 테스트
- 실제 Hy-MT2 API-key 기동과 영어→일본어 번역
- 프로젝트 외 CWD에서 모델 절대경로 기동
- 쿠키 없는 REST 401, 악성 Host 403
- 악성 WebSocket Origin 거부, 정상 쿠키·Origin snapshot 수신
- 실제 WASAPI loopback과 SAPI 출력 GUID는 기존 실기 통과 결과 유지
