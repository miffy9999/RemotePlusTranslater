# 언어와 TTS 정책

0.5.0에는 설치형 Windows 음성팩이 없다. 하나의 Whisper small과 하나의 Hy-MT2 모델이 지원 언어 전체를 처리한다. 고객 언어는 화면에서 수동 선택하며 자동 감지는 제품 경로에서 제거됐다.

답변 음성은 Edge Neural TTS를 온라인으로 호출한다. 따라서 언어별 모델 다운로드나 Windows 언어팩은 필요 없지만 인터넷과 Microsoft 서비스 가용성이 필요하다. 출력 선택은 pygame/SDL 장치이며, 사라진 장치는 시스템 기본 출력으로 fallback한다.

지원 언어 목록과 voice mapping은 `translator_app/languages.py`, `translator_app/tts.py`가 기준이다. 새 언어를 추가할 때는 Hy-MT2 지원, Whisper 코드, Edge voice, hotel regression 문장을 모두 확인해야 한다.
