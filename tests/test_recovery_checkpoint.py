"""Tests for the minimal Zabin recovery checkpoint contract."""

from __future__ import annotations

import copy
import json
import stat
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock

from scripts.recovery_checkpoint import (
    DEFAULT_STATE_DIR,
    REDACTED,
    SCHEMA_ID,
    SCHEMA_VERSION,
    STATE_DIR_ENV,
    CheckpointKey,
    InvalidCheckpointError,
    ReconciliationConflictError,
    RecoveryCheckpointStore,
    UnsupportedSchemaVersionError,
    build_checkpoint,
    decode_snapshot,
    default_state_dir,
    encode_snapshot,
    migrate_checkpoint,
    redact_secrets,
    retire_fields,
    validate_checkpoint,
)
from tests.test_contract_schemas import Draft202012SubsetValidator, SchemaValidationError


ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40
PHASE_BASE = "b" * 40
DIGEST = "c" * 64


def checkpoint_key() -> CheckpointKey:
    return CheckpointKey(
        project_id="prj_01",
        plan_id="plan_01",
        phase_id="phase_01",
        wave_id="wave_01",
        task_id="task_01",
        sha=SHA,
    )


def complete_checkpoint() -> dict[str, object]:
    key = checkpoint_key()
    return build_checkpoint(
        key,
        phase_base=PHASE_BASE,
        payload_references=[
            {
                "kind": "research",
                "reference": "zabin://attachments/research-full.json",
                "content_sha256": DIGEST,
                "full_payload": True,
            },
            {
                "kind": "review",
                "reference": "zabin://attachments/review-full.json",
                "content_sha256": "d" * 64,
                "full_payload": True,
            },
        ],
        task_verdict={
            "round": 2,
            "verdict": "APPROVED_WITH_CONCERNS",
            "evidence": [
                {
                    "reference": "zabin://task-verdicts/task_01/2",
                    "content_sha256": "e" * 64,
                }
            ],
        },
        gate_snapshots=[
            {
                "task_id": key.task_id,
                "gate": "task_validation",
                "status": "PASS",
                "snapshot": encode_snapshot(
                    {
                        "tests": 7,
                        "authorization": "Bearer should-not-survive",
                        "details": {"passed": True, "failures": []},
                    }
                ),
                "captured_at": "2026-08-11T12:00:00Z",
            }
        ],
        completion_summary_evidence=[
            {
                "reference": "zabin://task-summaries/task_01",
                "content_sha256": "f" * 64,
            }
        ],
        action_item_resolutions=[
            {
                "action_item_id": "action_01",
                "status": "resolved",
                "resolution": "Covered by the focused recovery test.",
                "evidence": [
                    {
                        "reference": "zabin://attachments/test-output.txt",
                        "content_sha256": "1" * 64,
                    }
                ],
                "captured_at": "2026-08-11T12:01:00Z",
            }
        ],
        commit_mappings=[
            {
                "source_sha": "2" * 40,
                "recorded_sha": "3" * 40,
                "merged_sha": None,
            }
        ],
    )


class RecoveryCheckpointSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(
            (ROOT / "schemas/recovery-checkpoint.schema.json").read_text(encoding="utf-8")
        )

    def assert_rejected_by_schema_and_runtime(self, checkpoint: dict[str, object]) -> None:
        with self.assertRaises(SchemaValidationError):
            Draft202012SubsetValidator(self.schema).validate(checkpoint)
        with self.assertRaises(InvalidCheckpointError):
            validate_checkpoint(checkpoint)

    def test_complete_checkpoint_validates_against_versioned_schema(self) -> None:
        checkpoint = complete_checkpoint()

        Draft202012SubsetValidator(self.schema).validate(checkpoint)
        validate_checkpoint(checkpoint)
        self.assertEqual(SCHEMA_ID, checkpoint["$schema"])
        self.assertEqual(SCHEMA_VERSION, checkpoint["schema_version"])

    def test_checkpoint_requires_every_recovery_gap_and_complete_key(self) -> None:
        checkpoint = complete_checkpoint()
        expected = {
            "project_id",
            "plan_id",
            "phase_id",
            "wave_id",
            "task_id",
            "sha",
        }
        self.assertEqual(expected, set(checkpoint["key"]))

        for field in (
            "phase_base",
            "payload_references",
            "task_verdict",
            "gate_snapshots",
            "completion_summary_evidence",
            "action_item_resolutions",
            "commit_mappings",
        ):
            invalid = copy.deepcopy(checkpoint)
            invalid.pop(field)
            with self.subTest(field=field), self.assertRaises(InvalidCheckpointError):
                validate_checkpoint(invalid)

    def test_task_gate_snapshot_must_match_checkpoint_task(self) -> None:
        checkpoint = complete_checkpoint()
        checkpoint["gate_snapshots"][0]["task_id"] = "task_other"

        with self.assertRaisesRegex(InvalidCheckpointError, "does not match"):
            validate_checkpoint(checkpoint)

    def test_gate_snapshot_uses_a_closed_recursive_json_representation(self) -> None:
        source = {
            "tests": 7,
            "passed": True,
            "details": {"failures": [], "note": None},
        }
        encoded = encode_snapshot(source)

        self.assertEqual({"type", "entries"}, set(encoded))
        self.assertEqual(source, decode_snapshot(encoded))

        checkpoint = complete_checkpoint()
        checkpoint["gate_snapshots"][0]["snapshot"]["unexpected"] = True
        self.assert_rejected_by_schema_and_runtime(checkpoint)

        checkpoint = complete_checkpoint()
        checkpoint["gate_snapshots"][0]["snapshot"] = {"tests": 7}
        self.assert_rejected_by_schema_and_runtime(checkpoint)

    def test_snapshot_encoding_is_canonical_across_mapping_insertion_order(self) -> None:
        forward = {
            "alpha": 1,
            "nested": {"first": True, "second": False},
            "omega": None,
        }
        reverse = {
            "omega": None,
            "nested": {"second": False, "first": True},
            "alpha": 1,
        }

        self.assertEqual(encode_snapshot(forward), encode_snapshot(reverse))
        self.assertEqual(
            ["alpha", "nested", "omega"],
            [entry["name"] for entry in encode_snapshot(reverse)["entries"]],
        )

    def test_runtime_rejects_noncanonical_persisted_snapshot_order(self) -> None:
        checkpoint = complete_checkpoint()
        checkpoint["gate_snapshots"][0]["snapshot"]["entries"].reverse()

        with self.assertRaisesRegex(InvalidCheckpointError, "sorted by property name"):
            validate_checkpoint(checkpoint)

    def test_schema_and_runtime_reject_length_pattern_timestamp_and_shape_gaps(self) -> None:
        cases: list[tuple[str, Callable[[dict[str, object]], None]]] = [
            (
                "verdict over maxLength",
                lambda value: value["task_verdict"].__setitem__("verdict", "v" * 65),
            ),
            (
                "gate status over maxLength",
                lambda value: value["gate_snapshots"][0].__setitem__("status", "s" * 65),
            ),
            (
                "action status over maxLength",
                lambda value: value["action_item_resolutions"][0].__setitem__(
                    "status", "s" * 65
                ),
            ),
            (
                "blank payload reference",
                lambda value: value["payload_references"][0].__setitem__("reference", "   "),
            ),
            (
                "invalid gate timestamp pattern",
                lambda value: value["gate_snapshots"][0].__setitem__(
                    "captured_at", "2026-08-11 12:00:00"
                ),
            ),
            (
                "invalid action timestamp pattern",
                lambda value: value["action_item_resolutions"][0].__setitem__(
                    "captured_at", "yesterday"
                ),
            ),
            (
                "invalid retired version pattern",
                lambda value: value["retired_fields"].append(
                    {
                        "name": "legacy",
                        "reason": "retired",
                        "retired_in_version": "v1",
                    }
                ),
            ),
            (
                "unexpected nested field",
                lambda value: value["task_verdict"].__setitem__("unexpected", True),
            ),
        ]

        for label, mutate in cases:
            with self.subTest(case=label):
                checkpoint = complete_checkpoint()
                mutate(checkpoint)
                self.assert_rejected_by_schema_and_runtime(checkpoint)

    def test_runtime_rejects_semantically_invalid_rfc3339_date(self) -> None:
        checkpoint = complete_checkpoint()
        checkpoint["gate_snapshots"][0]["captured_at"] = "2026-13-40T25:61:61Z"

        with self.assertRaisesRegex(InvalidCheckpointError, "RFC 3339"):
            validate_checkpoint(checkpoint)

    def test_unsafe_key_cannot_escape_state_directory(self) -> None:
        with self.assertRaises(ValueError):
            CheckpointKey("../project", "plan", "phase", "wave", "task", SHA)


