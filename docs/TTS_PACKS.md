# 언어 선택과 Windows TTS 음성팩

## 서로 다른 세 가지 언어 기능

- 음성인식: Whisper 단일 다국어 모델
- 번역: Hy-MT2 단일 다국어 모델
- 음성출력: Windows에 언어별로 설치하는 Text-to-Speech 기능

따라서 영어·한국어·중국어·스페인어마다 Whisper나 번역 모델을 다시 받을 필요는 없다. 첫 실행에서 선택한 언어는 자동 감지 후보, 수동 선택 목록, TTS 준비 상태에 함께 적용된다.

## 왜 Windows 음성 파일을 EXE에 넣지 않는가

Windows 음성은 운영체제 빌드와 아키텍처에 맞는 Features on Demand 패키지다. 일반 프로그램 파일처럼 다른 PC에 복사하는 방식은 지원되지 않는다. 0.4.0의 설치 도우미는 Microsoft가 정의한 다음 기능을 Windows Update에서 설치한다.

- `Language.Basic~~~<locale>~0.0.1.0`
- `Language.TextToSpeech~~~<locale>~0.0.1.0`

지원 로캘은 `en-US`, `ko-KR`, `zh-CN`, `es-ES`다. 설치에는 인터넷 연결, 관리자 승인, 조직의 Windows Update 정책 허용이 필요할 수 있다.

공식 문서: https://learn.microsoft.com/windows-hardware/manufacture/desktop/features-on-demand-language-fod

## 온라인 번역기의 TTS가 많은 이유

Google·Azure 같은 온라인 서비스는 대형 신경망 음성 모델을 클라우드 서버에 보관한다. 사용자는 텍스트만 서버에 보내고 합성된 오디오를 내려받으므로 PC에 음성팩이 없어도 된다. 그 대신 네트워크, API 인증, 사용량 비용, 외부 데이터 전송이 필요하다.

RemotePlus는 비용과 개인정보 전송을 피하기 위해 Windows 로컬 음성을 기본값으로 사용한다. 더 자연스러운 완전 로컬 음성이 필요하면 모델별 상업 라이선스, 언어당 저장 용량, CPU 지연을 검증한 뒤 별도 백엔드로 추가해야 한다.
