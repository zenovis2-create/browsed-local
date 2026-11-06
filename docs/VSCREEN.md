# 포인터 표시, 창 가드, 에이전트 도구 (vscreen)

가상 모니터를 브라우저로 볼 때 생기는 세 가지 문제를 다루는 선택 기능입니다. 모두 화면 서버와 별도의 작은 Python 프로그램이고, Voxl과 가상 디스플레이 드라이버는 수정하지 않습니다.

## 왜 필요한가

Windows에는 마우스 커서가 하나뿐입니다. 브라우저의 스트림 위에서 마우스를 움직이면 Voxl이 `SendInput`으로 커서를 가상 모니터의 같은 위치로 옮깁니다. 그 커서는 가상 모니터 위에 있어서 실제 모니터에서는 보이지 않고, 스트림 영상(DXGI)에도 커서는 포함되지 않습니다. 그래서 "마우스는 동작하는데 포인터가 안 보이는" 상태가 됩니다. 에이전트가 스크린샷으로 화면을 읽을 때도 포인터와 휠 동작을 알 수 없습니다.

또 Windows는 새 창을 주 모니터(실제 모니터)에 여는 경우가 많아서, 가상 모니터에서 켠 앱이 실제 모니터로 넘어옵니다.

## 포인터 오버레이 (`cursor_overlay.py`)

가상 모니터 위에만 클릭이 통과하는 투명 최상위 창을 띄워 포인터를 직접 그립니다. 그린 것은 화면의 일부이므로 스트림, `/screenshot`, `/record`에 그대로 나옵니다.

| 표시 | 내용 |
| --- | --- |
| 포인터 | 현재 시스템 커서 모양(화살표, I자, 손, 크기 조절, 대기, 금지 등)을 따라 바뀝니다 |
| 클릭 물결 | 클릭 지점에 확산 링. 왼쪽 주황, 오른쪽 파랑, 가운데 보라 |
| 휠 배지 | 포인터 옆 알약 모양. 위로 굴리면 위 삼각형, 아래로 굴리면 아래 삼각형이 노란색으로 켜지고 가로 휠은 좌우로 표시됩니다 |

- 커서가 실제 모니터에 있으면 아무것도 그리지 않습니다. 가상 모니터는 `\\.\DISPLAYn`의 어댑터 이름(`Virtual Display Driver`)으로 자동 식별합니다. 다르게 쓰려면 `--device \\.\DISPLAY5`.
- 옵션: `--scale 1.8`(포인터 크기), `--no-effects`(포인터만), `--debug`.
- 클릭과 휠은 저수준 마우스 훅으로 감지합니다. 입력은 가로채지 않고 그대로 통과시킵니다. 기록하거나 저장하는 것은 없습니다.
- 한계: 영상에 그려 넣는 방식이라 포인터의 지연은 스트림 지연과 같습니다. 오디오·마이크·클립보드 동기화에는 관여하지 않습니다.

## 창 가드 (`window_guard.py`)

규칙은 하나입니다. **가상 모니터에서 입력한 직후(기본 12초) 실제 모니터에 새로 나타난 창은 가상 모니터로 옮깁니다.** 실제 모니터에서 키보드나 마우스를 쓰면 이 상태가 바로 취소됩니다.

안전장치:

- 가드가 시작될 때 이미 있던 모든 창은 대상에서 제외합니다. 스트림을 보는 브라우저, 제어창 같은 기존 창은 절대 옮기지 않습니다.
- 도구창, 툴팁, 작업 표시줄, 숨겨진 UWP 프레임, 소유자가 있는 대화상자, 전체 화면 창, 아주 작은 창은 제외합니다.
- 제목에 `browsed-local` 또는 `가상 화면 제어`가 들어간 창은 옮기지 않습니다. 다른 뷰어 제목은 `--ignore-title`, 앱은 `--ignore-exe`로 제외합니다.
- 창당 한 번만 처리하고, 새 창이 자리를 잡을 시간을 두고 두 번(0.35초, 1.6초 뒤) 확인합니다.
- 옮길 때는 같은 상대 위치를 유지하고 가상 모니터 작업 영역에 맞게 크기를 줄입니다. 배율이 다른 모니터(200%와 100%)로 넘어갈 때 앱이 크기를 다시 스케일하므로 안정될 때까지 다시 맞춥니다. 최대화된 창은 최대화를 유지합니다.
- `--dry-run`은 옮기지 않고 기록만 합니다.

