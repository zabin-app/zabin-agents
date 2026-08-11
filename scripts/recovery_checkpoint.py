"""Atomic, redacted recovery checkpoints for gaps in Zabin's read model.

Zabin remains authoritative.  Checkpoints are intentionally small snapshots of
state that cannot be reconstructed from the live service alone; callers must
reconcile against Zabin before using them to resume work.
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, TypeAlias


SCHEMA_ID = "https://zabin.dev/schemas/recovery-checkpoint.schema.json"
SCHEMA_VERSION = "1.0.0"
STATE_DIR_ENV = "ZABIN_RECOVERY_STATE_DIR"
DEFAULT_STATE_DIR = Path(".runtime/checkpoints")
REDACTED = "[REDACTED]"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})$"
)
_SECRET_KEY_RE = re.compile(
    r"(?:authorization|bearer|cookie|credential|passwd|password|private[_-]?key|"
    r"secret|session[_-]?id|token|api[_-]?key)",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"\bBearer\s+[^\s,;]+", re.IGNORECASE)
_BASIC_AUTH_URL_RE = re.compile(r"(?P<scheme>https?://)[^/@\s]+:[^/@\s]+@", re.IGNORECASE)
_QUERY_SECRET_RE = re.compile(
    r"(?P<prefix>[?&](?:access_token|api_key|key|password|secret|token)=)[^&#\s]+",
    re.IGNORECASE,
)

JsonObject: TypeAlias = dict[str, Any]
Migration: TypeAlias = Callable[[JsonObject], JsonObject]
RemoteReader: TypeAlias = Callable[["CheckpointKey"], Mapping[str, Any] | None]


class RecoveryCheckpointError(RuntimeError):
    """Base error for recovery checkpoint operations."""


class InvalidCheckpointError(RecoveryCheckpointError, ValueError):
    """Raised when a checkpoint does not satisfy the contract."""


class UnsupportedSchemaVersionError(RecoveryCheckpointError):
    """Raised when no explicit migration can advance a checkpoint."""


class ReconciliationConflictError(RecoveryCheckpointError):
    """Raised when local recovery state diverges from authoritative Zabin state."""

    def __init__(self, local: Mapping[str, Any], zabin: Mapping[str, Any]) -> None:
        super().__init__(
            "local recovery checkpoint conflicts with Zabin; "
            "resolve the divergence explicitly before writing either state"
        )
        # Values are already redacted by reconcile(), but copy them to prevent a
        # caller from mutating the evidence attached to this exception.
        self.local = copy.deepcopy(dict(local))
        self.zabin = copy.deepcopy(dict(zabin))


@dataclass(frozen=True, slots=True)
class CheckpointKey:
    """The complete identity of one checkpoint and its on-disk location."""

    project_id: str
    plan_id: str
    phase_id: str
    wave_id: str
    task_id: str
    sha: str

    def __post_init__(self) -> None:
        for name in ("project_id", "plan_id", "phase_id", "wave_id", "task_id"):
            value = getattr(self, name)
            if _IDENTIFIER_RE.fullmatch(value) is None:
                raise ValueError(f"{name} is not a safe checkpoint identifier: {value!r}")
        if _SHA_RE.fullmatch(self.sha) is None:
            raise ValueError(f"sha is not a lowercase hexadecimal git SHA: {self.sha!r}")

    def as_dict(self) -> dict[str, str]:
        return {
            "project_id": self.project_id,
            "plan_id": self.plan_id,
            "phase_id": self.phase_id,
            "wave_id": self.wave_id,
            "task_id": self.task_id,
            "sha": self.sha,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CheckpointKey":
        required = ("project_id", "plan_id", "phase_id", "wave_id", "task_id", "sha")
        missing = [name for name in required if name not in value]
        if missing:
            raise InvalidCheckpointError(f"checkpoint key is missing: {', '.join(missing)}")
        try:
            return cls(**{name: value[name] for name in required})
        except (TypeError, ValueError) as error:
            raise InvalidCheckpointError(str(error)) from error


ReconciliationStatus = Literal[
    "absent", "consistent", "zabin_only", "checkpoint_only", "conflict"
]


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """Read-only outcome from comparing Zabin with a local checkpoint."""

    status: ReconciliationStatus
    zabin: JsonObject | None
    checkpoint: JsonObject | None


def default_state_dir(
    repo_root: str | os.PathLike[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Return an explicit external directory or the ignored repo-local default."""

    environment = os.environ if environ is None else environ
    configured = environment.get(STATE_DIR_ENV)
    if configured:
        return Path(configured).expanduser()
    root = Path.cwd() if repo_root is None else Path(repo_root)
    return root / DEFAULT_STATE_DIR


