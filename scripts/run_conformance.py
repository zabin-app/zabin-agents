#!/usr/bin/env python3
"""Pinned, fail-closed conformance orchestration for Zabin's MCP surfaces.

The runner never downloads dependencies.  Live execution is opt-in and begins
only after the local lock, runtimes, client versions, artifact digests, exact
commands, and exact arguments have been verified.  Captured streams are held in
memory only long enough to redact them; only the redacted report is persisted.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if os.fspath(ROOT) not in sys.path:
    sys.path.insert(0, os.fspath(ROOT))

from scripts import recovery_checkpoint, zabin_doctor


DEFAULT_LOCK = ROOT / "tests" / "conformance" / "runner-lock.json"
DEFAULT_POLICY = ROOT / "config" / "zabin-mcp.json"
RESULT_SCHEMA = "1.0.0"
EXPECTED_CANONICAL_LOCK_SHA256 = "3ab8039900b027608feebf0b42e2cdd201ca1580b749aa148e64391a848bc434"
EXPECTED_OFFICIAL_PINS = {
    "repository": "https://github.com/modelcontextprotocol/conformance",
    "action_version": "v0.1.11",
    "package": "@modelcontextprotocol/conformance",
    "package_version": "0.1.11",
    "commit": "bd1a195ab439841b58d90face7c96333d227e098",
    "artifact_sha256": "da66070321d0d0137239bdac0b510a95a360aecaf46992c1ba13349b57537bb2",
    "transitive_lock_sha256": "0fea65876736fa7185525137524f324695771c4cd4eb438c4479c434c9a5443b",
    "server_arguments": ("server", "--url", "{url}", "--requirements", "2025-11-25"),
    "forbidden_arguments": (
        "--expected-failures", "--suite", "--scenario", "--spec-version", "--force"
    ),
}
EXPECTED_RUNTIME_PINS = {
    "python": ("python3", ("--version",), "Python 3.14.6"),
    "node": ("node", "/usr/bin/node", ("--version",), "v20.19.5"),
}
EXPECTED_CLIENT_PINS = {
    "claude_code": (
        "claude",
        ("--version",),
        "2.1.220 (Claude Code)",
        (
            "claude", "--print", "--bare", "--strict-mcp-config", "--mcp-config",
            "{config}", "--permission-mode", "dontAsk", "--allowedTools",
            "{allowed_tool}", "--output-format", "json", "--no-session-persistence",
            "{prompt}",
        ),
    ),
    "codex": (
        "codex",
        ("--version",),
        "codex-cli 0.147.0",
        (
            "codex", "exec", "--ephemeral", "--strict-config", "--sandbox",
            "read-only", "--json", "-C", "{project}", "{prompt}",
        ),
    ),
}
EXPECTED_GOOSE_PIN = (
    "goose",
    "GOOSE_NATIVE_BINARY",
    ("--version",),
    "1.45.0",
    "adapters/goose/client-lock.json",
    "sha256:748eac1ac94347bf6d77df41371e0e9538b897d1dc721e08b945513ae3646e7f",
    "sha256:9ef3ae45d819e41d1b7bcb1533033765d1e1876aba4a35ff0f6e722337512b3b",
    False,
    None,
    "GOOSE_PATH_ROOT",
    "explicit recipe plus isolated GOOSE_PATH_ROOT",
)
EXPECTED_LIFECYCLE_PINS = (
    (
        "project_scope", "incremental_plan", "approval_observed", "overlap_report",
        "sized_worker_lease", "in_review", "verdict", "validated", "wave_gates",
        "completion", "release", "checkpoint_reconciliation",
    ),
    1800,
    "ZABIN_CONFORMANCE_PROJECT_ALLOWLIST",
)
STATUS = frozenset({"pass", "fail", "skip"})
SECRET_PATTERN = re.compile(
    r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;\"']+|"
    r"((?:api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*)[^\s,;\"']+"
)
SHA256 = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
GIT_SHA1 = re.compile(r"^[0-9a-f]{40}$")
GOOSE_EXTERNAL_REPORT_ID = "zabin-conformance/goose-external-report-v1"
GOOSE_TEMP_PREFIX = "zabin-goose-conformance-"


class ConformanceError(RuntimeError):
    """A safe failure whose message must not contain credential material."""


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    status: str
    detail: str
    required: bool = True
    evidence: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.status not in STATUS:
            raise ValueError(f"invalid check status: {self.status}")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConformanceError(f"cannot load {label}: {type(exc).__name__}") from None
    if not isinstance(value, dict):
        raise ConformanceError(f"{label} root must be an object")
    return value


def _load_canonical_lock(path: Path) -> dict[str, Any]:
    expected = DEFAULT_LOCK.absolute()
    if path.absolute() != expected:
        raise ConformanceError("alternate runner lock paths are forbidden")
    for component in (ROOT / "tests", ROOT / "tests" / "conformance", expected):
        if component.is_symlink():
            raise ConformanceError("runner lock path substitution is forbidden")
    try:
        before = expected.stat()
        if not stat.S_ISREG(before.st_mode):
            raise ConformanceError("runner lock must be a regular file")
        content = expected.read_text(encoding="utf-8")
        after = expected.stat()
    except OSError as exc:
        raise ConformanceError(f"cannot safely read canonical runner lock: {type(exc).__name__}") from None
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after or expected.resolve(strict=True) != expected:
        raise ConformanceError("runner lock changed during read or resolved elsewhere")
    try:
        lock = json.loads(content)
    except json.JSONDecodeError:
        raise ConformanceError("canonical runner lock is invalid JSON") from None
    if not isinstance(lock, dict):
        raise ConformanceError("runner lock root must be an object")
    return lock


def load_lock() -> dict[str, Any]:
    lock = _load_canonical_lock(DEFAULT_LOCK)
    validate_lock(lock)
    return lock


def validate_lock(lock: Mapping[str, Any]) -> None:
    required_roots = {
        "schema_version",
        "requirements_revision",
        "official_conformance",
        "runtimes",
        "clients",
        "servers",
        "timeouts_seconds",
        "lifecycle",
    }
    if set(lock) != required_roots:
        raise ConformanceError("runner lock has missing or unexpected top-level fields")
    if lock["schema_version"] != "1.0.0" or lock["requirements_revision"] != "2025-11-25":
        raise ConformanceError("runner lock schema or requirements revision is unsupported")

    official = lock["official_conformance"]
    required_official = {
        "repository",
        "action_version",
        "package",
        "package_version",
        "integrity",
        "artifact_environment",
        "artifact_sha256",
        "transitive_lock_environment",
        "transitive_lock_sha256",
        "transitive_artifact_manifest_environment",
        "result_schema",
        "server_arguments",
        "forbidden_arguments",
    }
    if not isinstance(official, Mapping) or set(official) != required_official:
        raise ConformanceError("official conformance lock is incomplete")
    integrity = official["integrity"]
    if integrity != {
        "algorithm": "git-commit-sha1",
        "digest": integrity.get("digest") if isinstance(integrity, Mapping) else None,
    } or not GIT_SHA1.fullmatch(str(integrity.get("digest", ""))):
        raise ConformanceError("official conformance action lacks an exact commit digest")
    arguments = official["server_arguments"]
    if arguments != ["server", "--url", "{url}", "--requirements", "2025-11-25"]:
        raise ConformanceError("official conformance arguments are not frozen")
    forbidden = set(official["forbidden_arguments"])
    if "--expected-failures" not in forbidden:
        raise ConformanceError("expected-failure baselines are not forbidden")
    for field in ("artifact_sha256", "transitive_lock_sha256"):
        if not SHA256.fullmatch(str(official.get(field, ""))):
            raise ConformanceError(f"official conformance {field} is not pinned")
    if official.get("result_schema") != {
        "schema_version": "1.0.0",
        "check_status": "passed",
        "summary_fields": [
            "passed", "failed", "skipped", "unscored", "expected_failures", "total"
        ],
    }:
        raise ConformanceError("official result schema lock is invalid")

    for runtime_name in ("python", "node"):
        runtime = lock["runtimes"].get(runtime_name)
        expected_fields = {"required", "executable", "version_arguments", "expected_output"}
        if runtime_name == "node":
            expected_fields.add("expected_path")
        if not isinstance(runtime, Mapping) or set(runtime) != expected_fields:
            raise ConformanceError(f"runtime lock is incomplete: {runtime_name}")
    for client_name in ("claude_code", "codex", "goose", "pi"):
        if client_name not in lock["clients"]:
            raise ConformanceError(f"client lock is missing: {client_name}")
    goose = lock["clients"]["goose"]
    if not isinstance(goose, Mapping) or set(goose) != {
        "supported", "required", "reason", "executable", "binary_environment", "version_arguments",
        "expected_output", "compatibility_lock", "compatibility_lock_sha256",
        "observed_binary_sha256", "official_artifact_verified",
        "official_artifact_sha256", "path_root_environment", "config_source",
    }:
        raise ConformanceError("Goose client lock is incomplete")
    if goose["supported"] is not False or goose["required"] is not True:
        raise ConformanceError("Goose must remain a required fail-closed conformance target")
    for field in ("compatibility_lock_sha256", "observed_binary_sha256"):
        if not SHA256.fullmatch(str(goose.get(field, ""))):
            raise ConformanceError(f"Goose {field} is not pinned")
    if goose["official_artifact_verified"] is not False or goose["official_artifact_sha256"] is not None:
        raise ConformanceError("Goose official artifact state differs from its compatibility audit")
    if lock["clients"]["pi"].get("supported") is not False:
        raise ConformanceError("PI must remain unsupported until its policy audit passes")

    for surface in ("conductor", "worker"):
        server = lock["servers"].get(surface)
        if not isinstance(server, Mapping):
            raise ConformanceError(f"server lock is missing: {surface}")
        if set(server) != {
            "url", "credential_environment", "service_name", "server_info_name",
            "surface", "version", "protocol_version", "tool_count", "inventory_sha256",
        }:
            raise ConformanceError(f"server identity lock is incomplete: {surface}")
        if server.get("surface") != surface or server.get("protocol_version") != "2025-11-25":
            raise ConformanceError(f"server identity is invalid: {surface}")
        if not SHA256.fullmatch(str(server.get("inventory_sha256", ""))):
            raise ConformanceError(f"server inventory digest is invalid: {surface}")
    actual_official_pins = {
        "repository": official["repository"],
        "action_version": official["action_version"],
        "package": official["package"],
        "package_version": official["package_version"],
        "commit": official["integrity"]["digest"],
        "artifact_sha256": official["artifact_sha256"],
        "transitive_lock_sha256": official["transitive_lock_sha256"],
        "server_arguments": tuple(official["server_arguments"]),
        "forbidden_arguments": tuple(official["forbidden_arguments"]),
    }
    actual_runtime_pins = {
        "python": (
            lock["runtimes"]["python"]["executable"],
            tuple(lock["runtimes"]["python"]["version_arguments"]),
            lock["runtimes"]["python"]["expected_output"],
        ),
        "node": (
            lock["runtimes"]["node"]["executable"],
            lock["runtimes"]["node"]["expected_path"],
            tuple(lock["runtimes"]["node"]["version_arguments"]),
            lock["runtimes"]["node"]["expected_output"],
        ),
    }
    actual_client_pins = {
        name: (
            lock["clients"][name]["executable"],
            tuple(lock["clients"][name]["version_arguments"]),
            lock["clients"][name]["expected_output"],
            tuple(lock["clients"][name]["noninteractive_command"]),
        )
        for name in ("claude_code", "codex")
    }
    actual_goose_pin = (
        goose["executable"],
        goose["binary_environment"],
        tuple(goose["version_arguments"]),
        goose["expected_output"],
        goose["compatibility_lock"],
        goose["compatibility_lock_sha256"],
        goose["observed_binary_sha256"],
        goose["official_artifact_verified"],
        goose["official_artifact_sha256"],
        goose["path_root_environment"],
        goose["config_source"],
    )
    lifecycle = lock["lifecycle"]
    actual_lifecycle_pins = (
        tuple(lifecycle["required_stages"]),
        lifecycle["minimum_worker_lease_seconds"],
        lifecycle["production_project_allowlist_environment"],
    )
    if (
        actual_official_pins != EXPECTED_OFFICIAL_PINS
        or actual_runtime_pins != EXPECTED_RUNTIME_PINS
        or actual_client_pins != EXPECTED_CLIENT_PINS
        or actual_goose_pin != EXPECTED_GOOSE_PIN
        or actual_lifecycle_pins != EXPECTED_LIFECYCLE_PINS
    ):
        raise ConformanceError("runner lock security pins differ from code-owned constants")
    actual_lock_digest = hashlib.sha256(_canonical_json(lock)).hexdigest()
    if actual_lock_digest != EXPECTED_CANONICAL_LOCK_SHA256:
        raise ConformanceError("runner lock security pins differ from code-owned constants")


def redact_text(text: str, secrets: Iterable[str] = ()) -> str:
    redacted = text
    for secret in sorted({value for value in secrets if value}, key=len, reverse=True):
        redacted = redacted.replace(secret, "[REDACTED]")
    return SECRET_PATTERN.sub(lambda match: f"{match.group(1) or match.group(2)}[REDACTED]", redacted)


def _redact_value(value: Any, secrets: Iterable[str]) -> Any:
    if isinstance(value, str):
        return redact_text(value, secrets)
    if isinstance(value, list):
        return [_redact_value(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: _redact_value(item, secrets) for key, item in value.items()}
    return value


def official_child_environment(
    environment: Mapping[str, str],
    *,
    isolated_home: Path,
) -> dict[str, str]:
    """Build a closed child environment without ambient execution injection."""

    child = {
        "HOME": os.fspath(isolated_home),
        "PATH": "/usr/bin:/bin",
        "TMPDIR": os.fspath(isolated_home / "tmp"),
    }
    for name in ("LANG", "LC_ALL", "LC_CTYPE", "TZ"):
        value = environment.get(name)
        if value:
            child[name] = value
    return child


def run_redacted(
    argv: Sequence[str],
    *,
    timeout: float,
    secrets: Sequence[str] = (),
    environment: Mapping[str, str] | None = None,
    cwd: Path = ROOT,
) -> dict[str, Any]:
    """Run one exact argv and return redacted streams without persisting raw bytes."""

    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(argv),
            cwd=cwd,
            env=dict(environment) if environment is not None else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        stdout = redact_text(completed.stdout, secrets)
        stderr = redact_text(completed.stderr, secrets)
        return {
            "argv": list(argv),
            "returncode": completed.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": False,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
    except subprocess.TimeoutExpired as exc:
        stdout = redact_text(str(exc.stdout or ""), secrets)
        stderr = redact_text(str(exc.stderr or ""), secrets)
        return {
            "argv": list(argv),
            "returncode": None,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": True,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
    except OSError as exc:
        return {
            "argv": list(argv),
            "returncode": None,
            "stdout": "",
            "stderr": f"launch failed ({type(exc).__name__})",
            "timed_out": False,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }


def verify_version(name: str, spec: Mapping[str, Any], timeout: float) -> Check:
    executable = str(spec["executable"])
    resolved = shutil.which(executable)
    required = bool(spec.get("required", spec.get("supported", True)))
    if resolved is None:
        return Check(name, "fail" if required else "skip", "executable is not installed", required)
    result = run_redacted(
        [resolved, *map(str, spec.get("version_arguments", ["--version"]))], timeout=timeout
    )
    # Some native launchers emit unrelated environment diagnostics on stderr.
    # The version contract is the exact stdout line when one exists; stderr is
    # retained as separately redacted evidence but never appended to it.
    observed = result["stdout"].strip() or result["stderr"].strip()
    expected = spec.get("expected_output")
    if result["returncode"] != 0 or observed != expected:
        return Check(
            name,
            "fail",
            "installed version differs from the lock",
            required,
            {
                "expected": expected,
                "observed": observed,
                "returncode": result["returncode"],
                "stderr": result["stderr"],
            },
        )
    return Check(name, "pass", "installed version exactly matches the lock", required, {"version": observed})


def verify_goose_client(
    spec: Mapping[str, Any],
    timeout: float,
    *,
    environment: Mapping[str, str],
) -> list[Check]:
    """Verify an explicit Goose binary inside a disposable path root."""

    raw_path = environment.get(str(spec["binary_environment"]), "")
    if not raw_path:
        return [
            Check("client_goose", "fail", "explicit Goose binary path is required"),
            Check("client_goose_binary", "fail", "Goose binary integrity is unavailable"),
            Check("client_goose_isolation", "fail", "native Goose was not launched"),
        ]
    binary = Path(raw_path)
    try:
        metadata = binary.lstat()
    except OSError:
        return [
            Check("client_goose", "fail", "Goose binary cannot be inspected"),
            Check("client_goose_binary", "fail", "Goose binary integrity is unavailable"),
            Check("client_goose_isolation", "fail", "native Goose was not launched"),
        ]
    safe_binary = (
        binary.is_absolute()
        and stat.S_ISREG(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and os.access(binary, os.X_OK)
    )
    if not safe_binary:
        return [
            Check("client_goose", "fail", "Goose binary is not an absolute non-symlink executable"),
            Check("client_goose_binary", "fail", "Goose binary integrity is unavailable"),
            Check("client_goose_isolation", "fail", "native Goose was not launched"),
        ]
    binary_check = verify_digest(
        binary, str(spec["observed_binary_sha256"]), "client_goose_binary"
    )
    if binary_check.status != "pass":
        return [
            Check("client_goose", "fail", "Goose binary differs from the observed lock"),
            binary_check,
            Check("client_goose_isolation", "fail", "unverified native Goose was not launched"),
        ]
    with tempfile.TemporaryDirectory(prefix="zabin-goose-conformance-") as temporary:
        path_root = Path(temporary)
        child = official_child_environment(environment, isolated_home=path_root)
        child.update(
            {
                str(spec["path_root_environment"]): os.fspath(path_root),
                "GOOSE_MODE": "approve",
            }
        )
        result = run_redacted(
            [os.fspath(binary), *map(str, spec["version_arguments"])],
            timeout=timeout,
            environment=child,
        )
        observed = result["stdout"].strip() or result["stderr"].strip()
        version_ok = result["returncode"] == 0 and observed == spec["expected_output"]
        isolation_ok = child[str(spec["path_root_environment"])] == os.fspath(path_root)
    return [
        Check(
            "client_goose",
            "pass" if version_ok else "fail",
            "Goose version exactly matches the lock" if version_ok else "Goose version differs from the lock",
            evidence={"version": observed},
        ),
        binary_check,
        Check(
            "client_goose_isolation",
            "pass" if isolation_ok else "fail",
            "native probe used a disposable GOOSE_PATH_ROOT" if isolation_ok else "native probe was not isolated",
        ),
    ]


def verify_node_runtime(
    spec: Mapping[str, Any],
    timeout: float,
    *,
    environment: Mapping[str, str],
) -> tuple[Check, Path | None]:
    expected = Path(str(spec["expected_path"]))
    resolved_value = shutil.which(str(spec["executable"]), path=environment.get("PATH"))
    if resolved_value is None:
        return Check("runtime_node", "fail", "pinned Node executable is not installed"), None
    resolved = Path(resolved_value)
    if not resolved.is_absolute() or resolved != expected:
        return Check("runtime_node", "fail", "resolved Node path differs from the pinned absolute path"), None
    try:
        metadata = resolved.lstat()
    except OSError:
        return Check("runtime_node", "fail", "pinned Node executable cannot be inspected"), None
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or not os.access(resolved, os.X_OK)
    ):
        return Check("runtime_node", "fail", "pinned Node path is not a non-symlink executable file"), None
    with tempfile.TemporaryDirectory(prefix="zabin-node-version-") as temporary:
        isolated_home = Path(temporary)
        (isolated_home / "tmp").mkdir(mode=0o700)
        result = run_redacted(
            [os.fspath(resolved), *map(str, spec["version_arguments"])],
            timeout=timeout,
            environment=official_child_environment(environment, isolated_home=isolated_home),
        )
    observed = result["stdout"].strip() or result["stderr"].strip()
    if result["returncode"] != 0 or observed != spec["expected_output"]:
        return Check(
            "runtime_node",
            "fail",
            "installed Node version differs from the lock",
            evidence={"expected": spec["expected_output"], "observed": observed},
        ), None
    return Check(
        "runtime_node",
        "pass",
        "absolute Node executable and exact version match the lock",
        evidence={"path": os.fspath(resolved), "version": observed},
    ), resolved


def verify_digest(path: Path, expected: str, name: str) -> Check:
    if not path.is_file() or path.is_symlink():
        return Check(name, "fail", "required artifact is missing or is not a regular file")
    actual = _sha256(path)
    normalized = expected.removeprefix("sha256:")
    if not SHA256.fullmatch(expected) or actual != normalized:
        return Check(name, "fail", "artifact digest differs from the lock")
    return Check(name, "pass", "artifact digest matches", evidence={"sha256": actual})


def verify_transitive_artifacts(lock_path: Path, manifest_path: Path) -> Check:
    """Verify every registry tarball named by a package-lock integrity entry."""

    package_lock = _load_json(lock_path, "official transitive lock")
    manifest = _load_json(manifest_path, "transitive artifact manifest")
    packages = package_lock.get("packages")
    artifacts = manifest.get("artifacts")
    if manifest.get("schema_version") != "1.0.0" or not isinstance(packages, Mapping) or not isinstance(artifacts, list):
        return Check("official_transitive_artifacts", "fail", "transitive lock or manifest shape is invalid")
    expected: dict[str, str] = {}
    for package_path, entry in packages.items():
        if not package_path:
            continue
        if not isinstance(entry, Mapping) or not {
            "version", "resolved", "integrity"
        }.issubset(entry):
            return Check(
                "official_transitive_artifacts",
                "fail",
                "every dependency must have exact version, registry resolution, and integrity",
            )
        resolved = entry["resolved"]
        integrity = entry["integrity"]
        if (
            not isinstance(resolved, str)
            or not resolved.startswith("https://registry.npmjs.org/")
            or not isinstance(integrity, str)
            or not integrity.startswith("sha512-")
        ):
            return Check(
                "official_transitive_artifacts",
                "fail",
                "non-registry, unresolved, or integrity-free dependency is forbidden",
            )
        expected[str(package_path)] = integrity
    observed: dict[str, Mapping[str, Any]] = {}
    for record in artifacts:
        if (
            not isinstance(record, Mapping)
            or set(record) != {"package_path", "integrity", "artifact"}
            or not isinstance(record.get("package_path"), str)
            or record["package_path"] in observed
        ):
            return Check("official_transitive_artifacts", "fail", "transitive manifest has an invalid record")
        observed[record["package_path"]] = record
    if not expected or set(observed) != set(expected):
        return Check("official_transitive_artifacts", "fail", "transitive artifact manifest is incomplete or has extras")
    for package_path, integrity in expected.items():
        record = observed[package_path]
        if record.get("integrity") != integrity or not integrity.startswith("sha512-"):
            return Check("official_transitive_artifacts", "fail", "transitive integrity metadata differs from package lock")
        artifact = Path(str(record.get("artifact", "")))
        if not artifact.is_file() or artifact.is_symlink():
            return Check("official_transitive_artifacts", "fail", "a transitive artifact is missing or unsafe")
        try:
            digest = hashlib.sha512(artifact.read_bytes()).digest()
        except OSError:
            return Check(
                "official_transitive_artifacts", "fail", "a transitive artifact cannot be read"
            )
        actual = "sha512-" + base64.b64encode(digest).decode("ascii")
        if actual != integrity:
            return Check("official_transitive_artifacts", "fail", "a transitive artifact digest differs from package lock")
    return Check(
        "official_transitive_artifacts",
        "pass",
        "every locked registry artifact matches its SHA-512 integrity",
        evidence={"artifact_count": len(expected)},
    )


def verify_policy_parity(lock: Mapping[str, Any], policy: Mapping[str, Any]) -> list[Check]:
    checks: list[Check] = []
    by_surface = {server["surface"]: server for server in policy.get("servers", [])}
    for surface in ("conductor", "worker"):
        expected = lock["servers"][surface]
        actual = by_surface.get(surface)
        if not isinstance(actual, Mapping):
            checks.append(Check(f"policy_{surface}", "fail", "surface is absent from canonical policy"))
            continue
        tools = sorted(tool["name"] for tool in actual.get("tools", []))
        digest = hashlib.sha256(
            _canonical_json({"surface": surface, "tools": tools})
        ).hexdigest()
        identity = actual.get("identity", {})
        parity = (
            actual.get("transport", {}).get("url") == expected["url"]
            and actual.get("credential", {}).get("name") == expected["credential_environment"]
            and identity.get("surface_name") == expected["surface"]
            and identity.get("service_name") == expected["service_name"]
            and identity.get("protocol_version") == expected["protocol_version"]
            and identity.get("server_version") == expected["version"]
            and len(tools) == expected["tool_count"]
            and digest == expected["inventory_sha256"]
        )
        checks.append(
            Check(
                f"policy_{surface}",
                "pass" if parity else "fail",
                "canonical policy matches lock" if parity else "canonical policy differs from lock",
                evidence={"tool_count": len(tools), "inventory_sha256": digest},
            )
        )
    return checks


def verify_startup(
    lock: Mapping[str, Any],
    *,
    environ: Mapping[str, str] = os.environ,
    verified_executables: dict[str, Path] | None = None,
) -> list[Check]:
    timeout = float(lock["timeouts_seconds"]["version_probe"])
    checks = [Check("lock", "pass", "runner lock is structurally valid")]
    checks.append(verify_version("runtime_python", lock["runtimes"]["python"], timeout))
    node_check, node_path = verify_node_runtime(
        lock["runtimes"]["node"], timeout, environment=environ
    )
    checks.append(node_check)
    if verified_executables is not None and node_path is not None:
        verified_executables["node"] = node_path
    for name in ("claude_code", "codex"):
        checks.append(verify_version(f"client_{name}", lock["clients"][name], timeout))

    goose = lock["clients"]["goose"]
    checks.extend(verify_goose_client(goose, timeout, environment=environ))
    checks.append(
        verify_digest(
            ROOT / goose["compatibility_lock"],
            goose["compatibility_lock_sha256"],
            "goose_compatibility_lock",
        )
    )
    checks.append(
        Check(
            "goose_official_artifact",
            "pass" if goose["official_artifact_verified"] is True else "fail",
            "official Goose artifact is verified" if goose["official_artifact_verified"] is True else "official Goose artifact integrity is unresolved",
        )
    )

    pi = lock["clients"]["pi"]
    checks.append(Check("client_pi", "skip", str(pi["reason"]), required=False))
    checks.append(verify_digest(ROOT / pi["extension_lock"], pi["extension_lock_sha256"], "pi_lock"))

    official = lock["official_conformance"]
    artifact_value = environ.get(official["artifact_environment"], "")
    if not artifact_value:
        checks.append(
            Check(
                "official_conformance_artifact",
                "fail",
                "artifact path is required before launch",
            )
        )
    else:
        checks.append(
            verify_digest(
                Path(artifact_value), official["artifact_sha256"], "official_conformance_artifact"
            )
        )

    transitive_value = environ.get(official["transitive_lock_environment"], "")
    if not transitive_value:
        checks.append(
            Check(
                "official_transitive_lock",
                "fail",
                "transitive dependency lock path is required",
            )
        )
    else:
        checks.append(
            verify_digest(
                Path(transitive_value), official["transitive_lock_sha256"], "official_transitive_lock"
            )
        )
        manifest_value = environ.get(official["transitive_artifact_manifest_environment"], "")
        if not manifest_value:
            checks.append(Check("official_transitive_artifacts", "fail", "verified transitive artifact manifest is required"))
        else:
            checks.append(verify_transitive_artifacts(Path(transitive_value), Path(manifest_value)))

    policy = _load_json(DEFAULT_POLICY, "canonical MCP policy")
    checks.extend(verify_policy_parity(lock, policy))
    return checks


def exact_server_command(
    lock: Mapping[str, Any],
    url: str,
    artifact: Path,
    verified_node: Path,
) -> list[str]:
    if (
        not verified_node.is_absolute()
        or verified_node != Path(lock["runtimes"]["node"]["expected_path"])
    ):
        raise ConformanceError("official launch Node path was not the verified pinned executable")
    arguments = [url if value == "{url}" else value for value in lock["official_conformance"]["server_arguments"]]
    for forbidden in lock["official_conformance"]["forbidden_arguments"]:
        if forbidden in arguments:
            raise ConformanceError(f"forbidden conformance argument present: {forbidden}")
    return [os.fspath(verified_node), os.fspath(artifact), *arguments]


def probe_locked_surface_identities(
    lock: Mapping[str, Any],
    policy: Mapping[str, Any],
    credentials: Mapping[str, zabin_doctor.Credential],
    *,
    timeout: float,
) -> list[Check]:
    """Probe build identity and inventory before any conformance process starts."""

    by_surface = {server["surface"]: server for server in policy["servers"]}
    checks: list[Check] = []
    for surface in ("conductor", "worker"):
        expected = lock["servers"][surface]
        credential = credentials[surface]
        token = credential._token
        if token is None:
            checks.append(Check(f"identity_{surface}", "fail", "credential unavailable; no identity probe launched"))
            continue
        try:
            client = zabin_doctor.McpClient(expected["url"], token, timeout=timeout)
            initialized = client.initialize()
            server_info = initialized.get("serverInfo")
            if not isinstance(server_info, Mapping):
                raise ConformanceError("initialize omitted serverInfo")
            names = zabin_doctor._list_all_tools(client)
            digest = hashlib.sha256(
                _canonical_json({"surface": surface, "tools": names})
            ).hexdigest()
            identity_pass = (
                initialized.get("protocolVersion") == expected["protocol_version"]
                and server_info.get("name") == expected["server_info_name"]
                and server_info.get("version") == expected["version"]
                and len(names) == expected["tool_count"]
                and digest == expected["inventory_sha256"]
                and by_surface[surface]["identity"]["service_name"] == expected["service_name"]
            )
            checks.append(
                Check(
                    f"identity_{surface}",
                    "pass" if identity_pass else "fail",
                    "live protocol, build identity, and inventory match" if identity_pass else "live protocol, build identity, or inventory differs",
                    evidence={"tool_count": len(names), "inventory_sha256": digest},
                )
            )
        except (zabin_doctor.DoctorError, ConformanceError) as exc:
            checks.append(Check(f"identity_{surface}", "fail", str(exc)))
    return checks


def _closed_nonnegative_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validate_result_node(
    node: Any,
    schema: Mapping[str, Any],
    *,
    root: bool,
) -> int:
    if not isinstance(node, Mapping):
        raise ConformanceError("official result node must be an object")
    expected_fields = {"summary", "checks", "scenarios"}
    if root:
        expected_fields.add("schema_version")
    else:
        expected_fields.add("name")
    if set(node) != expected_fields:
        raise ConformanceError("official result node has unknown or missing fields")
    if root and node["schema_version"] != schema["schema_version"]:
        raise ConformanceError("official result schema version differs from lock")
    if not root and (not isinstance(node["name"], str) or not node["name"]):
        raise ConformanceError("official scenario name is invalid")

    checks = node["checks"]
    scenarios = node["scenarios"]
    if not isinstance(checks, list) or not isinstance(scenarios, list):
        raise ConformanceError("official result checks and scenarios must be arrays")
    identifiers: set[str] = set()
    direct_passed = 0
    for entry in checks:
        if not isinstance(entry, Mapping) or set(entry) != {
            "id", "status", "scored", "expected_failure"
        }:
            raise ConformanceError("official check has unknown or missing fields")
        identifier = entry["id"]
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise ConformanceError("official check id is invalid or duplicated")
        identifiers.add(identifier)
        if entry["status"] != schema["check_status"]:
            raise ConformanceError("official check status is not the locked passing value")
        if entry["scored"] is not True or entry["expected_failure"] is not False:
            raise ConformanceError("official check is unscored or expected-failure")
        direct_passed += 1

    scenario_names: set[str] = set()
    nested_passed = 0
    for scenario in scenarios:
        if isinstance(scenario, Mapping) and scenario.get("name") in scenario_names:
            raise ConformanceError("official scenario name is duplicated")
        nested_passed += _validate_result_node(scenario, schema, root=False)
        scenario_names.add(str(scenario["name"]))
    computed_passed = direct_passed + nested_passed

    summary = node["summary"]
    summary_fields = schema["summary_fields"]
    if not isinstance(summary, Mapping) or set(summary) != set(summary_fields):
        raise ConformanceError("official summary has unknown or missing fields")
    if not all(_closed_nonnegative_count(summary[field]) for field in summary_fields):
        raise ConformanceError("official summary counts must be nonnegative integers")
    if (
        summary["passed"] != computed_passed
        or summary["total"] != computed_passed
        or any(summary[field] != 0 for field in ("failed", "skipped", "unscored", "expected_failures"))
    ):
        raise ConformanceError("official summary counts do not describe a complete full pass")
    return computed_passed


def assess_conformance_results(
    result_root: Path,
    surface: str,
    lock: Mapping[str, Any],
) -> Check:
    name = f"official_{surface}_results"
    if surface not in {"conductor", "worker"}:
        return Check(name, "fail", "unknown conformance surface")
    check_files = sorted(result_root.glob("**/checks.json"))
    if len(check_files) != 1:
        return Check(name, "fail", "surface must produce exactly one checks.json")
    try:
        payload = json.loads(check_files[0].read_text(encoding="utf-8"))
        count = _validate_result_node(
            payload, lock["official_conformance"]["result_schema"], root=True
        )
        if count == 0:
            raise ConformanceError("official result contains no checks")
    except (OSError, json.JSONDecodeError, ConformanceError) as exc:
        return Check(name, "fail", str(exc) if isinstance(exc, ConformanceError) else "official result is unreadable")
    return Check(
        name,
        "pass",
        "surface emitted one closed-schema, fully scored passing result",
        evidence={"check_count": count},
    )


def assess_independent_surface_results(
    result_roots: Mapping[str, Path],
    lock: Mapping[str, Any],
) -> list[Check]:
    if set(result_roots) != {"conductor", "worker"}:
        return [Check("official_surface_isolation", "fail", "both exact surface roots are required")]
    resolved = [path.resolve() for path in result_roots.values()]
    if len(set(resolved)) != 2:
        return [Check("official_surface_isolation", "fail", "surfaces must use distinct result roots")]
    checks = [Check("official_surface_isolation", "pass", "surface result roots are distinct")]
    checks.extend(
        assess_conformance_results(result_roots[surface], surface, lock)
        for surface in ("conductor", "worker")
    )
    return checks


def _expected_host_tools(policy: Mapping[str, Any], host: str) -> dict[str, set[str]]:
    tools: dict[str, set[str]] = {}
    for server in policy["servers"]:
        key = next(
            requirement["server_key"]
            for requirement in server["adapter_requirements"]
            if requirement["client"] == host
        )
        raw = {tool["name"] for tool in server["tools"] if tool["approval"] != "deny"}
        if host == "claude_code":
            tools[server["surface"]] = {f"mcp__{key}__{name}" for name in raw}
        elif host == "goose":
            tools[server["surface"]] = {f"{key}__{name}" for name in raw}
        else:
            tools[server["surface"]] = raw
    return tools


def _goose_receipt_projection(report: Mapping[str, Any]) -> dict[str, Any]:
    """Select every claim whose truth depends on native execution receipts."""

    surfaces = report.get("surfaces")
    projected_surfaces: dict[str, Any] = {}
    if isinstance(surfaces, Mapping):
        for surface in ("conductor", "worker"):
            observation = surfaces.get(surface)
            if isinstance(observation, Mapping):
                projected_surfaces[surface] = {
                    name: observation.get(name)
                    for name in (
                        "server_identity",
                        "enumerated_tools",
                        "hidden_tool",
                        "allowed_call",
                        "forbidden_call",
                        "auth",
                        "drift",
                    )
                }
            else:
                projected_surfaces[surface] = observation
    return {
        "path_root": report.get("path_root"),
        "surfaces": projected_surfaces,
        "runtime_policy": report.get("runtime_policy"),
        "context_discovery": report.get("context_discovery"),
        "timeout_cancellation": report.get("timeout_cancellation"),
        "raw_streams_persisted": report.get("raw_streams_persisted"),
        "cleanup": report.get("cleanup"),
    }


def goose_report_integrity(
    report: Mapping[str, Any],
    lock: Mapping[str, Any],
    evidence_root: Path,
) -> dict[str, Any]:
    """Create self-consistency metadata for an external Goose report.

    These hashes detect mutation after report construction. They are deliberately
    not an attestation and establish no execution provenance: an external caller
    can compute every value in this envelope.
    """

    if "integrity" in report:
        raise ConformanceError("Goose report integrity may be added exactly once")
    return {
        "schema_version": "1.0.0",
        "format": GOOSE_EXTERNAL_REPORT_ID,
        "implementation_sha256": _sha256(Path(__file__).resolve(strict=True)),
        "lock_sha256": _json_sha256(lock),
        "root": os.fspath(evidence_root),
        "evidence_sha256": _json_sha256(report),
        "receipt_sha256": _json_sha256(_goose_receipt_projection(report)),
    }


def _canonical_goose_evidence_root(value: Any) -> Path | None:
    """Accept only a live, private, direct child of the canonical temp root."""

    if not isinstance(value, str) or not value:
        return None
    candidate = Path(value)
    if not candidate.is_absolute() or ".." in candidate.parts:
        return None
    try:
        temporary_root = Path(tempfile.gettempdir()).resolve(strict=True)
        metadata = candidate.lstat()
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None
    mode = stat.S_IMODE(metadata.st_mode)
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or resolved != candidate
        or resolved.parent != temporary_root
        or not resolved.name.startswith(GOOSE_TEMP_PREFIX)
        or mode & 0o077
        or (hasattr(os, "getuid") and metadata.st_uid != os.getuid())
    ):
        return None
    return resolved


def _closed_receipt_count(value: Any, expected: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == expected


def _untrusted_goose_observation(
    name: str,
    structurally_valid: bool,
    invalid_detail: str,
) -> Check:
    detail = (
        "external report is structurally consistent but has no trusted execution provenance"
        if structurally_valid
        else invalid_detail
    )
    return Check(name, "fail", detail)


def assess_goose_native_report(
    report: Mapping[str, Any],
    lock: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    canaries: Sequence[str] = (),
) -> list[Check]:
    """Validate external Goose report integrity without trusting its observations."""

    required_fields = {
        "schema_version", "host", "version", "binary_sha256",
        "compatibility_lock_sha256", "support_status", "path_root", "surfaces",
        "runtime_policy", "context_discovery", "timeout_cancellation", "logs",
        "raw_streams_persisted", "cleanup", "integrity",
    }
    if set(report) != required_fields:
        return [Check("host_goose_shape", "fail", "Goose observer report shape is not exact")]
    goose = lock["clients"]["goose"]
    checks = [
        Check(
            "host_goose_support_gate",
            "pass" if goose["supported"] is True and report["support_status"] == "supported" else "fail",
            "Goose is supported by every pinned gate" if goose["supported"] is True else str(goose["reason"]),
        )
    ]
    checks.append(
        Check(
            "host_goose_provenance",
            "fail",
            "external --host-report input is caller-authored; no trusted in-process Goose observer exists",
        )
    )
    integrity = report["integrity"]
    body = {key: value for key, value in report.items() if key != "integrity"}
    evidence_root = (
        _canonical_goose_evidence_root(integrity.get("root"))
        if isinstance(integrity, Mapping)
        else None
    )
    integrity_ok = (
        isinstance(integrity, Mapping)
        and set(integrity) == {
            "schema_version",
            "format",
            "implementation_sha256",
            "lock_sha256",
            "root",
            "evidence_sha256",
            "receipt_sha256",
        }
        and integrity["schema_version"] == "1.0.0"
        and integrity["format"] == GOOSE_EXTERNAL_REPORT_ID
        and integrity["implementation_sha256"] == _sha256(Path(__file__).resolve(strict=True))
        and integrity["lock_sha256"] == _json_sha256(lock)
        and integrity["evidence_sha256"] == _json_sha256(body)
        and integrity["receipt_sha256"]
        == _json_sha256(_goose_receipt_projection(body))
        and evidence_root is not None
    )
    checks.append(
        Check(
            "host_goose_report_integrity",
            "pass" if integrity_ok else "fail",
            "external report hashes are self-consistent but establish no execution provenance"
            if integrity_ok
            else "external report hashes or evidence-root constraints are invalid",
        )
    )
    identity_pass = (
        report["schema_version"] == "1.0.0"
        and report["host"] == "goose"
        and report["version"] == goose["expected_output"]
        and report["binary_sha256"] == goose["observed_binary_sha256"]
        and report["compatibility_lock_sha256"] == goose["compatibility_lock_sha256"]
        and report["support_status"] == "unsupported"
    )
    checks.append(_untrusted_goose_observation("host_goose_pin", identity_pass, "reported Goose pins differ from the lock"))

    path_root = report["path_root"]
    raw_path_value = path_root.get("value") if isinstance(path_root, Mapping) else None
    path_value = Path(raw_path_value) if isinstance(raw_path_value, str) else Path()
    path_is_canonical_child = (
        evidence_root is not None
        and path_value.is_absolute()
        and ".." not in path_value.parts
        and path_value.parent == evidence_root
        and not os.path.lexists(path_value)
    )
    path_pass = (
        isinstance(path_root, Mapping)
        and set(path_root) == {"environment", "value", "isolated", "disposable", "production_unchanged"}
        and path_root["environment"] == goose["path_root_environment"]
        and path_is_canonical_child
        and path_root["isolated"] is True
        and path_root["disposable"] is True
        and path_root["production_unchanged"] is True
    )
    checks.append(_untrusted_goose_observation("host_goose_path_root", path_pass, "isolated disposable GOOSE_PATH_ROOT was not proven"))

    expected_tools = _expected_host_tools(policy, "goose")
    observed_surfaces = report["surfaces"]
    if not isinstance(observed_surfaces, Mapping) or set(observed_surfaces) != {
        "conductor",
        "worker",
    }:
        checks.append(
            Check(
                "host_goose_surfaces_shape",
                "fail",
                "Goose surface observations must be exact and closed",
            )
        )
        observed_surfaces = {}
    for surface in ("conductor", "worker"):
        name = f"host_goose_{surface}"
        observation = observed_surfaces.get(surface) if isinstance(observed_surfaces, Mapping) else None
        expected_server = lock["servers"][surface]
        expected_extension = f"zabin-{surface}"
        expected_identity = {
            "service_name": expected_server["service_name"],
            "server_info_name": expected_server["server_info_name"],
            "surface": surface,
            "version": expected_server["version"],
            "protocol_version": expected_server["protocol_version"],
            "inventory_sha256": expected_server["inventory_sha256"],
        }
        if not isinstance(observation, Mapping) or set(observation) != {
            "extension_name", "server_identity", "enumerated_tools", "hidden_tool",
            "allowed_call", "forbidden_call", "auth", "drift",
        }:
            checks.append(Check(f"{name}_shape", "fail", "surface observation shape is not exact"))
            continue
        identity_ok = observation["extension_name"] == expected_extension and observation["server_identity"] == expected_identity
        checks.append(_untrusted_goose_observation(f"{name}_identity", identity_ok, "surface identity differs from the lock"))
        actual_tools = observation["enumerated_tools"]
        hidden_tool = f"{expected_extension}__conformance_forbidden"
        inventory_ok = (
            isinstance(actual_tools, list)
            and actual_tools == sorted(expected_tools[surface])
            and observation["hidden_tool"] == hidden_tool
            and hidden_tool not in actual_tools
        )
        checks.append(_untrusted_goose_observation(f"{name}_inventory", inventory_ok, "qualified inventory or hidden-tool evidence differs"))
        allowed = observation["allowed_call"]
        allowed_ok = isinstance(allowed, Mapping) and set(allowed) == {"tool", "success", "receipt_count"} and allowed.get("tool") == f"{expected_extension}__get_task" and allowed.get("success") is True and _closed_receipt_count(allowed.get("receipt_count"), 1)
        checks.append(_untrusted_goose_observation(f"{name}_allowed_call", allowed_ok, "allowed dispatch receipt is not exact"))
        forbidden = observation["forbidden_call"]
        forbidden_ok = isinstance(forbidden, Mapping) and set(forbidden) == {"tool", "rejected_before_transport", "receipt_count"} and forbidden.get("tool") == hidden_tool and forbidden.get("rejected_before_transport") is True and _closed_receipt_count(forbidden.get("receipt_count"), 0)
        checks.append(_untrusted_goose_observation(f"{name}_forbidden_call", forbidden_ok, "forbidden dispatch containment was not proven"))
        auth = observation["auth"]
        auth_ok = (
            isinstance(auth, Mapping)
            and set(auth) == {"credential_environment", "missing", "swapped"}
            and auth.get("credential_environment") == expected_server["credential_environment"]
            and all(
                isinstance(auth.get(case), Mapping)
                and set(auth[case]) == {"rejected", "receipt_count"}
                and auth[case]["rejected"] is True
                and _closed_receipt_count(auth[case]["receipt_count"], 0)
                for case in ("missing", "swapped")
            )
        )
        checks.append(_untrusted_goose_observation(f"{name}_auth", auth_ok, "credential-separation evidence is incomplete"))
        drift = observation["drift"]
        drift_ok = (
            isinstance(drift, Mapping)
            and set(drift) == {"server_info", "inventory", "redirect"}
            and all(
                isinstance(drift.get(case), Mapping)
                and set(drift[case]) == {"rejected_before_credential", "credential_receipt_count", "request_receipt_count"}
                and drift[case]["rejected_before_credential"] is True
                and _closed_receipt_count(drift[case]["credential_receipt_count"], 0)
                and _closed_receipt_count(drift[case]["request_receipt_count"], 0)
                for case in ("server_info", "inventory", "redirect")
            )
        )
        checks.append(_untrusted_goose_observation(f"{name}_drift", drift_ok, "pre-credential drift rejection was not proven"))

    runtime = report["runtime_policy"]
    runtime_ok = isinstance(runtime, Mapping) and set(runtime) == {"mode", "permissions_mutually_exclusive", "default_extensions"} and runtime["mode"] == "approve" and runtime["permissions_mutually_exclusive"] is True and runtime["default_extensions"] == []
    checks.append(_untrusted_goose_observation("host_goose_runtime_policy", runtime_ok, "runtime permission or default-extension policy differs"))
    context = report["context_discovery"]
    context_ok = isinstance(context, Mapping) and set(context) == {"agents_md", "skills"} and all(isinstance(context.get(kind), Mapping) and set(context[kind]) == {"observed", "marker"} and context[kind]["observed"] is True and isinstance(context[kind]["marker"], str) and bool(context[kind]["marker"]) for kind in ("agents_md", "skills"))
    checks.append(_untrusted_goose_observation("host_goose_context", context_ok, "shared context discovery evidence is incomplete"))
    bounded = report["timeout_cancellation"]
    bounded_ok = isinstance(bounded, Mapping) and set(bounded) == {"timeout_seconds", "timed_out", "cancel_requested", "child_terminated"} and isinstance(bounded["timeout_seconds"], (int, float)) and not isinstance(bounded["timeout_seconds"], bool) and 0 < bounded["timeout_seconds"] <= float(lock["timeouts_seconds"]["host"]) and bounded["timed_out"] is True and bounded["cancel_requested"] is True and bounded["child_terminated"] is True
    checks.append(_untrusted_goose_observation("host_goose_timeout_cancellation", bounded_ok, "bounded timeout and cancellation were not proven"))
    logs = report["logs"]
    leaked = not isinstance(logs, str) or any(canary and canary in logs for canary in canaries) or bool(SECRET_PATTERN.search(logs))
    checks.append(_untrusted_goose_observation("host_goose_redaction", not leaked, "credential-like material appears in observer logs"))
    cleanup = report["cleanup"]
    cleanup_ok = (
        report["raw_streams_persisted"] is False
        and isinstance(cleanup, Mapping)
        and set(cleanup) == {"status", "path_root_removed", "fixtures_stopped"}
        and cleanup["status"] == "complete"
        and cleanup["path_root_removed"] is True
        and cleanup["fixtures_stopped"] is True
    )
    checks.append(_untrusted_goose_observation("host_goose_cleanup", cleanup_ok, "Goose cleanup evidence is incomplete"))
    return checks


def assess_native_host_report(
    host: str,
    report: Mapping[str, Any],
    lock: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    canaries: Sequence[str] = (),
) -> list[Check]:
    """Validate a deterministic observer report; the model's choices are irrelevant."""

    checks: list[Check] = []
    required_fields = {
        "host", "version", "command", "config_source", "workspace_trust",
        "server_approval", "activation", "connected_servers", "enumerated_tools",
        "allowed_call", "forbidden_call", "missing_secret", "logs", "raw_streams_persisted",
        "cleanup",
    }
    if set(report) != required_fields:
        return [Check(f"host_{host}_shape", "fail", "native-host report shape is not exact")]
    client = lock["clients"][host]
    checks.append(Check(f"host_{host}_version", "pass" if report["version"] == client["expected_output"] else "fail", "host version matches lock" if report["version"] == client["expected_output"] else "host version differs from lock"))
    checks.append(Check(f"host_{host}_command", "pass" if report["command"] == client["noninteractive_command"] else "fail", "noninteractive command matches lock" if report["command"] == client["noninteractive_command"] else "noninteractive command differs from lock"))
    checks.append(Check(f"host_{host}_config", "pass" if report["config_source"] == client["config_source"] else "fail", "installed configuration source observed" if report["config_source"] == client["config_source"] else "configuration source differs from lock"))

    trust = report["workspace_trust"]
    if host == "claude_code" and not client["interactive_trust_automatable"]:
        checks.append(Check("host_claude_interactive_trust", "skip", "interactive project trust is not automatable; headless activation is not approval evidence", required=False))
    else:
        trust_pass = isinstance(trust, Mapping) and trust.get("state") == "approved" and trust.get("evidence") == "interactive"
        checks.append(Check(f"host_{host}_trust", "pass" if trust_pass else "fail", "interactive trust observed" if trust_pass else "interactive trust was not observed"))
    checks.append(Check(f"host_{host}_approval", "pass" if report["server_approval"] == "approved" else "fail", "server approval observed" if report["server_approval"] == "approved" else "server approval is not approved"))
    checks.append(Check(f"host_{host}_activation", "pass" if report["activation"] == "active" else "fail", "server activation observed" if report["activation"] == "active" else "server is not active"))

    connected = report["connected_servers"]
    expected_connected = {
        surface: {
            "url": server["url"],
            "service_name": server["service_name"],
            "server_info_name": server["server_info_name"],
            "surface": surface,
            "version": server["version"],
            "protocol_version": server["protocol_version"],
            "inventory_sha256": server["inventory_sha256"],
        }
        for surface, server in lock["servers"].items()
    }
    checks.append(Check(f"host_{host}_identity", "pass" if connected == expected_connected else "fail", "connected server identities match" if connected == expected_connected else "connected server identities differ"))

    expected_tools = _expected_host_tools(policy, host)
    actual_tools = {surface: set(names) for surface, names in report["enumerated_tools"].items()} if isinstance(report["enumerated_tools"], Mapping) else {}
    checks.append(Check(f"host_{host}_tools", "pass" if actual_tools == expected_tools else "fail", "exact registered tool names match" if actual_tools == expected_tools else "registered tool names differ"))

    allowed = report["allowed_call"]
    allowed_pass = isinstance(allowed, Mapping) and allowed.get("success") is True and allowed.get("receipt_count") == 1
    checks.append(Check(f"host_{host}_allowed_call", "pass" if allowed_pass else "fail", "direct allowed call reached the server once" if allowed_pass else "direct allowed call was not proven"))
    forbidden = report["forbidden_call"]
    forbidden_pass = isinstance(forbidden, Mapping) and forbidden.get("absent_or_rejected") is True and forbidden.get("receipt_count") == 0
    checks.append(Check(f"host_{host}_forbidden_call", "pass" if forbidden_pass else "fail", "forbidden tool was absent or rejected before transport" if forbidden_pass else "forbidden call was not contained"))
    missing = report["missing_secret"]
    missing_pass = isinstance(missing, Mapping) and missing.get("blocked_before_client_launch") is True and missing.get("enumeration_count") == 0 and missing.get("invocation_count") == 0
    checks.append(Check(f"host_{host}_missing_secret", "pass" if missing_pass else "fail", "missing secret blocked before launch with zero MCP activity" if missing_pass else "missing-secret containment was not proven"))

    logs = str(report["logs"])
    leaked = any(canary and canary in logs for canary in canaries) or bool(SECRET_PATTERN.search(logs))
    checks.append(Check(f"host_{host}_redaction", "fail" if leaked else "pass", "credential-like material appears in logs" if leaked else "logs contain no canary or credential-bearing header"))
    cleanup_pass = report["raw_streams_persisted"] is False and report["cleanup"] == "complete"
    checks.append(Check(f"host_{host}_cleanup", "pass" if cleanup_pass else "fail", "no raw streams retained and cleanup completed" if cleanup_pass else "raw-stream retention or cleanup failure reported"))
    return checks


