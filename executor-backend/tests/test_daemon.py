from __future__ import annotations

import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from executor_backend.daemon import run_auto_nav_if_due


class AutoNavTest(unittest.TestCase):
    def test_auto_nav_requires_initial_manual_settlement(self) -> None:
        state = SimpleNamespace(last_settled_day=0)

        with patch("executor_backend.daemon.subprocess.run") as runner:
            result = run_auto_nav_if_due(SimpleNamespace(), state, day=20260806)

        self.assertEqual(result["status"], "blocked")
        self.assertIn("initial NAV", result["error"])
        runner.assert_not_called()

    def test_auto_nav_skips_day_already_settled(self) -> None:
        state = SimpleNamespace(last_settled_day=20260806)

        with patch("executor_backend.daemon.subprocess.run") as runner:
            result = run_auto_nav_if_due(SimpleNamespace(), state, day=20260806)

        self.assertEqual(result, {"status": "already_settled", "day": 20260806})
        runner.assert_not_called()

    def test_auto_nav_runs_guarded_send_for_unsettled_utc_day(self) -> None:
        state = SimpleNamespace(last_settled_day=20260805)
        completed = subprocess.CompletedProcess([], 0, stdout='{"tx":{"status":"submitted"}}', stderr="")

        with patch("executor_backend.daemon.subprocess.run", return_value=completed) as runner:
            result = run_auto_nav_if_due(SimpleNamespace(), state, day=20260806)

        self.assertEqual(result["status"], "submitted")
        command = runner.call_args.args[0]
        self.assertEqual(command[-4:], ["nav-cycle", "--day", "20260806", "--send"])

    def test_auto_nav_does_not_resubmit_while_chain_confirmation_is_pending(self) -> None:
        state = SimpleNamespace(last_settled_day=20260805)

        with patch("executor_backend.daemon.subprocess.run") as runner:
            result = run_auto_nav_if_due(
                SimpleNamespace(),
                state,
                day=20260806,
                previous_result={"status": "submitted", "day": 20260806},
            )

        self.assertEqual(result["status"], "awaiting_chain_confirmation")
        runner.assert_not_called()

    def test_auto_nav_reports_nav_guard_or_signer_failure(self) -> None:
        state = SimpleNamespace(last_settled_day=20260805)
        completed = subprocess.CompletedProcess([], 1, stdout="", stderr="NAV change exceeds limit")

        with patch("executor_backend.daemon.subprocess.run", return_value=completed):
            result = run_auto_nav_if_due(SimpleNamespace(), state, day=20260806)

        self.assertEqual(result["status"], "failed")
        self.assertIn("NAV change exceeds limit", result["error"])


if __name__ == "__main__":
    unittest.main()