def redact_secrets(value: Any) -> Any:
    """Deep-copy JSON-like data while replacing common credential material."""

    if isinstance(value, Mapping):
        if value.get("type") == "object" and set(value) == {"type", "entries"}:
            entries = value.get("entries")
            if isinstance(entries, list):
                redacted_entries: list[Any] = []
                for entry in entries:
                    if not isinstance(entry, Mapping) or set(entry) != {"name", "value"}:
                        redacted_entries.append(redact_secrets(entry))
                        continue
                    name = entry.get("name")
                    item = entry.get("value")
                    redacted_entries.append(
                        {
                            "name": redact_secrets(name),
                            "value": (
                                {"type": "string", "value": REDACTED}
                                if isinstance(name, str) and _SECRET_KEY_RE.search(name)
                                else redact_secrets(item)
                            ),
                        }
                    )
                return {"type": "object", "entries": redacted_entries}
        redacted: JsonObject = {}
        for key, item in value.items():
            name = str(key)
            redacted[name] = REDACTED if _SECRET_KEY_RE.search(name) else redact_secrets(item)
        return redacted
    if isinstance(value, (list, tuple)):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        result = _BEARER_RE.sub(f"Bearer {REDACTED}", value)
        result = _BASIC_AUTH_URL_RE.sub(rf"\g<scheme>{REDACTED}@", result)
        return _QUERY_SECRET_RE.sub(rf"\g<prefix>{REDACTED}", result)
    return copy.deepcopy(value)


def encode_snapshot(snapshot: Mapping[str, Any]) -> JsonObject:
    """Encode a flexible JSON object into the checkpoint's closed representation."""

    return _encode_json_value(snapshot, require_object=True)


def decode_snapshot(snapshot: Mapping[str, Any]) -> JsonObject:
    """Decode a validated closed snapshot representation into a plain JSON object."""

    _validate_json_value(snapshot, "snapshot", require_object=True)
    decoded = _decode_json_value(snapshot)
    if not isinstance(decoded, dict):  # Guard the public return type against future variants.
        raise InvalidCheckpointError("snapshot did not decode to an object")
    return decoded


def retire_fields(
    checkpoint: Mapping[str, Any],
    field_names: Iterable[str],
    *,
    reason: str,
    replacement: str | None = None,
) -> JsonObject:
    """Explicitly remove top-level fields and preserve auditable tombstones."""

    if not reason.strip():
        raise ValueError("field retirement requires a non-empty reason")
    result = copy.deepcopy(dict(checkpoint))
    records = result.setdefault("retired_fields", [])
    if not isinstance(records, list):
        raise InvalidCheckpointError("retired_fields must be an array")
    known = {record.get("name") for record in records if isinstance(record, Mapping)}
    for name in field_names:
        if not name or name in {
            "$schema",
            "schema_version",
            "key",
            "phase_base",
            "retired_fields",
        }:
            raise ValueError(f"field cannot be retired: {name!r}")
        if name not in result or name in known:
            continue
        result.pop(name)
        record: JsonObject = {
            "name": name,
            "reason": reason,
            "retired_in_version": SCHEMA_VERSION,
        }
        if replacement is not None:
            record["replacement"] = replacement
        records.append(record)
        known.add(name)
    return result