def assess_lifecycle_evidence(
    evidence: Mapping[str, Any],
    lock: Mapping[str, Any],
    *,
    allowed_projects: set[str],
) -> list[Check]:
    if set(evidence) != {"schema_version", "project_id", "disposable", "stages"}:
        return [Check("lifecycle_schema", "fail", "lifecycle evidence has unknown or missing fields")]
    if evidence["schema_version"] != "1.0.0" or not isinstance(evidence["disposable"], bool):
        return [Check("lifecycle_schema", "fail", "lifecycle schema version or disposable flag is invalid")]
    project_id = evidence.get("project_id")
    disposable = evidence.get("disposable") is True
    if not isinstance(project_id, str) or not project_id:
        return [Check("lifecycle_scope", "fail", "lifecycle evidence lacks an explicit project id")]
    if not disposable and project_id not in allowed_projects:
        return [Check("lifecycle_scope", "fail", "production project is not explicitly allowlisted")]
    stages = evidence.get("stages")
    required = lock["lifecycle"]["required_stages"]
    checks = [Check("lifecycle_scope", "pass", "disposable or explicitly allowlisted project scope observed")]
    if not isinstance(stages, list):
        return checks + [Check("lifecycle_stages", "fail", "lifecycle stages are missing")]
    names = [stage.get("name") if isinstance(stage, Mapping) else None for stage in stages]
    if names != required or len(names) != len(set(names)):
        return checks + [
            Check(
                "lifecycle_order",
                "fail",
                "lifecycle stages must be exact, unique, complete, and ordered",
            )
        ]
    for stage, name in zip(stages, required, strict=True):
        fields = {"name", "status", "evidence"}
        if name == "sized_worker_lease":
            fields.add("lease_ttl_seconds")
        if name == "checkpoint_reconciliation":
            fields.add("outcome")
        if not isinstance(stage, Mapping) or set(stage) != fields:
            return checks + [Check(f"lifecycle_{name}", "fail", "stage schema is not closed")]
        evidence_ref = stage["evidence"]
        passed_stage = (
            stage["name"] == name
            and stage["status"] == "pass"
            and isinstance(evidence_ref, str)
            and evidence_ref.startswith("zabin://")
            and len(evidence_ref) > len("zabin://")
        )
        if name == "sized_worker_lease":
            ttl = stage["lease_ttl_seconds"]
            passed_stage = (
                passed_stage
                and isinstance(ttl, int)
                and not isinstance(ttl, bool)
                and ttl >= int(lock["lifecycle"]["minimum_worker_lease_seconds"])
            )
        if name == "checkpoint_reconciliation":
            passed_stage = passed_stage and stage["outcome"] in {"consistent", "zabin_only"}
        checks.append(
            Check(
                f"lifecycle_{name}",
                "pass" if passed_stage else "fail",
                "stage has authoritative terminal evidence" if passed_stage else "stage is invalid, unscored, nonterminal, or lacks authoritative evidence",
            )
        )
    return checks


