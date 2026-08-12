"""Tests for the safe static and opt-in live Zabin doctor."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from typing import Any, Mapping

from scripts import render_adapters, zabin_doctor


ROOT = Path(__file__).resolve().parents[1]
POLICY = render_adapters.load_and_validate_policy(
    ROOT / "config" / "zabin-mcp.json", ROOT / "schemas" / "mcp-policy.schema.json"
)
SECRETS = {
    "conductor": "conductor-secret-that-must-never-appear",
    "worker": "worker-secret-that-must-never-appear",
}


class FakeMcpTransport:
    def __init__(self, *, mismatch_surface: str | None = None) -> None:
        self.mismatch_surface = mismatch_surface
        self.calls: list[tuple[str, str, str]] = []
        self.servers = {server["surface"]: server for server in POLICY["servers"]}

    def __call__(
        self, url: str, headers: Mapping[str, str], body: bytes, timeout: float
    ) -> zabin_doctor.HttpResponse:
        del timeout
        payload = json.loads(body)
        authorization = headers.get("Authorization", "")
        surface = next((name for name, token in SECRETS.items() if authorization == f"Bearer {token}"), None)
        intended = "conductor" if "conductor" in url else "worker"
        if surface != intended:
            raise zabin_doctor.TransportError("HTTP request rejected with status 401", status=401)
        self.calls.append((surface, payload["method"], payload.get("params", {}).get("name", "")))
        response_headers = {"Mcp-Session-Id": f"session-{surface}"}
        if payload["method"] == "notifications/initialized":
            return zabin_doctor.HttpResponse(202, response_headers, b"")
        if payload["method"] == "initialize":
            result: dict[str, Any] = {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "zabin-mcp", "version": "0.1.0"},
            }
        elif payload["method"] == "tools/list":
            names = [tool["name"] for tool in self.servers[surface]["tools"]]
            if surface == self.mismatch_surface:
                names.remove(names[0])
                names.append("unexpected_tool")
            result = {"tools": [{"name": name} for name in names]}
        elif payload["method"] == "tools/call":
            name = payload["params"]["name"]
            if name == "get_server_info":
                result = {
                    "isError": False,
                    "structuredContent": {
                        "name": "zabin-mcp",
                        "version": "0.1.0",
                        "protocol_version": "2025-11-25",
                        "tool_groups": [],
                        "tools": sorted(tool["name"] for tool in self.servers[surface]["tools"]),
                    },
                }
            elif name == "search_context":
                result = {
                    "isError": True,
                    "structuredContent": {"error_code": "not_found"},
                }
            else:
                raise AssertionError(name)
        else:
            raise AssertionError(payload["method"])
        message = {"jsonrpc": "2.0", "id": payload.get("id"), "result": result}
        event = f"event: message\ndata: {json.dumps(message)}\n\n".encode()
        return zabin_doctor.HttpResponse(200, response_headers, event)


class ResetTransport:
    def __call__(
        self, url: str, headers: Mapping[str, str], body: bytes, timeout: float
    ) -> zabin_doctor.HttpResponse:
        del url, headers, body, timeout
        raise zabin_doctor.TransportError("HTTP request failed (ConnectionResetError)")


class ZabinDoctorTests(unittest.TestCase):
    maxDiff = None

    def credential_files(self, root: Path) -> dict[str, Path]:
        files = {surface: root / f"{surface}.token" for surface in SECRETS}
        for surface, path in files.items():
            path.write_text(SECRETS[surface], encoding="utf-8")
        return files

    def test_static_default_validates_every_contract_without_network_or_secret_read(self) -> None:
        def forbidden_transport(*args: Any, **kwargs: Any) -> zabin_doctor.HttpResponse:
            raise AssertionError("static mode must not use the network")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = self.credential_files(root)
            report = zabin_doctor.run_doctor(
                live=False,
                environ={"ZABIN_MCP_TOKEN": SECRETS["conductor"]},
                token_files=files,
                transport=forbidden_transport,
            )
        self.assertEqual("pass", report["status"])
        self.assertEqual("static", report["mode"])
        self.assertEqual(
            {
                "canonical_mcp_policy",
                "agent_and_model_contracts",
                "recovery_compatibility",
                "adapter_readiness",
                "goose_compatibility",
                "canonical_surface_fingerprints",
            },
            {check["name"] for check in report["checks"]},
        )
        serialized = json.dumps(report)
        for secret in SECRETS.values():
            self.assertNotIn(secret, serialized)
        goose = next(check for check in report["checks"] if check["name"] == "goose_compatibility")
        self.assertEqual("unsupported", goose["support_status"])
        self.assertEqual([], goose["active_artifacts"])
        self.assertTrue(goose["blocking_gate_ids"])
        self.assertIn("active artifacts are disabled", goose["detail"])

    def test_explicit_goose_binary_probe_reports_local_pin_without_support_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / "goose"
            binary.write_bytes(b"pinned-goose-test-binary")
            binary.chmod(0o700)
            digest = zabin_doctor.hashlib.sha256(binary.read_bytes()).hexdigest()
            lock = json.loads(
                (ROOT / "adapters" / "goose" / "client-lock.json").read_text(
                    encoding="utf-8"
                )
            )
            lock["artifact_evidence"]["local_observation"]["sha256"] = digest
            completed = zabin_doctor.subprocess.CompletedProcess(
                [str(binary), "--version"], 0, "1.45.0\n", ""
            )
            with mock.patch(
                "scripts.render_adapters.load_and_validate_goose_lock",
                return_value=lock,
            ), mock.patch("scripts.zabin_doctor.subprocess.run", return_value=completed) as run:
                check = zabin_doctor.diagnose_goose_binary(binary, POLICY)
        self.assertEqual("degraded", check["status"])
        self.assertEqual("unsupported", check["support_status"])
        self.assertTrue(check["version_matches"])
        self.assertTrue(check["digest_matches"])
        self.assertFalse(check["official_artifact_verified"])
        self.assertIn("support remains disabled", check["detail"])
        environment = run.call_args.kwargs["env"]
        self.assertEqual({"GOOSE_PATH_ROOT", "PATH"}, set(environment))
        self.assertFalse(any(secret in json.dumps(check) for secret in SECRETS.values()))

    def test_goose_binary_drift_fails_actionably_and_symlinks_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / "goose"
            binary.write_bytes(b"not-the-pinned-binary")
            binary.chmod(0o700)
            completed = zabin_doctor.subprocess.CompletedProcess(
                [str(binary), "--version"], 0, "9.9.9\n", ""
            )
            with mock.patch("scripts.zabin_doctor.subprocess.run", return_value=completed):
                drift = zabin_doctor.diagnose_goose_binary(binary, POLICY)
            link = root / "goose-link"
            link.symlink_to(binary)
            refused = zabin_doctor.diagnose_goose_binary(link, POLICY)
        self.assertEqual("fail", drift["status"])
        self.assertFalse(drift["version_matches"])
        self.assertEqual("fail", refused["status"])
        self.assertIn("non-symlink regular file", refused["detail"])

    def test_live_probe_checks_exact_surfaces_auth_boundaries_and_degrades_retrieval(self) -> None:
        transport = FakeMcpTransport()
        with tempfile.TemporaryDirectory() as temporary:
            report = zabin_doctor.run_doctor(
                live=True,
                environ={},
                token_files=self.credential_files(Path(temporary)),
                urls={
                    "conductor": "http://local/conductor",
                    "worker": "http://local/worker",
                },
                transport=transport,
            )
        self.assertEqual("degraded", report["status"])
        by_name = {check["name"]: check for check in report["checks"]}
        self.assertEqual("pass", by_name["conductor_live_surface"]["status"])
        self.assertEqual("pass", by_name["worker_live_surface"]["status"])
        self.assertEqual("pass", by_name["conductor_authorization_boundary"]["status"])
        self.assertEqual("pass", by_name["worker_authorization_boundary"]["status"])
        self.assertEqual("degraded", by_name["conductor_optional_retrieval"]["status"])
        self.assertEqual("degraded", by_name["worker_optional_retrieval"]["status"])
        self.assertIn(("conductor", "tools/call", "get_server_info"), transport.calls)
        self.assertNotIn(("worker", "tools/call", "get_server_info"), transport.calls)
        serialized = json.dumps(report)
        for secret in SECRETS.values():
            self.assertNotIn(secret, serialized)

    def test_live_inventory_must_match_canonical_policy_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report = zabin_doctor.run_doctor(
                live=True,
                environ={},
                token_files=self.credential_files(Path(temporary)),
                urls={
                    "conductor": "http://local/conductor",
                    "worker": "http://local/worker",
                },
                transport=FakeMcpTransport(mismatch_surface="worker"),
            )
        self.assertEqual("fail", report["status"])
        worker = next(check for check in report["checks"] if check["name"] == "worker_live_surface")
        self.assertEqual("fail", worker["status"])
        self.assertTrue(worker["missing_tools"])
        self.assertEqual(["unexpected_tool"], worker["unexpected_tools"])
        self.assertNotEqual(worker["expected_fingerprint"], worker["actual_fingerprint"])

    def test_live_requires_credentials_but_reports_names_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = zabin_doctor.run_doctor(
                live=True,
                environ={},
                token_files={"conductor": root / "missing-a", "worker": root / "missing-b"},
                urls={
                    "conductor": "http://local/conductor",
                    "worker": "http://local/worker",
                },
                transport=FakeMcpTransport(),
            )
        self.assertEqual("fail", report["status"])
        self.assertFalse(any(item["live_credential_available"] for item in report["credentials"]))
        self.assertIn("ZABIN_MCP_TOKEN", json.dumps(report))
        self.assertIn("missing-a", json.dumps(report))

    def test_internal_credential_representation_redacts_the_token(self) -> None:
        credential = zabin_doctor.Credential(
            surface="worker",
            environment_name="ZABIN_MCP_WORKER_TOKEN",
            file_path=Path("worker.token"),
            environment_available=True,
            file_available=False,
            _token=SECRETS["worker"],
        )
        self.assertNotIn(SECRETS["worker"], repr(credential))

    def test_help_does_not_advertise_the_grpc_listener_as_streamable_http(self) -> None:
        parser = zabin_doctor.build_parser()
        help_text = parser.format_help()
        self.assertNotIn("http://127.0.0.1:50051/mcp", help_text)
        self.assertIn("explicitly configured Streamable HTTP gateway", help_text)
        self.assertIn("--goose-binary", help_text)
        args = parser.parse_args(
            ["--live", "--live-url", "http://127.0.0.1:50051/mcp", "--json"]
        )
        self.assertTrue(args.live)
        self.assertEqual("http://127.0.0.1:50051/mcp", args.live_url)

    def test_grpc_listener_reset_has_config_derived_safe_transport_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            report = zabin_doctor.run_doctor(
                live=True,
                environ={},
                token_files=self.credential_files(Path(temporary)),
                urls={
                    "conductor": "http://127.0.0.1:50051/mcp",
                    "worker": "http://127.0.0.1:50051/mcp",
                },
                transport=ResetTransport(),
            )
        live_checks = [
            check for check in report["checks"] if check["name"].endswith("_live_surface")
        ]
        self.assertEqual(2, len(live_checks))
        for check in live_checks:
            self.assertIn("port 50051 is the Zabin gRPC listener", check["detail"])
            self.assertIn("not Streamable HTTP", check["detail"])
            self.assertIn("http://127.0.0.1:50052/mcp", check["detail"])
            self.assertIn("http://127.0.0.1:50053/mcp-worker", check["detail"])
        serialized = json.dumps(report)
        for secret in SECRETS.values():
            self.assertNotIn(secret, serialized)

        relocated = json.loads(json.dumps(POLICY))
        by_surface = {server["surface"]: server for server in relocated["servers"]}
        by_surface["conductor"]["transport"]["url"] = "http://127.0.0.1:61052/mcp"
        by_surface["worker"]["transport"]["url"] = "http://127.0.0.1:61053/mcp-worker"
        detail = zabin_doctor._transport_failure_detail(
            "http://127.0.0.1:61051/mcp",
            zabin_doctor.TransportError("HTTP request failed (ConnectionResetError)"),
            relocated,
        )
        self.assertIn("port 61051 is the Zabin gRPC listener", detail)
        self.assertIn("http://127.0.0.1:61052/mcp", detail)
        self.assertIn("http://127.0.0.1:61053/mcp-worker", detail)
        self.assertNotIn("5005", detail)

    def test_machine_and_human_output_are_stable_and_secret_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            files = self.credential_files(Path(temporary))
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = zabin_doctor.main(
                    [
                        "--json",
                        "--conductor-token-file",
                        str(files["conductor"]),
                        "--worker-token-file",
                        str(files["worker"]),
                    ],
                    {"ZABIN_MCP_WORKER_TOKEN": SECRETS["worker"]},
                )
            self.assertEqual(0, result)
            machine = json.loads(stdout.getvalue())
            human = zabin_doctor.render_human(machine)
        self.assertIn("Zabin doctor: PASS", human)
        self.assertIn("ZABIN_MCP_WORKER_TOKEN", human)
        for secret in SECRETS.values():
            self.assertNotIn(secret, stdout.getvalue())
            self.assertNotIn(secret, human)


if __name__ == "__main__":
    unittest.main()
