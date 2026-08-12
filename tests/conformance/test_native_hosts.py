from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts import run_conformance


ROOT = Path(__file__).resolve().parents[2]


class NativeHostTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock = run_conformance.load_lock()
        self.policy = json.loads((ROOT / "config" / "zabin-mcp.json").read_text(encoding="utf-8"))

    def report(self, host: str) -> dict:
        client = self.lock["clients"][host]
        return {
            "host": host,
            "version": client["expected_output"],
            "command": client["noninteractive_command"],
            "config_source": client["config_source"],
            "workspace_trust": {"state": "approved", "evidence": "interactive"},
            "server_approval": "approved",
            "activation": "active",
            "connected_servers": {
                surface: {
                    "url": server["url"],
                    "service_name": server["service_name"],
                    "server_info_name": server["server_info_name"],
                    "surface": surface,
                    "version": server["version"],
                    "protocol_version": server["protocol_version"],
                    "inventory_sha256": server["inventory_sha256"],
                }
                for surface, server in self.lock["servers"].items()
            },
            "enumerated_tools": {
                surface: sorted(tools)
                for surface, tools in run_conformance._expected_host_tools(self.policy, host).items()
            },
            "allowed_call": {"tool": "get_task", "success": True, "receipt_count": 1},
            "forbidden_call": {"tool": "delete_attachment", "absent_or_rejected": True, "receipt_count": 0},
            "missing_secret": {
                "blocked_before_client_launch": True,
                "enumeration_count": 0,
                "invocation_count": 0,
            },
            "logs": "observer: redacted and clean",
            "raw_streams_persisted": False,
            "cleanup": "complete",
        }

    def test_codex_report_proves_separate_install_trust_activation_and_dispatch_states(self) -> None:
        checks = run_conformance.assess_native_host_report(
            "codex", self.report("codex"), self.lock, self.policy, canaries=["canary"]
        )
        self.assertTrue(run_conformance.passed(checks), checks)
        names = {check.name for check in checks}
        self.assertTrue(
            {
                "host_codex_config", "host_codex_trust", "host_codex_approval",
                "host_codex_activation", "host_codex_identity", "host_codex_tools",
                "host_codex_allowed_call", "host_codex_forbidden_call",
                "host_codex_missing_secret", "host_codex_redaction", "host_codex_cleanup",
            }.issubset(names)
        )

    def test_claude_headless_activation_never_claims_interactive_trust(self) -> None:
        report = self.report("claude_code")
        report["workspace_trust"] = {"state": "unknown", "evidence": "headless"}
        checks = run_conformance.assess_native_host_report(
            "claude_code", report, self.lock, self.policy
        )
        trust = {check.name: check for check in checks}["host_claude_interactive_trust"]
        self.assertEqual("skip", trust.status)
        self.assertFalse(trust.required)
        self.assertIn("headless activation is not approval evidence", trust.detail)

    def test_command_or_config_source_drift_is_not_a_native_host_pass(self) -> None:
        report = self.report("codex")
        report["command"] = ["codex", "exec", "unsafe"]
        report["config_source"] = "ambient user config"
        checks = run_conformance.assess_native_host_report("codex", report, self.lock, self.policy)
        by_name = {check.name: check for check in checks}
        self.assertEqual("fail", by_name["host_codex_command"].status)
        self.assertEqual("fail", by_name["host_codex_config"].status)

    def test_forbidden_transport_receipt_is_failure_even_when_host_reports_rejection(self) -> None:
        report = self.report("codex")
        report["forbidden_call"]["receipt_count"] = 1
        checks = run_conformance.assess_native_host_report("codex", report, self.lock, self.policy)
        self.assertEqual("fail", {check.name: check for check in checks}["host_codex_forbidden_call"].status)

    def test_missing_secret_requires_zero_launch_enumeration_and_invocation(self) -> None:
        for field in ("blocked_before_client_launch", "enumeration_count", "invocation_count"):
            with self.subTest(field=field):
                report = self.report("codex")
                report["missing_secret"][field] = False if field == "blocked_before_client_launch" else 1
                checks = run_conformance.assess_native_host_report("codex", report, self.lock, self.policy)
                self.assertEqual("fail", {check.name: check for check in checks}["host_codex_missing_secret"].status)

    def test_canary_or_credential_header_in_logs_fails(self) -> None:
        for leaked in ("synthetic-canary", "Authorization: Bearer reflected-value"):
            with self.subTest(leaked=leaked):
                report = self.report("codex")
                report["logs"] = leaked
                checks = run_conformance.assess_native_host_report(
                    "codex", report, self.lock, self.policy, canaries=["synthetic-canary"]
                )
                self.assertEqual("fail", {check.name: check for check in checks}["host_codex_redaction"].status)

    def test_raw_stream_retention_or_cleanup_failure_is_non_pass(self) -> None:
        report = self.report("codex")
        report["raw_streams_persisted"] = True
        report["cleanup"] = "failed"
        checks = run_conformance.assess_native_host_report("codex", report, self.lock, self.policy)
        self.assertEqual("fail", {check.name: check for check in checks}["host_codex_cleanup"].status)

    def test_pi_is_explicitly_unsupported_not_skipped_as_if_supported(self) -> None:
        pi = self.lock["clients"]["pi"]
        self.assertFalse(pi["supported"])
        self.assertIn("fails", pi["reason"])
        self.assertIsNone(pi["noninteractive_command"])


if __name__ == "__main__":
    unittest.main()