def passed(checks: Sequence[Check]) -> bool:
    return all(check.status == "pass" for check in checks if check.required)


def write_report(path: Path, report: Mapping[str, Any], secrets: Sequence[str]) -> None:
    redacted = _redact_value(dict(report), secrets)
    serialized = json.dumps(redacted, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600)


def _parse_host_report(value: str) -> tuple[str, Path]:
    host, separator, path = value.partition("=")
    if separator != "=" or host not in {"claude_code", "codex", "goose"} or not path:
        raise argparse.ArgumentTypeError(
            "host report must be claude_code=PATH, codex=PATH, or goose=PATH"
        )
    return host, Path(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="opt in to canonical localhost MCP probes")
    parser.add_argument("--host-report", action="append", type=_parse_host_report, default=[])
    parser.add_argument("--lifecycle-evidence", type=Path)
    parser.add_argument("--allow-project", action="append", default=[])
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    lock = load_lock()
    canaries = (
        "zabin-canary-conductor-7f31c9",
        "zabin-canary-worker-3a60de",
    )
    secret_names = [server["credential_environment"] for server in lock["servers"].values()]
    secrets = [*canaries, *(os.environ.get(name, "") for name in secret_names)]
    verified_executables: dict[str, Path] = {}
    checks = verify_startup(lock, verified_executables=verified_executables)
    policy = _load_json(DEFAULT_POLICY, "canonical MCP policy")

    for host, path in args.host_report:
        report = _load_json(path, f"{host} native-host report")
        if host == "goose":
            checks.extend(
                assess_goose_native_report(
                    report,
                    lock,
                    policy,
                    canaries=[value for value in secrets if value],
                )
            )
        else:
            checks.extend(
                assess_native_host_report(
                    host,
                    report,
                    lock,
                    policy,
                    canaries=[value for value in secrets if value],
                )
            )
    supplied_hosts = {host for host, _ in args.host_report}
    for host in ({"claude_code", "codex", "goose"} - supplied_hosts):
        checks.append(Check(f"host_{host}", "skip", "native-host observer report was not supplied"))

    if args.lifecycle_evidence:
        evidence = _load_json(args.lifecycle_evidence, "lifecycle evidence")
        environment_allowlist = {
            item.strip()
            for item in os.environ.get(lock["lifecycle"]["production_project_allowlist_environment"], "").split(",")
            if item.strip()
        }
        checks.extend(assess_lifecycle_evidence(evidence, lock, allowed_projects=set(args.allow_project) | environment_allowlist))
    else:
        checks.append(Check("lifecycle", "skip", "disposable lifecycle evidence was not supplied"))

    if args.live:
        if not passed(checks):
            checks.append(Check("live_launch", "fail", "strict startup did not pass; no client or conformance process launched"))
        else:
            token_files = {
                "conductor": zabin_doctor.DEFAULT_CONDUCTOR_TOKEN_FILE,
                "worker": zabin_doctor.DEFAULT_WORKER_TOKEN_FILE,
            }
            credentials = zabin_doctor.discover_credentials(policy, os.environ, token_files, read_tokens=True)
            checks.extend(
                probe_locked_surface_identities(
                    lock,
                    policy,
                    credentials,
                    timeout=float(lock["timeouts_seconds"]["readiness"]),
                )
            )
            live_checks = zabin_doctor.probe_live(
                policy,
                credentials,
                urls={surface: server["url"] for surface, server in lock["servers"].items()},
                timeout=float(lock["timeouts_seconds"]["readiness"]),
            )
            for item in live_checks:
                status = "pass" if item["status"] == "pass" else "fail"
                checks.append(Check(f"readiness_{item['name']}", status, str(item["detail"])))
            if not passed(checks):
                checks.append(
                    Check(
                        "official_launch",
                        "fail",
                        "identity or readiness gate failed; neither official surface runner launched",
                    )
                )
            else:
                artifact = Path(os.environ[lock["official_conformance"]["artifact_environment"]])
                verified_node = verified_executables.get("node")
                if verified_node is None:
                    checks.append(
                        Check(
                            "official_launch",
                            "fail",
                            "verified absolute Node executable was not retained; no runner launched",
                        )
                    )
                else:
                    with tempfile.TemporaryDirectory(prefix="zabin-conformance-") as temporary:
                        result_roots = {
                            surface: Path(temporary) / surface
                            for surface in ("conductor", "worker")
                        }
                        for result_root in result_roots.values():
                            result_root.mkdir(mode=0o700)
                            (result_root / "tmp").mkdir(mode=0o700)
                        for surface in ("conductor", "worker"):
                            server = lock["servers"][surface]
                            command = exact_server_command(
                                lock, server["url"], artifact, verified_node
                            )
                            result = run_redacted(
                                command,
                                timeout=float(lock["timeouts_seconds"]["conformance"]),
                                secrets=secrets,
                                environment=official_child_environment(
                                    os.environ, isolated_home=result_roots[surface]
                                ),
                                cwd=result_roots[surface],
                            )
                            process_passed = result["returncode"] == 0 and not result["timed_out"]
                            checks.append(
                                Check(
                                    f"official_{surface}_process",
                                    "pass" if process_passed else "fail",
                                    "official process exited successfully" if process_passed else "official process failed or timed out",
                                    evidence=result,
                                )
                            )
                        checks.extend(assess_independent_surface_results(result_roots, lock))
                    checks.append(
                        Check(
                            "temporary_cleanup",
                            "pass",
                            "isolated result trees were removed; raw process streams were never persisted",
                        )
                    )
    else:
        checks.append(Check("live_launch", "skip", "live execution requires explicit --live", required=False))

    report = {
        "schema_version": RESULT_SCHEMA,
        "requirements_revision": lock["requirements_revision"],
        "overall": "pass" if passed(checks) else "fail",
        "checks": [asdict(check) for check in checks],
        "security": {
            "raw_streams_persisted": False,
            "redaction_before_persistence": True,
            "synthetic_canaries_used": list(canaries),
        },
    }
    output = args.output or Path("/tmp/codex-artifacts") / ROOT.name / "conformance" / "report.json"
    write_report(output, report, secrets)
    print(json.dumps(_redact_value(report, secrets), indent=2, sort_keys=True))
    return 0 if report["overall"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