기록은 `windows/logs/window-guard.log`에 한 줄(JSON)씩 남습니다. **창 제목이 들어 있으므로 이슈나 공개 저장소에 올리지 마세요.** 이 폴더는 Git에서 제외됩니다.

한계: 입력이 가상 모니터에서 일어났는지는 마우스 클릭 위치와 키보드 포커스 창으로 추정합니다. 앱이 아주 늦게 창을 띄우면(12초 이상) 옮기지 못합니다.

## 켜기와 끄기

`windows/start.ps1`이 서버를 켠 뒤 `windows/start-helpers.ps1`을 호출하고, `windows/stop.ps1`이 `windows/stop-helpers.ps1`을 호출합니다. 헬퍼 시작이 실패해도 서버에는 영향이 없습니다. 따로 쓰려면:

```powershell
pwsh -NoProfile -File .\windows\start-helpers.ps1                      # 둘 다
pwsh -NoProfile -File .\windows\start-helpers.ps1 -NoGuard             # 포인터 오버레이만
pwsh -NoProfile -File .\windows\start-helpers.ps1 -DryRunGuard         # 가드는 기록만
pwsh -NoProfile -File .\windows\start-helpers.ps1 -IgnoreTitle '내 뷰어 제목'
pwsh -NoProfile -File .\windows\stop-helpers.ps1
```

두 번 실행해도 두 번째 복사본은 바로 종료합니다. 중지는 이 폴더의 스크립트 경로와 일치하는 Python 프로세스만 대상으로 합니다.

## 에이전트 도구 (`vscreen.py`)

Aside, Codex, Claude 같은 에이전트가 가상 모니터를 안정적으로 쓰도록 만든 CLI입니다. 출력은 JSON(UTF-8)입니다. `stream` 좌표는 가상 모니터 왼쪽 위가 (0, 0)인 화면 픽셀이고, 스트림 스크린샷의 좌표와 같습니다.

```powershell
python windows\vscreen\vscreen.py info                         # 모니터 구성, 어느 쪽이 가상인지, 스트림 크기
python windows\vscreen\vscreen.py list                         # 가상 모니터의 창 + 스트림 좌표 (--all 은 전체)
python windows\vscreen\vscreen.py open notepad.exe --wait 15   # 앱을 켜고 창을 가상 모니터로
python windows\vscreen\vscreen.py move --title 메모 --to real  # 창 이동 (virtual | real, --maximize)
python windows\vscreen\vscreen.py focus --title 메모
python windows\vscreen\vscreen.py shot --out s.png             # 가상 모니터 PNG
python windows\vscreen\vscreen.py wait --idle 300              # 화면이 300ms 멈출 때까지 대기
python windows\vscreen\vscreen.py click 960 540 [--button right] [--double]
python windows\vscreen\vscreen.py hover 960 540
python windows\vscreen\vscreen.py scroll 960 540 --dy 3        # 양수 = 아래로
python windows\vscreen\vscreen.py drag 100 100 400 300
python windows\vscreen\vscreen.py type "안녕 hello"            # 유니코드, 줄바꿈 = Enter
python windows\vscreen\vscreen.py key ctrl+l
```

