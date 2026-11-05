import unittest
from pathlib import Path
import subprocess
import tempfile
from unittest import mock

import control_model
from control_model import RequestState, ServerBackend, ServerStatus, parse_status


class StateTests(unittest.TestCase):
    def test_stale_poll_cannot_overwrite_stop_result(self):
        state = RequestState()
        poll = state.begin("status")
        stop = state.begin("stop")
        self.assertTrue(state.finish(stop, ServerStatus("off", "stopped")))
        self.assertFalse(state.finish(poll, ServerStatus("on", "ready")))
        self.assertEqual(state.status.state, "off")

    def test_poll_during_operation_cannot_change_pending_state(self):
        state = RequestState()
        poll = state.begin("status")
        start = state.begin("start")
        self.assertFalse(state.finish(poll, ServerStatus("off", "stopped")))
        self.assertEqual(state.pending_action, start)
        self.assertIsNone(state.begin("stop"))
        self.assertIsNone(state.begin("status"))

    def test_error_cannot_be_described_as_off(self):
        result = parse_status('{"state":"off","code":"ownership_check_failed"}')
        self.assertEqual(result.state, "error")

    def test_unknown_response_and_secret_fields_are_not_displayed(self):
        result = parse_status('{"state":"error","code":"ownership_check_failed","message":"secret-value"}')
        self.assertNotIn("secret-value", result.message)
        self.assertEqual(parse_status("not json").code, "invalid_response")

    def test_light_ready_response(self):
        result = parse_status('{"state":"on","code":"ready","pid":81728}')
        self.assertEqual((result.state, result.pid), ("on", 81728))

    def test_json_non_objects_are_rejected(self):
        for output in ('[]', '[1]', 'null', '"status"', '3'):
            self.assertEqual(parse_status(output).code, "invalid_response")

    def test_missing_powershell_is_actionable_without_starting_process(self):
        with mock.patch.object(control_model, "PWSH", Path("pwsh-not-installed")), mock.patch.object(control_model.subprocess, "run") as run:
            self.assertEqual(ServerBackend().call("start").code, "bridge_unavailable")
            run.assert_not_called()

    def test_timeout_cleans_request_and_does_not_expose_exception(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary)
            script = fixture / "backend.ps1"
            script.write_text("# test fixture", encoding="utf-8")
            with mock.patch.object(control_model, "CONTROL_ROOT", fixture), mock.patch.object(control_model, "PWSH", script), mock.patch.object(control_model.subprocess, "run", side_effect=subprocess.TimeoutExpired("sensitive-fixture", 60)):
                result = ServerBackend().call("start")
                self.assertEqual(result.code, "command_timeout")
                self.assertNotIn("sensitive-fixture", result.message)
            self.assertEqual(list(fixture.glob("request-*.json")), [])


if __name__ == "__main__":
    unittest.main()
