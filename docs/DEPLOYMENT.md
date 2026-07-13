# Windows 배포

## Portable

`build.ps1` 실행 후 `dist\RemotePlusTranslator` 폴더 전체를 대상 PC로 복사한다. Python,
Windows TTS 언어팩, 별도 음성팩은 필요 없다. `RemotePlusTranslator.exe` 하나만 복사하면
`_internal`, web asset, DLL, 모델이 누락되므로 반드시 폴더 전체를 옮긴다.

첫 실행 전에 빌드 폴더에 다음 모델이 포함되어야 한다.

- `models\whisper`
- `models\hymt2\Hy-MT2-1.8B-Q4_K_M.gguf`
- `models\hymt2\llama\llama-server.exe`

## 현장 확인

1. EXE 실행 및 일본어 UI 확인
2. 고객 언어 선택
3. 대상 PC의 마이크/PC 재생음 입력 장치 선택
4. 고객 음성 → 일본어 카드 확인
5. 직원 일본어 입력 → 고객 언어 카드 확인
6. 가타카나·로마자 읽기 확인
7. 장치 변경과 앱 종료 후 남은 프로세스 확인
8. 30~60분 실제 장치 안정성 확인

설정과 로그는 `%LOCALAPPDATA%\RemotePlusTranslator`에 남는다. 앱 업데이트는 portable 폴더만
교체할 수 있으며 사용자 설정은 유지된다.
