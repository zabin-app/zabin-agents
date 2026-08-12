#!/usr/bin/env python3
"""Safe, dependency-free diagnostics for the canonical Zabin MCP surfaces.

Static checks are the default. Network access and credential reads happen only
with ``--live``. Reports contain credential names and availability only; token
values are never included in diagnostics or exception text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import recovery_checkpoint, render_adapters


DEFAULT_POLICY = ROOT / "config" / "zabin-mcp.json"
DEFAULT_POLICY_SCHEMA = ROOT / "schemas" / "mcp-policy.schema.json"
DEFAULT_CONDUCTOR_TOKEN_FILE = Path("/home/ed/.zabin/mcp.token")
DEFAULT_WORKER_TOKEN_FILE = Path("/home/ed/.zabin/mcp-worker.token")
PROTOCOL_VERSION = "2025-11-25"
EMPTY_PROJECT_ID = "prj_00000000000000000000000000"

JsonObject = dict[str, Any]


class DoctorError(RuntimeError):
    """A safe diagnostic failure whose message contains no credential value."""


class TransportError(DoctorError):
    """HTTP or MCP transport failure, reduced to safe status metadata."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class Credential:
    surface: str
    environment_name: str
    file_path: Path
    environment_available: bool
    file_available: bool
    _token: str | None = field(default=None, repr=False)

    def report(self) -> JsonObject:
        return {
            "surface": self.surface,
            "environment_name": self.environment_name,
            "environment_available": self.environment_available,
            "file_name": self.file_path.name,
            "file_available": self.file_available,
            "live_credential_available": self._token is not None,
        }


Transport = Callable[[str, Mapping[str, str], bytes, float], HttpResponse]


def _default_transport(
    url: str, headers: Mapping[str, str], body: bytes, timeout: float
) -> HttpResponse:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResponse(
                status=response.status,
                headers=dict(response.headers.items()),
                body=response.read(),
            )
    except urllib.error.HTTPError as error:
        # Do not retain the response body: an auth proxy is allowed to reflect
        # request material, and diagnostics never need it for a rejected call.
        raise TransportError(
            f"HTTP request rejected with status {error.code}", status=error.code
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        reason = type(getattr(error, "reason", error)).__name__
        raise TransportError(f"HTTP request failed ({reason})") from None


def _header(headers: Mapping[str, str], name: str) -> str | None:
    lowered = name.lower()
    return next((value for key, value in headers.items() if key.lower() == lowered), None)


def _decode_response(body: bytes) -> JsonObject:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise TransportError("MCP response was not UTF-8") from None
    candidates: list[Any] = []
    for line in text.splitlines():
        if line.startswith("data:"):
            data = line[5:].strip()
            if data:
                try:
                    candidates.append(json.loads(data))
                except json.JSONDecodeError:
                    raise TransportError("MCP event contained invalid JSON") from None
    if not candidates and text.strip():
        try:
            candidates.append(json.loads(text))
        except json.JSONDecodeError:
            raise TransportError("MCP response contained invalid JSON") from None
    if not candidates or not isinstance(candidates[-1], dict):
        raise TransportError("MCP response did not contain a JSON-RPC object")
    return candidates[-1]


class McpClient:
    """Minimal Streamable HTTP client with an injectable unit-test transport."""

    def __init__(
        self,
        url: str,
        token: str | None,
        *,
        timeout: float = 10.0,
        transport: Transport = _default_transport,
    ) -> None:
        self.url = url
        self._token = token
        self.timeout = timeout
        self._transport = transport
        self._session_id: str | None = None
        self._request_id = 0

    def _post(self, payload: Mapping[str, Any], *, expect_response: bool = True) -> JsonObject | None:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self._token is not None:
            headers["Authorization"] = f"Bearer {self._token}"
        if self._session_id is not None:
            headers["Mcp-Session-Id"] = self._session_id
        response = self._transport(
            self.url,
            headers,
            json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            self.timeout,
        )
        if response.status < 200 or response.status >= 300:
            raise TransportError(
                f"HTTP request rejected with status {response.status}", status=response.status
            )
        session = _header(response.headers, "Mcp-Session-Id")
        if session:
            self._session_id = session
        if not expect_response or not response.body.strip():
            return None
        message = _decode_response(response.body)
        if "error" in message:
            error = message["error"]
            code = error.get("code") if isinstance(error, Mapping) else None
            raise TransportError(f"MCP request returned JSON-RPC error code {code}")
        return message

    def initialize(self) -> JsonObject:
        self._request_id += 1
        response = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "zabin-doctor", "version": "1.0"},
                },
            }
        )
        if response is None or not isinstance(response.get("result"), Mapping):
            raise TransportError("initialize returned no result")
        self._post(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            expect_response=False,
        )
        return dict(response["result"])

    def request(self, method: str, params: Mapping[str, Any] | None = None) -> JsonObject:
        self._request_id += 1
        payload: JsonObject = {"jsonrpc": "2.0", "id": self._request_id, "method": method}
        if params is not None:
            payload["params"] = dict(params)
        response = self._post(payload)
        if response is None or not isinstance(response.get("result"), Mapping):
            raise TransportError(f"{method} returned no result")
        return dict(response["result"])

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> JsonObject:
        return self.request("tools/call", {"name": name, "arguments": dict(arguments)})


