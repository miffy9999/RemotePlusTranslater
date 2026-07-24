# WebView2 오프라인 설치 파일

호텔 운영 설치본을 만들기 전에 Microsoft 공식 WebView2 다운로드 페이지에서 x64용
Evergreen Standalone Installer를 받아 이 폴더에 다음 이름으로 둔다.

`MicrosoftEdgeWebView2RuntimeInstallerX64.exe`

`build.ps1 -CommercialRelease`는 이 파일의 Authenticode 서명이 유효하고 서명 주체에
Microsoft가 포함되는지 확인한다. 파일을 저장소에 커밋하거나 임의 사이트에서 받지 않는다.
완성된 설치 프로그램은 대상 PC에 WebView2가 없을 때 `/silent /install`로 설치한다.

공식 안내: https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution
