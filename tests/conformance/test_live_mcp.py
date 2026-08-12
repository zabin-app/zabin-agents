from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import run_conformance, zabin_doctor


ROOT = Path(__file__).resolve().parents[2]
LIVE = os.environ.get("ZABIN_RUN_LIVE_CONFORMANCE") == "1"


class LifecycleEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock = run_conformance.load_lock()

    def evidence(self, *, disposable: bool = True, project_id: str = "prj_disposable") -> dict:
        return {
            "schema_version": "1.0.0",
            "project_id": project_id,
            "disposable": disposable,
            "stages": [
                {
                    "name": name,
                    "status": "pass",
                    "evidence": f"zabin://evidence/{name}",
                    **({"lease_ttl_seconds": 3600} if name == "sized_worker_lease" else {}),
                    **({"outcome": "consistent"} if name == "checkpoint_reconciliation" else {}),
                }
                for name in self.lock["lifecycle"]["required_stages"]
            ],
        }

    def test_disposable_lifecycle_requires_every_authoritative_stage(self) -> None:
        checks = run_conformance.assess_lifecycle_evidence(
            self.evidence(), self.lock, allowed_projects=set()
        )
        self.assertTrue(run_conformance.passed(checks), checks)
        self.assertEqual(
            set(self.lock["lifecycle"]["required_stages"]),
            {check.name.removeprefix("lifecycle_") for check in checks if check.name != "lifecycle_scope"},
        )

    def test_skipped_unscored_or_missing_lifecycle_stage_is_failure(self) -> None:
        for mutation in ("skip", "missing", "no_evidence"):
            with self.subTest(mutation=mutation):
                evidence = self.evidence()
                if mutation == "missing":
                    evidence["stages"] = evidence["stages"][1:]
                elif mutation == "skip":
                    evidence["stages"][0]["status"] = "skip"
                else:
                    evidence["stages"][0]["evidence"] = ""
                checks = run_conformance.assess_lifecycle_evidence(evidence, self.lock, allowed_projects=set())
                self.assertFalse(run_conformance.passed(checks))

    def test_worker_lease_must_be_sized(self) -> None:
        evidence = self.evidence()
        stage = next(item for item in evidence["stages"] if item["name"] == "sized_worker_lease")
        stage["lease_ttl_seconds"] = 899
        checks = run_conformance.assess_lifecycle_evidence(evidence, self.lock, allowed_projects=set())
        self.assertEqual("fail", {check.name: check for check in checks}["lifecycle_sized_worker_lease"].status)

    def test_production_project_requires_explicit_allowlist(self) -> None:
        evidence = self.evidence(disposable=False, project_id="prj_production")
        denied = run_conformance.assess_lifecycle_evidence(evidence, self.lock, allowed_projects=set())
        allowed = run_conformance.assess_lifecycle_evidence(
            evidence, self.lock, allowed_projects={"prj_production"}
        )
        self.assertEqual("fail", denied[0].status)
        self.assertTrue(run_conformance.passed(allowed), allowed)

    def test_checkpoint_conflict_is_fail_closed(self) -> None:
        evidence = self.evidence()
        stage = next(item for item in evidence["stages"] if item["name"] == "checkpoint_reconciliation")
        stage["outcome"] = "conflict"
        checks = run_conformance.assess_lifecycle_evidence(evidence, self.lock, allowed_projects=set())
        self.assertEqual(
            "fail",
            {check.name: check for check in checks}["lifecycle_checkpoint_reconciliation"].status,
        )

    def test_lifecycle_rejects_duplicates_unexpected_out_of_order_and_open_fields(self) -> None:
        mutations = []
        duplicate = self.evidence()
        duplicate["stages"].insert(1, dict(duplicate["stages"][0]))
        mutations.append(duplicate)
        out_of_order = self.evidence()
        out_of_order["stages"][0], out_of_order["stages"][1] = (
            out_of_order["stages"][1], out_of_order["stages"][0]
        )
        mutations.append(out_of_order)
        unexpected = self.evidence()
        unexpected["stages"].append(
            {"name": "extra", "status": "pass", "evidence": "zabin://extra"}
        )
        mutations.append(unexpected)
        open_root = self.evidence()
        open_root["secret"] = "smuggled"
        mutations.append(open_root)
        open_stage = self.evidence()
        open_stage["stages"][0]["extra"] = True
        mutations.append(open_stage)
        for evidence in mutations:
            with self.subTest(evidence=evidence):
                checks = run_conformance.assess_lifecycle_evidence(
                    evidence, self.lock, allowed_projects=set()
                )
                self.assertFalse(run_conformance.passed(checks))

    def test_required_skip_never_counts_as_overall_pass(self) -> None:
        checks = [
            run_conformance.Check("unit", "pass", "ok"),
            run_conformance.Check("live", "skip", "not run"),
        ]
        self.assertFalse(run_conformance.passed(checks))
        self.assertTrue(
            run_conformance.passed([run_conformance.Check("optional", "skip", "unsupported", required=False)])
        )

    def test_missing_startup_inputs_prevent_live_client_launch(self) -> None:
        with mock.patch("scripts.run_conformance.verify_startup", return_value=[run_conformance.Check("artifact", "fail", "missing")]), mock.patch(
            "scripts.run_conformance.zabin_doctor.probe_live"
        ) as probe, mock.patch("scripts.run_conformance.write_report"):
            with mock.patch("builtins.print"):
                code = run_conformance.main(["--live"])
        self.assertEqual(1, code)
        probe.assert_not_called()

    def test_failed_identity_or_readiness_hard_stops_both_official_processes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            host = root / "host.json"
            lifecycle = root / "lifecycle.json"
            host.write_text("{}", encoding="utf-8")
            lifecycle.write_text("{}", encoding="utf-8")
            with mock.patch(
                "scripts.run_conformance.verify_startup",
                return_value=[run_conformance.Check("startup", "pass", "ok")],
            ), mock.patch(
                "scripts.run_conformance.assess_native_host_report",
                return_value=[run_conformance.Check("host", "pass", "ok")],
            ), mock.patch(
                "scripts.run_conformance.assess_lifecycle_evidence",
                return_value=[run_conformance.Check("lifecycle", "pass", "ok")],
            ), mock.patch(
                "scripts.run_conformance.zabin_doctor.discover_credentials", return_value={}
            ), mock.patch(
                "scripts.run_conformance.probe_locked_surface_identities",
                return_value=[run_conformance.Check("identity", "fail", "mismatch")],
            ), mock.patch(
                "scripts.run_conformance.zabin_doctor.probe_live",
                return_value=[{"name": "surface", "status": "pass", "detail": "ok"}],
            ), mock.patch("scripts.run_conformance.run_redacted") as run_process, mock.patch(
                "scripts.run_conformance.write_report"
            ), mock.patch("builtins.print"):
                code = run_conformance.main(
                    [
                        "--live",
                        "--host-report",
                        f"codex={host}",
                        "--host-report",
                        f"claude_code={host}",
                        "--lifecycle-evidence",
                        os.fspath(lifecycle),
                    ]
                )
            self.assertEqual(1, code)
            run_process.assert_not_called()

    def test_locked_identity_probe_checks_server_info_and_inventory_before_conformance(self) -> None:
        policy = json.loads((ROOT / "config" / "zabin-mcp.json").read_text(encoding="utf-8"))
        credentials = {
            surface: zabin_doctor.Credential(
                surface=surface,
                environment_name=server["credential_environment"],
                file_path=Path("unused"),
                environment_available=True,
                file_available=False,
                _token=f"{surface}-canary",
            )
            for surface, server in self.lock["servers"].items()
        }
        clients = []

        class FakeClient:
            def __init__(self, url, token, timeout):
                self.surface = "worker" if url.endswith("mcp-worker") else "conductor"
                clients.append((url, timeout))

            def initialize(self):
                expected = self_lock["servers"][self.surface]
                return {
                    "protocolVersion": expected["protocol_version"],
                    "serverInfo": {
                        "name": expected["server_info_name"],
                        "version": expected["version"],
                    },
                }

        self_lock = self.lock
        names = {
            server["surface"]: sorted(tool["name"] for tool in server["tools"])
            for server in policy["servers"]
        }
        with mock.patch("scripts.run_conformance.zabin_doctor.McpClient", FakeClient), mock.patch(
            "scripts.run_conformance.zabin_doctor._list_all_tools",
            side_effect=lambda client: names[client.surface],
        ):
            checks = run_conformance.probe_locked_surface_identities(
                self.lock, policy, credentials, timeout=2
            )
        self.assertTrue(run_conformance.passed(checks), checks)
        self.assertEqual(2, len(clients))


@unittest.skipUnless(LIVE, "set ZABIN_RUN_LIVE_CONFORMANCE=1 for canonical localhost probes")
class CanonicalLiveMcpTests(unittest.TestCase):
    def test_two_surfaces_match_protocol_identity_and_exact_inventory(self) -> None:
        lock = run_conformance.load_lock()
        policy = json.loads((ROOT / "config" / "zabin-mcp.json").read_text(encoding="utf-8"))
        credentials = zabin_doctor.discover_credentials(
            policy,
            os.environ,
            {
                "conductor": zabin_doctor.DEFAULT_CONDUCTOR_TOKEN_FILE,
                "worker": zabin_doctor.DEFAULT_WORKER_TOKEN_FILE,
            },
            read_tokens=True,
        )
        checks = zabin_doctor.probe_live(
            policy,
            credentials,
            urls={surface: server["url"] for surface, server in lock["servers"].items()},
            timeout=float(lock["timeouts_seconds"]["readiness"]),
        )
        core = [item for item in checks if item["name"].endswith("_live_surface")]
        self.assertEqual(2, len(core))
        self.assertTrue(all(item["status"] == "pass" for item in core), core)


if __name__ == "__main__":
    unittest.main()