- 마우스 명령은 끝난 뒤 **사용자의 실제 커서를 원래 자리로 되돌립니다**(커서가 원래 가상 모니터에 있었다면 그대로 둡니다). 가상 모니터에 남기려면 `--keep-cursor`.
- `shot`과 `wait`는 Voxl의 `/screenshot`, `/wait`를 씁니다. 자격증명은 `windows/credentials.json`(또는 `--credentials`, 환경변수 `BROWSED_CREDENTIALS`)에서 읽고 출력하거나 기록하지 않습니다. 서버가 꺼져 있으면 `agent-desktop`(설치된 경우)으로 직접 캡처합니다.
- `open`은 시작한 뒤 새로 나타난 창을 가상 모니터로 옮깁니다. 런처 프로세스가 다른 프로세스로 앱을 띄우는 경우를 위해 `--title-contains`, `--exe`로 대상을 좁힐 수 있습니다.
- 한계: Windows 커서가 하나라서 입력 중에는 잠깐 가상 모니터로 건너갑니다. 키보드는 포어그라운드 창으로 가므로 `type` 전에 대상 창을 클릭하거나 `focus` 하세요. UAC와 잠금 화면, 관리자 권한 창에는 입력이 전달되지 않을 수 있습니다.

## Aside와 에이전트 사용 요령

관측과 조작을 분리하면 훨씬 빠르고 정확합니다.

| 목적 | 방법 | 측정 (이 PC) |
| --- | --- | --- |
| 화면 읽기 | 서버의 `GET /screenshot` (1920x1080 원본 PNG, 헤더 `X-Voxl-Seq`) | 약 22 ms |
| 브라우저 페이지 캡처와 비교 | 브라우저 스크린샷은 스트림을 축소·압축해 다시 찍은 것 | 약 456 ms |
| 화면 안정 대기 | `GET /wait?idle=300` 또는 `since=<seq>` | 고정 `sleep` 대신 사용 |
| 앱 켜기, 창 정리 | `vscreen open / list / move / focus` | 창 제목과 스트림 좌표를 구조화된 값으로 |
| 클릭, 입력 | `vscreen click / type / key / scroll`, 또는 페이지의 마우스 이벤트 | 브라우저 경유 없이 직접 |

Aside의 REPL에서 쓰는 예시입니다(자격증명 파일은 읽기만 하고 출력하지 마세요).

```js
const creds = JSON.parse(await fs.readFile(CREDENTIALS_JSON_PATH, 'utf8'));
const auth = 'Basic ' + Buffer.from(`${creds.username}:${creds.password}`).toString('base64');
const base = 'http://127.0.0.1:16901';
const shot = await fetch(base + '/screenshot', { headers: { Authorization: auth } });
const seq = shot.headers.get('x-voxl-seq');
// ... 행동 후 ...
await fetch(`${base}/wait?idle=300&timeout=10000&since=${seq}`, { headers: { Authorization: auth } });
```

브라우저 탭으로 조작할 때는 뷰포트를 스트림 폭(1920)에 맞추면 확대·축소가 없어 페이지 좌표와 스트림 좌표가 1:1이 됩니다(`page.setViewportSize`). 포인터 오버레이를 켜 두면 에이전트의 스크린샷에도 포인터가 찍혀 마지막 동작 위치를 알 수 있습니다.

UI 구조가 필요하면 `agent-desktop`의 접근성 스냅샷이 포인터 없이 창과 컨트롤을 읽고 의미 단위로 조작할 수 있습니다. 이 도구들은 서로 대체재가 아니라 상황에 맞게 섞어 쓰는 것입니다.

## 검증

```powershell
pwsh -NoProfile -File .\scripts\verify.ps1
```

`windows/vscreen`의 단위 테스트(스프라이트, 모니터 선택, 창 배치 계산, 가드 규칙, 입력 좌표·키 조합)를 포함합니다. 실제 화면에 닿는 동작(오버레이 표시, 창 이동, 입력)은 테스트가 장치를 바꾸지 않도록 자동 테스트에서 제외했습니다. 수동 확인 방법은 [VALIDATION.md](VALIDATION.md)를 참고하세요.
