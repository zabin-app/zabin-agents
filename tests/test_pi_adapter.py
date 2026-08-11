"""Fail-closed compatibility checks for the audited PI MCP candidate."""

from __future__ import annotations

import base64
import json
import re
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_DIR = ROOT / "adapters" / "pi"
COMPATIBILITY_PATH = ADAPTER_DIR / "COMPATIBILITY.md"
LOCK_PATH = ADAPTER_DIR / "extension-lock.json"
SETTINGS_PATH = ADAPTER_DIR / "settings.json.template"
EXACT_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
SHA1 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must contain a JSON object")
    return value


def package_name(path: str) -> str:
    return path.rsplit("node_modules/", 1)[-1]


class PiAdapterCompatibilityTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.compatibility = COMPATIBILITY_PATH.read_text(encoding="utf-8")
        cls.lock = load_json(LOCK_PATH)
        cls.settings = load_json(SETTINGS_PATH)

    def test_unsupported_gate_disables_native_settings_template(self) -> None:
        advertised_in_doc = re.search(
            r"\*\*Status:\s*(?:conditionally\s+)?supported\b",
            self.compatibility,
            flags=re.IGNORECASE,
        )
        advertised_in_lock = str(self.lock.get("support_status", "")).startswith("supported")
        advertised_in_settings = bool(self.settings.get("packages"))
        self.assertIsNone(advertised_in_doc)
        self.assertFalse(advertised_in_lock)
        self.assertFalse(advertised_in_settings)
        self.assertEqual("unsupported", self.lock["support_status"])
        self.assertEqual({"packages": []}, self.settings)

    def test_immutable_pi_and_extension_artifacts_are_recorded(self) -> None:
        pi = self.lock["pi"]
        extension = self.lock["extension"]
        self.assertEqual("@earendil-works/pi-coding-agent", pi["package"])
        self.assertEqual("0.84.1", pi["version"])
        self.assertRegex(pi["source_revision"], SHA1)
        self.assertRegex(pi["release_asset_sha256"], SHA256)
        self.assertRegex(pi["source_archive_sha256"], SHA256)
        self.assertEqual("MIT", pi["license"])
        self.assertEqual("pi-mcp-adapter", extension["package"])
        self.assertEqual("2.22.0", extension["version"])
        self.assertRegex(extension["source_revision"], SHA1)
        self.assertRegex(extension["tag_object"], SHA1)
        self.assertEqual("unsigned", extension["tag_signature"])
        self.assertRegex(extension["registry_tarball_sha256"], SHA256)
        self.assertEqual("MIT", extension["license"])
        for artifact in (pi, extension):
            integrity = artifact["registry_integrity"]
            self.assertTrue(integrity.startswith("sha512-"))
            self.assertEqual(64, len(base64.b64decode(integrity.removeprefix("sha512-"), validate=True)))
            self.assertTrue(artifact["registry_tarball"].startswith("https://registry.npmjs.org/"))

    def test_transitive_lock_is_complete_hashed_and_licensed(self) -> None:
        packages = self.lock["packages"]
        self.assertEqual(self.lock["resolution"]["package_count"], len(packages))
        self.assertEqual(56, len(packages))
        paths = [entry["path"] for entry in packages]
        self.assertEqual(len(paths), len(set(paths)))
        names = {package_name(path) for path in paths}
        self.assertIn("pi-mcp-adapter", names)

        for entry in packages:
            with self.subTest(path=entry["path"]):
                self.assertTrue(entry["path"].startswith("node_modules/"))
                self.assertRegex(entry["version"], EXACT_VERSION)
                self.assertTrue(entry["resolved"].startswith("https://registry.npmjs.org/"))
                integrity = entry["integrity"]
                self.assertTrue(integrity.startswith("sha512-"))
                digest = base64.b64decode(integrity.removeprefix("sha512-"), validate=True)
                self.assertEqual(64, len(digest))
                self.assertIn(entry["license"], {"MIT", "ISC", "BSD-3-Clause", "0BSD"})
                for dependency in entry.get("dependencies", {}):
                    self.assertIn(dependency, names)

        extension_entry = next(
            entry for entry in packages if entry["path"] == "node_modules/pi-mcp-adapter"
        )
        self.assertEqual(self.lock["extension"]["version"], extension_entry["version"])
        self.assertEqual(self.lock["extension"]["registry_integrity"], extension_entry["integrity"])

    def test_audit_covers_every_required_policy_boundary(self) -> None:
        required_evidence = (
            "Streamable HTTP",
            "Protocol negotiation",
            "Header secrets and redaction",
            "Server identity",
            "Canonical names",
            "Pre-registration allowlist",
            "Alternate dispatch paths",
            "Failure behavior",
            "Updates and integrity",
            "Sandbox and arbitrary code",
            "serverInfo",
            "ui-server.ts",
        )
        for marker in required_evidence:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.compatibility)
        self.assertGreaterEqual(len(re.findall(r"\*\*Blocking\b", self.compatibility)), 4)

    def test_denial_proof_records_dispatch_and_zero_server_receipts(self) -> None:
        self.assertRegex(self.compatibility, r"direct\s+dispatcher attempt")
        self.assertIn("registered tool not found: delete_attachment", self.compatibility)
        self.assertIn('"forbidden_receipts": 0', self.compatibility)
        self.assertIn('"allowed_receipts": 1', self.compatibility)
        self.assertIn('"authorization_header_valid": true', self.compatibility)
        self.assertNotIn("isolated-secret", self.compatibility)
        self.assertNotIn("isolated-secret", LOCK_PATH.read_text(encoding="utf-8"))
        self.assertNotIn("isolated-secret", SETTINGS_PATH.read_text(encoding="utf-8"))

    def test_primary_sources_are_pinned_and_authoritative(self) -> None:
        expected_urls = (
            "https://pi.dev/",
            "https://github.com/earendil-works/pi/releases/tag/v0.84.1",
            "https://github.com/earendil-works/pi/blob/v0.84.1/packages/coding-agent/docs/extensions.md",
            "https://github.com/earendil-works/pi/blob/v0.84.1/packages/coding-agent/docs/packages.md",
            "https://github.com/nicobailon/pi-mcp-adapter/tree/852a12fa27b42c53d1d455c5937b9101d71af48a",
            "https://registry.npmjs.org/pi-mcp-adapter/2.22.0",
            "https://modelcontextprotocol.io/specification/2025-11-25/basic/transports",
            "https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle",
        )
        for url in expected_urls:
            with self.subTest(url=url):
                self.assertIn(url, self.compatibility)


if __name__ == "__main__":
    unittest.main()