def migrate_checkpoint(
    checkpoint: Mapping[str, Any],
    migrations: Mapping[str, Migration] | None = None,
    *,
    target_version: str = SCHEMA_VERSION,
) -> JsonObject:
    """Run explicit, one-version-at-a-time migrations without guessing intent."""

    result = copy.deepcopy(dict(checkpoint))
    available = {} if migrations is None else dict(migrations)
    visited: set[str] = set()
    while result.get("schema_version") != target_version:
        version = result.get("schema_version")
        if not isinstance(version, str) or not version:
            raise UnsupportedSchemaVersionError("checkpoint has no usable schema_version")
        if version in visited:
            raise UnsupportedSchemaVersionError(f"migration cycle detected at {version}")
        migration = available.get(version)
        if migration is None:
            raise UnsupportedSchemaVersionError(
                f"no migration registered from checkpoint schema {version!r}"
            )
        visited.add(version)
        migrated = migration(copy.deepcopy(result))
        if not isinstance(migrated, dict):
            raise InvalidCheckpointError(f"migration from {version!r} did not return an object")
        if migrated.get("schema_version") == version:
            raise UnsupportedSchemaVersionError(f"migration from {version!r} did not advance")
        result = migrated
    return result


def build_checkpoint(
    key: CheckpointKey,
    *,
    phase_base: str,
    payload_references: Sequence[Mapping[str, Any]] = (),
    task_verdict: Mapping[str, Any] | None = None,
    gate_snapshots: Sequence[Mapping[str, Any]] = (),
    completion_summary_evidence: Sequence[Mapping[str, Any]] = (),
    action_item_resolutions: Sequence[Mapping[str, Any]] = (),
    commit_mappings: Sequence[Mapping[str, Any]] = (),
) -> JsonObject:
    """Build the complete v1 checkpoint shape with empty optional collections."""

    checkpoint: JsonObject = {
        "$schema": SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "key": key.as_dict(),
        "phase_base": phase_base,
        "payload_references": list(payload_references),
        "task_verdict": (
            {"round": 0, "verdict": None, "evidence": []}
            if task_verdict is None
            else dict(task_verdict)
        ),
        "gate_snapshots": list(gate_snapshots),
        "completion_summary_evidence": list(completion_summary_evidence),
        "action_item_resolutions": list(action_item_resolutions),
        "commit_mappings": list(commit_mappings),
        "retired_fields": [],
    }
    validate_checkpoint(checkpoint)
    return checkpoint


