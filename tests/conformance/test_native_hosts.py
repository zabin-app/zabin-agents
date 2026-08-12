from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts import run_conformance


ROOT = Path(__file__).resolve().parents[2]


class NativeHostTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock = run_conformance.load_lock()
        self.policy = json.loads((ROOT / "config" / "zabin-mcp.json").read_text(encoding="utf-8"))
        self.execution = tempfile.TemporaryDirectory(
            prefix=run_conformance.GOOSE_TEMP_PREFIX
        )
        os.chmod(self.execution.name, 0o700)

    def tearDown(self) -> None:
        self.execution.cleanup()

    def report(self, host: str) -> dict:
        client = self.lock["clients"][host]
        report = {
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
        return report

    def goose_report(self) -> dict:
        goose = self.lock["clients"]["goose"]
        report = {
            "schema_version": "1.0.0",
            "host": "goose",
            "version": goose["expected_output"],
            "binary_sha256": goose["observed_binary_sha256"],
            "compatibility_lock_sha256": goose["compatibility_lock_sha256"],
            "support_status": "unsupported",
            "path_root": {
                "environment": "GOOSE_PATH_ROOT",
                "value": os.fspath(Path(self.execution.name) / "goose-root"),
                "isolated": True,
                "disposable": True,
                "production_unchanged": True,
            },
            "surfaces": {
                surface: {
                    "extension_name": f"zabin-{surface}",
                    "server_identity": {
                        "service_name": server["service_name"],
                        "server_info_name": server["server_info_name"],
                        "surface": surface,
                        "version": server["version"],
                        "protocol_version": server["protocol_version"],
                        "inventory_sha256": server["inventory_sha256"],
                    },
                    "enumerated_tools": sorted(
                        run_conformance._expected_host_tools(self.policy, "goose")[surface]
                    ),
                    "hidden_tool": f"zabin-{surface}__conformance_forbidden",
                    "allowed_call": {
                        "tool": f"zabin-{surface}__get_task",
                        "success": True,
                        "receipt_count": 1,
                    },
                    "forbidden_call": {
                        "tool": f"zabin-{surface}__conformance_forbidden",
                        "rejected_before_transport": True,
                        "receipt_count": 0,
                    },
                    "auth": {
                        "credential_environment": server["credential_environment"],
                        "missing": {"rejected": True, "receipt_count": 0},
                        "swapped": {"rejected": True, "receipt_count": 0},
                    },
                    "drift": {
                        kind: {
                            "rejected_before_credential": True,
                            "credential_receipt_count": 0,
                            "request_receipt_count": 0,
                        }
                        for kind in ("server_info", "inventory", "redirect")
                    },
                }
                for surface, server in self.lock["servers"].items()
            },
            "runtime_policy": {
                "mode": "approve",
                "permissions_mutually_exclusive": True,
                "default_extensions": [],
            },
            "context_discovery": {
                "agents_md": {"observed": True, "marker": "agents-marker"},
                "skills": {"observed": True, "marker": "skill-marker"},
            },
            "timeout_cancellation": {
                "timeout_seconds": 2,
                "timed_out": True,
                "cancel_requested": True,
                "child_terminated": True,
            },
            "logs": "observer: redacted and clean",
            "raw_streams_persisted": False,
            "cleanup": {
                "status": "complete",
                "path_root_removed": True,
                "fixtures_stopped": True,
            },
        }
        report["execution"] = run_conformance.goose_execution_attestation(
            report, self.lock, Path(self.execution.name)
        )
        return report

    def reattest(self, report: dict, root: Path | None = None) -> dict:
        report.pop("execution", None)
        report["execution"] = run_conformance.goose_execution_attestation(
            report, self.lock, root or Path(self.execution.name)
        )
        return report

    def test_goose_evidence_is_scored_but_unsupported_lock_prevents_pass(self) -> None:
        checks = run_conformance.assess_goose_native_report(
            self.goose_report(), self.lock, self.policy, canaries=["synthetic-canary"]
        )
        by_name = {check.name: check for check in checks}
        self.assertEqual("fail", by_name["host_goose_support_gate"].status)
        self.assertTrue(all(
            check.status == "pass"
            for check in checks
            if check.name != "host_goose_support_gate"
        ), checks)
        self.assertFalse(run_conformance.passed(checks))

    def test_goose_requires_exact_qualified_inventory_and_hidden_tool_absence(self) -> None:
        report = self.goose_report()
        report["surfaces"]["worker"]["enumerated_tools"].append(
            "zabin-worker__conformance_forbidden"
        )
        checks = run_conformance.assess_goose_native_report(report, self.lock, self.policy)
        self.assertEqual(
            "fail", {check.name: check for check in checks}["host_goose_worker_inventory"].status
        )

    def test_goose_forbidden_and_auth_receipts_must_stay_zero(self) -> None:
        mutations = (
            ("conductor", "forbidden_call", "receipt_count"),
            ("worker", "auth", "missing", "receipt_count"),
            ("worker", "auth", "swapped", "receipt_count"),
        )
        for path in mutations:
            with self.subTest(path=path):
                report = self.goose_report()
                target = report["surfaces"]
                for component in path[:-1]:
                    target = target[component]
                target[path[-1]] = 1
                checks = run_conformance.assess_goose_native_report(
                    report, self.lock, self.policy
                )
                self.assertFalse(run_conformance.passed(checks))

    def test_goose_receipt_and_execution_mutations_break_content_bindings(self) -> None:
        mutations = []
        allowed = self.goose_report()
        allowed["surfaces"]["conductor"]["allowed_call"]["success"] = False
        mutations.append(allowed)
        receipt = self.goose_report()
        receipt["surfaces"]["worker"]["forbidden_call"]["receipt_count"] = 1
        mutations.append(receipt)
        production = self.goose_report()
        production["path_root"]["production_unchanged"] = False
        mutations.append(production)
        permissions = self.goose_report()
        permissions["runtime_policy"]["permissions_mutually_exclusive"] = False
        mutations.append(permissions)
        for report in mutations:
            with self.subTest(report=report):
                binding = {
                    check.name: check
                    for check in run_conformance.assess_goose_native_report(
                        report, self.lock, self.policy
                    )
                }["host_goose_evidence_binding"]
                self.assertEqual("fail", binding.status)

    def test_goose_path_root_rejects_traversal_symlink_and_production_paths(self) -> None:
        traversal = self.goose_report()
        traversal["path_root"]["value"] = os.fspath(
            Path(self.execution.name) / ".." / "production" / "goose-root"
        )
        self.reattest(traversal)

        production = self.goose_report()
        production["path_root"]["value"] = os.fspath(
            Path.home() / ".config" / "goose"
        )
        self.reattest(production)

        symlink = self.goose_report()
        symlink_path = Path(symlink["path_root"]["value"])
        symlink_path.symlink_to(Path(self.execution.name))
        self.reattest(symlink)
        try:
            for report in (traversal, production, symlink):
                with self.subTest(path=report["path_root"]["value"]):
                    by_name = {
                        check.name: check
                        for check in run_conformance.assess_goose_native_report(
                            report, self.lock, self.policy
                        )
                    }
                    self.assertEqual("fail", by_name["host_goose_path_root"].status)
        finally:
            symlink_path.unlink(missing_ok=True)

    def test_goose_nested_schemas_and_receipt_counts_are_closed(self) -> None:
        extra_surface = self.goose_report()
        extra_surface["surfaces"]["worker"]["allowed_call"]["extra"] = True
        self.reattest(extra_surface)
        bool_count = self.goose_report()
        bool_count["surfaces"]["conductor"]["allowed_call"]["receipt_count"] = True
        self.reattest(bool_count)
        extra_topology = self.goose_report()
        extra_topology["surfaces"]["other"] = extra_topology["surfaces"]["worker"]
        self.reattest(extra_topology)
        for report in (extra_surface, bool_count, extra_topology):
            with self.subTest(report=report):
                self.assertTrue(
                    any(
                        check.status == "fail"
                        for check in run_conformance.assess_goose_native_report(
                            report, self.lock, self.policy
                        )[1:]
                    )
                )

    def test_goose_drift_must_be_rejected_before_credential_and_request(self) -> None:
        for kind in ("server_info", "inventory", "redirect"):
            with self.subTest(kind=kind):
                report = self.goose_report()
                report["surfaces"]["conductor"]["drift"][kind][
                    "credential_receipt_count"
                ] = 1
                checks = run_conformance.assess_goose_native_report(
                    report, self.lock, self.policy
                )
                self.assertEqual(
                    "fail",
                    {check.name: check for check in checks}[
                        "host_goose_conductor_drift"
                    ].status,
                )

    def test_goose_runtime_context_timeout_cleanup_and_redaction_fail_closed(self) -> None:
        mutations = []
        mode = self.goose_report()
        mode["runtime_policy"]["mode"] = "auto"
        mutations.append(mode)
        defaults = self.goose_report()
        defaults["runtime_policy"]["default_extensions"] = ["developer"]
        mutations.append(defaults)
        context = self.goose_report()
        context["context_discovery"]["skills"]["observed"] = False
        mutations.append(context)
        timeout = self.goose_report()
        timeout["timeout_cancellation"]["child_terminated"] = False
        mutations.append(timeout)
        cleanup = self.goose_report()
        cleanup["cleanup"]["path_root_removed"] = False
        mutations.append(cleanup)
        leaked = self.goose_report()
        leaked["logs"] = "Authorization: Bearer synthetic-canary"
        mutations.append(leaked)
        for report in mutations:
            with self.subTest(report=report):
                checks = run_conformance.assess_goose_native_report(
                    report, self.lock, self.policy, canaries=["synthetic-canary"]
                )
                self.assertTrue(any(check.status == "fail" for check in checks[1:]))

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
