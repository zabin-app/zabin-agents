#!/usr/bin/env python3
"""Render deterministic client adapters from the canonical Zabin MCP policy.

The module is intentionally dependency-free so it can run before any client is
installed.  It validates the policy, renders every artifact in memory, and only
then performs per-file atomic replacements in a caller-selected directory.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "config" / "zabin-mcp.json"
DEFAULT_SCHEMA = ROOT / "schemas" / "mcp-policy.schema.json"
SUPPORTED_SCHEMA_ID = "https://zabin.dev/schemas/mcp-policy.schema.json"
SUPPORTED_SCHEMA_MAJOR = 1
CODEX_APPROVAL_MODES = {
    "auto": "auto",
    "scope_granted": "auto",
    "prompt": "prompt",
    "human_gate": "prompt",
}


class RenderError(ValueError):
    """Raised when validation or rendering must fail closed."""


class SchemaValidationError(RenderError):
    """Raised when a policy does not conform to the bundled schema subset."""


@dataclass(frozen=True)
class TargetSpec:
    """Client capabilities that must be true before rendering is permitted."""

    name: str
    artifacts: tuple[PurePosixPath, ...]
    required_fields: frozenset[str]
    supports_tool_filtering: bool
    supports_approval_policy: bool
    renderer: Callable[[dict[str, Any]], dict[PurePosixPath, bytes]]


class Draft202012SubsetValidator:
    """Validate the JSON Schema features used by the MCP policy contract."""

    def __init__(self, schema: dict[str, Any]) -> None:
        self.schema = schema

    def validate(self, instance: Any) -> None:
        self._validate(instance, self.schema, "$")

    def _resolve(self, reference: str) -> dict[str, Any]:
        if not reference.startswith("#/"):
            raise SchemaValidationError(f"unsupported external schema reference: {reference}")
        node: Any = self.schema
        for segment in reference[2:].split("/"):
            node = node[segment.replace("~1", "/").replace("~0", "~")]
        if not isinstance(node, dict):
            raise SchemaValidationError(f"schema reference is not an object: {reference}")
        return node

    @staticmethod
    def _is_type(instance: Any, expected: str) -> bool:
        checks = {
            "object": lambda value: isinstance(value, dict),
            "array": lambda value: isinstance(value, list),
            "string": lambda value: isinstance(value, str),
            "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
            "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": lambda value: isinstance(value, bool),
            "null": lambda value: value is None,
        }
        return checks[expected](instance)

    def _validate(self, instance: Any, schema: dict[str, Any], path: str) -> None:
        if "$ref" in schema:
            self._validate(instance, self._resolve(schema["$ref"]), path)
            return
        if "const" in schema and instance != schema["const"]:
            raise SchemaValidationError(f"{path}: expected constant {schema['const']!r}")
        if "enum" in schema and instance not in schema["enum"]:
            raise SchemaValidationError(f"{path}: {instance!r} is not in enum")

        expected = schema.get("type")
        if expected is not None:
            expected_types = [expected] if isinstance(expected, str) else expected
            if not any(self._is_type(instance, item) for item in expected_types):
                raise SchemaValidationError(
                    f"{path}: expected {expected_types}, got {type(instance).__name__}"
                )

        if isinstance(instance, dict):
            for name in schema.get("required", []):
                if name not in instance:
                    raise SchemaValidationError(f"{path}: missing required property {name!r}")
            properties = schema.get("properties", {})
            additional = schema.get("additionalProperties", True)
            for name, value in instance.items():
                if name in properties:
                    self._validate(value, properties[name], f"{path}.{name}")
                elif additional is False:
                    raise SchemaValidationError(f"{path}: unexpected property {name!r}")
                elif isinstance(additional, dict):
                    self._validate(value, additional, f"{path}.{name}")

        if isinstance(instance, list):
            if len(instance) < schema.get("minItems", 0):
                raise SchemaValidationError(f"{path}: too few items")
            if "maxItems" in schema and len(instance) > schema["maxItems"]:
                raise SchemaValidationError(f"{path}: too many items")
            if schema.get("uniqueItems"):
                fingerprints = [json.dumps(item, sort_keys=True) for item in instance]
                if len(fingerprints) != len(set(fingerprints)):
                    raise SchemaValidationError(f"{path}: duplicate items")
            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for index, value in enumerate(instance):
                    self._validate(value, item_schema, f"{path}[{index}]")

        if isinstance(instance, str):
            if len(instance) < schema.get("minLength", 0):
                raise SchemaValidationError(f"{path}: string is too short")
            if "maxLength" in schema and len(instance) > schema["maxLength"]:
                raise SchemaValidationError(f"{path}: string is too long")
            if "pattern" in schema and re.search(schema["pattern"], instance) is None:
                raise SchemaValidationError(
                    f"{path}: {instance!r} does not match {schema['pattern']!r}"
                )


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RenderError(f"cannot read {label} {path}: {exc.strerror}") from exc
    except json.JSONDecodeError as exc:
        raise RenderError(f"invalid JSON in {label} {path}: line {exc.lineno}, column {exc.colno}") from exc
    if not isinstance(value, dict):
        raise RenderError(f"{label} root must be an object: {path}")
    return value


def _schema_major(version: str) -> int:
    try:
        return int(version.split(".", 1)[0])
    except (AttributeError, ValueError) as exc:
        raise RenderError(f"invalid policy schema_version: {version!r}") from exc


def validate_server_identities(policy: dict[str, Any]) -> None:
    """Check cross-field invariants that JSON Schema cannot express."""

    servers = policy["servers"]
    expected = {"zabin-conductor": "conductor", "zabin-worker": "worker"}
    seen_ids: set[str] = set()
    seen_surfaces: set[str] = set()
    seen_keys: set[str] = set()
    seen_urls: set[str] = set()
    seen_credentials: set[str] = set()

    for server in servers:
        server_id = server["id"]
        surface = server["surface"]
        identity = server["identity"]
        if server_id in seen_ids or surface in seen_surfaces:
            raise RenderError(f"duplicate server identity or surface: {server_id}/{surface}")
        if expected.get(server_id) != surface:
            raise RenderError(f"server identity mismatch: {server_id!r} cannot expose {surface!r}")
        if identity["surface_name"] != surface or identity["service_name"] != "zabin":
            raise RenderError(f"server identity fields do not match {server_id!r}")

        key = identity["client_server_key"]
        url = server["transport"]["url"]
        credential = server["credential"]["name"]
        if key in seen_keys or url in seen_urls or credential in seen_credentials:
            raise RenderError(f"server key, URL, and credential must be distinct: {server_id!r}")
        if server["credential"]["source"] != "environment":
            raise RenderError(f"literal credentials are forbidden for {server_id!r}")

        tool_names = [tool["name"] for tool in server["tools"]]
        if len(tool_names) != len(set(tool_names)):
            raise RenderError(f"duplicate canonical tool name in {server_id!r}")
        known_tools = set(tool_names)
        unknown_gates = set(server["approval_policy"]["human_gates"]) - known_tools
        if unknown_gates:
            raise RenderError(
                f"human gates reference unknown tools for {server_id!r}: "
                + ", ".join(sorted(unknown_gates))
            )
        for adapter in server["adapter_requirements"]:
            if adapter["server_key"] != key:
                raise RenderError(
                    f"adapter server key does not match identity for {server_id!r}: "
                    f"{adapter['server_key']!r} != {key!r}"
                )

        seen_ids.add(server_id)
        seen_surfaces.add(surface)
        seen_keys.add(key)
        seen_urls.add(url)
        seen_credentials.add(credential)

    if seen_ids != set(expected):
        raise RenderError(f"policy must define exactly these server identities: {', '.join(sorted(expected))}")


def load_and_validate_policy(policy_path: Path, schema_path: Path) -> dict[str, Any]:
    """Load a policy, verify its declared schema, and validate all invariants."""

    policy_path = policy_path.resolve()
    schema_path = schema_path.resolve()
    policy = _load_json(policy_path, "policy")
    schema = _load_json(schema_path, "schema")
    if schema.get("$id") != SUPPORTED_SCHEMA_ID:
        raise RenderError(f"unsupported schema identity: {schema.get('$id')!r}")
    declared_schema = policy.get("$schema")
    if not isinstance(declared_schema, str):
        raise RenderError("policy must declare a string $schema")
    if (policy_path.parent / declared_schema).resolve() != schema_path:
        raise RenderError(
            f"policy schema reference does not resolve to selected schema: {declared_schema!r}"
        )
    Draft202012SubsetValidator(schema).validate(policy)
    if _schema_major(policy["schema_version"]) != SUPPORTED_SCHEMA_MAJOR:
        raise RenderError(f"unsupported policy schema major: {policy['schema_version']!r}")
    validate_server_identities(policy)
    return policy


def required_environment(policy: dict[str, Any]) -> tuple[str, ...]:
    return tuple(sorted({server["credential"]["name"] for server in policy["servers"]}))


def missing_environment(
    policy: dict[str, Any], environ: Mapping[str, str]
) -> tuple[str, ...]:
    """Return absent or empty credential variable names without reading values out."""

    return tuple(name for name in required_environment(policy) if not environ.get(name))


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")


def _qualified_tool(server_key: str, tool_name: str) -> str:
    return f"mcp__{server_key}__{tool_name}"


def _adapter_for(server: dict[str, Any], target: str) -> dict[str, Any]:
    matches = [item for item in server["adapter_requirements"] if item["client"] == target]
    if len(matches) != 1:
        raise RenderError(f"{server['id']!r} must declare exactly one {target!r} adapter")
    return matches[0]


def _ordered_servers(policy: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(policy["servers"], key=lambda item: item["identity"]["client_server_key"])


def _ordered_tools(server: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(server["tools"], key=lambda item: item["name"])


def _render_claude(policy: dict[str, Any]) -> dict[PurePosixPath, bytes]:
    mcp_servers: dict[str, Any] = {}
    permissions = {"allow": [], "ask": [], "deny": []}
    for server in _ordered_servers(policy):
        adapter = _adapter_for(server, "claude_code")
        key = adapter["server_key"]
        credential = server["credential"]["name"]
        mcp_servers[key] = {
            "headers": {"Authorization": f"Bearer ${{{credential}}}"},
            "type": "http",
            "url": server["transport"]["url"],
        }
        for tool in _ordered_tools(server):
            rule = _qualified_tool(key, tool["name"])
            approval = tool["approval"]
            if approval in {"auto", "scope_granted"}:
                permissions["allow"].append(rule)
            elif approval in {"prompt", "human_gate"}:
                permissions["ask"].append(rule)
            else:
                permissions["deny"].append(rule)
    for rules in permissions.values():
        rules.sort()
    return {
        PurePosixPath(".mcp.json"): _json_bytes({"mcpServers": mcp_servers}),
        PurePosixPath(".claude/settings.json"): _json_bytes({"permissions": permissions}),
    }


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _toml_array(values: Sequence[str]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def _render_codex(policy: dict[str, Any]) -> dict[PurePosixPath, bytes]:
    lines = ["# Generated from config/zabin-mcp.json; do not edit.", ""]
    for server in _ordered_servers(policy):
        adapter = _adapter_for(server, "codex")
        key = adapter["server_key"]
        table = f"mcp_servers.{_toml_string(key)}"
        tools = _ordered_tools(server)
        enabled = [tool["name"] for tool in tools if tool["approval"] != "deny"]
        disabled = [tool["name"] for tool in tools if tool["approval"] == "deny"]
        default_mode = CODEX_APPROVAL_MODES.get(server["approval_policy"]["default"], "prompt")
        lines.extend(
            [
                f"[{table}]",
                f"url = {_toml_string(server['transport']['url'])}",
                f"bearer_token_env_var = {_toml_string(server['credential']['name'])}",
                f"enabled_tools = {_toml_array(enabled)}",
                f"disabled_tools = {_toml_array(disabled)}",
                f"default_tools_approval_mode = {_toml_string(default_mode)}",
                "",
            ]
        )
        for tool in tools:
            if tool["approval"] == "deny":
                continue
            lines.extend(
                [
                    f"[{table}.tools.{_toml_string(tool['name'])}]",
                    f"approval_mode = {_toml_string(CODEX_APPROVAL_MODES[tool['approval']])}",
                    "",
                ]
            )
    return {PurePosixPath(".codex/config.toml"): ("\n".join(lines)).encode("utf-8")}


TARGETS: dict[str, TargetSpec] = {
    "claude_code": TargetSpec(
        name="claude_code",
        artifacts=(PurePosixPath(".mcp.json"), PurePosixPath(".claude/settings.json")),
        required_fields=frozenset({"type", "url", "headers.Authorization"}),
        supports_tool_filtering=True,
        supports_approval_policy=True,
        renderer=_render_claude,
    ),
    "codex": TargetSpec(
        name="codex",
        artifacts=(PurePosixPath(".codex/config.toml"),),
        required_fields=frozenset({"url", "bearer_token_env_var", "enabled_tools"}),
        supports_tool_filtering=True,
        supports_approval_policy=True,
        renderer=_render_codex,
    ),
}


def validate_target(policy: dict[str, Any], target: TargetSpec) -> None:
    """Refuse adapters that would weaken filtering or approval semantics."""

    missing_capabilities = []
    if not target.supports_tool_filtering:
        missing_capabilities.append("required tool filtering")
    if not target.supports_approval_policy:
        missing_capabilities.append("required approval policy")
    if missing_capabilities:
        raise RenderError(
            f"target {target.name!r} cannot express " + " and ".join(missing_capabilities)
        )
    for server in policy["servers"]:
        adapter = _adapter_for(server, target.name)
        fields = set(adapter["required_fields"])
        missing = target.required_fields - fields
        if missing:
            raise RenderError(
                f"target {target.name!r} adapter for {server['id']!r} is missing required fields: "
                + ", ".join(sorted(missing))
            )


def render_target(policy: dict[str, Any], target_name: str) -> dict[PurePosixPath, bytes]:
    try:
        target = TARGETS[target_name]
    except KeyError as exc:
        raise RenderError(f"unknown target: {target_name!r}") from exc
    validate_target(policy, target)
    artifacts = target.renderer(policy)
    if tuple(sorted(artifacts)) != tuple(sorted(target.artifacts)):
        raise RenderError(f"target {target_name!r} produced an unexpected artifact set")
    return dict(sorted(artifacts.items(), key=lambda item: item[0].as_posix()))


def _safe_destination(output_dir: Path, relative_path: PurePosixPath) -> Path:
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise RenderError(f"unsafe adapter output path: {relative_path}")
    return output_dir.joinpath(*relative_path.parts)


def write_artifacts(output_dir: Path, artifacts: Mapping[PurePosixPath, bytes]) -> None:
    """Atomically replace rendered artifacts after all content is available."""

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    for relative_path, content in sorted(artifacts.items(), key=lambda item: item[0].as_posix()):
        destination = _safe_destination(output_dir, relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent, delete=False
            ) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def check_artifacts(
    output_dir: Path, artifacts: Mapping[PurePosixPath, bytes]
) -> tuple[PurePosixPath, ...]:
    stale = []
    for relative_path, expected in sorted(artifacts.items(), key=lambda item: item[0].as_posix()):
        destination = _safe_destination(output_dir, relative_path)
        try:
            actual = destination.read_bytes()
        except OSError:
            stale.append(relative_path)
            continue
        if actual != expected:
            stale.append(relative_path)
    return tuple(stale)


def dry_run_manifest(target: str, artifacts: Mapping[PurePosixPath, bytes]) -> str:
    manifest = {
        "artifacts": {
            path.as_posix(): content.decode("utf-8")
            for path, content in sorted(artifacts.items(), key=lambda item: item[0].as_posix())
        },
        "target": target,
    }
    return json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--target", required=True, choices=sorted(TARGETS))
    parser.add_argument("--output-dir", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="render to stdout without writing")
    mode.add_argument("--check", action="store_true", help="fail if output differs without writing")
    return parser


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        policy = load_and_validate_policy(args.policy, args.schema)
        missing = missing_environment(policy, os.environ if environ is None else environ)
        if missing:
            raise RenderError("missing required environment variables: " + ", ".join(missing))
        artifacts = render_target(policy, args.target)
        if args.dry_run:
            sys.stdout.write(dry_run_manifest(args.target, artifacts))
        elif args.check:
            stale = check_artifacts(args.output_dir, artifacts)
            if stale:
                sys.stderr.write(
                    "adapter check failed; stale or missing artifacts: "
                    + ", ".join(path.as_posix() for path in stale)
                    + "\n"
                )
                return 1
        else:
            write_artifacts(args.output_dir, artifacts)
    except RenderError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