def validate_checkpoint(checkpoint: Mapping[str, Any]) -> None:
    """Validate security- and recovery-critical v1 invariants without dependencies."""

    required = {
        "$schema",
        "schema_version",
        "key",
        "phase_base",
        "payload_references",
        "task_verdict",
        "gate_snapshots",
        "completion_summary_evidence",
        "action_item_resolutions",
        "commit_mappings",
        "retired_fields",
    }
    unknown = set(checkpoint) - required
    missing = required - set(checkpoint)
    if missing or unknown:
        detail = []
        if missing:
            detail.append(f"missing fields: {', '.join(sorted(missing))}")
        if unknown:
            detail.append(f"unknown fields: {', '.join(sorted(unknown))}")
        raise InvalidCheckpointError("; ".join(detail))
    if checkpoint["$schema"] != SCHEMA_ID or checkpoint["schema_version"] != SCHEMA_VERSION:
        raise InvalidCheckpointError("checkpoint does not use the current schema identity")
    if not isinstance(checkpoint["key"], Mapping):
        raise InvalidCheckpointError("key must be an object")
    key = CheckpointKey.from_mapping(checkpoint["key"])
    if set(checkpoint["key"]) != set(key.as_dict()):
        raise InvalidCheckpointError("key contains unknown fields")
    _require_sha(checkpoint["phase_base"], "phase_base")

    _require_list(checkpoint, "payload_references")
    for index, reference in enumerate(checkpoint["payload_references"]):
        _validate_payload_reference(reference, f"payload_references[{index}]")

    verdict = checkpoint["task_verdict"]
    if not isinstance(verdict, Mapping) or set(verdict) != {"round", "verdict", "evidence"}:
        raise InvalidCheckpointError("task_verdict has an invalid shape")
    if isinstance(verdict["round"], bool) or not isinstance(verdict["round"], int) or verdict["round"] < 0:
        raise InvalidCheckpointError("task_verdict.round must be a non-negative integer")
    if verdict["verdict"] is not None and (
        not isinstance(verdict["verdict"], str) or not verdict["verdict"].strip()
    ):
        raise InvalidCheckpointError("task_verdict.verdict must be null or a non-empty string")
    if isinstance(verdict["verdict"], str) and len(verdict["verdict"]) > 64:
        raise InvalidCheckpointError("task_verdict.verdict must be at most 64 characters")
    _validate_evidence_list(verdict["evidence"], "task_verdict.evidence")

    _require_list(checkpoint, "gate_snapshots")
    for index, snapshot in enumerate(checkpoint["gate_snapshots"]):
        path = f"gate_snapshots[{index}]"
        _require_mapping_keys(snapshot, {"task_id", "gate", "status", "snapshot", "captured_at"}, path)
        _require_identifier(snapshot["task_id"], f"{path}.task_id")
        if snapshot["task_id"] != key.task_id:
            raise InvalidCheckpointError(f"{path}.task_id does not match checkpoint key")
        _require_identifier(snapshot["gate"], f"{path}.gate")
        _require_non_empty_string(snapshot["status"], f"{path}.status", max_length=64)
        _validate_json_value(snapshot["snapshot"], f"{path}.snapshot", require_object=True)
        _require_timestamp(snapshot["captured_at"], f"{path}.captured_at")

    _validate_evidence_list(
        checkpoint["completion_summary_evidence"], "completion_summary_evidence"
    )

    _require_list(checkpoint, "action_item_resolutions")
    for index, resolution in enumerate(checkpoint["action_item_resolutions"]):
        path = f"action_item_resolutions[{index}]"
        _require_mapping_keys(
            resolution,
            {"action_item_id", "status", "resolution", "evidence", "captured_at"},
            path,
        )
        _require_identifier(resolution["action_item_id"], f"{path}.action_item_id")
        _require_non_empty_string(resolution["status"], f"{path}.status", max_length=64)
        _require_non_empty_string(resolution["resolution"], f"{path}.resolution")
        _validate_evidence_list(resolution["evidence"], f"{path}.evidence")
        _require_timestamp(resolution["captured_at"], f"{path}.captured_at")

    _require_list(checkpoint, "commit_mappings")
    for index, mapping in enumerate(checkpoint["commit_mappings"]):
        path = f"commit_mappings[{index}]"
        _require_mapping_keys(mapping, {"source_sha", "recorded_sha", "merged_sha"}, path)
        _require_sha(mapping["source_sha"], f"{path}.source_sha")
        _require_sha(mapping["recorded_sha"], f"{path}.recorded_sha")
        if mapping["merged_sha"] is not None:
            _require_sha(mapping["merged_sha"], f"{path}.merged_sha")

    _require_list(checkpoint, "retired_fields")
    for index, record in enumerate(checkpoint["retired_fields"]):
        path = f"retired_fields[{index}]"
        allowed = {"name", "reason", "retired_in_version", "replacement"}
        if not isinstance(record, Mapping) or not {"name", "reason", "retired_in_version"} <= set(record):
            raise InvalidCheckpointError(f"{path} is missing required fields")
        if set(record) - allowed:
            raise InvalidCheckpointError(f"{path} contains unknown fields")
        for name in ("name", "reason", "retired_in_version"):
            _require_non_empty_string(record[name], f"{path}.{name}")
        if _SEMVER_RE.fullmatch(record["retired_in_version"]) is None:
            raise InvalidCheckpointError(f"{path}.retired_in_version must be a semantic version")
        if "replacement" in record and record["replacement"] is not None:
            _require_non_empty_string(record["replacement"], f"{path}.replacement")


