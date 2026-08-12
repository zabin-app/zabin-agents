from __future__ import annotations

import hashlib
import base64
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import run_conformance


ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "tests" / "conformance" / "runner-lock.json"
POLICY = ROOT / "config" / "zabin-mcp.json"


class PolicyParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock = run_conformance.load_lock()
        self.policy = json.loads(POLICY.read_text(encoding="utf-8"))

    def test_lock_pins_exact_official_action_runtime_clients_and_arguments(self) -> None:
        official = self.lock["official_conformance"]
        self.assertEqual("v0.1.11", official["action_version"])
        self.assertEqual("0.1.11", official["package_version"])
        self.assertRegex(official["integrity"]["digest"], r"^[0-9a-f]{40}$")
        self.assertRegex(official["artifact_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(official["transitive_lock_sha256"], r"^[0-9a-f]{64}$")
        self.assertNotIn("artifact_digest_environment", official)
        self.assertNotIn("transitive_lock_sha256_environment", official)
        self.assertEqual(
            ["server", "--url", "{url}", "--requirements", "2025-11-25"],
            official["server_arguments"],
        )
        self.assertIn("--expected-failures", official["forbidden_arguments"])
        self.assertEqual("2.1.220 (Claude Code)", self.lock["clients"]["claude_code"]["expected_output"])
        self.assertEqual("codex-cli 0.147.0", self.lock["clients"]["codex"]["expected_output"])
        self.assertFalse(self.lock["clients"]["goose"]["supported"])
        self.assertTrue(self.lock["clients"]["goose"]["required"])
        self.assertEqual("1.45.0", self.lock["clients"]["goose"]["expected_output"])
        self.assertFalse(self.lock["clients"]["goose"]["official_artifact_verified"])
        self.assertFalse(self.lock["clients"]["pi"]["supported"])

    def test_lock_rejects_argument_drift_and_unpinned_integrity(self) -> None:
        changed = json.loads(json.dumps(self.lock))
        changed["official_conformance"]["server_arguments"][-1] = "draft"
        with self.assertRaisesRegex(run_conformance.ConformanceError, "not frozen"):
            run_conformance.validate_lock(changed)
        changed = json.loads(json.dumps(self.lock))
        changed["official_conformance"]["integrity"]["digest"] = "main"
        with self.assertRaisesRegex(run_conformance.ConformanceError, "exact commit"):
            run_conformance.validate_lock(changed)
        changed = json.loads(json.dumps(self.lock))
        changed["official_conformance"]["artifact_sha256"] = ""
        with self.assertRaisesRegex(run_conformance.ConformanceError, "artifact_sha256"):
            run_conformance.validate_lock(changed)

    def test_code_owned_lock_rejects_well_formed_security_pin_changes(self) -> None:
        mutations = (
            ("official tag", ("official_conformance", "action_version"), "v0.1.12"),
            ("official package", ("official_conformance", "package_version"), "0.1.12"),
            ("official commit", ("official_conformance", "integrity", "digest"), "1" * 40),
            ("artifact digest", ("official_conformance", "artifact_sha256"), "1" * 64),
            ("transitive digest", ("official_conformance", "transitive_lock_sha256"), "2" * 64),
            ("Python version", ("runtimes", "python", "expected_output"), "Python 3.14.7"),
            ("Node version", ("runtimes", "node", "expected_output"), "v20.19.6"),
            ("Node path", ("runtimes", "node", "expected_path"), "/opt/node/bin/node"),
            ("Claude command", ("clients", "claude_code", "noninteractive_command", 1), "--version"),
            ("Codex version", ("clients", "codex", "expected_output"), "codex-cli 0.148.0"),
            ("Goose compatibility", ("clients", "goose", "compatibility_lock_sha256"), "3" * 64),
            ("Goose binary", ("clients", "goose", "observed_binary_sha256"), "4" * 64),
            ("Goose version", ("clients", "goose", "expected_output"), "1.45.1"),
            ("Goose binary environment", ("clients", "goose", "binary_environment"), "OTHER_BINARY"),
            ("lifecycle lease", ("lifecycle", "minimum_worker_lease_seconds"), 1801),
        )
        for label, path, replacement in mutations:
            with self.subTest(pin=label):
                changed = json.loads(json.dumps(self.lock))
                target = changed
                for component in path[:-1]:
                    target = target[component]
                target[path[-1]] = replacement
                with self.assertRaisesRegex(
                    run_conformance.ConformanceError, "security pins differ"
                ):
                    run_conformance.validate_lock(changed)

    def test_only_repository_canonical_non_symlink_lock_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            alternate = root / "runner-lock.json"
            alternate.write_text(LOCK.read_text(encoding="utf-8"), encoding="utf-8")
            with self.assertRaisesRegex(
                run_conformance.ConformanceError, "alternate runner lock paths"
            ):
                run_conformance._load_canonical_lock(alternate)

            substituted = root / "substituted-lock.json"
            substituted.symlink_to(LOCK)
            with mock.patch.object(run_conformance, "DEFAULT_LOCK", substituted):
                with self.assertRaisesRegex(
                    run_conformance.ConformanceError, "path substitution"
                ):
                    run_conformance.load_lock()

        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            run_conformance.build_parser().parse_args(["--lock", os.fspath(LOCK)])

    def test_policy_identity_inventory_and_credentials_match_lock(self) -> None:
        checks = run_conformance.verify_policy_parity(self.lock, self.policy)
        self.assertTrue(run_conformance.passed(checks), checks)
        self.assertEqual({"policy_conductor", "policy_worker"}, {check.name for check in checks})

    def test_policy_drift_is_a_failure(self) -> None:
        changed = json.loads(json.dumps(self.policy))
        changed["servers"][1]["tools"].pop()
        checks = run_conformance.verify_policy_parity(self.lock, changed)
        self.assertEqual("fail", {check.name: check for check in checks}["policy_worker"].status)

    def test_exact_command_cannot_add_baselines_or_change_requirements(self) -> None:
        command = run_conformance.exact_server_command(
            self.lock,
            "http://127.0.0.1:50052/mcp",
            Path("/verified/conformance.js"),
            Path("/usr/bin/node"),
        )
        self.assertEqual(
            [
                "/usr/bin/node", "/verified/conformance.js", "server", "--url",
                "http://127.0.0.1:50052/mcp", "--requirements", "2025-11-25",
            ],
            command,
        )
        self.assertNotIn("--expected-failures", command)
        with self.assertRaisesRegex(run_conformance.ConformanceError, "verified pinned"):
            run_conformance.exact_server_command(
                self.lock,
                "http://127.0.0.1:50052/mcp",
                Path("/verified/conformance.js"),
                Path("/tmp/spoofed-node"),
            )

    def test_path_spoofed_node_is_rejected_without_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            spoofed = Path(temporary) / "node"
            spoofed.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            spoofed.chmod(0o700)
            with mock.patch(
                "scripts.run_conformance.shutil.which", return_value=os.fspath(spoofed)
            ), mock.patch("scripts.run_conformance.run_redacted") as launch:
                check, executable = run_conformance.verify_node_runtime(
                    self.lock["runtimes"]["node"],
                    1,
                    environment={"PATH": temporary},
                )
            self.assertEqual("fail", check.status)
            self.assertIsNone(executable)
            launch.assert_not_called()

    def test_node_is_verified_and_launched_by_one_exact_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            node = Path(temporary) / "node"
            node.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            node.chmod(0o700)
            spec = dict(self.lock["runtimes"]["node"])
            spec["expected_path"] = os.fspath(node)
            captured: dict[str, object] = {}

            def launch(argv, **kwargs):
                captured["argv"] = list(argv)
                captured["environment"] = dict(kwargs["environment"])
                return {
                    "stdout": f"{spec['expected_output']}\n",
                    "stderr": "",
                    "returncode": 0,
                    "timed_out": False,
                }

            ambient = {
                "PATH": "/attacker/bin",
                "NODE_OPTIONS": "--require=/tmp/preload.js",
                "NODE_PATH": "/tmp/modules",
                "NPM_CONFIG_USERCONFIG": "/tmp/npmrc",
                "LD_PRELOAD": "/tmp/preload.so",
                "UNRELATED_SECRET": "do-not-forward",
                "LANG": "C.UTF-8",
            }
            with mock.patch(
                "scripts.run_conformance.shutil.which", return_value=os.fspath(node)
            ) as which, mock.patch(
                "scripts.run_conformance.run_redacted", side_effect=launch
            ):
                check, executable = run_conformance.verify_node_runtime(
                    spec, 1, environment=ambient
                )
            self.assertEqual("pass", check.status)
            self.assertEqual(node, executable)
            which.assert_called_once_with("node", path=ambient["PATH"])
            self.assertEqual(os.fspath(node), captured["argv"][0])
            child = captured["environment"]
            self.assertEqual("/usr/bin:/bin", child["PATH"])
            self.assertEqual("C.UTF-8", child["LANG"])
            for forbidden in (
                "NODE_OPTIONS", "NODE_PATH", "NPM_CONFIG_USERCONFIG",
                "LD_PRELOAD", "UNRELATED_SECRET",
            ):
                self.assertNotIn(forbidden, child)

    def test_official_child_environment_is_a_closed_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            environment = run_conformance.official_child_environment(
                {
                    "PATH": "/attacker/bin",
                    "NODE_OPTIONS": "--inspect",
                    "NODE_PATH": "/attacker/modules",
                    "npm_config_prefix": "/attacker/npm",
                    "DYLD_INSERT_LIBRARIES": "/attacker/dylib",
                    "LANG": "C",
                    "TZ": "UTC",
                    "TOKEN": "secret",
                },
                isolated_home=home,
            )
        self.assertEqual(
            {"HOME", "PATH", "TMPDIR", "LANG", "TZ"}, set(environment)
        )
        self.assertEqual("/usr/bin:/bin", environment["PATH"])

    def test_digest_requires_regular_file_and_exact_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "artifact"
            path.write_bytes(b"pinned")
            digest = hashlib.sha256(b"pinned").hexdigest()
            self.assertEqual("pass", run_conformance.verify_digest(path, digest, "artifact").status)
            self.assertEqual("fail", run_conformance.verify_digest(path, "0" * 64, "artifact").status)

    def test_startup_uses_only_locked_digests_while_environment_supplies_paths(self) -> None:
        seen: dict[str, str] = {}

        def capture(path, expected, name):
            seen[name] = expected
            return run_conformance.Check(name, "pass", "mocked")

        environment = {
            "ZABIN_CONFORMANCE_ARTIFACT": "/staged/index.js",
            "ZABIN_CONFORMANCE_TRANSITIVE_LOCK": "/staged/package-lock.json",
            "ZABIN_CONFORMANCE_TRANSITIVE_ARTIFACT_MANIFEST": "/staged/artifacts.json",
            "ZABIN_CONFORMANCE_ARTIFACT_SHA256": "0" * 64,
            "ZABIN_CONFORMANCE_TRANSITIVE_LOCK_SHA256": "1" * 64,
        }
        with mock.patch(
            "scripts.run_conformance.verify_version",
            side_effect=lambda name, spec, timeout: run_conformance.Check(name, "pass", "mocked"),
        ), mock.patch(
            "scripts.run_conformance.verify_node_runtime",
            return_value=(run_conformance.Check("runtime_node", "pass", "mocked"), Path("/usr/bin/node")),
        ), mock.patch("scripts.run_conformance.verify_digest", side_effect=capture), mock.patch(
            "scripts.run_conformance.verify_transitive_artifacts",
            return_value=run_conformance.Check("official_transitive_artifacts", "pass", "mocked"),
        ):
            run_conformance.verify_startup(self.lock, environ=environment)
        official = self.lock["official_conformance"]
        self.assertEqual(official["artifact_sha256"], seen["official_conformance_artifact"])
        self.assertEqual(official["transitive_lock_sha256"], seen["official_transitive_lock"])
        self.assertNotEqual(environment["ZABIN_CONFORMANCE_ARTIFACT_SHA256"], seen["official_conformance_artifact"])

    def test_every_transitive_registry_artifact_is_rehashed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "one.tgz"
            artifact.write_bytes(b"one-package")
            integrity = "sha512-" + base64.b64encode(
                hashlib.sha512(b"one-package").digest()
            ).decode("ascii")
            package_lock = root / "package-lock.json"
            package_lock.write_text(
                json.dumps(
                    {
                        "packages": {
                            "": {"name": "root"},
                            "node_modules/one": {
                                "version": "1.0.0",
                                "resolved": "https://registry.npmjs.org/one/-/one-1.0.0.tgz",
                                "integrity": integrity,
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0.0",
                        "artifacts": [
                            {
                                "package_path": "node_modules/one",
                                "integrity": integrity,
                                "artifact": os.fspath(artifact),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                "pass", run_conformance.verify_transitive_artifacts(package_lock, manifest).status
            )
            artifact.write_bytes(b"tampered")
            self.assertEqual(
                "fail", run_conformance.verify_transitive_artifacts(package_lock, manifest).status
            )

    def test_unresolved_nonregistry_and_integrity_free_dependencies_are_rejected(self) -> None:
        bad_entries = [
            {"version": "1.0.0", "integrity": "sha512-value"},
            {"version": "1.0.0", "resolved": "file:../one", "integrity": "sha512-value"},
            {"version": "1.0.0", "resolved": "https://registry.npmjs.org/one/-/one.tgz"},
        ]
        for entry in bad_entries:
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                package_lock = root / "package-lock.json"
                package_lock.write_text(
                    json.dumps({"packages": {"": {"name": "root"}, "node_modules/one": entry}}),
                    encoding="utf-8",
                )
                manifest = root / "manifest.json"
                manifest.write_text(
                    json.dumps({"schema_version": "1.0.0", "artifacts": []}),
                    encoding="utf-8",
                )
                self.assertEqual(
                    "fail",
                    run_conformance.verify_transitive_artifacts(package_lock, manifest).status,
                )

    def result_payload(self, *, identifier: str = "one") -> dict:
        return {
            "schema_version": "1.0.0",
            "summary": {
                "passed": 1,
                "failed": 0,
                "skipped": 0,
                "unscored": 0,
                "expected_failures": 0,
                "total": 1,
            },
            "checks": [
                {
                    "id": identifier,
                    "status": "passed",
                    "scored": True,
                    "expected_failure": False,
                }
            ],
            "scenarios": [],
        }

    def test_results_reject_expected_failures_skips_unscored_and_stale_baselines(self) -> None:
        bad_payloads = []
        for field, value in (
            ("status", "skipped"),
            ("scored", False),
            ("expected_failure", True),
        ):
            payload = self.result_payload()
            payload["checks"][0][field] = value
            bad_payloads.append(payload)
        stale = self.result_payload()
        stale["summary"]["expected_failures"] = 1
        bad_payloads.append(stale)
        for payload in bad_payloads:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "checks.json").write_text(json.dumps(payload), encoding="utf-8")
                self.assertEqual(
                    "fail",
                    run_conformance.assess_conformance_results(root, "conductor", self.lock).status,
                )

    def test_results_reject_unknown_fields_and_malicious_nested_summaries(self) -> None:
        payloads = []
        root_extra = self.result_payload()
        root_extra["credential"] = "smuggled"
        payloads.append(root_extra)
        check_extra = self.result_payload()
        check_extra["checks"][0]["unexpected"] = True
        payloads.append(check_extra)
        nested = self.result_payload()
        nested["checks"] = []
        nested["summary"]["passed"] = nested["summary"]["total"] = 1
        nested["scenarios"] = [
            {
                "name": "nested",
                "summary": {
                    "passed": 1,
                    "failed": 0,
                    "skipped": 1,
                    "unscored": 0,
                    "expected_failures": 0,
                    "total": 1,
                },
                "checks": self.result_payload()["checks"],
                "scenarios": [],
            }
        ]
        payloads.append(nested)
        unknown_status = self.result_payload()
        unknown_status["checks"][0]["status"] = "success"
        payloads.append(unknown_status)
        for payload in payloads:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "checks.json").write_text(json.dumps(payload), encoding="utf-8")
                self.assertEqual(
                    "fail",
                    run_conformance.assess_conformance_results(root, "worker", self.lock).status,
                )

    def test_results_pass_only_when_every_emitted_check_is_scored_and_passed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "checks.json").write_text(
                json.dumps(self.result_payload()),
                encoding="utf-8",
            )
            self.assertEqual(
                "pass",
                run_conformance.assess_conformance_results(root, "conductor", self.lock).status,
            )

    def test_conductor_and_worker_results_must_be_complete_and_independent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            conductor = root / "conductor"
            worker = root / "worker"
            conductor.mkdir()
            worker.mkdir()
            (conductor / "checks.json").write_text(
                json.dumps(self.result_payload(identifier="conductor-check")), encoding="utf-8"
            )
            isolated = run_conformance.assess_independent_surface_results(
                {"conductor": conductor, "worker": worker}, self.lock
            )
            self.assertFalse(run_conformance.passed(isolated))
            shared = run_conformance.assess_independent_surface_results(
                {"conductor": conductor, "worker": conductor}, self.lock
            )
            self.assertEqual("fail", shared[0].status)

    def test_redaction_happens_before_restricted_report_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "private" / "report.json"
            secret = "zabin-canary-secret"
            run_conformance.write_report(
                output,
                {"log": f"Authorization: Bearer {secret}", "nested": [secret]},
                [secret],
            )
            serialized = output.read_text(encoding="utf-8")
            self.assertNotIn(secret, serialized)
            self.assertIn("[REDACTED]", serialized)
            self.assertEqual(0o600, stat.S_IMODE(output.stat().st_mode))
            self.assertEqual(0o700, stat.S_IMODE(output.parent.stat().st_mode))

    def test_version_probe_compares_full_output_not_a_range(self) -> None:
        spec = {
            "required": True,
            "executable": "example",
            "version_arguments": ["--version"],
            "expected_output": "example 1.2.3",
        }
        with mock.patch("scripts.run_conformance.shutil.which", return_value="/bin/example"), mock.patch(
            "scripts.run_conformance.run_redacted",
            return_value={"stdout": "example 1.2.4\n", "stderr": "", "returncode": 0},
        ):
            self.assertEqual("fail", run_conformance.verify_version("example", spec, 1).status)

    def test_goose_probe_requires_explicit_binary_and_isolated_path_root(self) -> None:
        spec = self.lock["clients"]["goose"]
        missing = run_conformance.verify_goose_client(spec, 1, environment={})
        self.assertFalse(run_conformance.passed(missing))
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / "goose"
            binary.write_text("#!/bin/sh\nprintf '1.45.0\\n'\n", encoding="utf-8")
            binary.chmod(0o700)
            changed = dict(spec)
            changed["observed_binary_sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
            seen: dict[str, str] = {}

            def launch(argv, **kwargs):
                del argv
                seen.update(kwargs["environment"])
                return {"stdout": "1.45.0\n", "stderr": "", "returncode": 0}

            with mock.patch("scripts.run_conformance.run_redacted", side_effect=launch):
                checks = run_conformance.verify_goose_client(
                    changed,
                    1,
                    environment={"GOOSE_NATIVE_BINARY": os.fspath(binary)},
                )
            self.assertTrue(run_conformance.passed(checks), checks)
            self.assertTrue(seen["GOOSE_PATH_ROOT"].startswith("/tmp/"))
            self.assertEqual("approve", seen["GOOSE_MODE"])

    def test_goose_execution_root_requires_private_canonical_temp_child(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix=run_conformance.GOOSE_TEMP_PREFIX
        ) as temporary:
            root = Path(temporary)
            os.chmod(root, 0o700)
            self.assertEqual(
                root,
                run_conformance._canonical_goose_execution_root(os.fspath(root)),
            )

            nested = root / f"{run_conformance.GOOSE_TEMP_PREFIX}nested"
            nested.mkdir(mode=0o700)
            self.assertIsNone(
                run_conformance._canonical_goose_execution_root(os.fspath(nested))
            )

            os.chmod(root, 0o755)
            self.assertIsNone(
                run_conformance._canonical_goose_execution_root(os.fspath(root))
            )
            os.chmod(root, 0o700)

        self.assertIsNone(
            run_conformance._canonical_goose_execution_root(
                os.fspath(Path.home() / ".config" / "goose")
            )
        )
        self.assertIsNone(
            run_conformance._canonical_goose_execution_root(
                "/tmp/zabin-goose-conformance-safe/../production"
            )
        )


if __name__ == "__main__":
    unittest.main()
