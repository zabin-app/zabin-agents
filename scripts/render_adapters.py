#!/usr/bin/env python3
"""Render deterministic client adapters from the canonical Zabin MCP policy.

The module is intentionally dependency-free so it can run before any client is
installed.  It validates the policy, renders every artifact in memory, and only
then performs per-file atomic replacements in a caller-selected directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "config" / "zabin-mcp.json"
DEFAULT_SCHEMA = ROOT / "schemas" / "mcp-policy.schema.json"
DEFAULT_GOOSE_LOCK = ROOT / "adapters" / "goose" / "client-lock.json"
TEMPLATE_ROOT = ROOT / "adapters"
SUPPORTED_SCHEMA_ID = "https://zabin.dev/schemas/mcp-policy.schema.json"
SUPPORTED_SCHEMA_MAJOR = 1
TEMPLATE_TOKEN = re.compile(r"@@([A-Z][A-Z0-9_]*)@@")
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


@dataclass(frozen=True)
class TemplateSpec:
    """A checked template and its exact output contract."""

    name: str
    source: PurePosixPath
    artifact: PurePosixPath
    placeholders: frozenset[str]
    syntax: str
    admin_only: bool = False


TEMPLATES: dict[str, TemplateSpec] = {
    "claude_mcp": TemplateSpec(
        name="claude_mcp",
        source=PurePosixPath("claude/mcp.json.template"),
        artifact=PurePosixPath(".mcp.json"),
        placeholders=frozenset({"MCP_SERVERS"}),
        syntax="json",
    ),
    "claude_settings": TemplateSpec(
        name="claude_settings",
        source=PurePosixPath("claude/settings.json.template"),
        artifact=PurePosixPath(".claude/settings.json"),
        placeholders=frozenset(
            {"ALLOW_RULES", "ASK_RULES", "DENY_RULES", "PREFLIGHT_COMMAND"}
        ),
        syntax="json",
    ),
    "codex_config": TemplateSpec(
        name="codex_config",
        source=PurePosixPath("codex/config.toml.template"),
        artifact=PurePosixPath(".codex/config.toml"),
        placeholders=frozenset({"MCP_SERVERS", "PREFLIGHT_COMMAND"}),
        syntax="toml",
    ),
    "codex_requirements": TemplateSpec(
        name="codex_requirements",
        source=PurePosixPath("codex/requirements.toml.template"),
        artifact=PurePosixPath("requirements.toml"),
        placeholders=frozenset({"MCP_SERVER_IDENTITIES"}),
        syntax="toml",
        admin_only=True,
    ),
    "goose_recipe": TemplateSpec(
        name="goose_recipe",
        source=PurePosixPath("goose/recipe.json.template"),
        artifact=PurePosixPath("goose/recipe.json"),
        placeholders=frozenset(),
        syntax="json",
    ),
    "goose_settings": TemplateSpec(
        name="goose_settings",
        source=PurePosixPath("goose/settings.json.template"),
        artifact=PurePosixPath("goose/settings.json"),
        placeholders=frozenset(),
        syntax="json",
    ),
}


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
    expected_adapters = {
        "claude_code": {
            "config_target": ".mcp.json",
            "credential_binding": "environment_interpolation",
            "tool_reference_mode": "client_qualified",
            "required_fields": {"type", "url", "headers.Authorization"},
        },
        "codex": {
            "config_target": ".codex/config.toml",
            "credential_binding": "bearer_token_env_var",
            "tool_reference_mode": "client_native",
            "required_fields": {"url", "bearer_token_env_var", "enabled_tools"},
        },
        "goose": {
            "config_target": "goose/recipe.json",
            "credential_binding": "environment_interpolation",
            "tool_reference_mode": "extension_qualified",
            "required_fields": {
                "type",
                "name",
                "uri",
                "headers.Authorization",
                "available_tools",
            },
        },
    }
    seen_ids: set[str] = set()
    seen_surfaces: set[str] = set()
    seen_keys: set[str] = set()
    seen_urls: set[str] = set()
    seen_credentials: set[str] = set()
    goose_keys: set[str] = set()

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
        if not tool_names:
            raise RenderError(f"server tool allowlist must not be empty: {server_id!r}")
        if len(tool_names) != len(set(tool_names)):
            raise RenderError(f"duplicate canonical tool name in {server_id!r}")
        known_tools = set(tool_names)
        gates = server["approval_policy"]["human_gates"]
        if len(gates) != len(set(gates)):
            raise RenderError(f"duplicate human gate in {server_id!r}")
        unknown_gates = set(server["approval_policy"]["human_gates"]) - known_tools
        if unknown_gates:
            raise RenderError(
                f"human gates reference unknown tools for {server_id!r}: "
                + ", ".join(sorted(unknown_gates))
            )
        approval_by_tool = {tool["name"]: tool["approval"] for tool in server["tools"]}
        non_gate_human_approvals = {
            name for name, approval in approval_by_tool.items() if approval == "human_gate"
        } - set(gates)
        if non_gate_human_approvals:
            raise RenderError(
                f"human-gated tools are missing from human_gates for {server_id!r}: "
                + ", ".join(sorted(non_gate_human_approvals))
            )
        wrong_gate_approvals = {name for name in gates if approval_by_tool[name] != "human_gate"}
        if wrong_gate_approvals:
            raise RenderError(
                f"human_gates reference tools without human_gate approval for {server_id!r}: "
                + ", ".join(sorted(wrong_gate_approvals))
            )

        adapters = server["adapter_requirements"]
        clients = [adapter["client"] for adapter in adapters]
        if len(clients) != len(set(clients)) or set(clients) != set(expected_adapters):
            raise RenderError(
                f"{server_id!r} must declare exactly one adapter for each supported client"
            )
        for adapter in adapters:
            expected_key = (
                f"zabin-{surface}" if adapter["client"] == "goose" else key
            )
            if adapter["server_key"] != expected_key:
                raise RenderError(
                    f"adapter server key does not match identity for {server_id!r}: "
                    f"{adapter['server_key']!r} != {expected_key!r}"
                )
            adapter_expected = expected_adapters[adapter["client"]]
            for field in ("config_target", "credential_binding", "tool_reference_mode"):
                if adapter[field] != adapter_expected[field]:
                    raise RenderError(
                        f"{adapter['client']!r} adapter {field} mismatch for {server_id!r}"
                    )
            required_fields = adapter["required_fields"]
            if len(required_fields) != len(set(required_fields)):
                raise RenderError(
                    f"duplicate required adapter field for {server_id!r}/{adapter['client']}"
                )
            missing_fields = adapter_expected["required_fields"] - set(required_fields)
            if missing_fields:
                raise RenderError(
                    f"{adapter['client']!r} adapter for {server_id!r} is missing required fields: "
                    + ", ".join(sorted(missing_fields))
                )
            unknown_fields = set(required_fields) - adapter_expected["required_fields"]
            if unknown_fields:
                raise RenderError(
                    f"unknown required adapter fields for {server_id!r}/{adapter['client']}: "
                    + ", ".join(sorted(unknown_fields))
                )
            if adapter["client"] == "goose":
                normalized = _normalize_goose_extension_name(adapter["server_key"])
                if not normalized or normalized in goose_keys:
                    raise RenderError("Goose extension names must normalize uniquely")
                goose_keys.add(normalized)

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
    risk_ids = [risk["id"] for risk in policy["risk_classes"]]
    if len(risk_ids) != len(set(risk_ids)):
        raise RenderError("duplicate risk class ids are forbidden")
    expected_risk_ids = {
        "read_only",
        "task_scoped_write",
        "durable_write",
        "destructive",
        "human_interaction",
    }
    if set(risk_ids) != expected_risk_ids:
        raise RenderError("policy must declare every canonical risk class exactly once")
    validate_server_identities(policy)
    return policy


def required_environment(policy: dict[str, Any]) -> tuple[str, ...]:
    return tuple(sorted({server["credential"]["name"] for server in policy["servers"]}))


def _is_literal_placeholder(name: str, value: str) -> bool:
    stripped = value.strip()
    placeholders = {
        f"${name}",
        f"${{{name}}}",
        f"Bearer ${name}",
        f"Bearer ${{{name}}}",
        f"@@{name}@@",
    }
    return stripped in placeholders or f"${{{name}}}" in stripped


def missing_environment(
    policy: dict[str, Any], environ: Mapping[str, str]
) -> tuple[str, ...]:
    """Return unusable credential names without exposing their values."""

    unusable = []
    for name in required_environment(policy):
        value = environ.get(name)
        if not value or _is_literal_placeholder(name, value):
            unusable.append(name)
    return tuple(unusable)


def validate_template_manifest(
    manifest: Mapping[str, TemplateSpec] = TEMPLATES,
) -> None:
    """Validate the complete checked template inventory and placeholder sets."""

    expected_names = {
        "claude_mcp",
        "claude_settings",
        "codex_config",
        "codex_requirements",
        "goose_recipe",
        "goose_settings",
    }
    if set(manifest) != expected_names:
        missing = sorted(expected_names - set(manifest))
        unknown = sorted(set(manifest) - expected_names)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if unknown:
            detail.append("unknown " + ", ".join(unknown))
        raise RenderError("invalid template manifest: " + "; ".join(detail))

    sources: set[PurePosixPath] = set()
    artifacts: set[PurePosixPath] = set()
    for name, spec in manifest.items():
        if name != spec.name:
            raise RenderError(f"template manifest key/name mismatch: {name!r}/{spec.name!r}")
        for label, path in (("source", spec.source), ("artifact", spec.artifact)):
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise RenderError(f"unsafe template {label} path for {name!r}: {path}")
        if spec.source.suffix != ".template":
            raise RenderError(f"template source must end in .template: {spec.source}")
        if spec.syntax not in {"json", "toml"}:
            raise RenderError(f"unknown template syntax for {name!r}: {spec.syntax!r}")
        if spec.admin_only != (name == "codex_requirements"):
            raise RenderError(f"template admin-only classification mismatch for {name!r}")
        if not spec.placeholders and not name.startswith("goose_"):
            raise RenderError(f"template {name!r} must declare placeholders")
        if spec.source in sources:
            raise RenderError(f"duplicate template source: {spec.source}")
        if spec.artifact in artifacts:
            raise RenderError(f"duplicate adapter artifact: {spec.artifact}")
        sources.add(spec.source)
        artifacts.add(spec.artifact)

        template_path = TEMPLATE_ROOT.joinpath(*spec.source.parts)
        try:
            template = template_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RenderError(
                f"cannot read adapter template {spec.source}: {exc.strerror}"
            ) from exc
        tokens = TEMPLATE_TOKEN.findall(template)
        if len(tokens) != len(set(tokens)):
            raise RenderError(f"duplicate placeholder in template {spec.source}")
        found = set(tokens)
        if found != set(spec.placeholders):
            missing = sorted(set(spec.placeholders) - found)
            unknown = sorted(found - set(spec.placeholders))
            detail = []
            if missing:
                detail.append("missing " + ", ".join(missing))
            if unknown:
                detail.append("unknown " + ", ".join(unknown))
            raise RenderError(
                f"template placeholder mismatch for {spec.source}: " + "; ".join(detail)
            )


def _render_template(spec: TemplateSpec, replacements: Mapping[str, str]) -> bytes:
    if set(replacements) != set(spec.placeholders):
        missing = sorted(set(spec.placeholders) - set(replacements))
        unknown = sorted(set(replacements) - set(spec.placeholders))
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if unknown:
            detail.append("unknown " + ", ".join(unknown))
        raise RenderError(
            f"replacement mismatch for template {spec.source}: " + "; ".join(detail)
        )
    try:
        template = TEMPLATE_ROOT.joinpath(*spec.source.parts).read_text(encoding="utf-8")
    except OSError as exc:
        raise RenderError(f"cannot read adapter template {spec.source}: {exc.strerror}") from exc
    rendered = template
    for name in sorted(replacements):
        rendered = rendered.replace(f"@@{name}@@", replacements[name])
    if any(f"@@{name}@@" in rendered for name in spec.placeholders):
        raise RenderError(f"unresolved placeholder in template {spec.source}")
    if not rendered.endswith("\n"):
        rendered += "\n"
    try:
        if spec.syntax == "json":
            json.loads(rendered)
        else:
            tomllib.loads(rendered)
    except (json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        raise RenderError(f"rendered {spec.source} is invalid {spec.syntax}: {exc}") from exc
    return rendered.encode("utf-8")


def _json_fragment(value: Any, indentation: int) -> str:
    fragment = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True)
    return fragment.replace("\n", "\n" + (" " * indentation))


def _preflight_command(policy: dict[str, Any]) -> str:
    """Build a shell preflight that stops a client before its first model turn."""

    clauses = []
    for name in required_environment(policy):
        value = f'"${{{name}:-}}"'
        clauses.append(f"[ -z {value} ]")
        for placeholder in (
            f"${name}",
            f"${{{name}}}",
            f"Bearer ${name}",
            f"Bearer ${{{name}}}",
            f"@@{name}@@",
        ):
            clauses.append(f"[ {value} = {shlex.quote(placeholder)} ]")
    response = json.dumps(
        {
            "continue": False,
            "stopReason": (
                "Zabin MCP credentials are missing or unresolved. The checked-in project "
                "adapter is a convenience default, not managed enforcement; administrators "
                "must deploy managed policy separately."
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        "if "
        + " || ".join(clauses)
        + f"; then printf '%s\\n' {shlex.quote(response)}; fi"
    )


def _qualified_tool(server_key: str, tool_name: str) -> str:
    return f"mcp__{server_key}__{tool_name}"


def _normalize_goose_extension_name(value: str) -> str:
    """Mirror the pinned Goose 1.45.0 extension-name normalization."""

    normalized = []
    for character in value.lower():
        if character.isspace():
            continue
        if character.isascii() and (character.isalnum() or character in {"-", "_"}):
            normalized.append(character)
        else:
            normalized.append("_")
    return "".join(normalized)


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
    mcp_spec = TEMPLATES["claude_mcp"]
    settings_spec = TEMPLATES["claude_settings"]
    return {
        mcp_spec.artifact: _render_template(
            mcp_spec,
            {"MCP_SERVERS": _json_fragment(mcp_servers, 2)},
        ),
        settings_spec.artifact: _render_template(
            settings_spec,
            {
                "ALLOW_RULES": _json_fragment(permissions["allow"], 4),
                "ASK_RULES": _json_fragment(permissions["ask"], 4),
                "DENY_RULES": _json_fragment(permissions["deny"], 4),
                "PREFLIGHT_COMMAND": json.dumps(
                    _preflight_command(policy), ensure_ascii=True
                ),
            },
        ),
    }


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _toml_array(values: Sequence[str]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def _render_codex(policy: dict[str, Any]) -> dict[PurePosixPath, bytes]:
    lines: list[str] = []
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
                "enabled = true",
                "required = true",
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
    spec = TEMPLATES["codex_config"]
    return {
        spec.artifact: _render_template(
            spec,
            {
                "MCP_SERVERS": "\n".join(lines).rstrip(),
                "PREFLIGHT_COMMAND": _toml_string(_preflight_command(policy)),
            },
        )
    }


def _render_codex_requirements(
    policy: dict[str, Any],
) -> dict[PurePosixPath, bytes]:
    lines: list[str] = []
    for server in _ordered_servers(policy):
        key = _adapter_for(server, "codex")["server_key"]
        lines.extend(
            [
                f"[mcp_servers.{_toml_string(key)}]",
                f"identity = {{ url = {_toml_string(server['transport']['url'])} }}",
                "",
            ]
        )
    spec = TEMPLATES["codex_requirements"]
    return {
        spec.artifact: _render_template(
            spec,
            {"MCP_SERVER_IDENTITIES": "\n".join(lines).rstrip()},
        )
    }


def _inventory_fingerprint(surface: str, tools: Sequence[str]) -> str:
    canonical = json.dumps(
        {"surface": surface, "tools": sorted(tools)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def load_and_validate_goose_lock(
    policy: dict[str, Any], lock_path: Path = DEFAULT_GOOSE_LOCK
) -> dict[str, Any]:
    """Load the pinned Goose decision and require exact canonical-policy parity."""

    lock = _load_json(lock_path.resolve(), "Goose compatibility lock")
    status = lock.get("support_status")
    decision = lock.get("decision")
    surfaces = lock.get("canonical_surfaces")
    gates = lock.get("required_gates")
    if status not in {"supported", "unsupported"}:
        raise RenderError("Goose compatibility lock has an invalid support_status")
    if not isinstance(decision, dict) or not isinstance(surfaces, dict):
        raise RenderError("Goose compatibility lock is incomplete")
    if not isinstance(gates, list) or not gates:
        raise RenderError("Goose compatibility lock has no required gates")

    policy_surfaces = {server["surface"]: server for server in policy["servers"]}
    if set(surfaces) != set(policy_surfaces):
        raise RenderError("Goose compatibility lock surface set differs from policy")
    normalized_names: set[str] = set()
    for surface, server in policy_surfaces.items():
        adapter = _adapter_for(server, "goose")
        locked = surfaces[surface]
        if not isinstance(locked, dict):
            raise RenderError(f"Goose lock surface {surface!r} is invalid")
        tools = [tool["name"] for tool in server["tools"]]
        expected = {
            "extension_name": adapter["server_key"],
            "normalized_extension_name": _normalize_goose_extension_name(
                adapter["server_key"]
            ),
            "credential_environment": server["credential"]["name"],
            "expected_tool_count": len(tools),
            "expected_inventory_sha256": _inventory_fingerprint(surface, tools),
        }
        if locked != expected:
            raise RenderError(f"Goose lock/policy parity failed for {surface!r}")
        normalized = expected["normalized_extension_name"]
        if not normalized or normalized in normalized_names:
            raise RenderError("Goose extension names must normalize uniquely")
        normalized_names.add(normalized)

    gate_ids = [gate.get("id") for gate in gates if isinstance(gate, dict)]
    if len(gate_ids) != len(gates) or len(gate_ids) != len(set(gate_ids)):
        raise RenderError("Goose compatibility lock gates must be unique objects")
    required_pass = all(
        gate.get("status") == "pass"
        for gate in gates
        if isinstance(gate, dict) and gate.get("required") is True
    )
    active_allowed = decision.get("active_credential_artifacts_allowed") is True
    active_artifacts = decision.get("active_artifacts")
    expected_artifacts = ["goose/recipe.json", "goose/settings.json"]
    if status == "supported":
        if not required_pass or not active_allowed or active_artifacts != expected_artifacts:
            raise RenderError("Goose supported state lacks complete activation evidence")
    elif active_allowed or active_artifacts != []:
        raise RenderError("Goose unsupported state must authorize no active artifacts")
    return lock


def _render_goose(policy: dict[str, Any]) -> dict[PurePosixPath, bytes]:
    lock = load_and_validate_goose_lock(policy)
    recipe_spec = TEMPLATES["goose_recipe"]
    settings_spec = TEMPLATES["goose_settings"]
    if lock["support_status"] == "unsupported":
        return {
            recipe_spec.artifact: _render_template(recipe_spec, {}),
            settings_spec.artifact: _render_template(settings_spec, {}),
        }

    extensions = []
    for server in _ordered_servers(policy):
        adapter = _adapter_for(server, "goose")
        tools = [tool["name"] for tool in _ordered_tools(server)]
        if not tools:
            raise RenderError(f"Goose allowlist is empty for {server['id']!r}")
        extensions.append(
            {
                "available_tools": tools,
                "headers": {
                    "Authorization": f"Bearer ${{{server['credential']['name']}}}"
                },
                "name": adapter["server_key"],
                "timeout": 30,
                "type": "streamable_http",
                "uri": server["transport"]["url"],
            }
        )
    recipe = {
        "description": "Pinned, isolated Zabin MCP recipe.",
        "extensions": extensions,
        "instructions": "Use canonical AGENTS.md and .agents/skills without duplication.",
        "title": "Zabin MCP workflow",
        "version": "1.0.0",
    }
    settings = {
        "active": True,
        "artifacts": ["goose/recipe.json", "goose/settings.json"],
        "client_version": lock["client"]["version"],
        "explicit_extensions_only": True,
        "mode": "approve",
        "support_status": "supported",
    }
    return {
        recipe_spec.artifact: (json.dumps(recipe, indent=2, sort_keys=True) + "\n").encode(),
        settings_spec.artifact: (
            json.dumps(settings, indent=2, sort_keys=True) + "\n"
        ).encode(),
    }


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
    "codex_admin_requirements": TargetSpec(
        name="codex_admin_requirements",
        artifacts=(PurePosixPath("requirements.toml"),),
        required_fields=frozenset({"url"}),
        supports_tool_filtering=True,
        supports_approval_policy=True,
        renderer=_render_codex_requirements,
    ),
    "goose": TargetSpec(
        name="goose",
        artifacts=(PurePosixPath("goose/recipe.json"), PurePosixPath("goose/settings.json")),
        required_fields=frozenset(
            {"type", "name", "uri", "headers.Authorization", "available_tools"}
        ),
        supports_tool_filtering=True,
        supports_approval_policy=True,
        renderer=_render_goose,
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
    policy_target = "codex" if target.name == "codex_admin_requirements" else target.name
    for server in policy["servers"]:
        adapter = _adapter_for(server, policy_target)
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
    validate_template_manifest()
    validate_server_identities(policy)
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
    """Transactionally replace a rendered artifact set after staging every file."""

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    ordered = sorted(artifacts.items(), key=lambda item: item[0].as_posix())
    staged: dict[Path, Path] = {}
    backups: dict[Path, Path | None] = {}
    replaced: list[Path] = []
    install_succeeded = False
    try:
        for relative_path, content in ordered:
            destination = _safe_destination(output_dir, relative_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent, delete=False
            ) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            staged[destination] = temporary

        for destination, temporary in list(staged.items()):
            backup: Path | None = None
            if destination.exists():
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix=f".{destination.name}.",
                    suffix=".backup",
                    dir=destination.parent,
                    delete=False,
                ) as handle:
                    backup = Path(handle.name)
                backup.unlink()
                os.replace(destination, backup)
            backups[destination] = backup
            os.replace(temporary, destination)
            replaced.append(destination)
            staged.pop(destination)
        install_succeeded = True
    except OSError as exc:
        rollback_errors = []
        for destination in reversed(list(backups)):
            backup = backups[destination]
            try:
                if backup is None:
                    if destination in replaced:
                        destination.unlink(missing_ok=True)
                else:
                    os.replace(backup, destination)
                    backups[destination] = None
            except OSError as rollback_exc:
                rollback_errors.append(f"{destination}: {rollback_exc.strerror}")
        detail = f"cannot install adapter artifacts: {exc.strerror}"
        if rollback_errors:
            detail += "; rollback failed for " + ", ".join(rollback_errors)
        raise RenderError(detail) from exc
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)
        for backup in backups.values():
            if install_succeeded and backup is not None:
                backup.unlink(missing_ok=True)


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
    parser.add_argument(
        "--admin-deployment",
        action="store_true",
        help="authorize the separate admin-only requirements.toml staging workflow",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="render to stdout without writing")
    mode.add_argument("--check", action="store_true", help="fail if output differs without writing")
    return parser


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        is_admin_target = args.target == "codex_admin_requirements"
        if is_admin_target != args.admin_deployment:
            if is_admin_target:
                raise RenderError(
                    "codex_admin_requirements requires explicit --admin-deployment authorization"
                )
            raise RenderError(
                "--admin-deployment is valid only with codex_admin_requirements"
            )
        policy = load_and_validate_policy(args.policy, args.schema)
        if not is_admin_target and args.target != "goose":
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