def _load_json(path: Path, label: str) -> JsonObject:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DoctorError(f"cannot load {label} {path.name}: {type(error).__name__}") from None
    if not isinstance(value, dict):
        raise DoctorError(f"{label} root must be an object: {path.name}")
    return value


def _check(name: str, status: str, detail: str, **extra: Any) -> JsonObject:
    return {"name": name, "status": status, "detail": detail, **extra}


def _fingerprint(surface: str, tools: Sequence[str]) -> str:
    canonical = json.dumps(
        {"surface": surface, "tools": sorted(tools)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _validate_registry(config_name: str, schema_name: str) -> JsonObject:
    config_path = ROOT / "config" / config_name
    schema_path = ROOT / "schemas" / schema_name
    config = _load_json(config_path, config_name)
    schema = _load_json(schema_path, schema_name)
    declared = config.get("$schema")
    if not isinstance(declared, str) or (config_path.parent / declared).resolve() != schema_path:
        raise DoctorError(f"{config_name} does not select {schema_name}")
    render_adapters.Draft202012SubsetValidator(schema).validate(config)
    return config


def validate_static_contracts(
    policy_path: Path = DEFAULT_POLICY,
    policy_schema_path: Path = DEFAULT_POLICY_SCHEMA,
) -> tuple[JsonObject, list[JsonObject]]:
    checks: list[JsonObject] = []
    policy = render_adapters.load_and_validate_policy(policy_path, policy_schema_path)
    checks.append(_check("canonical_mcp_policy", "pass", "policy and server identities validate"))

    agents = _validate_registry("agents.json", "agent-role.schema.json")
    tiers = _validate_registry("model-tiers.json", "model-tier.schema.json")
    tier_ids = {tier["id"] for tier in tiers["tiers"]}
    unknown_tiers = sorted({role["model_tier"] for role in agents["roles"]} - tier_ids)
    if unknown_tiers:
        raise DoctorError("agent roles reference unknown model tier names: " + ", ".join(unknown_tiers))
    missing_sources = sorted(
        role["source"] for role in agents["roles"] if not (ROOT / role["source"]).is_file()
    )
    if missing_sources:
        raise DoctorError("agent source files are missing: " + ", ".join(missing_sources))
    checks.append(_check("agent_and_model_contracts", "pass", "registries validate and cross-link"))

    recovery_schema = _load_json(
        ROOT / "schemas" / "recovery-checkpoint.schema.json", "recovery checkpoint schema"
    )
    if recovery_schema.get("$id") != recovery_checkpoint.SCHEMA_ID:
        raise DoctorError("recovery schema identity differs from recovery module")
    sample = recovery_checkpoint.build_checkpoint(
        recovery_checkpoint.CheckpointKey(
            project_id="prj_doctor",
            plan_id="fplan_doctor",
            phase_id="pph_doctor",
            wave_id="wav_doctor",
            task_id="tsk_doctor",
            sha="0123456789abcdef",
        ),
        phase_base="0123456789abcdef",
    )
    render_adapters.Draft202012SubsetValidator(recovery_schema).validate(sample)
    checks.append(
        _check(
            "recovery_compatibility",
            "pass",
            f"module and schema agree on {recovery_checkpoint.SCHEMA_VERSION}",
        )
    )

    rendered = {
        target: sorted(path.as_posix() for path in render_adapters.render_target(policy, target))
        for target in sorted(render_adapters.TARGETS)
    }
    checks.append(
        _check("adapter_readiness", "pass", "all declared adapters render in memory", artifacts=rendered)
    )
    goose_lock = render_adapters.load_and_validate_goose_lock(policy)
    goose_client = goose_lock.get("client", {})
    goose_gates = goose_lock.get("required_gates", [])
    blocking_gate_ids = [
        str(gate["id"])
        for gate in goose_gates
        if isinstance(gate, Mapping)
        and gate.get("required") is True
        and gate.get("status") != "pass"
    ]
    support_status = str(goose_lock["support_status"])
    client_version = goose_client.get("version")
    release_commit = goose_client.get("release_commit")
    if not isinstance(client_version, str) or not client_version:
        raise DoctorError("Goose compatibility lock has no pinned client version")
    if not isinstance(release_commit, str) or len(release_commit) != 40:
        raise DoctorError("Goose compatibility lock has no pinned release commit")
    artifact_evidence = goose_lock.get("artifact_evidence")
    local_observation = (
        artifact_evidence.get("local_observation")
        if isinstance(artifact_evidence, Mapping)
        else None
    )
    local_digest = (
        local_observation.get("sha256")
        if isinstance(local_observation, Mapping)
        else None
    )
    if (
        not isinstance(local_digest, str)
        or len(local_digest) != 64
        or any(character not in "0123456789abcdef" for character in local_digest)
        or local_observation.get("version_output") != client_version
    ):
        raise DoctorError("Goose compatibility lock has invalid local binary evidence")
    source_evidence = goose_lock.get("source_evidence")
    if not isinstance(source_evidence, list) or not source_evidence:
        raise DoctorError("Goose compatibility lock has no source evidence")
    if any(
        not isinstance(item, Mapping)
        or item.get("commit") != release_commit
        or not isinstance(item.get("sha256"), str)
        or len(item["sha256"]) != 64
        for item in source_evidence
    ):
        raise DoctorError("Goose source evidence differs from the pinned release")
    checks.append(
        _check(
            "goose_compatibility",
            "pass",
            (
                f"Goose {client_version} is {support_status}; "
                + (
                    "active artifacts are disabled; blocking gates: "
                    + ", ".join(blocking_gate_ids)
                    if support_status == "unsupported"
                    else "the compatibility lock authorizes isolated artifacts"
                )
            ),
            support_status=support_status,
            client_version=client_version,
            release_commit=release_commit,
            active_artifacts=list(goose_lock["decision"]["active_artifacts"]),
            blocking_gate_ids=blocking_gate_ids,
            operator_action=(
                "Keep the Goose installer target inert and use --live --goose-binary "
                "with an explicit absolute path for a pinned-binary drift check."
                if support_status == "unsupported"
                else "Verify the pinned native client before activation."
            ),
        )
    )
    checks.append(
        _check(
            "canonical_surface_fingerprints",
            "pass",
            "canonical public tool inventories fingerprinted",
            surfaces={
                server["surface"]: {
                    "tool_count": len(server["tools"]),
                    "fingerprint": _fingerprint(
                        server["surface"], [tool["name"] for tool in server["tools"]]
                    ),
                }
                for server in policy["servers"]
            },
        )
    )
    return policy, checks


def diagnose_goose_binary(path: Path, policy: Mapping[str, Any]) -> JsonObject:
    """Compare one explicitly selected native binary with the local audit pin."""

    if not path.is_absolute():
        return _check(
            "goose_native_binary", "fail", "Goose binary path must be absolute"
        )
    try:
        metadata = path.lstat()
    except OSError as error:
        return _check(
            "goose_native_binary",
            "fail",
            f"cannot inspect Goose binary: {type(error).__name__}",
        )
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        return _check(
            "goose_native_binary",
            "fail",
            "Goose binary must be a non-symlink regular file",
        )

    lock = render_adapters.load_and_validate_goose_lock(dict(policy))
    expected_version = lock["client"]["version"]
    expected_sha256 = lock["artifact_evidence"]["local_observation"]["sha256"]
    try:
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory(prefix="zabin-goose-doctor-") as temporary:
            result = subprocess.run(
                [os.fspath(path), "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
                env={"GOOSE_PATH_ROOT": temporary, "PATH": os.defpath},
            )
        after = hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, subprocess.SubprocessError) as error:
        return _check(
            "goose_native_binary",
            "fail",
            f"cannot execute Goose version probe: {type(error).__name__}",
        )
    version = result.stdout.strip()
    if before != after:
        return _check(
            "goose_native_binary", "fail", "Goose binary changed during inspection"
        )
    if result.returncode != 0 or version != expected_version or before != expected_sha256:
        return _check(
            "goose_native_binary",
            "fail",
            "Goose binary differs from the pinned local audit observation",
            expected_version=expected_version,
            observed_version=version or "<empty>",
            version_matches=version == expected_version,
            digest_matches=before == expected_sha256,
            support_status=lock["support_status"],
        )
    official_verified = lock["artifact_evidence"].get("official_artifact_verified") is True
    supported = lock["support_status"] == "supported"
    status = "pass" if official_verified and supported else "degraded"
    return _check(
        "goose_native_binary",
        status,
        (
            "Goose binary matches the pinned local audit observation; "
            "official artifact integrity remains unverified and support remains disabled"
            if status == "degraded"
            else "Goose binary matches the supported official artifact pin"
        ),
        expected_version=expected_version,
        observed_version=version,
        version_matches=True,
        digest_matches=True,
        official_artifact_verified=official_verified,
        support_status=lock["support_status"],
    )


def discover_credentials(
    policy: Mapping[str, Any],
    environ: Mapping[str, str],
    token_files: Mapping[str, Path],
    *,
    read_tokens: bool,
) -> dict[str, Credential]:
    credentials: dict[str, Credential] = {}
    for server in policy["servers"]:
        surface = server["surface"]
        environment_name = server["credential"]["name"]
        file_path = token_files[surface]
        environment_available = bool(environ.get(environment_name))
        try:
            file_available = file_path.is_file() and file_path.stat().st_size > 0
        except OSError:
            file_available = False
        token: str | None = None
        if read_tokens:
            if environment_available:
                token = environ[environment_name]
            elif file_available:
                try:
                    candidate = file_path.read_text(encoding="utf-8").strip()
                except OSError:
                    candidate = ""
                token = candidate or None
        credentials[surface] = Credential(
            surface=surface,
            environment_name=environment_name,
            file_path=file_path,
            environment_available=environment_available,
            file_available=file_available,
            _token=token,
        )
    return credentials


def _tool_payload(result: Mapping[str, Any]) -> tuple[JsonObject | None, bool]:
    is_error = bool(result.get("isError"))
    structured = result.get("structuredContent")
    return (dict(structured) if isinstance(structured, Mapping) else None, is_error)


def _probe_auth_rejection(
    *, url: str, token: str | None, timeout: float, transport: Transport
) -> bool | None:
    try:
        McpClient(url, token, timeout=timeout, transport=transport).initialize()
    except TransportError as error:
        return True if error.status in {401, 403} else None
    return False


def _list_all_tools(client: McpClient) -> list[str]:
    names: list[str] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while True:
        listed = client.request("tools/list", {"cursor": cursor} if cursor else None)
        entries = listed.get("tools")
        if not isinstance(entries, list) or not all(
            isinstance(entry, Mapping) and isinstance(entry.get("name"), str) for entry in entries
        ):
            raise DoctorError("tools/list returned an invalid inventory")
        names.extend(entry["name"] for entry in entries)
        next_cursor = listed.get("nextCursor")
        if next_cursor is None:
            break
        if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
            raise DoctorError("tools/list returned an invalid pagination cursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    if len(names) != len(set(names)):
        raise DoctorError("tools/list returned duplicate public tool names")
    return sorted(names)


def _transport_failure_detail(
    attempted_url: str,
    error: TransportError,
    policy: Mapping[str, Any],
) -> str:
    """Explain a failed HTTP probe without reflecting URL credential material."""

    canonical = {
        server["surface"]: server["transport"]["url"] for server in policy["servers"]
    }
    guidance = (
        f"use canonical configured endpoints conductor {canonical['conductor']} and "
        f"worker {canonical['worker']}"
    )
    try:
        attempted = urllib.parse.urlsplit(attempted_url)
        conductor = urllib.parse.urlsplit(canonical["conductor"])
        worker = urllib.parse.urlsplit(canonical["worker"])
        derived_grpc_listener = (
            attempted.scheme == "http"
            and attempted.hostname == conductor.hostname == worker.hostname
            and attempted.path == "/mcp"
            and attempted.port is not None
            and conductor.port == attempted.port + 1
            and worker.port == conductor.port + 1
            and conductor.path == "/mcp"
            and worker.path == "/mcp-worker"
        )
    except ValueError:
        derived_grpc_listener = False
        attempted = urllib.parse.SplitResult("", "", "", "", "")
    if derived_grpc_listener:
        return (
            f"transport mismatch: port {attempted.port} is the Zabin gRPC listener, not "
            f"Streamable HTTP; {guidance}"
        )
    return f"Streamable HTTP transport failed ({error}); {guidance}"


def probe_live(
    policy: Mapping[str, Any],
    credentials: Mapping[str, Credential],
    *,
    urls: Mapping[str, str],
    timeout: float = 10.0,
    transport: Transport = _default_transport,
) -> list[JsonObject]:
    checks: list[JsonObject] = []
    servers = {server["surface"]: server for server in policy["servers"]}
    tokens = {surface: credential._token for surface, credential in credentials.items()}

    for surface in ("conductor", "worker"):
        server = servers[surface]
        expected_tools = sorted(tool["name"] for tool in server["tools"])
        token = tokens[surface]
        if token is None:
            checks.append(
                _check(
                    f"{surface}_live_surface",
                    "fail",
                    f"credential unavailable ({server['credential']['name']} or {credentials[surface].file_path.name})",
                )
            )
            continue
        try:
            client = McpClient(urls[surface], token, timeout=timeout, transport=transport)
            initialized = client.initialize()
            negotiated = initialized.get("protocolVersion")
            expected_protocol = server["identity"]["protocol_version"]
            if negotiated != expected_protocol:
                raise DoctorError(
                    f"negotiated protocol {negotiated!r} differs from canonical {expected_protocol!r}"
                )
            server_info = initialized.get("serverInfo")
            expected_version = server["identity"]["server_version"]
            if not isinstance(server_info, Mapping) or server_info.get("version") != expected_version:
                raise DoctorError("initialize server version differs from canonical policy")
            actual_tools = _list_all_tools(client)
            expected_fingerprint = _fingerprint(surface, expected_tools)
            actual_fingerprint = _fingerprint(surface, actual_tools)
            if actual_tools != expected_tools:
                missing = sorted(set(expected_tools) - set(actual_tools))
                unexpected = sorted(set(actual_tools) - set(expected_tools))
                checks.append(
                    _check(
                        f"{surface}_live_surface",
                        "fail",
                        "live inventory differs from canonical policy",
                        missing_tools=missing,
                        unexpected_tools=unexpected,
                        expected_fingerprint=expected_fingerprint,
                        actual_fingerprint=actual_fingerprint,
                    )
                )
                continue

            if "get_server_info" in expected_tools:
                payload, is_error = _tool_payload(client.call_tool("get_server_info", {}))
                if is_error or payload is None:
                    raise DoctorError("get_server_info did not return structured success")
                if payload.get("protocol_version") != expected_protocol:
                    raise DoctorError("get_server_info protocol differs from canonical policy")
                if payload.get("version") != expected_version:
                    raise DoctorError("get_server_info version differs from canonical policy")
                reported_tools = payload.get("tools")
                if not isinstance(reported_tools, list) or sorted(reported_tools) != expected_tools:
                    raise DoctorError("get_server_info inventory differs from canonical policy")

            checks.append(
                _check(
                    f"{surface}_live_surface",
                    "pass",
                    "protocol and exact public tool inventory match canonical policy",
                    tool_count=len(actual_tools),
                    fingerprint=actual_fingerprint,
                )
            )

            payload, is_error = _tool_payload(
                client.call_tool(
                    "search_context",
                    {"project_id": EMPTY_PROJECT_ID, "query": "zabin doctor readiness", "limit": 1},
                )
            )
            if is_error:
                checks.append(
                    _check(
                        f"{surface}_optional_retrieval",
                        "degraded",
                        "search_context empty-project probe failed; core MCP readiness is unaffected",
                    )
                )
            else:
                checks.append(
                    _check(
                        f"{surface}_optional_retrieval",
                        "pass",
                        "search_context empty-project probe completed",
                        hit_count=(payload or {}).get("count"),
                    )
                )
        except TransportError as error:
            checks.append(
                _check(
                    f"{surface}_live_surface",
                    "fail",
                    _transport_failure_detail(urls[surface], error, policy),
                )
            )
        except (DoctorError, render_adapters.RenderError) as error:
            checks.append(_check(f"{surface}_live_surface", "fail", str(error)))

    for surface, other_surface in (("conductor", "worker"), ("worker", "conductor")):
        url = urls[surface]
        missing_rejected = _probe_auth_rejection(
            url=url, token=None, timeout=timeout, transport=transport
        )
        swapped_rejected = _probe_auth_rejection(
            url=url, token=tokens[other_surface], timeout=timeout, transport=transport
        )
        boundary_passed = missing_rejected is True and swapped_rejected is True
        if missing_rejected is None or swapped_rejected is None:
            detail = "authorization boundary is indeterminate because the endpoint was unavailable"
        elif boundary_passed:
            detail = "missing and swapped credentials are rejected"
        else:
            detail = "missing or swapped credential unexpectedly reached the surface"
        checks.append(
            _check(
                f"{surface}_authorization_boundary",
                "pass" if boundary_passed else "fail",
                detail,
                missing_rejected=missing_rejected,
                swapped_rejected=swapped_rejected,
            )
        )
    return checks


def _overall(checks: Sequence[Mapping[str, Any]]) -> str:
    statuses = {check["status"] for check in checks}
    if "fail" in statuses:
        return "fail"
    if "degraded" in statuses:
        return "degraded"
    return "pass"


def run_doctor(
    *,
    live: bool,
    policy_path: Path = DEFAULT_POLICY,
    policy_schema_path: Path = DEFAULT_POLICY_SCHEMA,
    environ: Mapping[str, str] | None = None,
    token_files: Mapping[str, Path] | None = None,
    urls: Mapping[str, str] | None = None,
    timeout: float = 10.0,
    transport: Transport = _default_transport,
    goose_binary: Path | None = None,
) -> JsonObject:
    environment = os.environ if environ is None else environ
    files = token_files or {
        "conductor": DEFAULT_CONDUCTOR_TOKEN_FILE,
        "worker": DEFAULT_WORKER_TOKEN_FILE,
    }
    try:
        policy, checks = validate_static_contracts(policy_path, policy_schema_path)
        credentials = discover_credentials(policy, environment, files, read_tokens=live)
        if live:
            if goose_binary is not None:
                checks.append(diagnose_goose_binary(goose_binary, policy))
            selected_urls = urls or {
                server["surface"]: server["transport"]["url"] for server in policy["servers"]
            }
            checks.extend(
                probe_live(
                    policy,
                    credentials,
                    urls=selected_urls,
                    timeout=timeout,
                    transport=transport,
                )
            )
    except (DoctorError, render_adapters.RenderError) as error:
        checks = [_check("static_contracts", "fail", str(error))]
        credentials = {}
    report = {
        "doctor_version": "1.0.0",
        "mode": "live" if live else "static",
        "status": _overall(checks),
        "credentials": [credentials[name].report() for name in sorted(credentials)],
        "checks": checks,
    }
    known_tokens = [credential._token for credential in credentials.values() if credential._token]
    serialized = json.dumps(report, sort_keys=True)
    if any(token in serialized for token in known_tokens):
        raise DoctorError("internal redaction guard rejected diagnostic output")
    return report


def render_human(report: Mapping[str, Any]) -> str:
    lines = [
        f"Zabin doctor: {str(report['status']).upper()} ({report['mode']} mode)",
        "Credentials (availability only):",
    ]
    for credential in report["credentials"]:
        lines.append(
            "  - {surface}: {environment_name} env={environment_available}; "
            "{file_name} file={file_available}".format(**credential)
        )
    lines.append("Checks:")
    for check in report["checks"]:
        lines.append(f"  - [{str(check['status']).upper()}] {check['name']}: {check['detail']}")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="explicitly enable read-only network probes")
    parser.add_argument(
        "--live-url",
        help="use one explicitly configured Streamable HTTP gateway URL for both tokens",
    )
    parser.add_argument("--conductor-url", help="override the canonical conductor endpoint")
    parser.add_argument("--worker-url", help="override the canonical worker endpoint")
    parser.add_argument("--conductor-token-file", type=Path, default=DEFAULT_CONDUCTOR_TOKEN_FILE)
    parser.add_argument("--worker-token-file", type=Path, default=DEFAULT_WORKER_TOKEN_FILE)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--policy-schema", type=Path, default=DEFAULT_POLICY_SCHEMA)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument(
        "--goose-binary",
        type=Path,
        help="absolute pinned Goose executable to inspect during --live diagnostics",
    )
    parser.add_argument("--json", action="store_true", help="emit the machine-readable report")
    return parser


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.live and (
        args.live_url or args.conductor_url or args.worker_url or args.goose_binary
    ):
        build_parser().error("URL overrides and --goose-binary require --live")
    urls: dict[str, str] | None = None
    if args.live:
        try:
            policy = render_adapters.load_and_validate_policy(args.policy, args.policy_schema)
        except render_adapters.RenderError:
            # run_doctor emits the structured, sanitized contract failure.
            pass
        else:
            urls = {server["surface"]: server["transport"]["url"] for server in policy["servers"]}
            if args.live_url:
                urls = {"conductor": args.live_url, "worker": args.live_url}
            if args.conductor_url:
                urls["conductor"] = args.conductor_url
            if args.worker_url:
                urls["worker"] = args.worker_url
    report = run_doctor(
        live=args.live,
        policy_path=args.policy,
        policy_schema_path=args.policy_schema,
        environ=environ,
        token_files={
            "conductor": args.conductor_token_file,
            "worker": args.worker_token_file,
        },
        urls=urls,
        timeout=args.timeout,
        goose_binary=args.goose_binary,
    )
    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(render_human(report))
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