class RecoveryCheckpointStore:
    """Filesystem store using atomic replacement and read-first reconciliation."""

    def __init__(
        self,
        state_dir: str | os.PathLike[str] | None = None,
        *,
        repo_root: str | os.PathLike[str] | None = None,
        environ: Mapping[str, str] | None = None,
        migrations: Mapping[str, Migration] | None = None,
    ) -> None:
        self.state_dir = (
            default_state_dir(repo_root, environ=environ) if state_dir is None else Path(state_dir)
        )
        self._migrations = {} if migrations is None else dict(migrations)

    def path_for(self, key: CheckpointKey) -> Path:
        """Map all identity fields to a stable path without lossy flattening."""

        return (
            self.state_dir
            / key.project_id
            / key.plan_id
            / key.phase_id
            / key.wave_id
            / key.task_id
            / f"{key.sha}.json"
        )

    def save(self, checkpoint: Mapping[str, Any]) -> Path:
        """Redact, validate, fsync, and atomically replace one checkpoint."""

        sanitized = redact_secrets(checkpoint)
        if not isinstance(sanitized, dict):
            raise InvalidCheckpointError("checkpoint must be an object")
        validate_checkpoint(sanitized)
        key = CheckpointKey.from_mapping(sanitized["key"])
        path = self.path_for(key)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(sanitized, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            self._fsync_directory(path.parent)
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            temporary.unlink(missing_ok=True)
            raise
        return path

    def load(self, key: CheckpointKey) -> JsonObject | None:
        """Load and explicitly migrate one checkpoint, returning no live references."""

        path = self.path_for(key)
        if not path.exists():
            return None
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise InvalidCheckpointError(f"cannot read checkpoint {path}: {error}") from error
        if not isinstance(loaded, dict):
            raise InvalidCheckpointError(f"checkpoint {path} is not a JSON object")
        migrated = migrate_checkpoint(loaded, self._migrations)
        migrated = redact_secrets(migrated)
        validate_checkpoint(migrated)
        if CheckpointKey.from_mapping(migrated["key"]) != key:
            raise InvalidCheckpointError(f"checkpoint identity does not match its path: {path}")
        return migrated

    def reconcile(
        self,
        key: CheckpointKey,
        read_zabin: RemoteReader,
        *,
        raise_on_conflict: bool = True,
    ) -> ReconciliationResult:
        """Read Zabin first, then compare local state without writing either side."""

        authoritative_raw = read_zabin(key)
        authoritative = (
            None if authoritative_raw is None else redact_secrets(dict(authoritative_raw))
        )
        checkpoint = self.load(key)

        if authoritative is None and checkpoint is None:
            return ReconciliationResult("absent", None, None)
        if checkpoint is None:
            return ReconciliationResult("zabin_only", authoritative, None)
        if authoritative is None:
            return ReconciliationResult("checkpoint_only", None, checkpoint)
        if _canonical_json(authoritative) == _canonical_json(checkpoint):
            return ReconciliationResult("consistent", authoritative, checkpoint)
        if raise_on_conflict:
            raise ReconciliationConflictError(checkpoint, authoritative)
        return ReconciliationResult("conflict", authoritative, checkpoint)

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(directory, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


# A short alias keeps call sites readable while retaining the domain-specific
# class name in docs and tracebacks.
CheckpointStore = RecoveryCheckpointStore


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        canonical = _canonicalize_tagged_objects(value)
        return json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise InvalidCheckpointError(f"state is not JSON-serializable: {error}") from error


def _require_list(checkpoint: Mapping[str, Any], name: str) -> None:
    if not isinstance(checkpoint[name], list):
        raise InvalidCheckpointError(f"{name} must be an array")


def _require_mapping_keys(value: Any, required: set[str], path: str) -> None:
    if not isinstance(value, Mapping) or set(value) != required:
        raise InvalidCheckpointError(f"{path} has an invalid shape")


def _require_identifier(value: Any, path: str) -> None:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        raise InvalidCheckpointError(f"{path} is not a safe identifier")


def _require_non_empty_string(value: Any, path: str, *, max_length: int | None = None) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidCheckpointError(f"{path} must be a non-empty string")
    if max_length is not None and len(value) > max_length:
        raise InvalidCheckpointError(f"{path} must be at most {max_length} characters")


def _require_timestamp(value: Any, path: str) -> None:
    if not isinstance(value, str) or _TIMESTAMP_RE.fullmatch(value) is None:
        raise InvalidCheckpointError(f"{path} must be an RFC 3339 date-time")
    normalized = value.replace("z", "+00:00").replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise InvalidCheckpointError(f"{path} must be an RFC 3339 date-time") from error
    if parsed.tzinfo is None:
        raise InvalidCheckpointError(f"{path} must include a timezone")


def _require_sha(value: Any, path: str) -> None:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        raise InvalidCheckpointError(f"{path} is not a lowercase hexadecimal git SHA")


def _validate_payload_reference(reference: Any, path: str) -> None:
    required = {"kind", "reference", "content_sha256", "full_payload"}
    _require_mapping_keys(reference, required, path)
    if reference["kind"] not in {"research", "review"}:
        raise InvalidCheckpointError(f"{path}.kind must be research or review")
    _require_non_empty_string(reference["reference"], f"{path}.reference")
    if not isinstance(reference["content_sha256"], str) or _DIGEST_RE.fullmatch(
        reference["content_sha256"]
    ) is None:
        raise InvalidCheckpointError(f"{path}.content_sha256 must be a SHA-256 digest")
    if reference["full_payload"] is not True:
        raise InvalidCheckpointError(f"{path}.full_payload must be true")


def _validate_evidence_list(value: Any, path: str) -> None:
    if not isinstance(value, list):
        raise InvalidCheckpointError(f"{path} must be an array")
    for index, reference in enumerate(value):
        item_path = f"{path}[{index}]"
        _require_mapping_keys(reference, {"reference", "content_sha256"}, item_path)
        _require_non_empty_string(reference["reference"], f"{item_path}.reference")
        digest = reference["content_sha256"]
        if not isinstance(digest, str) or _DIGEST_RE.fullmatch(digest) is None:
            raise InvalidCheckpointError(f"{item_path}.content_sha256 must be a SHA-256 digest")


def _encode_json_value(value: Any, *, require_object: bool = False) -> JsonObject:
    if value is None and not require_object:
        return {"type": "null"}
    if isinstance(value, bool) and not require_object:
        return {"type": "boolean", "value": value}
    if isinstance(value, (int, float)) and not isinstance(value, bool) and not require_object:
        if isinstance(value, float) and not math.isfinite(value):
            raise InvalidCheckpointError("snapshot numbers must be finite")
        return {"type": "number", "value": value}
    if isinstance(value, str) and not require_object:
        return {"type": "string", "value": value}
    if isinstance(value, list) and not require_object:
        return {"type": "array", "items": [_encode_json_value(item) for item in value]}
    if isinstance(value, Mapping):
        items = list(value.items())
        for name, _item in items:
            if not isinstance(name, str) or not name:
                raise InvalidCheckpointError("snapshot object keys must be non-empty strings")
        entries = []
        for name, item in sorted(items, key=lambda pair: pair[0]):
            entries.append({"name": name, "value": _encode_json_value(item)})
        return {"type": "object", "entries": entries}
    expected = "object" if require_object else "JSON value"
    raise InvalidCheckpointError(f"snapshot must contain a {expected}")


def _decode_json_value(value: Mapping[str, Any]) -> Any:
    kind = value["type"]
    if kind == "null":
        return None
    if kind in {"boolean", "number", "string"}:
        return value["value"]
    if kind == "array":
        return [_decode_json_value(item) for item in value["items"]]
    return {entry["name"]: _decode_json_value(entry["value"]) for entry in value["entries"]}


def _validate_json_value(value: Any, path: str, *, require_object: bool = False) -> None:
    if not isinstance(value, Mapping):
        raise InvalidCheckpointError(f"{path} must use the closed JSON value representation")
    kind = value.get("type")
    if require_object and kind != "object":
        raise InvalidCheckpointError(f"{path} must represent a JSON object")
    if kind == "null":
        _require_mapping_keys(value, {"type"}, path)
        return
    if kind == "boolean":
        _require_mapping_keys(value, {"type", "value"}, path)
        if not isinstance(value["value"], bool):
            raise InvalidCheckpointError(f"{path}.value must be a boolean")
        return
    if kind == "number":
        _require_mapping_keys(value, {"type", "value"}, path)
        number = value["value"]
        if (
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or (isinstance(number, float) and not math.isfinite(number))
        ):
            raise InvalidCheckpointError(f"{path}.value must be a finite number")
        return
    if kind == "string":
        _require_mapping_keys(value, {"type", "value"}, path)
        if not isinstance(value["value"], str):
            raise InvalidCheckpointError(f"{path}.value must be a string")
        return
    if kind == "array":
        _require_mapping_keys(value, {"type", "items"}, path)
        if not isinstance(value["items"], list):
            raise InvalidCheckpointError(f"{path}.items must be an array")
        for index, item in enumerate(value["items"]):
            _validate_json_value(item, f"{path}.items[{index}]")
        return
    if kind == "object":
        _require_mapping_keys(value, {"type", "entries"}, path)
        entries = value["entries"]
        if not isinstance(entries, list):
            raise InvalidCheckpointError(f"{path}.entries must be an array")
        names: list[str] = []
        for index, entry in enumerate(entries):
            entry_path = f"{path}.entries[{index}]"
            _require_mapping_keys(entry, {"name", "value"}, entry_path)
            if not isinstance(entry["name"], str) or len(entry["name"]) < 1:
                raise InvalidCheckpointError(f"{entry_path}.name must be a non-empty string")
            names.append(entry["name"])
            _validate_json_value(entry["value"], f"{entry_path}.value")
        if len(names) != len(set(names)):
            raise InvalidCheckpointError(f"{path}.entries must use unique property names")
        if names != sorted(names):
            raise InvalidCheckpointError(
                f"{path}.entries must be sorted by property name for canonical encoding"
            )
        return
    raise InvalidCheckpointError(f"{path}.type is not a supported JSON value type")


def _canonicalize_tagged_objects(value: Any) -> Any:
    """Normalize tagged-object entry order for semantic reconciliation comparisons."""

    if isinstance(value, Mapping):
        if value.get("type") == "object" and set(value) == {"type", "entries"}:
            entries = value.get("entries")
            if isinstance(entries, list) and all(
                isinstance(entry, Mapping)
                and set(entry) == {"name", "value"}
                and isinstance(entry.get("name"), str)
                for entry in entries
            ):
                return {
                    "type": "object",
                    "entries": [
                        {
                            "name": entry["name"],
                            "value": _canonicalize_tagged_objects(entry["value"]),
                        }
                        for entry in sorted(entries, key=lambda entry: entry["name"])
                    ],
                }
        return {str(key): _canonicalize_tagged_objects(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonicalize_tagged_objects(item) for item in value]
    return value
