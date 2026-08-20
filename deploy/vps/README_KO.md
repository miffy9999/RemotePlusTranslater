# VPS 배포 실행서

RemotePlus의 음성 인식과 번역은 계속 호텔 Windows PC에서 실행한다. VPS에는 정적 다운로드
사이트, 서명된 설치 파일, 업데이트 매니페스트만 둔다. 따라서 고객 WAV, 음성, 번역문, 로그는
서버로 전송되지 않으며 별도 Python API나 데이터베이스도 실행하지 않는다.

## 서버를 받기 전에 한 번만 준비

1. `deployment-profile.example.json`을 저장소 밖의 개인 파일로 복사한다.
2. 실제 사이트·다운로드 도메인, 관리자/지원 이메일, 개인정보 URL, 호텔 고정 공인 IP 또는
   VPN CIDR을 입력한다. 예제 도메인과 전 인터넷 허용 CIDR은 생성기가 거부한다.
3. 다음 명령으로 배포 설정을 렌더링한다.

```powershell
.\.venv\Scripts\python.exe scripts\prepare_vps_deployment.py `
  --profile C:\secure\remoteplus-vps.json `
  --output .\dist\vps-deployment
```

4. `config.toml`의 `[updates]`에 생성된 `manifest_url`과 코드 서명 인증서 SHA-1 지문을 넣고
   `enabled = true`로 바꾼다. 인증서 갱신 기간에는 신·구 지문을 함께 넣는다.
5. 실제 운영자 정보, 서명 인증서, Microsoft 서명 WebView2 오프라인 설치 파일을 준비한 뒤
   상업용 설치본과 서버 릴리스 트리를 만든다.

```powershell
$env:REMOTEPLUS_SIGN_CERT_SHA1 = '실제_코드서명_인증서_SHA1'
.\build.ps1 -CommercialRelease
.\publish_release.ps1 -Channel stable
```

`publish_release.ps1`은 유효한 Authenticode 서명과 렌더링된 배포 설정을 요구한다. 같은 버전
경로가 이미 있으면 파일 해시가 완전히 같을 때만 재사용하며 다른 파일로 덮어쓰지 않는다.

## VPS를 받은 날

1. Sakura 관리 화면에서 SSH 호스트 키 지문을 확인하고 최초 접속 때 표시되는 지문과 대조한다.
2. 기존 채팅 서비스의 메모리·디스크·80/443 포트·프록시·DB를 조사한다.
3. `check_capacity.sh --strict` 결과가 통과하고 최근 OOM 또는 swap thrashing이 없는지 확인한다.
4. `remoteplus` 전용 일반 계정을 만들고 그 계정만 `/srv/remoteplus`에 쓰게 한다. 웹 서버는
   해당 경로를 읽기만 하게 한다. SSH 개인키와 비밀번호는 저장소에 넣지 않는다.
5. 생성된 `Caddyfile`을 기존 프록시 설정에 병합한다. 채팅 프로그램 설정을 덮어쓰지 말고
   `caddy validate` 또는 사용 중인 프록시의 설정 검사 후 reload한다.
6. Windows 배포 PC에서 다음 명령으로 업로드한다. 엄격한 용량 검사가 다시 통과해야만
   설치 파일과 매니페스트가 원자적으로 활성화된다.

```powershell
.\deploy_to_vps.ps1 `
  -RemoteHost vps.example.jp `
  -RemoteUser remoteplus `
  -IdentityFile C:\secure\remoteplus_ed25519 `
  -Channel stable
```

7. 허용된 호텔 회선에서 실제 HTTPS 응답, 보안 헤더, 매니페스트, 설치 파일 해시,
   Authenticode와 고정 배포자 인증서를 끝까지 검증한다.

```powershell
.\.venv\Scripts\python.exe scripts\verify_vps_release.py `
  --manifest-url https://download.example.jp/channels/stable/manifest.json `
  --channel stable `
  --trusted-thumbprint 실제_코드서명_인증서_SHA1
```

허용되지 않은 회선에서는 두 도메인이 403을 반환하는지도 확인한다. 문제가 생기면 서버에서
`sh /srv/remoteplus/ops/rollback_channel.sh stable /srv/remoteplus`를 실행한다. 롤백은 직전
매니페스트와 실제 설치 파일 존재를 모두 확인한 뒤 채널만 되돌린다.

## 서버 구조와 공존 기준

```text
/srv/remoteplus/
  site/index.html
  channels/stable/manifest.json
  channels/stable/manifest.previous.json
  releases/0.8.0/RemotePlusTranslator-Setup-0.8.0.exe
  ops/rollback_channel.sh
```

채팅 프로그램 기동 후 가용 메모리 700MB 미만, 디스크 여유 4GB 미만, 최근 OOM, 지속적인
swap thrashing, 80/443 분기 불가 중 하나라도 발견되면 자동 배포를 진행하지 않고 USB 배포를
유지한다. 호텔 공인 IP가 변동형이면 `0.0.0.0/0`으로 열지 말고 관리형 VPN을 구성한다.
