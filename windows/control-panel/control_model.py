"""Server bridge and request ordering; this module never imports Tk or logs secrets."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

CONTROL_ROOT = Path(__file__).resolve().parent
SERVER_ROOT = CONTROL_ROOT.parent
PWSH = Path(shutil.which("pwsh") or "pwsh-not-installed")
SCREEN_URL = "http://127.0.0.1:16901/"

MESSAGES = {
    "ready": "가상 화면 서버가 켜져 있습니다.",
    "already_on": "가상 화면 서버가 이미 켜져 있습니다.",
    "stopped": "가상 화면 서버가 꺼져 있습니다.",
    "already_off": "가상 화면 서버가 이미 꺼져 있습니다.",
    "ownership_check_failed": "서버 소유권을 확인하지 못했습니다. 다른 프로세스를 종료하지 않았습니다.",
    "listener_inspection_failed": "연결 상태를 확인하지 못했습니다. 잠시 후 다시 확인합니다.",
    "port_conflict": "다른 프로그램이 서버 포트를 사용 중입니다. 해당 프로그램은 종료하지 않습니다.",
    "owned_not_listening": "서버 프로세스가 응답하지 않습니다. 끄기를 누른 뒤 다시 켜 보세요.",
    "invalid_launch_state": "현재 서버가 가상 화면 전용 설정과 다릅니다. 설정 확인이 필요합니다.",
    "health_failed": "서버가 응답하지 않거나 인증 상태가 예상과 다릅니다.",
    "action_failed": "서버 명령을 완료하지 못했습니다. 다시 상태를 확인해 주세요.",
    "bridge_unavailable": "PowerShell 7 또는 제어 파일을 찾지 못했습니다.",
    "command_timeout": "서버 확인이 지연되고 있습니다. 잠시 후 다시 확인합니다.",
    "invalid_response": "서버 상태 응답을 확인하지 못했습니다.",
}
NORMAL_STATES = {"ready": "on", "already_on": "on", "stopped": "off", "already_off": "off"}


@dataclass(frozen=True)
class ServerStatus:
    state: str
    code: str
    pid: int | None = None

    @property
    def message(self) -> str:
        return MESSAGES.get(self.code, MESSAGES["invalid_response"])


def parse_status(output: str) -> ServerStatus:
    try:
        data = json.loads(output.lstrip("\ufeff"))
        state, code = data["state"], data["code"]
        if code not in MESSAGES or state not in {"on", "off", "error"}:
            raise ValueError
        expected = NORMAL_STATES.get(code, "error")
        if state != expected:
            raise ValueError
        pid = data.get("pid")
        if pid is not None and (type(pid) is not int or pid <= 0):
            raise ValueError
        return ServerStatus(state, code, pid)
    except (ValueError, TypeError, KeyError, IndexError):
        return ServerStatus("error", "invalid_response")


class ServerBackend:
    def call(self, action: str) -> ServerStatus:
        if action not in {"status", "start", "stop"}:
            return ServerStatus("error", "invalid_response")
        script = CONTROL_ROOT / "backend.ps1"
        if not PWSH.is_file() or not script.is_file():
            return ServerStatus("error", "bridge_unavailable")
        try:
            with tempfile.NamedTemporaryFile(prefix="request-", suffix=".json", dir=CONTROL_ROOT, delete=False) as request:
                result_path = Path(request.name)
            try:
                # No PIPE: a long-lived supervisor may inherit these handles.
                # Wait only for the backend parent, then read its closed JSON file.
                subprocess.run(
                    [str(PWSH), "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(script), "-Action", action, "-ResultFile", str(result_path)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=60,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    check=False,
                )
                return parse_status(result_path.read_text(encoding="utf-8-sig"))
            finally:
                result_path.unlink(missing_ok=True)
        except subprocess.TimeoutExpired:
            return ServerStatus("error", "command_timeout")
        except OSError:
            return ServerStatus("error", "bridge_unavailable")


@dataclass(frozen=True)
class RequestTicket:
    number: int
    generation: int
    action: str


class RequestState:
    """Ignore a stale periodic result if an ON/OFF operation began after it."""

    def __init__(self) -> None:
        self.generation = 0
        self.sequence = 0
        self.pending_action: RequestTicket | None = None
        self.pending_poll: RequestTicket | None = None
        self.status = ServerStatus("error", "invalid_response")

    def begin(self, action: str) -> RequestTicket | None:
        if action == "status":
            if self.pending_action or self.pending_poll:
                return None
        else:
            if self.pending_action or action not in {"start", "stop"}:
                return None
            self.generation += 1
        self.sequence += 1
        ticket = RequestTicket(self.sequence, self.generation, action)
        if action == "status":
            self.pending_poll = ticket
        else:
            self.pending_action = ticket
        return ticket

    def finish(self, ticket: RequestTicket, status: ServerStatus) -> bool:
        if ticket.action == "status":
            if self.pending_poll != ticket:
                return False
            self.pending_poll = None
            if ticket.generation != self.generation or self.pending_action:
                return False
        else:
            if self.pending_action != ticket:
                return False
            self.pending_action = None
        self.status = status
        return True
