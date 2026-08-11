#!/usr/bin/env python3
"""Safely synchronize portable skills, role instructions, and client adapters.

The installer deliberately has no implicit home-directory destinations.  It
never reads credential environment variables and ordinary runs never render or
touch Codex ``requirements.toml``.  Native client configuration is merged as a
data structure; installer ownership lives in a sidecar manifest so no private
metadata is injected into client configuration.  File identities and source
content are rechecked immediately before replacement to narrow check/use races.
Python cannot lock an entire pathname walk: a hostile local actor able to rename
ancestor directories concurrently can still race installation, so destinations
and the canonical checkout must remain locally trusted while this tool runs.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import stat
import sys
import tomllib
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, os.fspath(Path(__file__).resolve().parents[1]))

from scripts import render_adapters


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PurePosixPath(".zabin/installer-manifest.json")
MANIFEST_VERSION = "1.0.0"
INSTALLER_ID = "portable-agent-contracts/install-adapters"
MODES = ("dry-run", "check", "copy", "symlink")
TRUST_STATES = ("unknown", "pending", "approved", "denied")
ACTIVATION_STATES = ("unknown", "inactive", "active", "failed")
SAFE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SAFE_DIFF_FIELDS = {
    "approval_mode",
    "default_tools_approval_mode",
    "disabled_tools",
    "enabled",
    "enabled_tools",
    "required",
    "server_id",
    "tool_rule",
    "type",
    "url",
}
SAFE_STRUCTURE_FIELDS = {
    "Authorization",
    "SessionStart",
    "allow",
    "ask",
    "bearer_token_env_var",
    "command",
    "deny",
    "headers",
    "hooks",
    "mcpServers",
    "mcp_servers",
    "permissions",
    "tools",
}


class InstallError(ValueError):
    """Raised when installation cannot continue safely."""


class CollisionError(InstallError):
    """Raised when unmanaged or user-modified content overlaps owned content."""

    def __init__(self, kind: str, path: Path, diff: list[dict[str, Any]]) -> None:
        self.kind = kind
        self.path = path
        self.diff = diff
        detail = json.dumps(diff, sort_keys=True, separators=(",", ":"))
        super().__init__(f"{kind} collision at {path}: {detail}")


@dataclass(frozen=True)
class Destinations:
    """All install roots are explicit and independently validated."""

    project: Path
    skills: Path
    instructions: Path


@dataclass(frozen=True)
class InstallOptions:
    mode: str
    destinations: Destinations
    targets: tuple[str, ...] = ("claude_code", "codex")
    workspace_trust: str = "pending"
    server_approval: str = "pending"
    activation: str = "inactive"


@dataclass
class PlannedChange:
    destination: Path
    kind: str
    content: bytes | None = None
    link_target: str | None = None
    mode: int = 0o600
    source: str | None = None
    owned: dict[str, str] = field(default_factory=dict)
    observed: "FileState | None" = None
    recorded_checksum: str | None = None
    delete: bool = False
    remove_manifest_keys: tuple[str, ...] = ()

    @property
    def checksum(self) -> str:
        if self.delete and self.recorded_checksum is not None:
            return self.recorded_checksum
        if self.content is not None:
            return _digest_bytes(self.content)
        if self.link_target is not None:
            return _digest_bytes(self.link_target.encode("utf-8"))
        return _digest_bytes(b"")


@dataclass(frozen=True)
class InstallReport:
    installation: str
    workspace_trust: str
    server_approval: str
    activation: str
    changes: tuple[str, ...]
    checksums: Mapping[str, str]
    backups: Mapping[str, str]
    provenance: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "activation": self.activation,
            "backups": dict(sorted(self.backups.items())),
            "changes": list(self.changes),
            "checksums": dict(sorted(self.checksums.items())),
            "installation": self.installation,
            "provenance": self.provenance,
            "server_approval": self.server_approval,
            "workspace_trust": self.workspace_trust,
            "state_notice": (
                "File installation does not grant workspace trust, approve MCP servers, "
                "or activate servers; each state is reported independently."
            ),
            "race_notice": (
                "Installer rechecks file identity and content before replacement, but "
                "cannot exclude a hostile local actor concurrently renaming ancestor paths."
            ),
        }


@dataclass(frozen=True)
class FileState:
    kind: str
    checksum: str | None = None
    mode: int | None = None
    link_target: str | None = None


def _digest_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _read_stable_regular(path: Path) -> tuple[bytes, FileState]:
    """Read one regular file without following its final symlink component."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise InstallError(f"cannot safely open regular file {path}: {exc.strerror}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise InstallError(f"path is not a regular file: {path}")
        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        pathname = path.lstat()
    except OSError as exc:
        raise InstallError(f"file changed while it was read: {path}") from exc
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    identity_path = (pathname.st_dev, pathname.st_ino, pathname.st_size, pathname.st_mtime_ns)
    if identity_before != identity_after or identity_after != identity_path:
        raise InstallError(f"file changed while it was read: {path}")
    content = b"".join(chunks)
    return content, FileState(
        "file", _digest_bytes(content), stat.S_IMODE(after.st_mode), None
    )


