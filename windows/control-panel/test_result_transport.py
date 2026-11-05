"""Focused regression: an inherited child output handle must not delay completion.

The fixture backend starts only a short sleeping child, never the screen server.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest import mock

import control_model


def main() -> None:
    control = control_model.CONTROL_ROOT
    # This explicit test-owned directory stays inside the approved control folder.
    with tempfile.TemporaryDirectory(prefix="transport-test-", dir=control) as temporary:
        fixture = Path(temporary)
        assert fixture.resolve().parent == control.resolve()
        python = str(Path(sys.executable)).replace("'", "''")
        (fixture / "backend.ps1").write_text(
            "param([string]$Action,[string]$ResultFile)\n"
            "$p=[Diagnostics.ProcessStartInfo]::new()\n"
            f"$p.FileName='{python}'\n"
            "$p.ArgumentList.Add('-c');$p.ArgumentList.Add('import time;time.sleep(6)')\n"
            "$p.UseShellExecute=$false;$p.CreateNoWindow=$true\n"
            "$p.WindowStyle=[Diagnostics.ProcessWindowStyle]::Hidden\n"
            "$null=[Diagnostics.Process]::Start($p)\n"
            "[IO.File]::WriteAllText($ResultFile,'{\"state\":\"on\",\"code\":\"ready\",\"pid\":1}')\n",
            encoding="utf-8",
        )
        actual_run = subprocess.run
        with mock.patch.object(control_model, "CONTROL_ROOT", fixture), mock.patch.object(control_model.subprocess, "run", wraps=actual_run) as run:
            started = time.monotonic()
            status = control_model.ServerBackend().call("status")
            elapsed = time.monotonic() - started
            assert status.state == "on", status.code
            kwargs = run.call_args.kwargs
            assert kwargs["stdout"] == subprocess.DEVNULL
            assert kwargs["stderr"] == subprocess.DEVNULL
            assert "capture_output" not in kwargs
            assert elapsed < 4, f"Backend waited for a six-second descendant: {elapsed:.2f}s"
            assert not list(fixture.glob("request-*.json")), "Request result was not cleaned up"
            print(f"PASS: backend returned in {elapsed:.2f}s while descendant lives six seconds; no PIPE; request cleaned")


if __name__ == "__main__":
    main()
