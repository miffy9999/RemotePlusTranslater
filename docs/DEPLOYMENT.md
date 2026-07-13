# 배포 결정 (0.5.2)

## 빠른 앱 업데이트와 전체 빌드의 구분

- `translator_app/`, 웹 UI, 프롬프트, 일반 설정 변경: `update_app.ps1` 실행 후 앱 재시작
- 의존성, 네이티브 DLL, PyInstaller spec, `launcher.py` 변경: `build.ps1` 전체 빌드
- 최종 고객 전달본과 설치 프로그램 생성: 반드시 `build.ps1` 전체 빌드

빠른 업데이트는 기존 모델과 런타임을 복사하지 않는다. 업데이트 파일마다 SHA-256을
검증하고, 불완전한 업데이트는 내장 앱으로 자동 폴백한다. 따라서 개발 중 반복 수정은
수 초 내 반영하면서도 마지막으로 검증된 EXE를 복구 경로로 유지한다.
이 checksum은 전송 손상과 불완전 복사를 감지하지만 전자서명은 아니다. 제3자에게 공개
배포할 때는 코드 서명 인증서 또는 별도의 서명된 업데이트 채널을 추가해야 한다.

납품 기준은 Windows x64 PyInstaller `onedir` 포터블 폴더다. Python, Whisper small, Hy-MT2 GGUF, llama.cpp runtime과 네이티브 DLL을 함께 넣는다. 수 GB 파일을 실행마다 임시 해제하는 onefile보다 시작·백신 예외·장애 분석이 안정적이다.

대상 PC에는 Python이나 Windows TTS 언어팩이 필요 없다. Chrome 또는 Edge가 있으면 독립 app 창으로 열고, 없으면 기본 브라우저를 사용한다. Edge Neural TTS 때문에 인터넷은 필요하다.

배포 절차:

1. `pytest`와 Ruff 통과
2. 공개 fixed-language 음성 회귀와 호텔 번역 holdout 확인
3. `build.ps1` 실행
4. `dist\RemotePlusTranslator`의 EXE doctor exit code 확인
5. 폴더 전체를 깨끗한 Windows Intel PC로 복사
6. 시작/장치 검색/STT/양방향 번역/TTS/다시 듣기/창 종료 확인
7. 작업 관리자에서 EXE, llama-server, 브라우저 전용 profile 프로세스 잔존 확인
8. 가능하면 조직 인증서로 EXE와 Setup 서명

권장 최소 RAM은 16GB다. 8GB는 OS와 다른 상담 프로그램까지 함께 쓰면 paging으로 지연이 크게 흔들릴 수 있다. CPU 세대·코어 수에 따라 같은 Intel PC라도 성능이 다르므로 실제 납품 기종에서 30~60분 수용 시험이 필요하다.

설정과 로그는 `%LOCALAPPDATA%\RemotePlusTranslator`에 저장하므로 Program Files 설치 권한과 분리된다. 모델 경로만 배포 폴더 기준 상대 경로다. USB 전달 시 EXE만이 아니라 폴더 전체를 복사한다.

Vercel은 소개/다운로드 페이지로만 사용할 수 있다. 브라우저 정적 페이지는 WASAPI, native CTranslate2/llama DLL, 장기 상주 수 GB 모델을 현재 납품 품질로 실행하지 못한다. 현재 서버는 DNS rebinding, origin, session cookie를 검사하고 localhost만 허용한다. LAN 공개는 별도 인증·TLS·방화벽·개인정보 설계 없이는 허용하지 않는다.
