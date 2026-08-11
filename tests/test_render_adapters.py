"""Tests for the deterministic, fail-closed adapter renderer."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from dataclasses import replace
from pathlib import Path, PurePosixPath
from unittest import mock

from scripts import render_adapters


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "zabin-mcp.json"
SCHEMA_PATH = ROOT / "schemas" / "mcp-policy.schema.json"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "adapter-policy.json"
ENVIRONMENT = {
    "ZABIN_MCP_TOKEN": "conductor-secret-that-must-not-appear",
    "ZABIN_MCP_WORKER_TOKEN": "worker-secret-that-must-not-appear",
}


class RenderAdapterTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.policy = render_adapters.load_and_validate_policy(POLICY_PATH, SCHEMA_PATH)
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def test_canonical_policy_schema_and_server_identities_validate(self) -> None:
        self.assertEqual("1.0.0", self.policy["schema_version"])
        self.assertEqual(
            self.fixture["expected_server_keys"],
            sorted(server["identity"]["client_server_key"] for server in self.policy["servers"]),
        )
        self.assertEqual(
            tuple(self.fixture["expected_environment"]),
            render_adapters.required_environment(self.policy),
        )

    def test_server_identity_mismatch_fails_closed(self) -> None:
        invalid = copy.deepcopy(self.policy)
        invalid["servers"][0]["identity"]["surface_name"] = "worker"
        with self.assertRaisesRegex(render_adapters.RenderError, "identity fields do not match"):
            render_adapters.validate_server_identities(invalid)

        invalid = copy.deepcopy(self.policy)
        invalid["servers"][0]["adapter_requirements"][0]["server_key"] = "wrong"
        with self.assertRaisesRegex(render_adapters.RenderError, "adapter server key"):
            render_adapters.validate_server_identities(invalid)

    def test_policy_must_reference_the_selected_schema_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy_path = root / "policy.json"
            policy = copy.deepcopy(self.policy)
            policy["$schema"] = "schema.json"
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            wrong_schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
            wrong_schema["$id"] = "https://example.invalid/wrong.json"
            schema_path = root / "schema.json"
            schema_path.write_text(json.dumps(wrong_schema), encoding="utf-8")
            with self.assertRaisesRegex(render_adapters.RenderError, "unsupported schema identity"):
                render_adapters.load_and_validate_policy(policy_path, schema_path)

    def test_rendering_is_deterministic_despite_policy_array_order(self) -> None:
        reordered = copy.deepcopy(self.policy)
        reordered["servers"].reverse()
        for server in reordered["servers"]:
            server["tools"].reverse()
            server["adapter_requirements"].reverse()
        for target in render_adapters.TARGETS:
            with self.subTest(target=target):
                self.assertEqual(
                    render_adapters.render_target(self.policy, target),
                    render_adapters.render_target(reordered, target),
                )

    def test_claude_output_has_exact_servers_tools_and_approval_buckets(self) -> None:
        artifacts = render_adapters.render_target(self.policy, "claude_code")
        self.assertEqual(
            self.fixture["expected_artifacts"]["claude_code"],
            [path.as_posix() for path in artifacts],
        )
        mcp = json.loads(artifacts[PurePosixPath(".mcp.json")])
        settings = json.loads(artifacts[PurePosixPath(".claude/settings.json")])
        self.assertEqual(set(self.fixture["expected_server_keys"]), set(mcp["mcpServers"]))
        all_rules = sum(settings["permissions"].values(), [])
        canonical_count = sum(len(server["tools"]) for server in self.policy["servers"])
        self.assertEqual(canonical_count, len(all_rules))
        self.assertEqual(len(all_rules), len(set(all_rules)))
        self.assertTrue(all(rule.startswith("mcp__") for rule in all_rules))
        serialized = b"".join(artifacts.values()).decode("utf-8")
        for secret in ENVIRONMENT.values():
            self.assertNotIn(secret, serialized)

    def test_codex_output_has_exact_enabled_tools_and_approvals(self) -> None:
        artifacts = render_adapters.render_target(self.policy, "codex")
        self.assertEqual(
            self.fixture["expected_artifacts"]["codex"],
            [path.as_posix() for path in artifacts],
        )
        config = tomllib.loads(artifacts[PurePosixPath(".codex/config.toml")].decode("utf-8"))
        worker = config["mcp_servers"]["zabin-worker"]
        self.assertEqual(self.fixture["expected_worker_tools"], worker["enabled_tools"])
        self.assertEqual([], worker["disabled_tools"])
        self.assertEqual("auto", worker["default_tools_approval_mode"])
        self.assertEqual(set(worker["enabled_tools"]), set(worker["tools"]))
        canonical_worker = next(
            server for server in self.policy["servers"] if server["surface"] == "worker"
        )
        expected_modes = {
            tool["name"]: render_adapters.CODEX_APPROVAL_MODES[tool["approval"]]
            for tool in canonical_worker["tools"]
        }
        self.assertEqual(
            expected_modes,
            {name: settings["approval_mode"] for name, settings in worker["tools"].items()},
        )
        self.assertEqual("ZABIN_MCP_WORKER_TOKEN", worker["bearer_token_env_var"])
        for secret in ENVIRONMENT.values():
            self.assertNotIn(secret, artifacts[PurePosixPath(".codex/config.toml")].decode())

    def test_unexpressive_target_is_refused(self) -> None:
        incomplete = replace(
            render_adapters.TARGETS["codex"],
            supports_tool_filtering=False,
            supports_approval_policy=False,
        )
        with self.assertRaisesRegex(
            render_adapters.RenderError, "cannot express required tool filtering and required approval policy"
        ):
            render_adapters.validate_target(self.policy, incomplete)

        incomplete_fields = copy.deepcopy(self.policy)
        incomplete_fields["servers"][0]["adapter_requirements"][1]["required_fields"].remove(
            "enabled_tools"
        )
        with self.assertRaisesRegex(render_adapters.RenderError, "missing required fields: enabled_tools"):
            render_adapters.render_target(incomplete_fields, "codex")

    def test_missing_environment_diagnostic_names_variables_not_values(self) -> None:
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stderr(stderr):
            result = render_adapters.main(
                ["--target", "codex", "--output-dir", temporary, "--dry-run"],
                {"UNRELATED": "sensitive-unrelated-value"},
            )
        self.assertEqual(2, result)
        diagnostic = stderr.getvalue()
        self.assertIn("ZABIN_MCP_TOKEN", diagnostic)
        self.assertIn("ZABIN_MCP_WORKER_TOKEN", diagnostic)
        self.assertNotIn("sensitive-unrelated-value", diagnostic)

    def test_dry_run_emits_deterministic_manifest_without_writing(self) -> None:
        outputs = []
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "not-created"
            for _ in range(2):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    result = render_adapters.main(
                        ["--target", "claude_code", "--output-dir", str(output_dir), "--dry-run"],
                        ENVIRONMENT,
                    )
                self.assertEqual(0, result)
                outputs.append(stdout.getvalue())
            self.assertFalse(output_dir.exists())
        self.assertEqual(outputs[0], outputs[1])
        for secret in ENVIRONMENT.values():
            self.assertNotIn(secret, outputs[0])

    def test_writes_use_atomic_replace_and_check_mode_detects_drift(self) -> None:
        artifacts = render_adapters.render_target(self.policy, "claude_code")
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            with mock.patch("scripts.render_adapters.os.replace", wraps=os.replace) as replace_mock:
                render_adapters.write_artifacts(output_dir, artifacts)
            self.assertEqual(len(artifacts), replace_mock.call_count)
            self.assertFalse(list(output_dir.rglob("*.tmp")))
            self.assertEqual((), render_adapters.check_artifacts(output_dir, artifacts))
            self.assertEqual(
                0,
                render_adapters.main(
                    ["--target", "claude_code", "--output-dir", str(output_dir), "--check"],
                    ENVIRONMENT,
                ),
            )
            (output_dir / ".mcp.json").write_text("stale\n", encoding="utf-8")
            self.assertEqual(
                (PurePosixPath(".mcp.json"),),
                render_adapters.check_artifacts(output_dir, artifacts),
            )
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                result = render_adapters.main(
                    ["--target", "claude_code", "--output-dir", str(output_dir), "--check"],
                    ENVIRONMENT,
                )
            self.assertEqual(1, result)
            self.assertIn(".mcp.json", stderr.getvalue())

    def test_cli_requires_explicit_target_and_output_directory(self) -> None:
        command = [sys.executable, str(ROOT / "scripts" / "render_adapters.py")]
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertEqual(2, result.returncode)
        self.assertIn("--target", result.stderr)
        self.assertIn("--output-dir", result.stderr)

    def test_two_temporary_cli_renders_are_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            for target, output in (("codex", first), ("codex", second)):
                result = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "scripts" / "render_adapters.py"),
                        "--target",
                        target,
                        "--output-dir",
                        output,
                    ],
                    cwd=ROOT,
                    env={**os.environ, **ENVIRONMENT},
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)
            first_files = {
                path.relative_to(first).as_posix(): path.read_bytes()
                for path in Path(first).rglob("*")
                if path.is_file()
            }
            second_files = {
                path.relative_to(second).as_posix(): path.read_bytes()
                for path in Path(second).rglob("*")
                if path.is_file()
            }
            self.assertEqual(first_files, second_files)


if __name__ == "__main__":
    unittest.main()
