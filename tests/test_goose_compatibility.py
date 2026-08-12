"""Fail-closed compatibility checks for the pinned Goose native client."""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_DIR = ROOT / "adapters" / "goose"
LOCK_PATH = ADAPTER_DIR / "client-lock.json"
COMPATIBILITY_PATH = ADAPTER_DIR / "COMPATIBILITY.md"
POLICY_PATH = ROOT / "config" / "zabin-mcp.json"
SHA1 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SECRET_PATTERNS = (
    re.compile(
        r"(?i)[\"']?authorization[\"']?\s*[:=]\s*[\"']?\s*"
        r"(?:bearer|basic)\s+[A-Za-z0-9+/_.=-]{8,}"
    ),
    re.compile(
        r"(?i)[\"']?(?:api[_-]?key|access[_-]?token|secret)[\"']?\s*[:=]\s*"
        r"[\"']?\s*[A-Za-z0-9+/_.=-]{12,}"
    ),
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9+/_.=-]{12,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
)
REQUIRED_GATE_IDS = {
    "official_artifact_integrity",
    "dual_surface_qualification",
    "nonempty_tool_allowlists",
    "credential_indirection_and_redaction",
    "identity_before_credential",
    "permission_exclusivity",
    "headless_approval_boundary",
    "hook_fail_closed_enforcement",
    "recipe_and_workspace_trust",
    "sandbox_containment",
    "cleanup_and_drift",
}


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must contain a JSON object")
    return value


def normalize_extension_name(name: str) -> str:
    """Mirror the pinned Goose name_to_key behavior used by the audit."""
    return "".join(
        character
        if character.isascii() and (character.isalnum() or character in "-_")
        else "_"
        for character in "".join(name.lower().split())
    )


def qualify(extension_name: str, tool_name: str) -> str:
    return f"{normalize_extension_name(extension_name)}__{tool_name}"


def exposed_tools(extension_name: str, advertised: list[str], available: list[str]) -> list[str]:
    """Fail closed instead of inheriting Goose's empty-means-all behavior."""
    if not available:
        raise ValueError("available_tools must be explicit and non-empty")
    allowed = set(available)
    return [qualify(extension_name, tool) for tool in advertised if tool in allowed]


def dispatch(extension_name: str, tool_name: str, available: list[str], receipts: list[str]) -> None:
    """Model the pinned pre-dispatch allowlist check and receipt boundary."""
    if not available or tool_name not in set(available):
        raise LookupError(f"tool not available: {qualify(extension_name, tool_name)}")
    receipts.append(tool_name)


def contains_secret_literal(text: str) -> bool:
    return any(pattern.search(text) is not None for pattern in SECRET_PATTERNS)


def resolve_permission_source_parity(
    principal: str,
    *,
    always_allow: list[str],
    ask_before: list[str],
    never_allow: list[str],
) -> str | None:
    """Mirror v1.45.0 config/permission.rs get_permission ordering."""
    if principal in always_allow:
        return "always_allow"
    if principal in ask_before:
        return "ask_before"
    if principal in never_allow:
        return "never_allow"
    return None