def _capture_state(path: Path) -> FileState:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return FileState("missing")
    except OSError as exc:
        raise InstallError(f"cannot inspect destination {path}: {exc.strerror}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        target = os.readlink(path)
        return FileState(
            "symlink",
            _digest_bytes(target.encode("utf-8")),
            stat.S_IMODE(metadata.st_mode),
            target,
        )
    if stat.S_ISREG(metadata.st_mode):
        _, state = _read_stable_regular(path)
        return state
    if stat.S_ISDIR(metadata.st_mode):
        records, _, _ = _tree_records(path)
        return FileState(
            "directory",
            _canonical_digest(records),
            stat.S_IMODE(metadata.st_mode),
        )
    return FileState("other", mode=stat.S_IMODE(metadata.st_mode))


def _tree_records(
    root: Path,
) -> tuple[list[dict[str, Any]], set[Path], bool]:
    """Snapshot a directory tree without following symlinks."""

    records: list[dict[str, Any]] = []
    leaves: set[Path] = set()
    has_unowned_empty_directory = False

    def visit(directory: Path, relative: PurePosixPath) -> None:
        nonlocal has_unowned_empty_directory
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            raise InstallError(f"cannot inspect stale directory {directory}: {exc.strerror}") from exc
        if not children and relative.parts:
            has_unowned_empty_directory = True
        for child in children:
            try:
                metadata = child.lstat()
            except OSError as exc:
                raise InstallError(f"cannot inspect stale path {child}: {exc.strerror}") from exc
            child_relative = relative / child.name
            if stat.S_ISDIR(metadata.st_mode):
                records.append(
                    {
                        "kind": "directory",
                        "mode": stat.S_IMODE(metadata.st_mode),
                        "path": child_relative.as_posix(),
                    }
                )
                visit(child, child_relative)
            elif stat.S_ISREG(metadata.st_mode):
                content, state = _read_stable_regular(child)
                records.append(
                    {
                        "checksum": _digest_bytes(content),
                        "kind": "file",
                        "mode": state.mode,
                        "path": child_relative.as_posix(),
                    }
                )
                leaves.add(child)
            elif stat.S_ISLNK(metadata.st_mode):
                target = os.readlink(child)
                records.append(
                    {
                        "checksum": _digest_bytes(target.encode("utf-8")),
                        "kind": "symlink",
                        "path": child_relative.as_posix(),
                        "target": target,
                    }
                )
                leaves.add(child)
            else:
                raise InstallError(f"unsupported entry in stale directory: {child}")

    visit(root, PurePosixPath())
    return records, leaves, has_unowned_empty_directory


def _assert_observed(change: PlannedChange) -> None:
    if change.observed is None:
        raise InstallError(f"missing preflight identity for {change.destination}")
    if _capture_state(change.destination) != change.observed:
        raise InstallError(f"destination changed after preflight: {change.destination}")
    _assert_symlink_source(change)


def _assert_symlink_source(change: PlannedChange) -> None:
    if change.link_target is not None:
        content, _ = _read_stable_regular(Path(change.link_target))
        if _digest_bytes(content) != change.checksum:
            raise InstallError(f"symlink source changed after preflight: {change.source}")


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return _digest_bytes(encoded)


def _safe_path(path: Path, label: str, *, require_absolute: bool = True) -> Path:
    if require_absolute and not path.is_absolute():
        raise InstallError(f"{label} must be an absolute path: {path}")
    if ".." in path.parts:
        raise InstallError(f"{label} contains path traversal: {path}")
    normalized = Path(os.path.abspath(os.fspath(path)))
    current = Path(normalized.anchor)
    for part in normalized.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            break
        except OSError as exc:
            raise InstallError(f"cannot inspect {label} {current}: {exc.strerror}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise InstallError(f"unsafe symlink in {label}: {current}")
    return normalized


def _ensure_directory(path: Path, mode: int = 0o700) -> None:
    path = _safe_path(path, "destination directory")
    missing: list[Path] = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    if not cursor.is_dir():
        raise InstallError(f"destination parent is not a directory: {cursor}")
    for directory in reversed(missing):
        directory.mkdir(mode=mode)
    _safe_path(path, "destination directory")


def _assert_regular_source(path: Path) -> None:
    root = ROOT.resolve()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise InstallError(f"source is outside repository: {path}") from exc
    cursor = root
    for part in relative.parts:
        cursor /= part
        metadata = cursor.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise InstallError(f"source symlinks are forbidden: {cursor}")
    if not path.is_file():
        raise InstallError(f"source is not a regular file: {path}")


def _source_inventory(root: Path) -> list[Path]:
    if not root.is_dir():
        raise InstallError(f"missing canonical source directory: {root}")
    files = sorted(path for path in root.rglob("*") if path.is_file() or path.is_symlink())
    for path in files:
        _assert_regular_source(path)
    return files


def _manifest_key(destination: Path) -> str:
    return _digest_bytes(os.fspath(destination).encode("utf-8"))


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        raw, _ = _read_stable_regular(path)
    except InstallError as exc:
        raise InstallError(f"cannot read {label} {path} safely") from exc
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallError(f"invalid JSON in {label} {path}") from exc
    if not isinstance(value, dict):
        raise InstallError(f"{label} root must be an object: {path}")
    return value


def _load_manifest(project: Path) -> dict[str, Any]:
    path = project.joinpath(*MANIFEST_PATH.parts)
    if not path.exists():
        return {
            "installer": INSTALLER_ID,
            "schema_version": MANIFEST_VERSION,
            "entries": {},
        }
    _safe_path(path, "ownership manifest")
    value = _read_json_object(path, "ownership manifest")
    if (
        value.get("installer") != INSTALLER_ID
        or value.get("schema_version") != MANIFEST_VERSION
        or not isinstance(value.get("entries"), dict)
    ):
        raise InstallError(f"unsupported or foreign ownership manifest: {path}")
    if set(value) != {"entries", "installer", "provenance", "schema_version"}:
        raise InstallError(f"ownership manifest has unexpected fields: {path}")
    if not isinstance(value.get("provenance"), str) or not DIGEST.fullmatch(value["provenance"]):
        raise InstallError(f"ownership manifest has invalid provenance: {path}")
    for key, entry in value["entries"].items():
        if not isinstance(key, str) or not DIGEST.fullmatch(key) or not isinstance(entry, dict):
            raise InstallError(f"ownership manifest has an invalid entry: {path}")
        if set(entry) != {"checksum", "destination", "kind", "owned", "source", "strategy"}:
            raise InstallError(f"ownership manifest entry has unexpected fields: {path}")
        destination = entry.get("destination")
        owned = entry.get("owned")
        source = entry.get("source")
        source_path = PurePosixPath(source) if isinstance(source, str) else None
        if (
            not isinstance(destination, str)
            or not Path(destination).is_absolute()
            or _manifest_key(Path(destination)) != key
            or not isinstance(entry.get("checksum"), str)
            or not DIGEST.fullmatch(entry["checksum"])
            or entry.get("kind") not in {"adapter", "instruction", "manifest", "skill"}
            or entry.get("strategy") not in {"copy", "symlink"}
            or source_path is None
            or source_path.is_absolute()
            or ".." in source_path.parts
            or (
                entry.get("kind") == "skill"
                and (not source_path.parts or source_path.parts[0] != "skills")
            )
            or (
                entry.get("kind") == "instruction"
                and (not source_path.parts or source_path.parts[0] != "agents")
            )
            or (
                entry.get("kind") == "adapter"
                and not source.startswith("render:")
            )
            or not isinstance(owned, dict)
            or any(
                not isinstance(component, str)
                or not isinstance(fingerprint, str)
                or not DIGEST.fullmatch(fingerprint)
                for component, fingerprint in owned.items()
            )
        ):
            raise InstallError(f"ownership manifest entry is invalid: {path}")
    return value


def _entry_for(manifest: Mapping[str, Any], destination: Path) -> dict[str, Any] | None:
    entry = manifest.get("entries", {}).get(_manifest_key(destination))
    if not isinstance(entry, dict) or entry.get("destination") != os.fspath(destination):
        return None
    return entry


def _safe_component(component: str) -> str:
    if component in SAFE_DIFF_FIELDS or component in SAFE_STRUCTURE_FIELDS:
        return component
    if SAFE_KEY.fullmatch(component) and component in {"zabin", "zabin-worker"}:
        return component
    return "<redacted-field>"


def _safe_value(path: tuple[str, ...], value: Any) -> Any:
    if path and path[-1] in SAFE_DIFF_FIELDS:
        if isinstance(value, (str, bool, int, float)) or value is None:
            return value
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return value
    return "<redacted>"


def structural_diff(
    current: Any, expected: Any, path: tuple[str, ...] = ()
) -> list[dict[str, Any]]:
    """Return a bounded, structurally redacted diff using field allowlists."""

    changes: list[dict[str, Any]] = []
    if isinstance(current, dict) and isinstance(expected, dict):
        keys = sorted(set(current) | set(expected))
        for key in keys:
            safe = _safe_component(str(key))
            child_path = path + (safe,)
            if key not in current:
                changes.append(
                    {"path": ".".join(child_path), "current": "<missing>", "expected": _safe_value(child_path, expected[key])}
                )
            elif key not in expected:
                changes.append(
                    {"path": ".".join(child_path), "current": _safe_value(child_path, current[key]), "expected": "<absent>"}
                )
            else:
                changes.extend(structural_diff(current[key], expected[key], child_path))
            if len(changes) >= 50:
                break
        return changes[:50]
    if isinstance(current, list) and isinstance(expected, list):
        if current != expected:
            changes.append(
                {"path": ".".join(path), "current": _safe_value(path, current), "expected": _safe_value(path, expected)}
            )
        return changes
    if current != expected:
        changes.append(
            {"path": ".".join(path), "current": _safe_value(path, current), "expected": _safe_value(path, expected)}
        )
    return changes


def _owned_matches(
    entry: Mapping[str, Any] | None, component: str, current: Any
) -> bool:
    if entry is None:
        return False
    owned = entry.get("owned")
    return isinstance(owned, dict) and owned.get(component) == _canonical_digest(current)


def _server_url(server: Mapping[str, Any]) -> Any:
    return server.get("url")


def _merge_servers(
    existing: dict[str, Any],
    desired: Mapping[str, Any],
    entry: Mapping[str, Any] | None,
    destination: Path,
    container_name: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    merged = dict(existing)
    owned: dict[str, str] = {}
    previous_owned = entry.get("owned", {}) if entry else {}
    if isinstance(previous_owned, dict):
        for component, fingerprint in previous_owned.items():
            if not component.startswith("server:"):
                continue
            old_key = component.removeprefix("server:")
            if old_key in desired:
                continue
            if old_key not in existing or _canonical_digest(existing[old_key]) != fingerprint:
                raise CollisionError(
                    "server ID",
                    destination,
                    [{"path": f"{container_name}.{_safe_component(old_key)}", "current": "<missing-or-modified>", "expected": "<owned-removal>"}],
                )
            merged.pop(old_key, None)
    desired_urls = {key: _server_url(value) for key, value in desired.items()}
    for existing_key, existing_server in merged.items():
        if existing_key in desired:
            continue
        if not isinstance(existing_server, dict):
            continue
        for desired_key, url in desired_urls.items():
            if url is not None and _server_url(existing_server) == url:
                raise CollisionError(
                    "server URL",
                    destination,
                    [{"path": f"{container_name}.{_safe_component(existing_key)}.url", "current": url, "expected": f"owned by {desired_key}"}],
                )
    for key, desired_server in desired.items():
        component = f"server:{key}"
        if key not in existing and isinstance(previous_owned, dict) and component in previous_owned:
            raise CollisionError(
                "server ID",
                destination,
                [{"path": f"{container_name}.{_safe_component(key)}", "current": "<missing-or-modified>", "expected": "<redacted>"}],
            )
        if key in existing and not _owned_matches(entry, component, existing[key]):
            diff = structural_diff(
                existing[key], desired_server, (container_name, _safe_component(key))
            )
            if not diff:
                diff = [{"path": f"{container_name}.{_safe_component(key)}", "current": "<unmanaged>", "expected": "<installer-owned>"}]
            raise CollisionError(
                "server ID",
                destination,
                diff,
            )
        merged[key] = desired_server
        owned[component] = _canonical_digest(desired_server)
    return merged, owned


def _merge_hook(
    existing: list[Any],
    desired: Any,
    entry: Mapping[str, Any] | None,
    destination: Path,
    component: str,
) -> tuple[list[Any], str]:
    previous_fingerprint = None
    if entry and isinstance(entry.get("owned"), dict):
        previous_fingerprint = entry["owned"].get(component)
    result = []
    found_owned = False
    for item in existing:
        fingerprint = _canonical_digest(item)
        if fingerprint == previous_fingerprint:
            if found_owned:
                raise CollisionError("owned field", destination, [{"path": "hooks.SessionStart", "current": "<redacted>", "expected": "single installer hook"}])
            result.append(desired)
            found_owned = True
        elif item == desired:
            raise CollisionError("owned field", destination, structural_diff(item, desired, ("hooks", "SessionStart")))
        else:
            result.append(item)
    if previous_fingerprint is not None and not found_owned:
        raise CollisionError("owned field", destination, [{"path": "hooks.SessionStart", "current": "<missing-or-modified>", "expected": "<redacted>"}])
    if not found_owned:
        result.append(desired)
    return result, _canonical_digest(desired)


def _merge_claude_mcp(
    existing: dict[str, Any], desired: dict[str, Any], entry: Mapping[str, Any] | None, destination: Path
) -> tuple[dict[str, Any], dict[str, str]]:
    current_servers = existing.get("mcpServers", {})
    if not isinstance(current_servers, dict):
        raise CollisionError("owned field", destination, structural_diff(current_servers, desired["mcpServers"], ("mcpServers",)))
    merged_servers, owned = _merge_servers(
        current_servers, desired["mcpServers"], entry, destination, "mcpServers"
    )
    result = dict(existing)
    result["mcpServers"] = merged_servers
    return result, owned


def _merge_claude_settings(
    existing: dict[str, Any], desired: dict[str, Any], entry: Mapping[str, Any] | None, destination: Path
) -> tuple[dict[str, Any], dict[str, str]]:
    result = dict(existing)
    current_permissions = existing.get("permissions", {})
    if not isinstance(current_permissions, dict):
        raise CollisionError("owned field", destination, structural_diff(current_permissions, desired["permissions"], ("permissions",)))
    permissions: dict[str, list[Any]] = {}
    desired_rules = {
        rule: bucket
        for bucket in ("allow", "ask", "deny")
        for rule in desired["permissions"][bucket]
    }
    previous_owned = entry.get("owned", {}) if entry else {}
    for bucket in ("allow", "ask", "deny"):
        values = current_permissions.get(bucket, [])
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise CollisionError("tool rule", destination, [{"path": f"permissions.{bucket}", "current": "<redacted>", "expected": "list"}])
        permissions[bucket] = list(values)
    if isinstance(previous_owned, dict):
        for component, fingerprint in previous_owned.items():
            if not component.startswith("tool:") or component in {
                f"tool:{rule}" for rule in desired_rules
            }:
                continue
            old_rule = component.removeprefix("tool:")
            locations = [bucket for bucket, values in permissions.items() if old_rule in values]
            occurrence_count = sum(values.count(old_rule) for values in permissions.values())
            if (
                occurrence_count != 1
                or not locations
                or _canonical_digest({"bucket": locations[0], "rule": old_rule}) != fingerprint
            ):
                raise CollisionError(
                    "tool rule",
                    destination,
                    [{"path": "permissions.tool_rule", "current": "<missing-or-modified>", "expected": "<owned-removal>"}],
                )
            permissions[locations[0]].remove(old_rule)
    for rule, desired_bucket in desired_rules.items():
        component = f"tool:{rule}"
        locations = [bucket for bucket, values in permissions.items() if rule in values]
        occurrence_count = sum(values.count(rule) for values in permissions.values())
        owned_location = previous_owned.get(component) if isinstance(previous_owned, dict) else None
        if locations and (
            occurrence_count != 1
            or owned_location != _canonical_digest({"bucket": locations[0], "rule": rule})
        ):
            raise CollisionError("tool rule", destination, [{"path": f"permissions.{locations[0]}.tool_rule", "current": rule, "expected": desired_bucket}])
        if owned_location is not None and not locations:
            raise CollisionError("tool rule", destination, [{"path": "permissions.tool_rule", "current": "<missing-or-modified>", "expected": desired_bucket}])
        for bucket in permissions:
            permissions[bucket] = [value for value in permissions[bucket] if value != rule]
        permissions[desired_bucket].append(rule)
    for bucket in permissions:
        permissions[bucket] = sorted(set(permissions[bucket]))
    result["permissions"] = {**current_permissions, **permissions}

    current_hooks = existing.get("hooks", {})
    if not isinstance(current_hooks, dict):
        raise CollisionError("owned field", destination, [{"path": "hooks", "current": "<redacted>", "expected": "object"}])
    session = current_hooks.get("SessionStart", [])
    if not isinstance(session, list):
        raise CollisionError("owned field", destination, [{"path": "hooks.SessionStart", "current": "<redacted>", "expected": "list"}])
    desired_hook = desired["hooks"]["SessionStart"][0]
    merged_hooks, hook_fingerprint = _merge_hook(
        session, desired_hook, entry, destination, "hook:SessionStart"
    )
    result["hooks"] = {**current_hooks, "SessionStart": merged_hooks}
    owned = {f"tool:{rule}": _canonical_digest({"bucket": bucket, "rule": rule}) for rule, bucket in desired_rules.items()}
    owned["hook:SessionStart"] = hook_fingerprint
    return result, owned


def _toml_value(value: Any) -> str:
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return repr(value)
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        return value.isoformat()
    if isinstance(value, dict):
        return "{ " + ", ".join(
            f"{_toml_key(str(key))} = {_toml_value(item)}"
            for key, item in value.items()
        ) + " }"
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise InstallError(f"cannot preserve unsupported TOML value of type {type(value).__name__}")


def _toml_key(value: str) -> str:
    return value if re.fullmatch(r"[A-Za-z0-9_-]+", value) else _toml_string(value)


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def _dump_toml_table(value: Mapping[str, Any], path: tuple[str, ...] = ()) -> list[str]:
    lines: list[str] = []
    scalars = [(key, item) for key, item in value.items() if not isinstance(item, dict) and not (isinstance(item, list) and item and all(isinstance(child, dict) for child in item))]
    mappings = [(key, item) for key, item in value.items() if isinstance(item, dict)]
    arrays = [(key, item) for key, item in value.items() if isinstance(item, list) and item and all(isinstance(child, dict) for child in item)]
    for key, item in scalars:
        lines.append(f"{_toml_key(str(key))} = {_toml_value(item)}")
    for key, mapping in mappings:
        child_path = path + (str(key),)
        if lines:
            lines.append("")
        lines.append("[" + ".".join(_toml_key(part) for part in child_path) + "]")
        lines.extend(_dump_toml_table(mapping, child_path))
    for key, items in arrays:
        child_path = path + (str(key),)
        for item in items:
            if lines:
                lines.append("")
            lines.append("[[" + ".".join(_toml_key(part) for part in child_path) + "]]" )
            lines.extend(_dump_toml_table(item, child_path))
    return lines


def _dump_toml(value: Mapping[str, Any]) -> bytes:
    return ("\n".join(_dump_toml_table(value)).rstrip() + "\n").encode("utf-8")


def _merge_codex(
    existing: dict[str, Any], desired: dict[str, Any], entry: Mapping[str, Any] | None, destination: Path
) -> tuple[dict[str, Any], dict[str, str]]:
    result = dict(existing)
    current_servers = existing.get("mcp_servers", {})
    if not isinstance(current_servers, dict):
        raise CollisionError("owned field", destination, [{"path": "mcp_servers", "current": "<redacted>", "expected": "object"}])
    merged_servers, owned = _merge_servers(
        current_servers, desired["mcp_servers"], entry, destination, "mcp_servers"
    )
    result["mcp_servers"] = merged_servers
    current_hooks = existing.get("hooks", {})
    if not isinstance(current_hooks, dict):
        raise CollisionError("owned field", destination, [{"path": "hooks", "current": "<redacted>", "expected": "object"}])
    sessions = current_hooks.get("SessionStart", [])
    if not isinstance(sessions, list):
        raise CollisionError("owned field", destination, [{"path": "hooks.SessionStart", "current": "<redacted>", "expected": "list"}])
    desired_hook = desired["hooks"]["SessionStart"][0]
    merged_hooks, hook_fingerprint = _merge_hook(
        sessions, desired_hook, entry, destination, "hook:SessionStart"
    )
    result["hooks"] = {**current_hooks, "SessionStart": merged_hooks}
    owned["hook:SessionStart"] = hook_fingerprint
    return result, owned


def _parse_config(path: PurePosixPath, content: bytes) -> dict[str, Any]:
    try:
        if path.suffix == ".json":
            value = json.loads(content)
        else:
            value = tomllib.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        raise InstallError(f"generated adapter is invalid: {path}") from exc
    if not isinstance(value, dict):
        raise InstallError(f"generated adapter root must be an object: {path}")
    return value


def _read_existing_config(path: Path, syntax: str) -> tuple[dict[str, Any], FileState]:
    if not path.exists():
        return {}, FileState("missing")
    _safe_path(path, "native configuration")
    try:
        raw, state = _read_stable_regular(path)
        value = json.loads(raw) if syntax == "json" else tomllib.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        raise InstallError(f"cannot structurally parse native configuration: {path}") from exc
    if not isinstance(value, dict):
        raise InstallError(f"native configuration root must be an object: {path}")
    return value, state


def _plan_configs(
    options: InstallOptions, manifest: Mapping[str, Any]
) -> list[PlannedChange]:
    policy = render_adapters.load_and_validate_policy(
        render_adapters.DEFAULT_POLICY, render_adapters.DEFAULT_SCHEMA
    )
    changes: list[PlannedChange] = []
    for target in options.targets:
        if target not in {"claude_code", "codex"}:
            raise InstallError(f"ordinary installation target is forbidden: {target}")
        for relative, rendered in render_adapters.render_target(policy, target).items():
            if relative.name == "requirements.toml":
                raise InstallError("ordinary installation must not include requirements.toml")
            destination = options.destinations.project.joinpath(*relative.parts)
            _safe_path(destination, "adapter destination")
            entry = _entry_for(manifest, destination)
            desired = _parse_config(relative, rendered)
            syntax = "json" if relative.suffix == ".json" else "toml"
            existing, observed = _read_existing_config(destination, syntax)
            if relative == PurePosixPath(".mcp.json"):
                merged, owned = _merge_claude_mcp(existing, desired, entry, destination)
            elif relative == PurePosixPath(".claude/settings.json"):
                merged, owned = _merge_claude_settings(existing, desired, entry, destination)
            elif relative == PurePosixPath(".codex/config.toml"):
                merged, owned = _merge_codex(existing, desired, entry, destination)
            else:
                raise InstallError(f"unexpected ordinary adapter artifact: {relative}")
            content = (
                (json.dumps(merged, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")
                if syntax == "json"
                else _dump_toml(merged)
            )
            changes.append(
                PlannedChange(destination, "adapter", content=content, mode=0o600, source=f"render:{target}", owned=owned, observed=observed)
            )
    return changes


def _plan_assets(
    options: InstallOptions, manifest: Mapping[str, Any]
) -> list[PlannedChange]:
    changes: list[PlannedChange] = []
    current_destinations: set[Path] = set()
    inventories = (
        (ROOT / "skills", options.destinations.skills, "skill"),
        (ROOT / "agents", options.destinations.instructions, "instruction"),
    )
    for source_root, destination_root, kind in inventories:
        if destination_root == source_root or source_root in destination_root.parents:
            raise InstallError(
                f"{kind} destination overlaps its canonical source: {destination_root}"
            )
        for source in _source_inventory(source_root):
            relative = source.relative_to(source_root)
            destination = destination_root / relative
            current_destinations.add(destination)
            _safe_path(destination.parent, f"{kind} destination parent")
            entry = _entry_for(manifest, destination)
            source_content, _ = _read_stable_regular(source)
            use_symlink = options.mode == "symlink" or (
                options.mode in {"check", "dry-run"}
                and entry is not None
                and entry.get("strategy") == "symlink"
            )
            if use_symlink:
                link_target = os.fspath(source)
                change = PlannedChange(destination, kind, content=source_content, link_target=link_target, mode=0o644, source=os.fspath(source.relative_to(ROOT)))
                change.owned["symlink-target"] = _digest_bytes(
                    link_target.encode("utf-8")
                )
            else:
                change = PlannedChange(destination, kind, content=source_content, mode=0o644, source=os.fspath(source.relative_to(ROOT)))
            if entry is not None:
                change.recorded_checksum = entry["checksum"]
            change.observed = _capture_state(destination)
            if destination.exists() or destination.is_symlink():
                if entry is None:
                    raise CollisionError(kind, destination, [{"path": "<redacted-field>", "current": "<unmanaged>", "expected": change.checksum}])
                if change.observed.kind == "symlink":
                    expected_source = ROOT.joinpath(*PurePosixPath(entry["source"]).parts)
                    _assert_regular_source(expected_source)
                    expected_target = os.fspath(expected_source)
                    if entry.get("strategy") != "symlink" or change.observed.link_target != expected_target:
                        raise CollisionError(kind, destination, [{"path": "<redacted-field>", "current": "<retargeted>", "expected": "<installer-owned>"}])
                    actual = _checksum_path(destination, expected_target)
                    if actual != change.checksum:
                        raise InstallError(
                            f"installed symlink target differs from canonical source: {destination}"
                        )
                else:
                    actual = _checksum_path(destination)
                if entry.get("checksum") != actual and change.observed.kind != "symlink":
                    raise CollisionError(kind, destination, [{"path": "<redacted-field>", "current": "<modified>", "expected": entry.get("checksum", "<redacted>")}])
            changes.append(change)
    stale = _plan_stale_assets(manifest, current_destinations)
    return changes + _collapse_stale_trees(stale, current_destinations)


def _stale_asset_change(key: str, entry: Mapping[str, Any]) -> PlannedChange:
    destination = Path(entry["destination"])
    _safe_path(destination.parent, "stale asset destination parent")
    observed = _capture_state(destination)
    strategy = entry["strategy"]
    if observed.kind == "file":
        if strategy != "copy" or observed.checksum != entry["checksum"]:
            raise CollisionError(
                entry["kind"],
                destination,
                [{"path": "<redacted-field>", "current": "<modified>", "expected": entry["checksum"]}],
            )
    elif observed.kind == "symlink":
        source = ROOT.joinpath(*PurePosixPath(entry["source"]).parts)
        expected_target = os.fspath(source)
        target_fingerprint = entry.get("owned", {}).get("symlink-target")
        actual_fingerprint = (
            _digest_bytes(observed.link_target.encode("utf-8"))
            if observed.link_target is not None
            else None
        )
        if (
            strategy != "symlink"
            or observed.link_target != expected_target
            or target_fingerprint != actual_fingerprint
        ):
            raise CollisionError(
                entry["kind"],
                destination,
                [{"path": "<redacted-field>", "current": "<retargeted>", "expected": "<installer-owned>"}],
            )
        if source.exists() or source.is_symlink():
            _assert_regular_source(source)
            content, _ = _read_stable_regular(source)
            if _digest_bytes(content) != entry["checksum"]:
                raise CollisionError(
                    entry["kind"],
                    destination,
                    [{"path": "<redacted-field>", "current": "<modified>", "expected": entry["checksum"]}],
                )
    elif observed.kind not in {"missing"}:
        raise CollisionError(
            entry["kind"],
            destination,
            [{"path": "<redacted-field>", "current": "<unexpected-kind>", "expected": "<installer-owned>"}],
        )
    return PlannedChange(
        destination,
        entry["kind"],
        source=entry["source"],
        observed=observed,
        recorded_checksum=entry["checksum"],
        delete=True,
        remove_manifest_keys=(key,),
    )


def _plan_stale_assets(
    manifest: Mapping[str, Any], current_destinations: set[Path]
) -> list[PlannedChange]:
    stale: list[PlannedChange] = []
    for key, raw_entry in sorted(manifest.get("entries", {}).items()):
        if not isinstance(raw_entry, dict) or raw_entry.get("kind") not in {
            "skill",
            "instruction",
        }:
            continue
        destination = Path(raw_entry["destination"])
        if destination not in current_destinations:
            stale.append(_stale_asset_change(key, raw_entry))
    return stale


def _stale_tree_root(change: PlannedChange) -> Path | None:
    if change.source is None:
        return None
    source = PurePosixPath(change.source)
    if len(source.parts) < 3 or source.parts[0] not in {"skills", "agents"}:
        return None
    relative = source.parts[1:]
    root = change.destination
    for _ in relative:
        root = root.parent
    if change.destination != root.joinpath(*relative):
        return None
    return root / relative[0]


def _collapse_stale_trees(
    changes: list[PlannedChange], current_destinations: set[Path]
) -> list[PlannedChange]:
    """Use one recoverable tombstone when an entire owned subtree is stale."""

    groups: dict[Path, list[PlannedChange]] = {}
    for change in changes:
        root = _stale_tree_root(change)
        if root is not None:
            groups.setdefault(root, []).append(change)
    collapsed: list[PlannedChange] = []
    consumed: set[int] = set()
    for root, group in sorted(groups.items(), key=lambda item: os.fspath(item[0])):
        if any(root in destination.parents for destination in current_destinations):
            continue
        state = _capture_state(root)
        if state.kind != "directory":
            continue
        _, leaves, has_empty_directory = _tree_records(root)
        owned_leaves = {
            change.destination
            for change in group
            if change.observed is not None and change.observed.kind != "missing"
        }
        if has_empty_directory or leaves != owned_leaves:
            continue
        keys = tuple(
            key for change in group for key in change.remove_manifest_keys
        )
        collapsed.append(
            PlannedChange(
                root,
                group[0].kind,
                source=PurePosixPath(group[0].source or "").parts[0]
                + "/"
                + root.name,
                observed=state,
                recorded_checksum=state.checksum,
                delete=True,
                remove_manifest_keys=keys,
            )
        )
        consumed.update(id(change) for change in group)
    return [change for change in changes if id(change) not in consumed] + collapsed


def _checksum_path(path: Path, expected_link_target: str | None = None) -> str:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        target = os.readlink(path)
        if expected_link_target is None or target != expected_link_target:
            raise InstallError(f"refusing to follow untrusted symlink: {path}")
        content, _ = _read_stable_regular(Path(target))
        return _digest_bytes(content)
    if not stat.S_ISREG(metadata.st_mode):
        raise InstallError(f"destination is neither a regular file nor symlink: {path}")
    content, _ = _read_stable_regular(path)
    return _digest_bytes(content)


def _provenance(changes: Iterable[PlannedChange]) -> str:
    material = [
        {"checksum": change.checksum, "kind": change.kind, "source": change.source}
        for change in sorted(changes, key=lambda item: os.fspath(item.destination))
        if not change.delete
    ]
    return _canonical_digest(material)


def _manifest_content(
    old: Mapping[str, Any], changes: Sequence[PlannedChange], provenance: str
) -> bytes:
    entries = dict(old.get("entries", {}))
    for change in changes:
        if change.delete:
            for key in change.remove_manifest_keys:
                entries.pop(key, None)
            continue
        entries[_manifest_key(change.destination)] = {
            "checksum": change.checksum,
            "destination": os.fspath(change.destination),
            "kind": change.kind,
            "owned": dict(sorted(change.owned.items())),
            "source": change.source,
            "strategy": "symlink" if change.link_target is not None else "copy",
        }
    manifest = {
        "entries": entries,
        "installer": INSTALLER_ID,
        "provenance": provenance,
        "schema_version": MANIFEST_VERSION,
    }
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")


def plan_install(options: InstallOptions) -> tuple[list[PlannedChange], str]:
    if options.mode not in MODES:
        raise InstallError(f"unknown install mode: {options.mode}")
    if options.workspace_trust not in TRUST_STATES or options.server_approval not in TRUST_STATES:
        raise InstallError("invalid trust or server approval state")
    if options.activation not in ACTIVATION_STATES:
        raise InstallError("invalid activation state")
    destinations = options.destinations
    for label, path in (("project destination", destinations.project), ("skills destination", destinations.skills), ("instructions destination", destinations.instructions)):
        _safe_path(path, label)
    manifest_path = destinations.project.joinpath(*MANIFEST_PATH.parts)
    manifest_before = _capture_state(manifest_path)
    manifest = _load_manifest(destinations.project)
    manifest_observed = _capture_state(manifest_path)
    if manifest_before != manifest_observed:
        raise InstallError("ownership manifest changed during preflight")
    changes = _plan_assets(options, manifest) + _plan_configs(options, manifest)
    destinations_seen: set[Path] = set()
    for change in changes:
        if change.destination in destinations_seen:
            raise InstallError(f"multiple install artifacts target {change.destination}")
        destinations_seen.add(change.destination)
    provenance = _provenance(changes)
    manifest_change = PlannedChange(
        manifest_path,
        "manifest",
        content=_manifest_content(manifest, changes, provenance),
        mode=0o600,
        source="internal:ownership-manifest",
        observed=manifest_observed,
    )
    changes.append(manifest_change)
    return changes, provenance


def _matches(change: PlannedChange) -> bool:
    path = change.destination
    if change.delete:
        return not path.exists() and not path.is_symlink()
    if not path.exists() and not path.is_symlink():
        return False
    try:
        metadata = path.lstat()
        if change.link_target is not None:
            return (
                stat.S_ISLNK(metadata.st_mode)
                and os.readlink(path) == change.link_target
                and _checksum_path(path, change.link_target) == change.checksum
            )
        content, _ = _read_stable_regular(path)
        return stat.S_ISREG(metadata.st_mode) and content == change.content and stat.S_IMODE(metadata.st_mode) == change.mode
    except (OSError, InstallError):
        return False


def _has_drift(change: PlannedChange) -> bool:
    return (change.delete and bool(change.remove_manifest_keys)) or not _matches(change) or (
        change.link_target is not None
        and change.recorded_checksum is not None
        and change.recorded_checksum != change.checksum
    )


def _atomic_apply(
    changes: Sequence[PlannedChange],
) -> tuple[tuple[str, ...], dict[str, str]]:
    pending = [
        change
        for change in changes
        if not _matches(change) or (change.delete and change.remove_manifest_keys)
    ]
    if not pending:
        return (), {}
    transaction_id = uuid.uuid4().hex
    staged: dict[Path, Path] = {}
    backups: dict[Path, Path | None] = {}
    backup_checksums: dict[str, str] = {}
    installed: list[PlannedChange] = []
    try:
        for change in pending:
            _assert_observed(change)
        for change in pending:
            _ensure_directory(change.destination.parent)
            _safe_path(change.destination.parent, "transaction destination parent")
            if change.delete:
                continue
            temporary = change.destination.parent / f".{change.destination.name}.{transaction_id}.tmp"
            if temporary.exists() or temporary.is_symlink():
                raise InstallError(f"transaction staging collision: {temporary}")
            if change.link_target is not None:
                _assert_observed(change)
                os.symlink(change.link_target, temporary)
            else:
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, change.mode)
                try:
                    assert change.content is not None
                    with os.fdopen(descriptor, "wb", closefd=False) as handle:
                        handle.write(change.content)
                        handle.flush()
                        os.fsync(handle.fileno())
                finally:
                    os.close(descriptor)
                os.chmod(temporary, change.mode, follow_symlinks=False)
            staged[change.destination] = temporary

        for change in pending:
            destination = change.destination
            backup: Path | None = None
            _assert_observed(change)
            for tracked in changes:
                _assert_symlink_source(tracked)
            if destination.exists() or destination.is_symlink():
                backup = destination.parent / f".{destination.name}.zabin-backup-{transaction_id}"
                if backup.exists() or backup.is_symlink():
                    raise InstallError(f"transaction backup collision: {backup}")
                os.replace(destination, backup)
            backups[destination] = backup
            if backup is not None or not change.delete:
                installed.append(change)
            if backup is not None:
                backup_state = _capture_state(backup)
                if backup_state != change.observed:
                    raise InstallError(f"backup identity mismatch for {destination}")
                if backup_state.kind == "symlink" and not change.delete:
                    assert backup_state.link_target is not None
                    backup_checksums[os.fspath(backup)] = _checksum_path(
                        backup, backup_state.link_target
                    )
                elif backup_state.checksum is not None:
                    backup_checksums[os.fspath(backup)] = backup_state.checksum
            if change.delete:
                continue
            if change.link_target is not None:
                content, _ = _read_stable_regular(Path(change.link_target))
                if _digest_bytes(content) != change.checksum:
                    raise InstallError(f"symlink source changed before replacement: {change.source}")
            temporary = staged[destination]
            os.replace(temporary, destination)
            staged.pop(destination)
            if change.link_target is None:
                os.chmod(destination, change.mode, follow_symlinks=False)
        for change in pending:
            if not _matches(change):
                raise InstallError(
                    f"post-install verification failed for {change.destination}"
                )
        for change in pending:
            try:
                directory_fd = os.open(change.destination.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
    except (OSError, InstallError) as exc:
        rollback_errors = []
        for change in reversed(installed):
            destination = change.destination
            backup = backups.get(destination)
            try:
                if destination.exists() or destination.is_symlink():
                    if change.delete or not _matches(change):
                        raise InstallError(
                            f"rollback destination changed concurrently: {destination}"
                        )
                    destination.unlink()
                if backup is not None:
                    os.replace(backup, destination)
            except (OSError, InstallError) as rollback_exc:
                rollback_errors.append(
                    f"{destination}: {getattr(rollback_exc, 'strerror', None) or rollback_exc}"
                )
        detail = f"installation transaction failed: {getattr(exc, 'strerror', None) or exc}"
        if rollback_errors:
            detail += "; rollback failed for " + ", ".join(rollback_errors)
        raise InstallError(detail) from exc
    finally:
        for temporary in staged.values():
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return tuple(os.fspath(change.destination) for change in pending), backup_checksums


def install(options: InstallOptions) -> InstallReport:
    changes, provenance = plan_install(options)
    differing = tuple(os.fspath(change.destination) for change in changes if _has_drift(change))
    if options.mode == "dry-run":
        status = "planned"
        backups: dict[str, str] = {}
    elif options.mode == "check":
        status = "verified" if not differing else "drift"
        backups = {}
    else:
        applied, backups = _atomic_apply(changes)
        differing = tuple(dict.fromkeys((*differing, *applied)))
        status = "installed" if differing else "unchanged"
    checksums = {os.fspath(change.destination): change.checksum for change in changes}
    return InstallReport(
        installation=status,
        workspace_trust=options.workspace_trust,
        server_approval=options.server_approval,
        activation=options.activation,
        changes=differing,
        checksums=checksums,
        backups=backups,
        provenance=provenance,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=MODES)
    parser.add_argument("--project-destination", required=True, type=Path)
    parser.add_argument("--skills-destination", required=True, type=Path)
    parser.add_argument("--instructions-destination", required=True, type=Path)
    parser.add_argument("--target", action="append", choices=("claude_code", "codex"))
    parser.add_argument("--workspace-trust", choices=TRUST_STATES, default="pending")
    parser.add_argument("--server-approval", choices=TRUST_STATES, default="pending")
    parser.add_argument("--activation", choices=ACTIVATION_STATES, default="inactive")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    options = InstallOptions(
        mode=args.mode,
        destinations=Destinations(args.project_destination, args.skills_destination, args.instructions_destination),
        targets=tuple(args.target or ("claude_code", "codex")),
        workspace_trust=args.workspace_trust,
        server_approval=args.server_approval,
        activation=args.activation,
    )
    try:
        report = install(options)
    except InstallError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    sys.stdout.write(json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n")
    return 1 if report.installation == "drift" else 0


if __name__ == "__main__":
    raise SystemExit(main())
