"""Dependency-free conformance tests for the canonical contract registries."""

from __future__ import annotations

import copy
import json
import re
import tomllib
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


class SchemaValidationError(AssertionError):
    """Raised when an instance does not conform to the supported schema subset."""


class Draft202012SubsetValidator:
    """Validate the JSON Schema features used by this repository.

    Keeping this small validator in the test suite preserves the zero-dependency
    bootstrap while still executing positive and negative schema conformance
    checks. Production adapters may use any full Draft 2020-12 implementation.
    """

    def __init__(self, schema: dict[str, Any]) -> None:
        self.schema = schema

    def validate(self, instance: Any) -> None:
        self._validate(instance, self.schema, "$")

    def _resolve(self, reference: str) -> dict[str, Any]:
        if not reference.startswith("#/"):
            raise SchemaValidationError(f"unsupported external reference: {reference}")
        node: Any = self.schema
        for segment in reference[2:].split("/"):
            key = segment.replace("~1", "/").replace("~0", "~")
            node = node[key]
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
                raise SchemaValidationError(f"{path}: expected {expected_types}, got {type(instance).__name__}")

        if isinstance(instance, dict):
            if len(instance) < schema.get("minProperties", 0):
                raise SchemaValidationError(f"{path}: too few properties")
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
                raise SchemaValidationError(f"{path}: {instance!r} does not match {schema['pattern']!r}")

        if isinstance(instance, (int, float)) and not isinstance(instance, bool):
            if "minimum" in schema and instance < schema["minimum"]:
                raise SchemaValidationError(f"{path}: value is below minimum")
            if "maximum" in schema and instance > schema["maximum"]:
                raise SchemaValidationError(f"{path}: value is above maximum")


def load_json(relative_path: str) -> dict[str, Any]:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


CONDUCTOR_TOOLS = {
    "add_action_item",
    "add_phase",
    "add_phase_tasks",
    "ask_user_questions",
    "attach_file",
    "claim_next_task",
    "claim_task",
    "complete_analysis_run",
    "create_board",
    "create_plan_draft",
    "create_tasks",
    "delete_attachment",
    "finalize_plan",
    "get_attachment",
    "get_graph_summary",
    "get_overlap_report",
    "get_pickup_context",
    "get_pipeline_state",
    "get_plan",
    "get_question_answers",
    "get_server_info",
    "get_task",
    "import_plan_document",
    "list_attachments",
    "list_tasks",
    "list_workspaces",
    "post_progress_message",
    "query_graph",
    "record_commits",
    "record_gate_result",
    "record_research_artifact",
    "record_review_round",
    "record_task_summary",
    "record_task_verdict",
    "record_wave",
    "register_project",
    "register_worktree",
    "release_task",
    "renew_task_lease",
    "resolve_project",
    "search_context",
    "set_layer_tour",
    "set_plan_section",
    "start_analysis_run",
    "update_action_item",
    "update_plan_document",
    "update_task_status",
    "update_wave_status",
    "update_worktree_status",
    "upsert_graph_edges",
    "upsert_graph_layer",
    "upsert_graph_nodes",
}

WORKER_TOOLS = {
    "attach_file",
    "claim_task",
    "get_attachment",
    "get_plan",
    "get_task",
    "list_attachments",
    "list_tasks",
    "list_workspaces",
    "post_progress_message",
    "record_commits",
    "record_task_summary",
    "register_worktree",
    "release_task",
    "renew_task_lease",
    "search_context",
    "update_task_status",
    "update_worktree_status",
}


class ContractSchemaTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.contracts = {
            "config/agents.json": "schemas/agent-role.schema.json",
            "config/model-tiers.json": "schemas/model-tier.schema.json",
            "config/zabin-mcp.json": "schemas/mcp-policy.schema.json",
        }

    def test_complete_configs_validate(self) -> None:
        for config_path, schema_path in self.contracts.items():
            with self.subTest(config=config_path):
                Draft202012SubsetValidator(load_json(schema_path)).validate(load_json(config_path))

    def test_schemas_require_complete_root_shape(self) -> None:
        for config_path, schema_path in self.contracts.items():
            config = load_json(config_path)
            validator = Draft202012SubsetValidator(load_json(schema_path))
            for required_name in load_json(schema_path)["required"]:
                invalid = copy.deepcopy(config)
                invalid.pop(required_name)
                with self.subTest(config=config_path, missing=required_name):
                    with self.assertRaises(SchemaValidationError):
                        validator.validate(invalid)
            invalid = copy.deepcopy(config)
            invalid["unexpected_root_field"] = True
            with self.subTest(config=config_path, extra="unexpected_root_field"):
                with self.assertRaises(SchemaValidationError):
                    validator.validate(invalid)

    def test_mcp_schema_rejects_client_qualified_tool_names(self) -> None:
        policy = load_json("config/zabin-mcp.json")
        policy["servers"][1]["tools"][0]["name"] = "mcp__zabin-worker__attach_file"
        validator = Draft202012SubsetValidator(load_json("schemas/mcp-policy.schema.json"))
        with self.assertRaises(SchemaValidationError):
            validator.validate(policy)

    def test_mcp_schema_rejects_literal_credentials(self) -> None:
        policy = load_json("config/zabin-mcp.json")
        policy["servers"][0]["credential"] = {
            "source": "literal",
            "value": "do-not-store-secrets-here",
        }
        validator = Draft202012SubsetValidator(load_json("schemas/mcp-policy.schema.json"))
        with self.assertRaises(SchemaValidationError):
            validator.validate(policy)

    def test_live_public_tool_inventories_are_exact_and_separate(self) -> None:
        policy = load_json("config/zabin-mcp.json")
        servers = {server["surface"]: server for server in policy["servers"]}
        conductor = {tool["name"] for tool in servers["conductor"]["tools"]}
        worker = {tool["name"] for tool in servers["worker"]["tools"]}

        self.assertEqual(CONDUCTOR_TOOLS, conductor)
        self.assertEqual(WORKER_TOOLS, worker)
        self.assertEqual(52, len(conductor))
        self.assertEqual(17, len(worker))
        self.assertLess(worker, conductor)
        self.assertNotIn("get_server_info", worker)
        self.assertNotIn("record_task_verdict", worker)

    def test_mcp_surfaces_have_distinct_identity_transport_and_credentials(self) -> None:
        policy = load_json("config/zabin-mcp.json")
        conductor, worker = policy["servers"]
        self.assertNotEqual(conductor["id"], worker["id"])
        self.assertNotEqual(conductor["identity"]["client_server_key"], worker["identity"]["client_server_key"])
        self.assertNotEqual(conductor["transport"]["url"], worker["transport"]["url"])
        self.assertNotEqual(conductor["credential"]["name"], worker["credential"]["name"])
        self.assertEqual("environment", conductor["credential"]["source"])
        self.assertEqual("environment", worker["credential"]["source"])

    def test_goose_requirements_are_exact_and_extension_names_are_unique(self) -> None:
        policy = load_json("config/zabin-mcp.json")
        expected_keys = {"conductor": "zabin-conductor", "worker": "zabin-worker"}
        normalized = set()
        for server in policy["servers"]:
            adapters = {
                requirement["client"]: requirement
                for requirement in server["adapter_requirements"]
            }
            self.assertEqual({"claude_code", "codex", "goose"}, set(adapters))
            goose = adapters["goose"]
            self.assertEqual("goose/recipe.json", goose["config_target"])
            self.assertEqual(expected_keys[server["surface"]], goose["server_key"])
            self.assertEqual("environment_interpolation", goose["credential_binding"])
            self.assertEqual("extension_qualified", goose["tool_reference_mode"])
            self.assertEqual(
                {"type", "name", "uri", "headers.Authorization", "available_tools"},
                set(goose["required_fields"]),
            )
            normalized.add(goose["server_key"].lower())
        self.assertEqual(2, len(normalized))

    def test_mcp_schema_rejects_unknown_or_incomplete_goose_adapter(self) -> None:
        policy = load_json("config/zabin-mcp.json")
        validator = Draft202012SubsetValidator(load_json("schemas/mcp-policy.schema.json"))
        invalid = copy.deepcopy(policy)
        invalid["servers"][0]["adapter_requirements"][2]["client"] = "unknown"
        with self.assertRaises(SchemaValidationError):
            validator.validate(invalid)
        invalid = copy.deepcopy(policy)
        invalid["servers"][0]["adapter_requirements"][2].pop("required_fields")
        with self.assertRaises(SchemaValidationError):
            validator.validate(invalid)

    def test_every_public_tool_has_risk_and_approval_metadata(self) -> None:
        policy = load_json("config/zabin-mcp.json")
        for server in policy["servers"]:
            names = [tool["name"] for tool in server["tools"]]
            self.assertEqual(len(names), len(set(names)), server["id"])
            for tool in server["tools"]:
                with self.subTest(server=server["id"], tool=tool["name"]):
                    self.assertFalse(tool["name"].startswith("mcp__"))
                    self.assertEqual(tool["mutates_state"], tool["risk_class"] != "read_only")
                    if tool["risk_class"] == "read_only":
                        self.assertEqual("auto", tool["approval"])

    def test_model_tiers_are_provider_neutral_capability_contracts(self) -> None:
        tiers = load_json("config/model-tiers.json")["tiers"]
        self.assertEqual({"fast", "balanced", "deep"}, {tier["id"] for tier in tiers})
        serialized = json.dumps(tiers).lower()
        for provider_marker in ("openai", "anthropic", "gpt-", "claude-", "provider_id", "model_id"):
            self.assertNotIn(provider_marker, serialized)
        for tier in tiers:
            self.assertGreaterEqual(len(tier["capabilities"]), 2)
            self.assertIn("constraints", tier)

    def test_agent_registry_covers_current_roles_and_required_contracts(self) -> None:
        roles = load_json("config/agents.json")["roles"]
        role_ids = {role["id"] for role in roles}
        source_ids = set()
        for source in (ROOT / "agents").glob("*.md"):
            match = re.search(r"^name:\s*([a-z0-9_]+)\s*$", source.read_text(encoding="utf-8"), re.MULTILINE)
            self.assertIsNotNone(match, source)
            source_ids.add(match.group(1))
        self.assertEqual(source_ids, role_ids)
        self.assertEqual(len(role_ids), len(roles))

        tiers = {tier["id"] for tier in load_json("config/model-tiers.json")["tiers"]}
        for role in roles:
            with self.subTest(role=role["id"]):
                self.assertIn(role["model_tier"], tiers)
                self.assertTrue(role["required_tools"])
                self.assertFalse(any(tool.startswith("mcp__") for tool in role["required_tools"]))
                self.assertEqual({"claude_code", "codex"}, {item["client"] for item in role["adapter_requirements"]})
                for io_name in ("input_schema", "output_schema"):
                    io_schema = role[io_name]
                    self.assertEqual("object", io_schema["type"])
                    self.assertLessEqual(set(io_schema["required"]), set(io_schema["properties"]))

    def test_pyproject_declares_supported_python_and_unittest_commands(self) -> None:
        with (ROOT / "pyproject.toml").open("rb") as handle:
            project = tomllib.load(handle)
        self.assertEqual(">=3.11", project["project"]["requires-python"])
        self.assertEqual([], project["project"]["dependencies"])
        self.assertEqual("python -m unittest tests.test_contract_schemas", project["tool"]["contracts"]["test"])
        self.assertEqual(
            "python -m unittest discover -s tests -p 'test_*.py'",
            project["tool"]["contracts"]["test_discovery"],
        )

    def test_gitignore_covers_generated_and_recovery_artifacts(self) -> None:
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for expected in (
            "__pycache__/",
            "*.py[cod]",
            ".tmp/adapters/",
            "*.bak",
            "conformance-results/",
            ".runtime/",
        ):
            with self.subTest(pattern=expected):
                self.assertIn(expected, ignored)


if __name__ == "__main__":
    unittest.main()