class RecoveryCheckpointStoreTests(unittest.TestCase):
    def test_default_and_external_state_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(root / DEFAULT_STATE_DIR, default_state_dir(root, environ={}))
            external = root / "external-state"
            self.assertEqual(
                external,
                default_state_dir(root, environ={STATE_DIR_ENV: str(external)}),
            )
            self.assertEqual(external, RecoveryCheckpointStore(external).state_dir)

    def test_atomic_save_keys_path_by_all_ids_and_sha_and_redacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RecoveryCheckpointStore(temporary)
            checkpoint = complete_checkpoint()

            path = store.save(checkpoint)

            self.assertEqual(
                Path(temporary)
                / "prj_01"
                / "plan_01"
                / "phase_01"
                / "wave_01"
                / "task_01"
                / f"{SHA}.json",
                path,
            )
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                REDACTED,
                decode_snapshot(persisted["gate_snapshots"][0]["snapshot"])["authorization"],
            )
            self.assertEqual(
                "Bearer should-not-survive",
                decode_snapshot(checkpoint["gate_snapshots"][0]["snapshot"])["authorization"],
            )
            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
            self.assertEqual([], list(path.parent.glob(".*.tmp")))

            checkpoint["task_verdict"]["round"] = 3
            self.assertEqual(path, store.save(checkpoint))
            self.assertEqual(3, store.load(checkpoint_key())["task_verdict"]["round"])

    def test_reconcile_reads_zabin_first_and_never_overwrites_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RecoveryCheckpointStore(temporary)
            local = complete_checkpoint()
            path = store.save(local)
            original_bytes = path.read_bytes()
            remote = copy.deepcopy(local)
            remote["phase_base"] = "4" * 40
            remote["api_token"] = "do-not-leak"
            calls: list[str] = []

            original_load = store.load

            def tracked_load(key: CheckpointKey) -> dict[str, object] | None:
                calls.append("checkpoint")
                return original_load(key)

            def read_zabin(key: CheckpointKey) -> dict[str, object]:
                self.assertEqual(checkpoint_key(), key)
                calls.append("zabin")
                return remote

            with mock.patch.object(store, "load", side_effect=tracked_load):
                with self.assertRaises(ReconciliationConflictError) as raised:
                    store.reconcile(checkpoint_key(), read_zabin)

            self.assertEqual(["zabin", "checkpoint"], calls)
            self.assertEqual(REDACTED, raised.exception.zabin["api_token"])
            self.assertEqual(original_bytes, path.read_bytes())

    def test_reconcile_reports_consistent_and_non_throwing_conflict_states(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RecoveryCheckpointStore(temporary)
            checkpoint = complete_checkpoint()
            store.save(checkpoint)
            persisted = store.load(checkpoint_key())

            result = store.reconcile(checkpoint_key(), lambda _key: persisted)
            self.assertEqual("consistent", result.status)

            divergent = copy.deepcopy(persisted)
            divergent["task_verdict"]["round"] += 1
            result = store.reconcile(
                checkpoint_key(), lambda _key: divergent, raise_on_conflict=False
            )
            self.assertEqual("conflict", result.status)

    def test_reconcile_canonicalizes_remote_tagged_object_entry_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RecoveryCheckpointStore(temporary)
            checkpoint = complete_checkpoint()
            store.save(checkpoint)
            remote = store.load(checkpoint_key())
            remote["gate_snapshots"][0]["snapshot"]["entries"].reverse()
            nested = next(
                entry
                for entry in remote["gate_snapshots"][0]["snapshot"]["entries"]
                if entry["name"] == "details"
            )
            nested["value"]["entries"].reverse()

            result = store.reconcile(checkpoint_key(), lambda _key: remote)

            self.assertEqual("consistent", result.status)

    def test_load_rejects_noncanonical_persisted_snapshot_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RecoveryCheckpointStore(temporary)
            checkpoint = complete_checkpoint()
            path = store.path_for(checkpoint_key())
            checkpoint["gate_snapshots"][0]["snapshot"]["entries"].reverse()
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(checkpoint), encoding="utf-8")

            with self.assertRaisesRegex(InvalidCheckpointError, "sorted by property name"):
                store.load(checkpoint_key())


class RecoveryCheckpointEvolutionTests(unittest.TestCase):
    def test_load_runs_explicit_schema_migration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            key = checkpoint_key()
            current = complete_checkpoint()
            legacy = copy.deepcopy(current)
            legacy["schema_version"] = "0.9.0"

            def migrate_legacy(payload: dict[str, object]) -> dict[str, object]:
                payload["schema_version"] = SCHEMA_VERSION
                return payload

            store = RecoveryCheckpointStore(
                temporary, migrations={"0.9.0": migrate_legacy}
            )
            path = store.path_for(key)
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(legacy), encoding="utf-8")

            self.assertEqual(redact_secrets(current), store.load(key))

    def test_unknown_schema_requires_an_explicit_migration(self) -> None:
        checkpoint = complete_checkpoint()
        checkpoint["schema_version"] = "0.9.0"
        with self.assertRaises(UnsupportedSchemaVersionError):
            migrate_checkpoint(checkpoint)

    def test_field_retirement_removes_data_and_adds_a_tombstone(self) -> None:
        checkpoint = complete_checkpoint()
        checkpoint["legacy_hint"] = "obsolete"

        retired = retire_fields(
            checkpoint,
            ["legacy_hint"],
            reason="The authoritative Zabin read model now exposes this field.",
            replacement="get_pipeline_state",
        )

        self.assertNotIn("legacy_hint", retired)
        self.assertEqual("legacy_hint", retired["retired_fields"][0]["name"])
        self.assertEqual("get_pipeline_state", retired["retired_fields"][0]["replacement"])
        validate_checkpoint(retired)

    def test_redaction_covers_nested_keys_headers_urls_and_query_values(self) -> None:
        source = {
            "password": "plain",
            "nested": [
                {"session_id": "session-secret"},
                "Authorization: Bearer abc.def",
                "https://user:pass@example.test/path?token=value&safe=yes",
            ],
        }

        redacted = redact_secrets(source)

        self.assertEqual(REDACTED, redacted["password"])
        self.assertEqual(REDACTED, redacted["nested"][0]["session_id"])
        self.assertNotIn("abc.def", redacted["nested"][1])
        self.assertNotIn("user:pass", redacted["nested"][2])
        self.assertNotIn("token=value", redacted["nested"][2])
        self.assertEqual("plain", source["password"])


if __name__ == "__main__":
    unittest.main()
