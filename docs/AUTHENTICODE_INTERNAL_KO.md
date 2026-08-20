# 호텔 내부 Authenticode 운영

## 현재 제품에 맞는 선택

불특정 다수에게 다운로드시키는 제품이 아니라 호텔이 관리하는 PC에서만 사용한다면, 공개 OV/EV
인증서를 매년 구매하는 것보다 호텔 IT가 배포한 내부 코드 서명 인증서를 쓰는 방식이 현실적이다.
Microsoft도 자체 서명 인증서를 개발·시험 또는 관리형 기업 내부 배포 용도로 구분한다. 단, 인증서를
신뢰하도록 설정하지 않은 일반 PC에서는 SmartScreen 경고가 나므로 외부 공개 배포에는 사용하지 않는다.

우선순위는 다음과 같다.

1. 호텔에 Active Directory Certificate Services가 있으면 IT가 발급한 Code Signing 인증서를 사용한다.
2. 없으면 전용 내부 서명 인증서를 만들고 공개 인증서만 Group Policy/Intune으로 관리 PC의 신뢰 저장소에
   배포한다.
3. 개인키는 빌드 PC의 Windows 인증서 저장소 또는 하드웨어 보안 장치에만 둔다. PFX를 USB나 Git에
   넣지 않는다.
4. 공개 판매로 전환할 때는 내부 인증서를 재사용하지 말고 Microsoft Store MSIX 또는 공인 OV 인증서로
   전환한다.

## 빌드 연결

Windows SDK의 `signtool.exe`와 Code Signing 용도의 인증서가 준비된 빌드 PC에서 다음처럼 설정한다.

```powershell
$env:REMOTEPLUS_SIGN_CERT_SHA1 = "인증서_지문"
.\build.ps1 -CommercialRelease
```

빌드 스크립트는 인증서의 개인키, 용도, 만료일을 확인하고 앱 EXE와 설치 프로그램을 각각
SHA-256과 타임스탬프로 서명한다. 서명이 `Valid`가 아니면 운영 빌드는 실패한다. 결과는
`dist\signature-report.json`에 남는다.

## 금지

- 개인키나 PFX를 저장소, 메신저, 공개 드라이브에 업로드하지 않는다.
- 비밀번호 없는 PFX를 만들지 않는다.
- 개발용 인증서를 외부 고객에게 수동 설치하도록 요구하지 않는다.
- 인증서 만료 직전에 서명하거나, 퇴사자 계정만 개인키에 접근 가능한 상태로 두지 않는다.

공식 비교표: https://learn.microsoft.com/windows/apps/package-and-deploy/code-signing-options
