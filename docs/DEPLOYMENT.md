# 배포 아키텍처 결정

## 납품 형태

최종 고객은 Python을 설치하지 않습니다. Windows x64용 포터블 폴더 또는 `RemotePlusTranslator-Setup-x.y.z.exe`에 프로그램, Python 런타임, 네이티브 라이브러리와 오프라인 모델이 함께 들어갑니다. PyInstaller의 onedir 방식을 택한 이유는 수 GB 런타임을 매 실행마다 임시 폴더에 푸는 onefile 방식보다 시작과 장애 분석이 안정적이기 때문입니다.

0.4.0 포터블 납품본은 USB 복사만으로 동작하도록 모델을 `models` 폴더에 포함합니다. 첫 실행에서 고객 언어를 선택하며, Windows TTS 음성은 OS 버전별 Features on Demand로 설치합니다. Windows 음성 CAB/DLL 자체는 앱에 재배포하지 않습니다.

배포 파이프라인은 다음 순서입니다.

1. 깨끗한 Windows x64 빌드 머신에서 테스트
2. PyInstaller portable 폴더 생성
3. 모델 없는 상태와 모델 설치 상태 모두 수용 테스트
4. Inno Setup으로 `Setup.exe` 생성
5. 가능하면 조직의 코드 서명 인증서로 EXE와 설치 파일 서명
6. Intel 8GB/16GB/32GB 기준 PC에서 설치·삭제·업데이트 회귀 테스트

## 다른 Intel PC

Intel CPU라는 사실만으로 성능이 같지는 않습니다. 세 가지 프로필을 수용 테스트합니다.

| 등급 | 권장 조건 | STT | 예상 용도 |
|---|---|---|---|
| Lite | 4코어, RAM 8GB | tiny 또는 base INT8 | 짧은 대화, 정확도 양보 |
| Standard | 6코어 이상, RAM 16GB | small INT8 | 기본 납품 사양 |
| Quality | 8코어 이상, RAM 32GB | medium INT8 | 정확도 우선 |

Hy-MT2 1.8B Q4와 Whisper-small이 주 메모리 부담입니다. 0.3.0 경량 배포본은 중복 번역 모델과 Torch를 제외하고, Hy-MT2 프로세스 장애 시 한 번 자동 재시작합니다. RAM 16GB를 기본 권장 사양으로 두고, 8GB PC는 동시 상주와 장시간 안정성을 별도 검증해야 합니다.

## Vercel 검토

Vercel에는 정적 소개 페이지, 설치 파일 다운로드 링크, 사용자 문서를 올릴 수 있습니다. 그러나 현재 로컬 AI 엔진을 Vercel Function으로 옮기는 것은 납품 목표와 맞지 않습니다.

- Python Function 번들 제한보다 모델 묶음이 큼
- Hobby 메모리는 2GB라 번역+Whisper 동시 상주에 부족
- 지속적인 모델 상주와 음성 스트리밍은 cold start와 실행시간 비용 발생
- 음성이 외부 서버로 나가므로 “완전 로컬” 요구가 사라짐
- 트래픽 증가 시 기존 유료 API와 같은 사용량 비용 문제가 재발

권장 구성은 `Vercel = 배포 포털`, `Windows 앱 = 로컬 엔진과 실제 UI`입니다. Vercel 페이지가 HTTPS에서 localhost API를 직접 조작하는 방식은 브라우저의 사설망 접근 정책, 인증서, CORS 문제 때문에 핵심 실행 경로로 사용하지 않습니다. 설치 앱이 자체적으로 `127.0.0.1` 화면을 여는 현재 구조가 안전합니다.

브라우저 WebGPU에 Whisper·번역·TTS를 모두 넣는 방식은 연구용 데모로는 가능하지만, 다중 모델 다운로드 크기, 브라우저별 WebGPU 차이, 메모리 회수, 첫 실행 시간 때문에 고객 납품 기준선으로 삼지 않습니다.

## 네트워크에서 보는 기능

같은 LAN의 다른 장치에서 자막을 보게 할 수는 있습니다. 이 경우 서버 host를 `0.0.0.0`으로 바꾸기 전에 세션 토큰, Windows 방화벽 규칙, 허용 IP, TLS 또는 신뢰된 내부망 조건을 구현해야 합니다. 현재 버전은 개인정보 보호를 위해 localhost만 허용합니다.
