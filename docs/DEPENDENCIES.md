# 외부 프로그램 준비

## Python과 PowerShell

Python 3.13의 Windows 설치 프로그램에서 Tcl/Tk 지원을 포함하고 실행 명령을 PATH에 등록합니다. `python -m tkinter`가 창을 열어야 합니다. PowerShell 7은 `pwsh -NoProfile -Command '$PSVersionTable.PSVersion'`으로 확인합니다.

GUI는 Python 표준 라이브러리만 사용하며 pip 의존성이 없습니다.

## Voxl v0.3.3

공식 소스 커밋은 `47bb94ec4d253638c1470eb81906676e1bef4b00`입니다. 이 버전의 공식 릴리스 자산은 소스 crate이며, Windows exe 다운로드가 있다고 가정하지 않습니다. 이미 신뢰할 수 있는 빌드가 있다면 그 `voxl.exe` 경로를 setup에 전달할 수 있습니다. setup은 파일의 해시를 현재 PC 설정에 고정하며, 해시 자체가 출처의 신뢰성을 보증하지는 않습니다.

직접 빌드하는 경우 [공식 Windows 빌드 문서](https://github.com/tembo/voxl/blob/47bb94ec4d253638c1470eb81906676e1bef4b00/README.md#windows)를 따릅니다. Rust MSVC 도구 체인, Visual Studio C++ 빌드 도구, LLVM, vcpkg, Node/npm과 esbuild가 필요합니다. 다음은 해당 버전 기준 명령입니다. vcpkg와 LLVM을 먼저 설정해야 합니다.

```powershell
git clone --branch v0.3.3 --depth 1 https://github.com/tembo/voxl.git
cd voxl
vcpkg install x264 libyuv opus --triplet x64-windows-static-md
$env:VCPKGRS_TRIPLET = 'x64-windows-static-md'
npm install -g esbuild
cargo build --release
# 생성 파일: target\release\voxl.exe
```

배포 시에는 Voxl뿐 아니라 링크한 코덱 라이브러리 등의 라이선스도 별도로 확인해야 합니다. browsed-local 릴리스는 이 바이너리를 포함하지 않습니다.

## 가상 디스플레이 드라이버

[공식 25.7.23 릴리스](https://github.com/VirtualDrivers/Virtual-Display-Driver/releases/tag/25.7.23)의 서명된 Virtual Driver Control / Virtual Display Driver를 사용합니다. 설치에는 Windows 관리자 승인이 필요할 수 있습니다. 공식 도구의 안내에 따라 설치한 뒤 Windows 디스플레이 설정에서 다음을 적용합니다.

1. 실제 화면을 주 모니터로 유지합니다.
2. 가상 모니터 1개를 확장 모드로 켭니다.
3. 가상 모니터를 1920×1080, 60 Hz, 가로 방향으로 설정합니다.
4. 실제 화면의 바로 오른쪽에 가상 모니터를 붙이고 위쪽을 맞춥니다.
5. 실제 화면에 제어창과 접속 브라우저를 둡니다.

드라이버 제거·비활성화는 공식 도구 또는 Windows 장치 관리자에서 수행합니다. browsed-local의 **끄기**는 화면 서버만 끕니다. 공식 설치 안내는 [드라이버 저장소](https://github.com/VirtualDrivers/Virtual-Display-Driver#-installation)를 참고하세요.