class _LoopbackRecorder:
    """Minimal in-process MCP plus OpenAI-compatible endpoint."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        recorder = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format: str, *args: Any) -> None:
                del args

            def do_POST(self) -> None:
                size = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(size)
                message = json.loads(raw) if raw else {}
                with recorder._lock:
                    recorder.events.append(
                        {
                            "path": self.path,
                            "authorization": self.headers.get("Authorization"),
                            "method": message.get("method"),
                            "tool_name": message.get("params", {}).get("name"),
                            "tools": [
                                tool.get("function", {}).get("name")
                                for tool in message.get("tools", [])
                            ],
                        }
                    )
                if self.path == "/v1/chat/completions":
                    offered = {
                        tool.get("function", {}).get("name")
                        for tool in message.get("tools", [])
                    }
                    has_tool_result = any(
                        entry.get("role") == "tool" for entry in message.get("messages", [])
                    )
                    if "recipe-probe__get_task" in offered and not has_tool_result:
                        delta: dict[str, Any] = {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "audit-call-1",
                                    "type": "function",
                                    "function": {"name": "recipe-probe__get_task", "arguments": "{}"},
                                }
                            ],
                        }
                        finish_reason = "tool_calls"
                    else:
                        delta = {"role": "assistant", "content": "done"}
                        finish_reason = "stop"
                    first_chunk = {
                        "id": "audit-response",
                        "object": "chat.completion.chunk",
                        "created": 0,
                        "model": "gpt-4o-mini",
                        "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                    }
                    last_chunk = {
                        "id": "audit-response",
                        "object": "chat.completion.chunk",
                        "created": 0,
                        "model": "gpt-4o-mini",
                        "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
                    }
                    payload = (
                        "data: "
                        + json.dumps(first_chunk, separators=(",", ":"))
                        + "\n\ndata: "
                        + json.dumps(last_chunk, separators=(",", ":"))
                        + "\n\ndata: [DONE]\n\n"
                    ).encode("utf-8")
                    content_type = "text/event-stream"
                elif message.get("id") is None:
                    self.send_response(202)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                elif message.get("method") == "initialize":
                    payload = json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": message["id"],
                            "result": {
                                "protocolVersion": "2025-03-26",
                                "capabilities": {"tools": {}},
                                "serverInfo": {"name": "hostile-before-identity", "version": "0"},
                            },
                        },
                        separators=(",", ":"),
                    ).encode("utf-8")
                    content_type = "application/json"
                elif message.get("method") == "tools/list":
                    payload = json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": message["id"],
                            "result": {
                                "tools": [
                                    {
                                        "name": "get_task",
                                        "description": "Allowed audit tool",
                                        "inputSchema": {"type": "object"},
                                    },
                                    {
                                        "name": "forbidden",
                                        "description": "Must be filtered",
                                        "inputSchema": {"type": "object"},
                                    },
                                ]
                            },
                        },
                        separators=(",", ":"),
                    ).encode("utf-8")
                    content_type = "application/json"
                else:
                    payload = json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": message["id"],
                            "result": {"content": [{"type": "text", "text": "ok"}]},
                        },
                        separators=(",", ":"),
                    ).encode("utf-8")
                    content_type = "application/json"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                if self.path != "/v1/chat/completions":
                    self.send_header("Mcp-Session-Id", "goose-audit")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.events)


def _native_recipe(port: int) -> dict[str, Any]:
    return {
        "version": "1.0.0",
        "title": "Zabin Goose isolated audit",
        "description": "Bounded native compatibility evidence",
        "instructions": "Return done without calling tools.",
        "prompt": "Return done.",
        "extensions": [
            {
                "type": "streamable_http",
                "name": "recipe-probe",
                "description": "Loopback recorder",
                "uri": f"http://127.0.0.1:{port}/recipe-mcp",
                "headers": {"Authorization": "Bearer ${ZABIN_AUDIT_PROBE_TOKEN}"},
                "env_keys": ["ZABIN_AUDIT_PROBE_TOKEN"],
                "envs": {},
                "timeout": 2,
                "available_tools": ["get_task"],
            }
        ],
    }


def _run_native(binary: Path, path_root: Path, recipe: Path, port: int, token: str | None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("ZABIN_MCP_TOKEN", None)
    environment.pop("ZABIN_MCP_WORKER_TOKEN", None)
    environment.update(
        {
            "GOOSE_PATH_ROOT": os.fspath(path_root),
            "GOOSE_MODE": "approve",
            "OPENAI_API_KEY": "loopback-provider-placeholder",
            "OPENAI_HOST": f"http://127.0.0.1:{port}",
            "OPENAI_BASE_PATH": "v1/chat/completions",
        }
    )
    if token is None:
        environment.pop("ZABIN_AUDIT_PROBE_TOKEN", None)
    else:
        environment["ZABIN_AUDIT_PROBE_TOKEN"] = token
    return subprocess.run(
        [
            os.fspath(binary),
            "run",
            "--recipe",
            os.fspath(recipe),
            "--no-session",
            "--max-turns",
            "1",
            "--provider",
            "openai",
            "--model",
            "gpt-4o-mini",
            "--quiet",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        env=environment,
    )


class GooseCompatibilityTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.lock = load_object(LOCK_PATH)
        cls.policy = load_object(POLICY_PATH)
        cls.compatibility = COMPATIBILITY_PATH.read_text(encoding="utf-8")

    def test_lock_has_exact_closed_top_level_contract(self) -> None:
        self.assertEqual(
            {
                "schema_version",
                "support_status",
                "decision",
                "client",
                "source_evidence",
                "artifact_evidence",
                "canonical_surfaces",
                "goose_semantics",
                "required_gates",
                "blocking_reasons",
                "reevaluation_requirements",
                "primary_sources",
            },
            set(self.lock),
        )
        self.assertEqual("1.0.0", self.lock["schema_version"])

    def test_release_and_local_observation_are_exact_but_distinct(self) -> None:
        client = self.lock["client"]
        self.assertEqual("goose", client["name"])
        self.assertEqual("Apache-2.0", client["license"])
        self.assertEqual("1.45.0", client["version"])
        self.assertEqual("v1.45.0", client["release_tag"])
        self.assertEqual("4dc0420f5704a92806c6628c8f0a3497d7a88759", client["release_commit"])
        self.assertEqual(client["release_commit"], client["source_audit_commit"])
        self.assertRegex(client["release_commit"], SHA1)
        self.assertRegex(client["source_audit_commit"], SHA1)
        artifact = self.lock["artifact_evidence"]
        self.assertIsNone(artifact["official_linux_x86_64_sha256"])
        self.assertFalse(artifact["official_artifact_verified"])
        self.assertRegex(artifact["local_observation"]["sha256"], SHA256)
        self.assertIn("not accepted", artifact["local_observation"]["provenance"])

    def test_release_source_evidence_is_digest_pinned(self) -> None:
        expected = {
            "crates/goose/src/agents/extension_manager.rs": "1b2c735c3df89e0222f293bf15c51fdf40c633d9ea5f58812e09a9d5d0d9c7aa",
            "crates/goose/src/agents/mcp_client.rs": "41c2f4740a679f9c646565eeb4c4c0ae2c323bb81834b06df0f0f5925815b35e",
            "crates/goose/src/config/extensions.rs": "d335231de1d2702723354f4d635903fc6c649fa3c8651b892cec11314ae9fd1c",
            "crates/goose/src/config/permission.rs": "b01629c770ad0909e274239dedf650787c8df7961257f32ff8d2fc77e02f12a6",
            "crates/goose/src/recipe/mod.rs": "95887d76180a1f9b2277eafd97afda9058709fb99bcbc2f17828a3e03a08880d",
            "crates/goose/src/recipe/recipe_extension_adapter.rs": "ab18d536806e051b4913975c0054fc348ffbe69a5c82f1b869138bea0e0c7aa5",
        }
        evidence = self.lock["source_evidence"]
        self.assertEqual(expected, {item["path"]: item["sha256"] for item in evidence})
        self.assertTrue(all(item["commit"] == self.lock["client"]["release_commit"] for item in evidence))

    def test_unsupported_gate_forbids_every_active_artifact(self) -> None:
        self.assertEqual("unsupported", self.lock["support_status"])
        self.assertFalse(self.lock["decision"]["active_credential_artifacts_allowed"])
        self.assertEqual([], self.lock["decision"]["active_artifacts"])
        self.assertEqual(
            {"COMPATIBILITY.md", "client-lock.json"},
            {path.name for path in ADAPTER_DIR.iterdir()},
        )
        self.assertFalse((ADAPTER_DIR / "settings.json.template").exists())
        self.assertFalse((ADAPTER_DIR / "recipe.json.template").exists())
        self.assertNotRegex(self.compatibility, r"\*\*Status:\s*supported\b")

    def test_canonical_inventory_counts_and_fingerprints_are_pinned(self) -> None:
        policy_servers = {server["surface"]: server for server in self.policy["servers"]}
        expected = self.lock["canonical_surfaces"]
        self.assertEqual({"conductor", "worker"}, set(expected))
        for surface, lock_server in expected.items():
            tools = [tool["name"] for tool in policy_servers[surface]["tools"]]
            canonical = json.dumps(
                {"surface": surface, "tools": sorted(tools)},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            digest = hashlib.sha256(canonical).hexdigest()
            self.assertEqual(lock_server["expected_tool_count"], len(tools))
            self.assertEqual(lock_server["expected_inventory_sha256"], digest)

    def test_dual_surfaces_remain_distinct_after_goose_normalization(self) -> None:
        surfaces = self.lock["canonical_surfaces"]
        normalized = {
            surface: normalize_extension_name(value["extension_name"])
            for surface, value in surfaces.items()
        }
        self.assertEqual(
            {surface: value["normalized_extension_name"] for surface, value in surfaces.items()},
            normalized,
        )
        self.assertEqual(2, len(set(normalized.values())))
        self.assertNotEqual(qualify("zabin-conductor", "get_task"), qualify("zabin-worker", "get_task"))
        self.assertNotEqual(normalize_extension_name("A-B"), normalize_extension_name("A_B"))
        self.assertEqual("a-b", normalize_extension_name(" A-B "))

    def test_allowlist_filters_enumeration_and_dispatch_before_receipt(self) -> None:
        advertised = ["get_task", "delete_attachment"]
        allowed = ["get_task"]
        self.assertEqual(["zabin-conductor__get_task"], exposed_tools("zabin-conductor", advertised, allowed))
        receipts: list[str] = []
        with self.assertRaisesRegex(LookupError, "delete_attachment"):
            dispatch("zabin-conductor", "delete_attachment", allowed, receipts)
        self.assertEqual([], receipts)
        dispatch("zabin-conductor", "get_task", allowed, receipts)
        self.assertEqual(["get_task"], receipts)

    def test_empty_allowlist_is_rejected_instead_of_becoming_allow_all(self) -> None:
        self.assertEqual("allow_all", self.lock["goose_semantics"]["available_tools_empty_means"])
        with self.assertRaisesRegex(ValueError, "explicit and non-empty"):
            exposed_tools("zabin-worker", ["get_task"], [])
        receipts: list[str] = []
        with self.assertRaises(LookupError):
            dispatch("zabin-worker", "get_task", [], receipts)
        self.assertEqual([], receipts)

    def test_only_credential_names_are_persisted(self) -> None:
        adapter_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(ADAPTER_DIR.rglob("*"))
            if path.is_file()
        )
        self.assertFalse(contains_secret_literal(adapter_text))
        names = {
            server["credential_environment"]
            for server in self.lock["canonical_surfaces"].values()
        }
        self.assertEqual({"ZABIN_MCP_TOKEN", "ZABIN_MCP_WORKER_TOKEN"}, names)
        self.assertNotIn("headers", self.lock)
        self.assertNotIn("secrets", self.lock)

    def test_secret_literal_canaries_cover_common_json_yaml_and_bare_forms(self) -> None:
        forbidden = (
            '{"Authorization": "Bearer abcdefghijklmnop"}',
            "Authorization: Basic YWxhZGRpbjpvcGVuc2VzYW1l",
            '{"api_key": "abcdefghijklmnop"}',
            "access-token='abcdefghijklmnop'",
            "Bearer abcdefghijklmnop",
            "eyJabcdefgh.ijklmnopq.rstuvwxyz",
        )
        for canary in forbidden:
            with self.subTest(canary=canary):
                self.assertTrue(contains_secret_literal(canary))
        for safe in (
            "ZABIN_MCP_TOKEN",
            "Authorization header name only",
            "Bearer values must not persist",
            "credential_environment: ZABIN_MCP_WORKER_TOKEN",
        ):
            with self.subTest(safe=safe):
                self.assertFalse(contains_secret_literal(safe))

    def test_every_required_gate_is_unique_and_support_derivation_fails_closed(self) -> None:
        gates = self.lock["required_gates"]
        ids = [gate["id"] for gate in gates]
        self.assertEqual(REQUIRED_GATE_IDS, set(ids))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(gate["required"] is True for gate in gates))
        self.assertTrue(all(gate["status"] in {"pass", "fail"} for gate in gates))
        mandatory_pass = all(gate["status"] == "pass" for gate in gates if gate["required"])
        self.assertFalse(mandatory_pass)
        self.assertEqual("supported" if mandatory_pass else "unsupported", self.lock["support_status"])

    def test_decisive_security_gates_are_nonpass(self) -> None:
        gates = {gate["id"]: gate for gate in self.lock["required_gates"]}
        for gate_id in (
            "official_artifact_integrity",
            "credential_indirection_and_redaction",
            "identity_before_credential",
            "permission_exclusivity",
            "headless_approval_boundary",
            "hook_fail_closed_enforcement",
            "recipe_and_workspace_trust",
            "sandbox_containment",
            "cleanup_and_drift",
        ):
            self.assertEqual("fail", gates[gate_id]["status"], gate_id)
            self.assertTrue(gates[gate_id]["evidence"].strip())

    def test_permission_conflict_matches_digest_pinned_release_precedence(self) -> None:
        principal = "zabin-worker__get_task"
        self.assertEqual(
            "always_allow",
            resolve_permission_source_parity(
                principal,
                always_allow=[principal],
                ask_before=[principal],
                never_allow=[principal],
            ),
        )
        semantics = self.lock["goose_semantics"]["permission_conflict_precedence"]
        self.assertEqual(["always_allow", "ask_before", "never_allow"], semantics)
        permission_source = next(
            item for item in self.lock["source_evidence"] if item["path"].endswith("config/permission.rs")
        )
        self.assertEqual(
            "b01629c770ad0909e274239dedf650787c8df7961257f32ff8d2fc77e02f12a6",
            permission_source["sha256"],
        )

    def test_compatibility_doc_covers_each_machine_blocker_and_source(self) -> None:
        self.assertGreaterEqual(self.compatibility.count("**Blocking.**"), 5)
        for marker in (
            "Credential release precedes identity",
            "Header indirection",
            "autonomous by default",
            "Hooks do not provide a fail-closed",
            "Trust and containment",
            "Integrity, cleanup, and drift",
            "zero forbidden server receipts",
        ):
            self.assertIn(marker, self.compatibility)
        for source in self.lock["primary_sources"]:
            self.assertIn(source, self.compatibility)

    def test_optional_native_regressions_are_loopback_isolated_and_cleaned(self) -> None:
        binary_name = os.environ.get("GOOSE_NATIVE_BINARY")
        if not binary_name:
            self.skipTest("set GOOSE_NATIVE_BINARY for bounded loopback native regressions")
        binary = Path(binary_name)
        self.assertTrue(binary.is_absolute())
        self.assertTrue(binary.is_file())
        expected = self.lock["artifact_evidence"]["local_observation"]
        self.assertEqual(expected["sha256"], hashlib.sha256(binary.read_bytes()).hexdigest())
        audit_parent = Path(tempfile.mkdtemp(prefix="goose-zabin-audit-parent-"))
        root = audit_parent / "root"
        recorder = _LoopbackRecorder()
        token = "native-audit-canary-7cf31d19"
        try:
            root.mkdir()
            environment = os.environ.copy()
            environment["GOOSE_PATH_ROOT"] = os.fspath(root)
            completed = subprocess.run(
                [os.fspath(binary), "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
                env=environment,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual(expected["version_output"], completed.stdout.strip())
            self.assertEqual([], list(root.rglob("secrets.yaml")))

            config_dir = root / "config"
            config_dir.mkdir(parents=True, exist_ok=True)
            (config_dir / "config.yaml").write_text(
                "extensions:\n"
                "  profile-probe:\n"
                "    type: streamable_http\n"
                "    name: profile-probe\n"
                "    enabled: true\n"
                f"    uri: \"http://127.0.0.1:{recorder.port}/profile-mcp\"\n"
                "    headers: {}\n"
                "    env_keys: []\n"
                "    envs: {}\n"
                "    timeout: 2\n"
                "    available_tools: [profile_tool]\n",
                encoding="utf-8",
            )
            (config_dir / "permission.yaml").write_text(
                "user:\n"
                "  always_allow: [recipe-probe__get_task]\n"
                "  ask_before: [recipe-probe__get_task]\n"
                "  never_allow: [recipe-probe__get_task]\n"
                "smart_approve:\n"
                "  always_allow: []\n"
                "  ask_before: []\n"
                "  never_allow: [recipe-probe__get_task]\n",
                encoding="utf-8",
            )
            recipe = audit_parent / "recipe.json"
            recipe.write_text(json.dumps(_native_recipe(recorder.port)), encoding="utf-8")

            first_start = len(recorder.snapshot())
            with_secret = _run_native(binary, root, recipe, recorder.port, token)
            self.assertEqual(0, with_secret.returncode, with_secret.stderr)
            with_secret_events = recorder.snapshot()[first_start:]
            mcp_events = [event for event in with_secret_events if event["path"].endswith("-mcp")]
            self.assertTrue(mcp_events)
            self.assertEqual("/recipe-mcp", mcp_events[0]["path"])
            self.assertEqual("initialize", mcp_events[0]["method"])
            self.assertEqual(f"Bearer {token}", mcp_events[0]["authorization"])
            self.assertFalse(any(event["path"] == "/profile-mcp" for event in with_secret_events))
            model_events = [
                event for event in with_secret_events if event["path"] == "/v1/chat/completions"
            ]
            self.assertTrue(model_events)
            self.assertEqual(["recipe-probe__get_task"], model_events[0]["tools"])
            self.assertTrue(
                any(
                    event["path"] == "/recipe-mcp" and event["method"] == "tools/call"
                    for event in with_secret_events
                ),
                f"native tool call missing; stdout={with_secret.stdout!r}; "
                f"stderr={with_secret.stderr!r}; events={with_secret_events!r}",
            )
            self.assertFalse(any(event["tool_name"] == "forbidden" for event in with_secret_events))

            missing_start = len(recorder.snapshot())
            without_secret = _run_native(binary, root, recipe, recorder.port, None)
            self.assertEqual(0, without_secret.returncode, without_secret.stderr)
            missing_events = recorder.snapshot()[missing_start:]
            self.assertFalse(any(event["path"].endswith("-mcp") for event in missing_events))
            self.assertTrue(any(event["path"] == "/v1/chat/completions" for event in missing_events))
            missing_output = without_secret.stdout + without_secret.stderr
            self.assertIn("Failed to start extension 'recipe-probe'", missing_output)
            self.assertIn("continuing without it", missing_output)

            persisted = b"".join(path.read_bytes() for path in root.rglob("*") if path.is_file())
            self.assertNotIn(token.encode("utf-8"), persisted)
            self.assertFalse(any(event["method"] == "delete" for event in recorder.snapshot()))
        finally:
            recorder.close()
            shutil.rmtree(audit_parent)
        self.assertFalse(audit_parent.exists())
        self.assertFalse(recorder.thread.is_alive())


if __name__ == "__main__":
    unittest.main()
