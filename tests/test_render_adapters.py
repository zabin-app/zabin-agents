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
        for server in self.policy["servers"]:
            key = server["identity"]["client_server_key"]
            rendered = mcp["mcpServers"][key]
            self.assertEqual("http", rendered["type"])
            self.assertEqual(server["transport"]["url"], rendered["url"])
            self.assertEqual(
                f"Bearer ${{{server['credential']['name']}}}",
                rendered["headers"]["Authorization"],
            )
            self.assertNotIn("oauth", rendered)
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
        for server in self.policy["servers"]:
            key = server["identity"]["client_server_key"]
            rendered = config["mcp_servers"][key]
            self.assertEqual(server["transport"]["url"], rendered["url"])
            self.assertEqual(server["credential"]["name"], rendered["bearer_token_env_var"])
            self.assertNotIn("command", rendered)
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
        self.assertTrue(worker["required"])
        self.assertTrue(worker["enabled"])
        self.assertNotIn("auth", worker)
        self.assertNotIn("oauth_resource", worker)
        self.assertNotIn("scopes", worker)
        for secret in ENVIRONMENT.values():
            self.assertNotIn(secret, artifacts[PurePosixPath(".codex/config.toml")].decode())

    def test_template_manifest_is_strict_and_complete(self) -> None:
        render_adapters.validate_template_manifest()

        unknown = dict(render_adapters.TEMPLATES)
        unknown["unexpected"] = next(iter(unknown.values()))
        with self.assertRaisesRegex(render_adapters.RenderError, "unknown unexpected"):
            render_adapters.validate_template_manifest(unknown)

        duplicate_source = dict(render_adapters.TEMPLATES)
        duplicate_source["codex_config"] = replace(
            duplicate_source["codex_config"],
            source=duplicate_source["claude_mcp"].source,
        )
        with self.assertRaisesRegex(render_adapters.RenderError, "duplicate template source"):
            render_adapters.validate_template_manifest(duplicate_source)

        wrong_placeholders = dict(render_adapters.TEMPLATES)
        wrong_placeholders["claude_mcp"] = replace(
            wrong_placeholders["claude_mcp"],
            placeholders=frozenset({"MCP_SERVERS", "UNKNOWN"}),
        )
        with self.assertRaisesRegex(render_adapters.RenderError, "missing UNKNOWN"):
            render_adapters.validate_template_manifest(wrong_placeholders)

    def test_json_and_toml_escaping_round_trip(self) -> None:
        values = ['quote"', "backslash\\", "line\nbreak", "snowman \u2603"]
        json_fragment = render_adapters._json_fragment(values, 2)
        self.assertEqual(values, json.loads(json_fragment))
        toml = "values = " + render_adapters._toml_array(values) + "\n"
        self.assertEqual(values, tomllib.loads(toml)["values"])

    def test_duplicate_unknown_and_empty_policy_entries_fail_closed(self) -> None:
        duplicate_tool = copy.deepcopy(self.policy)
        duplicate_tool["servers"][0]["tools"].append(
            copy.deepcopy(duplicate_tool["servers"][0]["tools"][0])
        )
        with self.assertRaisesRegex(render_adapters.RenderError, "duplicate canonical tool"):
            render_adapters.validate_server_identities(duplicate_tool)

        unknown_gate = copy.deepcopy(self.policy)
        unknown_gate["servers"][0]["approval_policy"]["human_gates"].append("not_a_tool")
        with self.assertRaisesRegex(render_adapters.RenderError, "unknown tools"):
            render_adapters.validate_server_identities(unknown_gate)

        duplicate_adapter = copy.deepcopy(self.policy)
        duplicate_adapter["servers"][0]["adapter_requirements"][1] = copy.deepcopy(
            duplicate_adapter["servers"][0]["adapter_requirements"][0]
        )
        with self.assertRaisesRegex(render_adapters.RenderError, "exactly one adapter"):
            render_adapters.validate_server_identities(duplicate_adapter)

        empty_tools = copy.deepcopy(self.policy)
        empty_tools["servers"][1]["tools"] = []
        with self.assertRaisesRegex(render_adapters.RenderError, "must not be empty"):
            render_adapters.validate_server_identities(empty_tools)

    def test_empty_enabled_allowlist_and_deny_precedence_remain_restrictive(self) -> None:
        denied = copy.deepcopy(self.policy)
        worker_policy = next(server for server in denied["servers"] if server["surface"] == "worker")
        for tool in worker_policy["tools"]:
            tool["approval"] = "deny"

        codex = tomllib.loads(
            render_adapters.render_target(denied, "codex")[
                PurePosixPath(".codex/config.toml")
            ].decode("utf-8")
        )["mcp_servers"]["zabin-worker"]
        expected = sorted(tool["name"] for tool in worker_policy["tools"])
        self.assertEqual([], codex["enabled_tools"])
        self.assertEqual(expected, codex["disabled_tools"])
        self.assertNotIn("tools", codex)

        claude = json.loads(
            render_adapters.render_target(denied, "claude_code")[
                PurePosixPath(".claude/settings.json")
            ]
        )["permissions"]
        worker_rules = {
            f"mcp__zabin-worker__{tool['name']}" for tool in worker_policy["tools"]
        }
        self.assertTrue(worker_rules.issubset(set(claude["deny"])))
        self.assertTrue(worker_rules.isdisjoint(set(claude["allow"])))
        self.assertTrue(worker_rules.isdisjoint(set(claude["ask"])))

    def test_runtime_preflight_stops_missing_empty_and_literal_credentials(self) -> None:
        claude = json.loads(
            render_adapters.render_target(self.policy, "claude_code")[
                PurePosixPath(".claude/settings.json")
            ]
        )
        command = claude["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        codex = tomllib.loads(
            render_adapters.render_target(self.policy, "codex")[
                PurePosixPath(".codex/config.toml")
            ].decode("utf-8")
        )
        self.assertEqual(command, codex["hooks"]["SessionStart"][0]["hooks"][0]["command"])

        valid = subprocess.run(
            ["/bin/sh", "-c", command],
            env=ENVIRONMENT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, valid.returncode)
        self.assertEqual("", valid.stdout)

        for environment in (
            {},
            {**ENVIRONMENT, "ZABIN_MCP_TOKEN": ""},
            {**ENVIRONMENT, "ZABIN_MCP_TOKEN": "${ZABIN_MCP_TOKEN}"},
            {**ENVIRONMENT, "ZABIN_MCP_TOKEN": "Bearer $ZABIN_MCP_TOKEN"},
        ):
            with self.subTest(environment=environment):
                blocked = subprocess.run(
                    ["/bin/sh", "-c", command],
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(0, blocked.returncode)
                decision = json.loads(blocked.stdout)
                self.assertFalse(decision["continue"])
                self.assertIn("convenience default", decision["stopReason"])
                for secret in ENVIRONMENT.values():
                    self.assertNotIn(secret, blocked.stdout)

    def test_literal_placeholder_environment_is_rejected_without_value_disclosure(self) -> None:
        for value in ("$ZABIN_MCP_TOKEN", "${ZABIN_MCP_TOKEN}", "Bearer ${ZABIN_MCP_TOKEN}"):
            with self.subTest(value=value):
                environment = {**ENVIRONMENT, "ZABIN_MCP_TOKEN": value}
                self.assertEqual(
                    ("ZABIN_MCP_TOKEN",),
                    render_adapters.missing_environment(self.policy, environment),
                )

    def test_admin_requirements_are_separate_exact_and_identity_pinned(self) -> None:
        artifacts = render_adapters.render_target(self.policy, "codex_admin_requirements")
        self.assertEqual([PurePosixPath("requirements.toml")], list(artifacts))
        text = artifacts[PurePosixPath("requirements.toml")].decode("utf-8")
        self.assertIn("ADMIN ONLY", text)
        requirements = tomllib.loads(text)
        self.assertEqual(set(self.fixture["expected_server_keys"]), set(requirements["mcp_servers"]))
        for server in self.policy["servers"]:
            key = server["identity"]["client_server_key"]
            self.assertEqual(
                server["transport"]["url"],
                requirements["mcp_servers"][key]["identity"]["url"],
            )
        for secret in ENVIRONMENT.values():
            self.assertNotIn(secret, text)

        with tempfile.TemporaryDirectory() as temporary:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                self.assertEqual(
                    2,
                    render_adapters.main(
                        [
                            "--target",
                            "codex_admin_requirements",
                            "--output-dir",
                            temporary,
                        ],
                        {},
                    ),
                )
            self.assertIn("requires explicit", stderr.getvalue())
            self.assertFalse((Path(temporary) / "requirements.toml").exists())
            self.assertEqual(
                0,
                render_adapters.main(
                    [
                        "--target",
                        "codex_admin_requirements",
                        "--output-dir",
                        temporary,
                        "--admin-deployment",
                    ],
                    {},
                ),
            )
            self.assertTrue((Path(temporary) / "requirements.toml").is_file())

    def test_ordinary_codex_install_never_touches_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            requirements = output / "requirements.toml"
            requirements.write_text("admin-owned\n", encoding="utf-8")
            self.assertEqual(
                0,
                render_adapters.main(
                    ["--target", "codex", "--output-dir", temporary],
                    ENVIRONMENT,
                ),
            )
            self.assertEqual("admin-owned\n", requirements.read_text(encoding="utf-8"))
            self.assertTrue((output / ".codex" / "config.toml").is_file())

    def test_failed_artifact_install_rolls_back_without_partial_output(self) -> None:
        artifacts = render_adapters.render_target(self.policy, "claude_code")
        real_replace = os.replace

        def fail_last(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
            if Path(source).suffix == ".tmp" and Path(destination).name == ".mcp.json":
                raise OSError(5, "injected write failure")
            real_replace(source, destination)

        with tempfile.TemporaryDirectory() as temporary, mock.patch(
            "scripts.render_adapters.os.replace", side_effect=fail_last
        ):
            output = Path(temporary)
            originals = {}
            for path in artifacts:
                destination = output.joinpath(*path.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                original = f"original:{path.as_posix()}\n".encode()
                destination.write_bytes(original)
                originals[path] = original
            with self.assertRaisesRegex(render_adapters.RenderError, "cannot install"):
                render_adapters.write_artifacts(output, artifacts)
            for path, original in originals.items():
                self.assertEqual(original, output.joinpath(*path.parts).read_bytes())
            self.assertFalse(list(output.rglob("*.tmp")))
            self.assertFalse(list(output.rglob("*.backup")))

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
